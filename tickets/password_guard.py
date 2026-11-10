"""
Catch passwords before they're sent, and keep an audit trail.

People sometimes paste a password into a request ("my password is ..."), a
reply, or an email to the help desk. find() looks for anything that might be
one. It leans towards false alarms on purpose: a wrong warning costs one click
("send anyway"), while a missed password sits in the ticket and in everyone's
mailbox.

Three checks:
    labelled  a value after a word like "password", "pw", "passcode" or
              "pin is"   ("my password is Summer24", "pw: hunter2")
    code      a sign-in, verification, recovery or PIN code
              ("the code is 482913", "PIN 4821")
    token     a word that looks like a password on its own
              ("Summer2024!", "xK9mQ2pL", "Password1")

The audit trail (PasswordWarning) records who, where, which checks matched and
what the person chose. It never stores the text that matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# Words that are enough on their own to mean "a password follows".
_STRONG_LABEL = (
    r"pass[\s-]?words?|pas+w(?:o|e)?r?ds?|passowrds?|pswds?|pwds?|pw|p/w|pwords?"
    r"|pass[\s-]?codes?|pass[\s-]?phrases?"
)
# Ordinary words too ("pass it on"), so they need a separator such as ":" or
# "is" straight after them, or a next word that looks like a password.
_WEAK_LABEL = r"pass|pins?|pin[\s-]?codes?|secrets?"
# Usually followed by a username, so the value must look like a password too.
_LOGIN_LABEL = r"log[\s-]?ins?|sign[\s-]?ins?|credentials?|creds"

_LABEL_RE = re.compile(
    rf"(?<![\w/@])(?:(?P<strong>{_STRONG_LABEL})|(?P<weak>{_WEAK_LABEL})|(?P<login>{_LOGIN_LABEL}))(?![\w/@])",
    re.I,
)
_SEP_RE = re.compile(
    r"\s*[:=]+\s*|\s*-+>\s*|\s+[-–—]\s+"
    r"|\s+(?:is|was|are)(?:\s+(?:now|still|currently))?\s*:?\s*"
    r"|\s+(?:changed|set|reset|updated)\s+to\s+"
    r"|\s+(?:should|will|would)\s+be\s+",
    re.I,
)
_WORD_RE = re.compile(r"[ \t]+([^\s:=]+)")
_VALUE_RE = re.compile(r"[\"'“‘(\[<]?(?P<value>[^\s\"'”’)\]>]{3,})")

# Words that follow "password is" without being a password.
_NOT_A_VALUE = set("""
a an the my your his her their our its it this that these those some any all same different
is was be been being are will would should could can cant cannot wont doesnt isnt wasnt didnt dont
has have had keeps keep asks asking ask for to of in on at and or but so if as by with without from
when what which who how why there here also too very really already just only still now not no none
expired expire expires expiring expiry expiration reset resets resetting change changed changes changing
update updated updating wrong incorrect invalid correct right ok okay fine good bad blank empty missing
unknown forgotten forgot lost locked unlocked disabled enabled saved stored remembered accepted rejected
denied ready set done sent working work works required requirement requirements needed needs need
manager policy prompt prompts prompting field box screen page window please help again issue issues
problem problems error errors request requests length characters character hint hints protected
case sensitive long short strong weak secure complex simple new old temporary temp current previous
default
""".split())

# "code", "PIN" and friends followed by 4 to 8 digits.
_CODE_RE = re.compile(
    r"(?<![\w-])(?:(?P<pre>[A-Za-z]+)\s+)?"
    r"(?:codes?|otp|pins?|pin[\s-]?codes?|recovery[\s-]?keys?|backup[\s-]?codes?"
    r"|one[\s-]?time[\s-]?(?:code|passcode|password)s?|verification|authenticator|mfa|2fa|two[\s-]?factor)"
    r"\b[^\d\n]{0,18}?(?<![\d.])(?P<value>\d{4,8}|\d{3}[\s-]\d{3})(?![\d.])",
    re.I,
)
# Codes that are just numbers people quote: "error code 1603", "zip code 90210".
_CODE_NOT_AFTER = {"error", "exit", "status", "zip", "postal", "area", "product", "promo", "discount", "country", "dial", "event", "return"}

_TOKEN_RE = re.compile(r"\S+")
_WRAPPERS = "\"'“”‘’()[]{}<>`*"
# Product and model names that would otherwise look like passwords ("Office365").
_KNOWN_NAMES = re.compile(
    r"^(?:microsoft|office|o365|m365|windows|win-?\d|iphone|ipad|ipados|ios|macos|android|galaxy|pixel"
    r"|surface|thinkpad|ideapad|latitude|optiplex|precision|elitebook|probook|zbook|macbook|imac"
    r"|outlook|teams|onedrive|sharepoint|exchange|excel|onenote|powerpoint|powerbi|powershell|python"
    r"|chrome|firefox|acrobat|autocad|quickbooks|webex|bitlocker|intune|azure|forticlient|globalprotect)"
    r"[\w.-]*$",
    re.I,
)
# Common password patterns that are short or plain: "Summer24", "welcome1".
_COMMON_STEMS = re.compile(
    r"^(?:spring|summer|fall|autumn|winter|welcome|changeme|letmein|qwerty|admin|password|passw0rd"
    r"|p@ssw0rd|p@ssword|monkey|dragon|football|baseball|sunshine|iloveyou)\W*\d{1,4}\W*$",
    re.I,
)
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HEX_RE = re.compile(r"^(?:0x)?[0-9a-f]+$", re.I)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_PLAIN_PUNCT = set("-_.'")


@dataclass(frozen=True)
class Finding:
    rule: str  # "labelled", "code" or "token"
    start: int
    end: int  # the suspected password is text[start:end]
    hint: str  # the words before it, with the password itself masked


def _mask(text: str, start: int, end: int) -> str:
    """'...my password is S•••••••' The same number of dots whatever the length."""
    before = " ".join(text[max(0, start - 40):start].split()[-4:])
    masked = text[start] + "•" * 7
    sep = " " if before and text[start - 1].isspace() else ""
    return f"…{before}{sep}{masked}" if before else masked


def _clean_value(value: str) -> str:
    return value.rstrip(".,;:!?").lower().replace("'", "").replace("’", "")


def _next_word_if_secret(text: str, pos: int, *, need_digit_or_symbol: bool = False):
    """'pw hunter2': no separator, but the next word looks like a password."""
    gap = re.compile(r"[ \t]+").match(text, pos)
    if not gap:
        return None
    candidate = _VALUE_RE.match(text, gap.end())
    if not candidate or not _looks_secret(candidate.group("value"), need_digit_or_symbol):
        return None
    return candidate


def _labelled(text: str) -> list[Finding]:
    found = []
    for label in _LABEL_RE.finditer(text):
        strong = bool(label.group("strong"))
        login = bool(label.group("login"))
        pos = label.end()
        value = None
        sep = _SEP_RE.match(text, pos)
        if sep:
            value = _VALUE_RE.match(text, sep.end())
            if login and value and not _looks_secret(value.group("value")):
                value = None  # "login: jdoe" is a username
        elif label.group("weak"):
            value = _next_word_if_secret(text, pos, need_digit_or_symbol=True)
        elif strong:
            # "the password for the VPN is ...": a few words, then a separator.
            q = pos
            for _ in range(4):
                word = _WORD_RE.match(text, q)
                if not word or word.group(1)[-1] in ".!?":
                    break
                q = word.end()
                sep = _SEP_RE.match(text, q)
                if sep:
                    value = _VALUE_RE.match(text, sep.end())
                    break
            if value is None:
                value = _next_word_if_secret(text, pos)
        if not value:
            continue
        word = value.group("value")
        if _clean_value(word) in _NOT_A_VALUE or not any(c.isalnum() for c in word):
            continue
        start, end = value.start("value"), value.end("value")
        found.append(Finding("labelled", start, end, _mask(text, start, end)))
    return found


def _codes(text: str) -> list[Finding]:
    found = []
    for match in _CODE_RE.finditer(text):
        if (match.group("pre") or "").lower() in _CODE_NOT_AFTER:
            continue
        start, end = match.start("value"), match.end("value")
        found.append(Finding("code", start, end, _mask(text, start, end)))
    return found


def _looks_secret(word: str, need_digit_or_symbol: bool = False) -> bool:
    """A digit, a symbol, or (unless need_digit_or_symbol) a capital after the first letter."""
    word = word.rstrip(".,;:!?")
    if any(c.isdigit() for c in word) or any(not c.isalnum() and c not in _PLAIN_PUNCT for c in word):
        return True
    return not need_digit_or_symbol and any(c.isupper() for c in word[1:])


def _token_is_password(token: str) -> bool:
    if len(token) < 4:
        return False
    if _COMMON_STEMS.match(token):
        return True
    if _KNOWN_NAMES.match(token):
        return False
    lowered = token.lower()
    if "://" in token or lowered.startswith("www.") or "/" in token or "\\" in token:
        return False  # links and file paths
    if _EMAIL_RE.match(token) or _GUID_RE.match(token) or _HEX_RE.match(token):
        return False  # email addresses, IDs from error messages, hex codes
    if token.isdigit() or (token.startswith("#") and token[1:].isdigit()):
        return False  # numbers and ticket references
    lower = any(c.islower() for c in token)
    upper = any(c.isupper() for c in token)
    digit = any(c.isdigit() for c in token)
    symbol = any(not c.isalnum() and c not in _PLAIN_PUNCT for c in token)
    letter = lower or upper
    core = token.rstrip("!")  # "I forgot my password!" isn't one
    if ("pass" in lowered or "p@ss" in lowered) and (
        any(c.isdigit() for c in core) or any(not c.isalnum() and c not in _PLAIN_PUNCT for c in core)
    ):
        return True  # "Password1", "P@ssw0rd!"
    if len(token) >= 8 and letter and digit and symbol:
        return True  # "Welcome1!", "Tr0ub4dor&3"
    if len(token) >= 8 and lower and upper and digit:
        return True  # "Summer2024", "xK9mQ2pL"
    if len(token) >= 20 and letter and digit:
        return True  # keys and tokens
    return False


def _tokens(text: str) -> list[Finding]:
    found = []
    for match in _TOKEN_RE.finditer(text):
        raw = match.group()
        token = raw.strip(_WRAPPERS).rstrip(".,;:?")
        token = token.strip(_WRAPPERS)
        if not token or not _token_is_password(token):
            continue
        start = match.start() + raw.index(token)
        end = start + len(token)
        found.append(Finding("token", start, end, _mask(text, start, end)))
    return found


def find(text: str) -> list[Finding]:
    """Everything in text that might be a password, in order, without overlaps."""
    if not text:
        return []
    candidates = sorted(_labelled(text) + _codes(text) + _tokens(text), key=lambda f: (f.start, -f.end))
    kept: list[Finding] = []
    for finding in candidates:
        if kept and finding.start < kept[-1].end:
            continue
        kept.append(finding)
    return kept


FIELD_NAMES = {"subject": "the subject", "description": "the description", "body": "your message"}


def hints(found: dict[str, list[Finding]]) -> list[str]:
    """One line per finding, e.g. 'In the description: …my password is S•••••••'."""
    lines = []
    for field, findings in found.items():
        for finding in findings[:3]:
            lines.append(f"In {FIELD_NAMES.get(field, field)}: {finding.hint}")
    return lines[:6]


def rules_used(found: dict[str, list[Finding]]) -> str:
    rules = sorted({f.rule for findings in found.values() for f in findings})
    return ", ".join(rules)


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def _record(*, outcome, place, user, ticket=None, comment=None, found=None):
    # Imported here: models imports nothing from this module, and forms import
    # find() from it, so this keeps the import order simple.
    from tickets.models import PasswordWarning, TicketEvent

    found = found or {}
    row = PasswordWarning.objects.create(
        user=user, ticket=ticket, comment=comment, place=place, outcome=outcome,
        fields=", ".join(found)[:100], rules=rules_used(found)[:100],
    )
    # IT sees a line in the ticket's history when a possible password went
    # through. Requesters never see history lines.
    if ticket is not None and outcome != PasswordWarning.Outcome.REMOVED:
        note = (
            "sent anyway after a warning"
            if outcome == PasswordWarning.Outcome.SENT_ANYWAY
            else "arrived by email, so no warning could be shown"
        )
        TicketEvent.objects.create(
            ticket=ticket, actor=user, kind=TicketEvent.Kind.PASSWORD,
            new_value=PasswordWarning.PLACE_PHRASES[place], note=note,
        )
    return row


def record_form(form, *, user, place, ticket, comment=None):
    """
    After a web form was sent: log "sent anyway" if it still had a possible
    password, or "removed" if the person was warned and took it out.
    """
    from tickets.models import PasswordWarning

    found = getattr(form, "password_findings", {}) or {}
    if found and form.cleaned_data.get("password_ack"):
        outcome = PasswordWarning.Outcome.SENT_ANYWAY
    elif not found and form.cleaned_data.get("password_warned"):
        outcome = PasswordWarning.Outcome.REMOVED
    else:
        return None
    return _record(outcome=outcome, place=place, user=user, ticket=ticket, comment=comment, found=found)


def record_email(*, sender, ticket, texts: dict[str, str], comment=None):
    """An email can't be warned about before it's sent, so just log it for IT."""
    from tickets.models import PasswordWarning

    found = {name: f for name, text in texts.items() if (f := find(text or ""))}
    if not found:
        return None
    return _record(
        outcome=PasswordWarning.Outcome.EMAILED, place=PasswordWarning.Place.EMAIL,
        user=sender, ticket=ticket, comment=comment, found=found,
    )
