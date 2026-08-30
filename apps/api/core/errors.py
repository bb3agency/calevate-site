"""RFC-9457 problem+json — the ONE error shape every service emits.

BACKEND-PATTERNS §3 is the spec: the raghava normalization ladder mapped onto
problem+json extensions (`kind`, `retryable`, `remediation`, `trace_id`, `fields`).
Rules that are not negotiable:

- Internal 500s log full detail server-side (redacted) and return a generic body —
  never an internals leak (hard rule: user-safe messages).
- 429 carries `Retry-After` from the limiter.
- 503 is the ONE status allowed to keep its detailed message (ops-UI contract).
- Every 5xx also fires the alert path with a `failure_stage` tag (§8).
"""

from __future__ import annotations

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
# Each line is what the CALLER can do, never what we would do: "contact support with the
# trace id" is an action a person can take, "the team has been alerted" is not.
_DEFAULT_REMEDIATION: dict[ErrorKind, str] = {
    "validation": "Correct the fields named in this response and send the request again.",
    "auth": (
        "Sign in again — your session may have expired, or this credential is not accepted here."
    ),
    "permission": (
        "Ask an account owner for the permission this action needs, or perform it from an "
        "account that has it."
    ),
    "not_found": "Check the identifier and the account you are signed in to.",
    "conflict": "Reload the record — something changed since you loaded it — then try again.",
    "business_rule": "Change the request so it meets the rule described here, then try again.",
    "dependency": (
        "An outside service did not answer. Wait a minute and try again; if it keeps "
        "happening, quote the trace id on this response to support."
    ),
    "transient": "Try again in a few seconds.",
    "internal": (
        "Try again in a moment. If it keeps happening, quote the trace id on this response "
        "to support."
    ),
}


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
            detail=f"No {what.lower()} matches this request.",
            remediation="Check the identifier and the account you are signed in to.",
        )

    @classmethod
    def conflict(cls, code: str, detail: str, *, remediation: str | None = None) -> Self:
        return cls(
            kind="conflict",
            code=code,
            title="Conflicting request",
            detail=detail,
            remediation=remediation,
        )

    @classmethod
    def forbidden(cls, detail: str = "You do not have access to this resource.") -> Self:
        return cls(kind="permission", code="forbidden", title="Forbidden", detail=detail)

    @classmethod
    def unauthorized(cls, detail: str = "Authentication is required.") -> Self:
        return cls(
            kind="auth",
            code="unauthorized",
            title="Unauthorized",
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    @classmethod
    def business_rule(cls, code: str, detail: str, *, remediation: str | None = None) -> Self:
        return cls(
            kind="business_rule",
            code=code,
            title="Request rejected by a business rule",
            detail=detail,
            remediation=remediation,
        )


class InvalidStatusTransitionError(ProblemError):
    """The CAS-lost-the-race / illegal-state-machine-move error (BACKEND-PATTERNS §5)."""

    def __init__(self, entity: str, frm: str, to: str) -> None:
        super().__init__(
            kind="conflict",
            code="invalid_status_transition",
            title="Invalid status transition",
            detail=f"A {entity} cannot move from {frm} to {to}.",
            remediation="Reload the record — someone else may have changed it.",
        )


def validation_fields(exc: Exception) -> list[dict[str, str]]:
    """A hand-caught pydantic `ValidationError` as our flat `{field, rule, message}` triple,
    with the offending `input` DROPPED (hard rule 6: it can be a phone number — or, on the
    action-config route, a credential the caller typed).

    For a service that catches `Model.model_validate(...)` and would otherwise put
    `detail=str(exc)` on a `ProblemError` — which in pydantic v2 embeds `input_value=…` and
    round-trips the submitter's own secret back to them. This keeps the field NAMES and the
    rule (which the submitter needs to fix their input) and discards only the value.

    THE FULL `loc` IS JOINED, unlike the global `RequestValidationError` handler which slices
    `[1:]`: fastapi prepends the source (`"body"`/`"query"`) to every loc, a raw
    `ValidationError` from `model_validate` does not — so slicing here would drop the
    top-level field name. `errors()` exists on `pydantic.ValidationError`; anything else
    yields one generic field rather than raising, so a caller can pass whatever it caught.
    """
    errors = exc.errors() if hasattr(exc, "errors") else []
    if not errors:
        return [{"field": "body", "rule": "invalid", "message": "Invalid value"}]
    return [
        {
            "field": ".".join(str(p) for p in err.get("loc", ())) or "body",
            "rule": str(err.get("type", "invalid")),
            "message": str(err.get("msg", "Invalid value")),
        }
        for err in errors
    ]


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
        # Pydantic's loc tuple → our flat {field, rule, message} triple. `input` is
        # deliberately dropped: it can contain a phone number (hard rule 6).
        fields = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ())[1:]) or "body",
                "rule": str(err.get("type", "invalid")),
                "message": str(err.get("msg", "Invalid value")),
            }
            for err in exc.errors()
        ]
        problem = ProblemError(
            kind="validation",
            code="validation_failed",
            title="Request validation failed",
            detail="One or more fields are invalid.",
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
        # floor would be wrong for both: a 404 from an unknown PATH is not "check the
        # identifier and the account", and a 405 lands on `business_rule`'s "change the
        # request so it meets the rule described here" when the rule is the method itself.
        by_status_remediation: dict[int, str] = {
            404: (
                "Check the URL. If it came from our own console, quote the trace id on "
                "this response to support."
            ),
            405: "Use the HTTP method this endpoint documents — see /docs for the schema.",
        }
        problem = ProblemError(
            kind=kind,
            code=f"http_{exc.status_code}",
            title=str(exc.detail) if exc.status_code < 500 else "Internal server error",
            detail=str(exc.detail) if exc.status_code < 500 else "Something went wrong.",
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
            title="Internal server error",
            detail="Something went wrong. The team has been alerted.",
        )
        return _problem_response(problem.as_problem(request.url.path), {})


__all__ = [
    "PROBLEM_CONTENT_TYPE",
    "ErrorKind",
    "InvalidStatusTransitionError",
    "ProblemError",
    "install_error_handlers",
]
