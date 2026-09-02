"""RFC-9457 problem+json — the ONE error shape every service emits.

BACKEND-PATTERNS §3 is the spec: the raghava normalization ladder mapped onto
problem+json extensions (`kind`, `retryable`, `remediation`, `trace_id`, `fields`).
Rules that are not negotiable:

- Internal 500s log full detail server-side (redacted) and return a generic body —
  never an internals leak (hard rule: user-safe messages).
- 429 carries `Retry-After` from the limiter.
- 503 is the ONE status allowed to keep its detailed message (ops-UI contract).
- Every 5xx also fires the alert path with a `failure_stage` tag (§8).
- Every string a screen renders — `title`, `detail`, `remediation` and the sentences
  under `fields` — is written for a person, not for an API client: no type names, no
  status codes, no library validator text, no column names. `tests/
  plain_language_guard_test.py` holds the line; the "Plain language" block below is
  where the ladder's own wording lives.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from http import HTTPStatus
from typing import Any, Literal, Self

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.core.alerting import FailureStage, alert
from apps.api.core.context import correlation_id_var
from apps.api.core.logging import get_logger

log = get_logger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_BASE = "https://calevate.tech/problems"

# The ladder. `retryable` tells a typed client whether a retry can possibly help —
# it is part of the contract, not a hint.
ErrorKind = Literal[
    "validation",
    "auth",
    "permission",
    "not_found",
    "conflict",
    "business_rule",
    "dependency",
    "transient",
    "internal",
]

_DEFAULT_STATUS: dict[ErrorKind, int] = {
    "validation": 422,
    "auth": 401,
    "permission": 403,
    "not_found": 404,
    "conflict": 409,
    "business_rule": 422,
    "dependency": 502,
    "transient": 503,
    "internal": 500,
}

_RETRYABLE: frozenset[ErrorKind] = frozenset({"dependency", "transient"})

# THE LADDER'S FLOOR: what a person can DO about a failure of this kind when the raise
# site said nothing (D-300).
#
# `remediation` is one of the five extensions BACKEND-PATTERNS §3 puts on the ladder, and
# it was the only one that could be absent: `kind`, `retryable`, `title` and `detail` are
# constructor arguments, `trace_id` comes from the correlation id, and `remediation` was
# an optional keyword 104 raise sites remembered and 66 did not. The ones that forgot
# were not the obscure ones — `forbidden()` and `unauthorized()` are raised by
# `auth.requires()` on EVERY 403 and EVERY 401 in the product, the framework handlers
# below answer every unknown path, every wrong method and every schema failure, and the
# generic 500 is what a caller sees when nothing else caught. So the most reachable
# failures on the whole HTTP surface were the ones with no next step on them, while a
# rare business rule three modules deep had a sentence.
#
# A DEFAULT PER KIND RATHER THAN 66 EDITS, because the alternative rots in one direction
# only: a new raise site is written by someone reading a neighbouring one, and the
# neighbour that forgot is the cheaper example to copy. This closes the class instead of
# its instances — including in `apps/api/engine/`, whose vendor failures surface as 502s
# to a client who cannot be told to "check the identifier" — and an explicit
# `remediation=` still wins, so every sentence already written stays exactly as written.
#
# Each line is what the READER can do, never what we would do: "give our team the support
# reference" is an action a person can take, "the team has been alerted" is not. The
# reference is called that, and not the trace id, because that is what the console labels
# it and a person quoting it should not have to translate.
_DEFAULT_REMEDIATION: dict[ErrorKind, str] = {
    "validation": "Fix what is listed here, then try again.",
    "auth": "Sign in again — your session may have ended, or this account cannot be used here.",
    "permission": (
        "Ask an owner of the account to give you access, or do this from an account that "
        "already has it."
    ),
    "not_found": "Check what you are looking for, and that you are in the right account.",
    "conflict": "Reload the page — something changed since you opened it — then try again.",
    "business_rule": (
        "Change what you are doing so it fits the rule described here, then try again."
    ),
    "dependency": (
        "An outside service did not answer. Wait a minute and try again. If it keeps "
        "happening, give our team the support reference shown with this message."
    ),
    "transient": "Wait a few seconds, then try again.",
    "internal": (
        "Try again in a moment. If it keeps happening, give our team the support reference "
        "shown with this message."
    ),
}


# --- Plain language ------------------------------------------------------------------
#
# WHY: a live sign-in refusal was photographed reading "One or more fields are invalid. /
# Correct the fields named in this response and send the request again. / password:
# String should have at least 12 characters." Four failures in one box — a sentence
# addressed to an API client, pydantic's own validator text passed through verbatim (it
# names a TYPE), the input named in its programmatic spelling, and a 32-character support
# reference given equal weight to the one thing the person had to do, which was use a
# longer password.
#
# The standard every string below is written to: say what happened in the reader's own
# words, say what they can do next, and never name an internal — a type, a status code,
# an exception class, a table or a column. Sentences stay short because this is a
# Telugu-first product and all of them get translated.

#: `_`-separated tokens whose plain rendering is not their spelling. Left: what the API
#: calls the input. Right: what a person calls it.
_LABEL_TOKENS: dict[str, str] = {
    "ai": "AI",
    "api": "API",
    "crm": "CRM",
    "dlt": "DLT",
    "dnc": "DNC",
    "gstin": "GSTIN",
    "id": "ID",
    "ids": "IDs",
    "kb": "knowledge base",
    "llm": "AI model",
    "otp": "one-time code",
    "pan": "PAN",
    "pe": "principal entity",
    "sms": "SMS",
    "stt": "speech recognition",
    "tm": "telemarketer",
    "tts": "voice",
    "url": "web address",
    "uuid": "ID",
}

#: Whole names whose humanised form would still read like a column.
_LABEL_OVERRIDES: dict[str, str] = {
    "body": "What you sent",
    "e164": "Phone number",
    "msisdn": "Phone number",
    "slug": "Web address name",
}

#: The source fastapi prepends to every `loc`. Never part of what a person filled in.
_LOC_SOURCES = frozenset({"body", "query", "path", "header", "cookie"})

#: Pydantic's own phrasings. Our validators raise `ValueError` with sentences we wrote and
#: those are worth showing; these openings mean the text came from the library instead, and
#: the library writes for whoever implements the model, not for whoever fills in the form.
_LIBRARY_PHRASINGS = (
    "input should",
    "string should",
    "value is not a valid",
    "value error",
    "field required",
    "extra inputs",
    "ensure this value",
    "unable to interpret",
    "assertion failed",
)


def _humanise_token(token: str) -> str:
    return _LABEL_TOKENS.get(token.lower(), token.lower())


def field_label(loc: Sequence[object]) -> str:
    """The name of an input as a person would say it, from pydantic's `loc` tuple.

    There is no richer source available here. `RequestValidationError` carries locations
    and rules, never the model, so a `Field(title=...)` cannot be reached from the
    handler — the label is derived from the name, with the two tables above fixing the
    tokens that derivation gets wrong. Where a raise site knows better it passes its own
    sentence, and that always wins.

    List positions are rendered as "item 3" rather than the index, and only the last two
    names are kept: "Contact phone number", never the whole path down a nested model.
    """
    parts = [str(p) for p in loc]
    if parts and parts[0] in _LOC_SOURCES:
        parts = parts[1:]
    if not parts:
        return _LABEL_OVERRIDES["body"]
    names: list[str] = []
    for part in parts:
        if part.isdigit():
            # The position belongs to the thing before it: `tags.2.name` is the name of
            # item 3, not a field called "2".
            if names:
                names[-1] = f"{names[-1]} item {int(part) + 1}"
            continue
        names.append(part)
    if not names:
        return _LABEL_OVERRIDES["body"]
    tail = names[-2:]
    words: list[str] = []
    for name in tail:
        override = _LABEL_OVERRIDES.get(name)
        if override is not None:
            words.append(override if not words else override.lower())
            continue
        words.extend(_humanise_token(token) for token in name.replace("-", "_").split("_") if token)
    # `otp_code` expands to "one-time code code": the token table already spells the
    # noun, and the name repeats it. Adjacent duplicates go.
    spoken: list[str] = []
    for word in " ".join(w for w in words if w).split():
        if not spoken or spoken[-1].lower() != word.lower():
            spoken.append(word)
    label = " ".join(spoken).strip()
    if not label:
        return _LABEL_OVERRIDES["body"]
    return label[0].upper() + label[1:]


def _plural(count: int, singular: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"


def _our_own_sentence(ctx: Mapping[str, Any]) -> str | None:
    """A `ValueError` one of our validators raised, when it reads like a sentence.

    Worth keeping: "Phone numbers must start with +91" is better than anything a generic
    map can produce. Worth dropping: pydantic re-uses `value_error` for its own failures
    (an email address is one), and those openings are the library talking.
    """
    raw = str(ctx.get("error") or ctx.get("reason") or "").strip()
    if not raw or len(raw) < 8:
        return None
    if any(raw.lower().startswith(opening) for opening in _LIBRARY_PHRASINGS):
        return None
    sentence = raw[0].upper() + raw[1:]
    return sentence if sentence.endswith((".", "?", "!")) else sentence + "."


def _message_for(rule: str, label: str, ctx: Mapping[str, Any], msg: str) -> str:
    """One pydantic failure as a sentence a person can act on.

    Rules are matched by their machine name, never by the message text: the text is what
    we are refusing to show, and it changes between pydantic releases anyway. Verified
    against pydantic v2 in this repo (`string_too_short` carries `min_length`, list
    `too_short` carries `field_type`/`min_length`, `literal_error` carries `expected`,
    an `EmailStr` failure arrives as `value_error` with a `reason`) on 2 Sep 2026.
    """
    if rule == "missing":
        # "Enter your date of birth", not "Date of birth is required" — GOV.UK's
        # "Recover from validation errors" pattern, which this module's guard test cites
        # as its standard: tell the person what to DO, in the words they would use. "Is
        # required" states our constraint and leaves them to infer the action.
        return f"Enter {label[0].lower() + label[1:]}."
    if rule == "extra_forbidden":
        return f"We do not use {label.lower()} here, so it cannot be saved."
    if rule in ("string_too_short", "too_short"):
        least = ctx.get("min_length")
        if ctx.get("field_type") == "List":
            return f"{label} needs at least {_plural(int(least or 1), 'item')}."
        if least is not None:
            return f"{label} needs to be at least {_plural(int(least), 'character')}."
        return f"{label} is too short."
    if rule in ("string_too_long", "too_long"):
        most = ctx.get("max_length")
        if ctx.get("field_type") == "List":
            return f"{label} can have at most {_plural(int(most or 1), 'item')}."
        if most is not None:
            return f"{label} can be at most {_plural(int(most), 'character')}."
        return f"{label} is too long."
    if rule == "string_pattern_mismatch":
        # Never the pattern itself: a regex is not something a person can read, and the
        # raise site that cares should say what the shape is in its own words.
        return f"{label} is not in the form we can accept."
    if rule in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        limits = {
            "greater_than": ("more than", "gt"),
            "greater_than_equal": ("at least", "ge"),
            "less_than": ("less than", "lt"),
            "less_than_equal": ("at most", "le"),
        }
        wording, key = limits[rule]
        bound = ctx.get(key)
        return (
            f"{label} has to be {wording} {bound}."
            if bound is not None
            else f"{label} is out of range."
        )
    if rule in ("literal_error", "enum"):
        # pydantic quotes each choice ("'a' or 'b'"); the quotes are punctuation from a
        # repr, and the choices themselves are what the person picks between.
        expected = str(ctx.get("expected") or "").replace("'", "").strip()
        return (
            f"{label} has to be one of: {expected}."
            if expected
            else f"{label} is not one we offer."
        )
    if rule.startswith(("int_", "float_", "decimal_")):
        return f"{label} has to be a number."
    if rule.startswith("bool_"):
        return f"{label} has to be yes or no."
    if rule.startswith(("date_", "datetime_", "time_", "timedelta_")):
        return f"{label} has to be a date and time."
    if rule.startswith("uuid_"):
        return f"{label} is not an ID we recognise."
    if rule.startswith("url_"):
        return f"{label} has to be a web address starting with https://"
    if rule == "value_error":
        if "email address" in msg:
            if "email" in label.lower():
                return f"{label} has to look like name@example.com."
            return f"{label} has to be an email address, like name@example.com."
        return _our_own_sentence(ctx) or f"{label} is not something we can accept."
    if rule == "json_invalid":
        return "We could not read what was sent."
    if rule.endswith("_type"):
        return f"{label} is not in the form we can accept."
    return f"{label} is not something we can accept."


def humanise_validation_errors(
    errors: Iterable[Mapping[str, Any]], *, drop_source: bool
) -> list[dict[str, str]]:
    """Pydantic's error list as our `{field, label, rule, message}` entries.

    `field` stays the programmatic path — the console needs it to put the message beside
    the right input — and `label` is the same thing in a person's spelling, so a screen
    never has to print `password:` at somebody. `message` is ours; pydantic's `msg` is
    read only to tell an email failure from any other `value_error`, and never rendered.

    THE INPUT IS DROPPED, always (hard rule 6): pydantic v2 puts `input_value` in its own
    string form of an error, and on the sign-in route that value is the password itself.

    `drop_source` is the one difference between the two callers. Fastapi prepends
    `"body"`/`"query"` to every `loc`; a `ValidationError` from a hand-called
    `model_validate` does not, and stripping there would eat the top-level field name.
    """
    entries: list[dict[str, str]] = []
    for err in errors:
        loc = tuple(err.get("loc", ()))
        rule = str(err.get("type", "invalid"))
        ctx = err.get("ctx") or {}
        label = field_label(loc if drop_source else ("body", *loc))
        entries.append(
            {
                "field": ".".join(str(p) for p in (loc[1:] if drop_source else loc)) or "body",
                "label": label,
                "rule": rule,
                "message": _message_for(rule, label, ctx, str(err.get("msg", ""))),
            }
        )
    return entries


def validation_summary(entries: Sequence[Mapping[str, str]]) -> str:
    """What the box says above the list. One problem gets said outright; several get
    counted and then the first two, because a wall of sentences is read as none."""
    messages = [str(e.get("message", "")) for e in entries if e.get("message")]
    if not messages:
        return "Something in this form needs fixing."
    if len(messages) == 1:
        return messages[0]
    if len(messages) <= 3:
        return " ".join(messages)
    return f"{messages[0]} {messages[1]} There are {len(messages) - 2} more to fix."


class ProblemError(Exception):
    """Raise this, never HTTPException — the handler renders problem+json.

    `code` is the stable machine identifier the frontend switches on; it becomes
    the last segment of `type` (`https://calevate.tech/problems/<code>`).
    """

    def __init__(
        self,
        *,
        kind: ErrorKind,
        code: str,
        title: str,
        detail: str,
        status: int | None = None,
        remediation: str | None = None,
        fields: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
        failure_stage: FailureStage = "ROUTE_HANDLER",
    ) -> None:
        self.kind = kind
        self.code = code
        self.title = title
        self.detail = detail
        self.status = status if status is not None else _DEFAULT_STATUS[kind]
        self.remediation = remediation
        self.fields = fields
        self.headers = headers or {}
        self.failure_stage: FailureStage = failure_stage
        super().__init__(f"{code}: {detail}")

    def as_problem(self, instance: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": f"{PROBLEM_BASE}/{self.code}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "kind": self.kind,
            "retryable": self.kind in _RETRYABLE,
        }
        if instance:
            body["instance"] = instance
        # Never absent: the raise site's sentence when it wrote one, this kind's floor
        # otherwise. `remediation` is the extension a screen renders as the next step, and
        # a failure with no next step is the one a user files a ticket about.
        body["remediation"] = self.remediation or _DEFAULT_REMEDIATION[self.kind]
        if self.fields:
            body["fields"] = self.fields
        trace_id = correlation_id_var.get()
        if trace_id:
            body["trace_id"] = trace_id
        return body

    # --- Constructors for the cases we raise constantly ----------------------

    @classmethod
    def not_found(cls, what: str, ident: str | None = None) -> Self:
        return cls(
            kind="not_found",
            code="not_found",
            title=f"{what} not found",
            # No ident echo for tenant-scoped objects: under RLS "not found" and
            # "belongs to another tenant" are the same answer, deliberately.
            detail=f"We could not find that {what.lower()}.",
            remediation=(
                "Check what you are looking for, and that you are in the right account. It "
                "may also have been deleted."
            ),
        )

    @classmethod
    def conflict(cls, code: str, detail: str, *, remediation: str | None = None) -> Self:
        return cls(
            kind="conflict",
            code=code,
            title="We could not complete that",
            detail=detail,
            remediation=remediation,
        )

    @classmethod
    def forbidden(cls, detail: str = "This account cannot open this part of Calevate.") -> Self:
        return cls(
            kind="permission", code="forbidden", title="You do not have access", detail=detail
        )

    @classmethod
    def unauthorized(cls, detail: str = "You need to be signed in to do this.") -> Self:
        return cls(
            kind="auth",
            code="unauthorized",
            title="Please sign in",
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    @classmethod
    def business_rule(cls, code: str, detail: str, *, remediation: str | None = None) -> Self:
        return cls(
            kind="business_rule",
            code=code,
            title="We cannot do that",
            detail=detail,
            remediation=remediation,
        )


class InvalidStatusTransitionError(ProblemError):
    """The CAS-lost-the-race / illegal-state-machine-move error (BACKEND-PATTERNS §5)."""

    def __init__(self, entity: str, frm: str, to: str) -> None:
        super().__init__(
            kind="conflict",
            code="invalid_status_transition",
            title="That change is not possible",
            detail=f"A {entity} cannot go from {frm} to {to}.",
            remediation="Reload the page — someone else may have changed it.",
        )


def validation_fields(exc: Exception) -> list[dict[str, str]]:
    """A hand-caught pydantic `ValidationError` as our `{field, label, rule, message}`
    entries, with the offending `input` DROPPED (hard rule 6: it can be a phone number —
    or, on the action-config route, a credential the caller typed).

    For a service that catches `Model.model_validate(...)` and would otherwise put
    `detail=str(exc)` on a `ProblemError` — which in pydantic v2 embeds `input_value=…` and
    round-trips the submitter's own secret back to them.

    THE FULL `loc` IS KEPT, unlike the global `RequestValidationError` handler which drops
    the source fastapi prepends: a raw `ValidationError` from `model_validate` has no such
    prefix, so dropping here would eat the top-level field name. `errors()` exists on
    `pydantic.ValidationError`; anything else yields one generic entry rather than raising,
    so a caller can pass whatever it caught.
    """
    errors = exc.errors() if hasattr(exc, "errors") else []
    if not errors:
        return [
            {
                "field": "body",
                "label": _LABEL_OVERRIDES["body"],
                "rule": "invalid",
                "message": "We could not read what was sent.",
            }
        ]
    return humanise_validation_errors(errors, drop_source=False)


def _problem_response(problem: dict[str, Any], headers: dict[str, str]) -> JSONResponse:
    return JSONResponse(
        status_code=int(problem["status"]),
        content=problem,
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Bootstrap step 5 wires this — every escape route ends in problem+json."""

    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        if exc.status >= 500:
            alert(exc.failure_stage, exc.code, detail=exc.detail)
        return _problem_response(exc.as_problem(request.url.path), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # THE SCREEN THIS FIXES: the sign-in box that read "One or more fields are invalid /
        # Correct the fields named in this response and send the request again / password:
        # String should have at least 12 characters". `detail` is now the sentence itself,
        # so a screen that renders only `title` and `detail` already says the useful thing.
        # `input` is deliberately dropped: it can be the password (hard rule 6).
        fields = humanise_validation_errors(exc.errors(), drop_source=True)
        problem = ProblemError(
            kind="validation",
            code="validation_failed",
            title="Check what you entered",
            detail=validation_summary(fields),
            fields=fields,
        )
        return _problem_response(problem.as_problem(request.url.path), {})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Framework-raised 404/405 etc. still have to speak our dialect.
        by_status: dict[int, ErrorKind] = {
            401: "auth",
            403: "permission",
            404: "not_found",
            409: "conflict",
            422: "validation",
            429: "transient",
        }
        fallback: ErrorKind = "internal" if exc.status_code >= 500 else "business_rule"
        kind: ErrorKind = by_status.get(exc.status_code, fallback)
        # The two the ROUTER raises, which no handler is reached to explain. Their kind's
        # floor would be wrong for both: a 404 from an unknown address is not "check that
        # you are in the right account", and a 405 lands on `business_rule`'s "change what
        # you are doing" when the thing to change is how the caller is calling.
        by_status_remediation: dict[int, str] = {
            404: (
                "Check the URL. If you got here from inside Calevate, give our team the "
                "support reference shown with this message."
            ),
            405: "Use the method this address accepts — /docs lists them.",
        }
        # STARLETTE'S OWN TITLES ARE NOT SENTENCES A PERSON READS: an unknown address
        # arrives as "Not Found", a wrong verb as "Method Not Allowed", and both were
        # being rendered as the heading of the box. Ours replace them ONLY where the
        # framework supplied its default phrase for the status — anything else was written
        # by a caller who meant it, and is passed through unchanged.
        by_status_text: dict[int, tuple[str, str]] = {
            401: ("Please sign in", "You need to be signed in to do this."),
            403: ("You do not have access", "This account cannot open this part of Calevate."),
            404: ("Nothing here", "There is nothing at this address."),
            405: ("That address does not work this way", "This address does not accept that."),
            406: (
                "We cannot answer in that form",
                "This address cannot answer in the form asked for.",
            ),
            409: ("We could not complete that", "Something changed while this was being done."),
            413: ("That is too big to send", "What was sent is larger than we accept."),
            415: (
                "We cannot read that kind of file",
                "This address does not take that kind of file.",
            ),
            429: ("Too many attempts", "Too many attempts in a short time."),
        }
        supplied = str(exc.detail) if exc.detail is not None else ""
        try:
            framework_default = HTTPStatus(exc.status_code).phrase
        except ValueError:  # a status outside the registry; whoever set it wrote the text
            framework_default = ""
        human = by_status_text.get(exc.status_code)
        if exc.status_code >= 500:
            title, detail = "Something went wrong at our end", "Something went wrong at our end."
        elif human is not None and supplied.strip() in ("", framework_default):
            title, detail = human
        else:
            title, detail = supplied, supplied
        problem = ProblemError(
            kind=kind,
            code=f"http_{exc.status_code}",
            title=title,
            detail=detail,
            status=exc.status_code,
            remediation=by_status_remediation.get(exc.status_code),
        )
        headers = dict(exc.headers or {})
        return _problem_response(problem.as_problem(request.url.path), headers)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Full detail server-side (the logger redacts), generic body to the client.
        log.exception("unhandled_exception", extra={"path": request.url.path})
        # THE EXCEPTION TYPE IS PART OF THE ALERT'S IDENTITY, not a detail hanging off
        # it. `alerting._admit` fingerprints on `stage:code` and suppresses repeats for
        # fifteen minutes, so one code shared by every crash in the service means the
        # FIRST crash class to fire silences every other one for a quarter of an hour.
        # That is not hypothetical: an uncaught `ClientDisconnect` — free, from anywhere,
        # indistinguishable from a flaky mobile network — held the voice-runtime
        # receiver's crash alarm down until it was caught at the one site it arose from
        # (`webhook_routes._read_bounded`, D-147). Catching it was right and it fixed one
        # instance; this fixes the class, for every exception type in both services,
        # including the ones nobody has met yet.
        #
        # Still a STABLE code and not a formatted string (the module docstring's rule):
        # `__name__` is a class name from our own import graph, low-cardinality and
        # unmintable by a caller, so it behaves like an Alertmanager label rather than
        # like the millisecond counts that must never enter a fingerprint. It also gives
        # the lock-screen subject the one fact worth waking up for, and
        # `code=unhandled_exception` still substring-matches in a log search.
        alert(
            "ROUTE_HANDLER",
            f"unhandled_exception:{type(exc).__name__}",
            detail="an exception escaped every handler; the response was a generic 500",
            path=request.url.path,
        )
        problem = ProblemError(
            kind="internal",
            code="internal_error",
            title="Something went wrong at our end",
            detail="Something went wrong at our end. Our team has been told about it.",
        )
        return _problem_response(problem.as_problem(request.url.path), {})


__all__ = [
    "PROBLEM_CONTENT_TYPE",
    "ErrorKind",
    "InvalidStatusTransitionError",
    "ProblemError",
    "install_error_handlers",
]
