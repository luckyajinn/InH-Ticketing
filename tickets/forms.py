from pathlib import Path

from django import forms
from django.conf import settings
from django.db.models import Q
from django.template.defaultfilters import filesizeformat

from accounts import people
from accounts.models import User
from core import departments
from tickets import password_guard
from tickets.models import TEXT_MAX_CHARS, Category, Ticket

POSSIBLE_PASSWORD = "possible_password"


def not_too_long(value: str) -> None:
    """Descriptions and replies: a clear message, rather than the browser cutting a paste short."""
    if len(value) > TEXT_MAX_CHARS:
        raise forms.ValidationError(
            f"That's {len(value):,} characters, over the {TEXT_MAX_CHARS:,} limit. "
            "Attach a long log or list as a file instead."
        )


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

    # A quick pick ("common requests") is the subject when one is chosen, so
    # the subject can be empty then. clean() checks it.
    subject = forms.CharField(
        max_length=200, required=False,
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "off"}),
    )
    # "<category id>:<number>" of a common request, never the text itself, so
    # only subjects an admin set up can be picked.
    subject_pick = forms.CharField(required=False)
    category = CategoryChoiceField(
        queryset=Category.objects.filter(is_active=True),
        empty_label="Choose a category",
        error_messages={"required": 'Choose a category. Pick "Other" if nothing fits.'},
        widget=forms.Select(attrs={"class": "select"}),
    )
    description = forms.CharField(
        error_messages={"required": "Describe the problem or what you need."},
        validators=[not_too_long],
        widget=forms.Textarea(attrs={"class": "textarea", "rows": 6}),
    )
    is_blocking = forms.BooleanField(required=False)
    attachments = AttachmentsField()
    password_ack = forms.BooleanField(required=False)
    password_warned = forms.BooleanField(required=False)
    # Staff only: open the request for someone else (at the desk, say). They
    # find a person the app knows by name or email, or type the work email
    # (and name) of someone it doesn't know yet. Ignored for everyone else.
    for_whom = forms.ChoiceField(choices=[("me", "Me"), ("other", "Someone else")], required=False)
    for_email = forms.EmailField(
        max_length=254, required=False,
        error_messages={"invalid": "Enter their full work email, like name@company.com."},
    )
    for_name = forms.CharField(max_length=120, required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    @property
    def can_open_for_others(self) -> bool:
        return bool(self.user and self.user.is_agent)

    @property
    def for_someone_else(self) -> bool:
        return self.can_open_for_others and (self["for_whom"].value() or "me") == "other"

    @property
    def quick_picks(self) -> list[tuple[Category, list[tuple[str, str]]]]:
        """Common requests of the active categories that have any: [(category, [(value, subject)])]."""
        groups = []
        for category in self.fields["category"].queryset:
            choices = category.subject_choices
            if choices:
                groups.append((category, [(f"{category.pk}:{i}", text) for i, text in enumerate(choices)]))
        return groups

    @property
    def picked_subject(self) -> str:
        """The subject of the common request chosen when the form was sent, or ""."""
        picked = self._picked(self.data.get("subject_pick")) if self.is_bound else None
        return picked[1] if picked else ""

    def _picked(self, value: str) -> tuple[Category, str] | None:
        """The (category, subject) a quick-pick value stands for, if it's a real, active one."""
        category_id, _, index = (value or "").partition(":")
        if not (category_id.isdecimal() and index.isdecimal()):
            return None
        category = self.fields["category"].queryset.filter(pk=int(category_id)).first()
        if category is None or int(index) >= len(category.subject_choices):
            return None
        return category, category.subject_choices[int(index)]

    def clean(self):
        cleaned = super().clean()
        picked = self._picked(cleaned.get("subject_pick"))
        # A chosen common request is the subject, over anything typed (the
        # page says so, and greys the subject out). It also sets the
        # department: a category the person chose themselves wins only if it's
        # that department's (the page offers no others once one is picked).
        # Otherwise, or with none chosen (as without JavaScript), it's the
        # pick's own category.
        if picked:
            category, text = picked
            cleaned["subject"] = text
            chosen = cleaned.get("category")
            if not chosen or chosen.department != category.department:
                cleaned["category"] = category
                self.errors.pop("category", None)
        if not cleaned.get("subject"):
            self.add_error("subject", "Enter a subject.")
        self._clean_requester(cleaned)
        self.check_for_passwords(cleaned)
        return cleaned

    def _clean_requester(self, cleaned: dict) -> None:
        """
        Who the request is for. Sets cleaned["requester"] to a person the app
        knows, or None with cleaned["new_person"] = (email, name) for one to
        add when the request is sent (requester()).
        """
        cleaned["requester"], cleaned["new_person"] = self.user, None
        if not self.for_someone_else:
            return
        email = (cleaned.get("for_email") or "").strip().lower()
        if not email:
            if "for_email" not in self.errors:
                self.add_error("for_email", "Enter their work email, or type part of their name to find them.")
            return
        known = people.by_email(email)
        if known is not None:
            if not known.is_active:
                self.add_error("for_email", f"{known}'s account is turned off. An admin can turn it back on in the admin site, under Users.")
                return
            cleaned["requester"] = known
            if known.pk == self.user.pk:
                return  # their own email: it's for them after all
        else:
            domains = people.work_domains(self.user)
            if domains and email.rsplit("@", 1)[-1] not in domains:
                self.add_error("for_email", "Use their work email: an address ending in " + " or ".join(f"@{d}" for d in domains) + ".")
                return
            name = " ".join((cleaned.get("for_name") or "").split())
            if not name:
                self.add_error("for_name", "Enter their name. They haven't used the help desk yet, so it doesn't know it.")
                return
            cleaned["requester"], cleaned["new_person"] = None, (email, name)
        category = cleaned.get("category")
        if category and not self.user.is_admin and category.department != self.user.agent_department:
            self.add_error(
                "category",
                f"For someone else, choose one of {self.user.department_label}'s categories. "
                "Only an admin can open another team's request for someone.",
            )

    def requester(self):
        """Who the request is for, adding the person now if the app didn't know them. After is_valid()."""
        if self.cleaned_data.get("new_person"):
            return people.add(*self.cleaned_data["new_person"])
        return self.cleaned_data["requester"]


class ReplyForm(PasswordCheckMixin, forms.Form):
    """A requester's reply, or IT's public reply / internal note."""

    password_fields = ("body",)
    VISIBILITY_CHOICES = [("public", "Public reply"), ("internal", "Internal note")]

    body = forms.CharField(
        error_messages={"required": "Write a message first."},
        validators=[not_too_long],
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    visibility = forms.ChoiceField(choices=VISIBILITY_CHOICES, required=False, initial="public")
    # Internal notes only: go with the ticket if an admin moves it to another department.
    share_on_move = forms.BooleanField(required=False)
    # Set by the composer's "Send and set Waiting on User" / "Send and resolve" buttons.
    then_status = forms.ChoiceField(
        choices=[("", "Keep status"), (Ticket.Status.WAITING, "Waiting on User"), (Ticket.Status.RESOLVED, "Resolved")],
        required=False,
    )
    attachments = AttachmentsField()
    password_ack = forms.BooleanField(required=False)
    password_warned = forms.BooleanField(required=False)

    def __init__(self, *args, user, ticket: Ticket | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.ticket = ticket

    def _works(self) -> bool:
        return self.user.works_on(self.ticket) if self.ticket else self.user.is_agent

    def clean_visibility(self):
        value = self.cleaned_data.get("visibility") or "public"
        # Only staff working the ticket can write internal notes, whatever the browser sends.
        if value == "internal" and not self._works():
            raise forms.ValidationError("Only staff working this ticket can add internal notes.")
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("then_status"):
            if not self._works():
                self.add_error("then_status", "Only staff working this ticket can change the status when replying.")
            elif cleaned.get("visibility") == "internal":
                # The requester wouldn't be told why their ticket changed.
                self.add_error("then_status", "Change the status with a public reply, or use the side panel.")
        self.check_for_passwords(cleaned)
        return cleaned

    @property
    def is_internal(self) -> bool:
        return self.cleaned_data.get("visibility") == "internal"

    @property
    def shares_on_move(self) -> bool:
        """An internal note marked to go with the ticket if it moves department."""
        return self.is_internal and bool(self.cleaned_data.get("share_on_move"))


def agent_choices(ticket: Ticket | None = None):
    """Who a ticket can be assigned to: its department's agents, and admins."""
    agents = Q(role=User.Role.AGENT)
    if ticket is not None:
        department = ticket.department
        agents &= Q(department=department) | (Q(department="") if department == departments.IT else Q(pk__in=[]))
    query = (agents | Q(role=User.Role.ADMIN)) & Q(is_active=True)
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
        # Within the ticket's department only: moving it elsewhere is MoveForm, for admins.
        self.fields["category"].queryset = Category.objects.filter(
            (Q(is_active=True) & Q(department=ticket.category.department)) | Q(pk=ticket.category_id)
        )


class RemovalForm(forms.Form):
    """What an admin takes out of one part of a ticket (the subject, the request, or a message)."""

    text = forms.CharField(
        required=False, max_length=500, strip=False,
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "off", "spellcheck": "false"}),
    )
    whole = forms.BooleanField(required=False)
    # Not "files": a form's .files is its uploads.
    remove_files = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, current: str, files=(), allow_whole: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.current = current
        self.allow_whole = allow_whole
        self.attachments = {str(a.pk): a for a in files}
        self.fields["remove_files"].choices = [(pk, a.original_name) for pk, a in self.attachments.items()]

    def clean(self):
        cleaned = super().clean()
        text, whole = cleaned.get("text") or "", cleaned.get("whole") and self.allow_whole
        cleaned["whole"] = bool(whole)
        if text and not whole:
            if len(text.strip()) < 4:
                self.add_error("text", "Enter at least 4 characters, so only the password is removed.")
            elif text not in self.current:
                self.add_error("text", "That text isn't in this message. Copy it exactly as it appears above.")
        if not text.strip() and not whole and not cleaned.get("remove_files"):
            raise forms.ValidationError("Enter the text to remove, or choose what else to remove.")
        cleaned["attachments"] = [self.attachments[pk] for pk in cleaned.get("remove_files") or []]
        return cleaned


class MoveForm(forms.Form):
    """An admin moves a ticket to another department's category."""

    category = forms.ModelChoiceField(
        queryset=Category.objects.none(), empty_label="Choose a category",
        widget=forms.Select(attrs={"class": "select select-sm"}),
        error_messages={"required": "Choose where it goes."},
    )
    confirmed = forms.BooleanField(
        error_messages={"required": "Check with the other department first, then tick this."},
    )

    def __init__(self, *args, ticket: Ticket, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True).exclude(
            department=ticket.category.department
        )
        names = dict(departments.choices())
        self.fields["category"].label_from_instance = (
            lambda c: f"{names.get(c.department, c.department)}: {c.name}"
        )


class MoveRequestForm(forms.Form):
    """Staff ask an admin to move a ticket that landed in the wrong department."""

    department = forms.ChoiceField(choices=(), widget=forms.Select(attrs={"class": "select select-sm"}))
    reason = forms.CharField(
        max_length=200, required=False,
        widget=forms.TextInput(attrs={"class": "input input-sm", "placeholder": "Why (optional)"}),
    )

    def __init__(self, *args, ticket: Ticket, **kwargs):
        super().__init__(*args, **kwargs)
        # Only departments a ticket can go to: with at least one active category.
        open_to = set(Category.objects.filter(is_active=True).values_list("department", flat=True))
        self.fields["department"].choices = [
            (value, label) for value, label in departments.choices()
            if value != ticket.category.department and value in open_to
        ]
