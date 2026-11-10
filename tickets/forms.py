from pathlib import Path

from django import forms
from django.conf import settings
from django.db.models import Q
from django.template.defaultfilters import filesizeformat

from accounts.models import User
from tickets import password_guard
from tickets.models import Category, Ticket

POSSIBLE_PASSWORD = "possible_password"


class PasswordCheckMixin:
    """
    The "this might include a password" check (tickets/password_guard.py).

    If a text field looks like it holds a password, the form isn't valid until
    the person either takes it out or ticks "send anyway" (password_ack).
    password_warned is set once a warning has been shown, so the audit trail
    can tell "took it out" from "never had one".
    """

    password_fields: tuple[str, ...] = ()
    password_findings: dict = {}

    def check_for_passwords(self, cleaned: dict) -> None:
        found = {}
        for name in self.password_fields:
            findings = password_guard.find(cleaned.get(name) or "")
            if findings:
                found[name] = findings
        self.password_findings = found
        if found and not cleaned.get("password_ack"):
            self.add_error(None, forms.ValidationError(
                "This might include a password. Take it out, or tick the box to send it anyway.",
                code=POSSIBLE_PASSWORD,
            ))

    @property
    def needs_password_confirm(self) -> bool:
        return any(e.code == POSSIBLE_PASSWORD for e in self.non_field_errors().as_data())

    @property
    def password_hints(self) -> list[str]:
        return password_guard.hints(self.password_findings) if self.needs_password_confirm else []

    @property
    def other_errors(self) -> list[str]:
        """Form-wide errors except the password warning, which has its own panel."""
        return [e.messages[0] for e in self.non_field_errors().as_data() if e.code != POSSIBLE_PASSWORD]

    @property
    def files_need_reattaching(self) -> bool:
        """The browser drops chosen files when the server sends the form back."""
        return self.needs_password_confirm and bool(self.files)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class AttachmentsField(forms.FileField):
    """Zero or more files, each checked for size and type."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"class": "file-input"}))
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            files = [single(item, initial) for item in data if item]
        else:
            files = [single(data, initial)] if data else []

        if len(files) > settings.ATTACHMENT_MAX_FILES:
            raise forms.ValidationError(
                f"Attach up to {settings.ATTACHMENT_MAX_FILES} files at a time."
            )
        for upload in files:
            ext = Path(upload.name).suffix.lower()
            if ext not in settings.ATTACHMENT_EXTENSIONS:
                raise forms.ValidationError(
                    f'"{upload.name}" isn\'t a file type we accept. Try a screenshot, PDF, '
                    "Office document, text file or zip."
                )
            if upload.size > settings.ATTACHMENT_MAX_BYTES:
                raise forms.ValidationError(
                    f'"{upload.name}" is {filesizeformat(upload.size)}. The limit is '
                    f"{filesizeformat(settings.ATTACHMENT_MAX_BYTES)} per file."
                )
        return files


class CategoryChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.label


class NewTicketForm(PasswordCheckMixin, forms.Form):
    password_fields = ("subject", "description")

    subject = forms.CharField(
        max_length=200,
        error_messages={"required": "Enter a subject."},
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "off"}),
    )
    category = CategoryChoiceField(
        queryset=Category.objects.filter(is_active=True),
        empty_label="Choose a category",
        error_messages={"required": 'Choose a category. Pick "Other" if nothing fits.'},
        widget=forms.Select(attrs={"class": "select"}),
    )
    description = forms.CharField(
        error_messages={"required": "Describe the problem or what you need."},
        widget=forms.Textarea(attrs={"class": "textarea", "rows": 6}),
    )
    is_blocking = forms.BooleanField(required=False)
    attachments = AttachmentsField()
    password_ack = forms.BooleanField(required=False)
    password_warned = forms.BooleanField(required=False)

    def clean(self):
        cleaned = super().clean()
        self.check_for_passwords(cleaned)
        return cleaned


class ReplyForm(PasswordCheckMixin, forms.Form):
    """A requester's reply, or IT's public reply / internal note."""

    password_fields = ("body",)
    VISIBILITY_CHOICES = [("public", "Public reply"), ("internal", "Internal note")]

    body = forms.CharField(
        error_messages={"required": "Write a message first."},
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    visibility = forms.ChoiceField(choices=VISIBILITY_CHOICES, required=False, initial="public")
    # Set by the composer's "Send and set Waiting on User" / "Send and resolve" buttons.
    then_status = forms.ChoiceField(
        choices=[("", "Keep status"), (Ticket.Status.WAITING, "Waiting on User"), (Ticket.Status.RESOLVED, "Resolved")],
        required=False,
    )
    attachments = AttachmentsField()
    password_ack = forms.BooleanField(required=False)
    password_warned = forms.BooleanField(required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_visibility(self):
        value = self.cleaned_data.get("visibility") or "public"
        # Only IT can write internal notes, whatever the browser sends.
        if value == "internal" and not self.user.is_agent:
            raise forms.ValidationError("Only IT can add internal notes.")
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("then_status"):
            if not self.user.is_agent:
                self.add_error("then_status", "Only IT can change the status when replying.")
            elif cleaned.get("visibility") == "internal":
                # The requester wouldn't be told why their ticket changed.
                self.add_error("then_status", "Change the status with a public reply, or use the side panel.")
        self.check_for_passwords(cleaned)
        return cleaned

    @property
    def is_internal(self) -> bool:
        return self.cleaned_data.get("visibility") == "internal"


def agent_choices(ticket: Ticket | None = None):
    query = Q(role__in=[User.Role.AGENT, User.Role.ADMIN], is_active=True)
    if ticket and ticket.assignee_id:
        query |= Q(pk=ticket.assignee_id)  # keep the current assignee selectable
    return User.objects.filter(query).order_by("display_name")


class TicketPropertiesForm(forms.Form):
    """IT's side panel: status, priority, assignee, category."""

    status = forms.ChoiceField(choices=Ticket.Status.choices, widget=forms.Select(attrs={"class": "select select-sm"}))
    priority = forms.TypedChoiceField(
        choices=sorted(Ticket.Priority.choices, reverse=True), coerce=int,
        widget=forms.Select(attrs={"class": "select select-sm"}),
    )
    assignee = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="Unassigned",
        widget=forms.Select(attrs={"class": "select select-sm"}),
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(), empty_label=None,
        widget=forms.Select(attrs={"class": "select select-sm"}),
    )

    def __init__(self, *args, ticket: Ticket, me=None, **kwargs):
        kwargs.setdefault(
            "initial",
            {
                "status": ticket.status,
                "priority": ticket.priority,
                "assignee": ticket.assignee_id,
                "category": ticket.category_id,
            },
        )
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = agent_choices(ticket)
        if me is not None:
            self.fields["assignee"].label_from_instance = (
                lambda u: f"{u} (me)" if u.pk == me.pk else str(u)
            )
        self.fields["category"].queryset = Category.objects.filter(
            Q(is_active=True) | Q(pk=ticket.category_id)
        )
