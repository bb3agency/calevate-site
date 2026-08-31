"""The copilot wire contract. The request is also the AUTHORITY every tool call is checked
against, which is why this file is longer than a request model usually is.

WHY A CLIENT-SUPPLIED SCREEN DESCRIPTION IS SAFE TO TRUST *AS THE AUTHORITY* AND THE
MODEL'S ANSWER IS NOT. Two different parties. The `fields` list is composed by our own
first-party console, over an authenticated session, and describes a form that exists in
that browser and nowhere else — a caller who lies in it can only lie about their own
screen, and the values never leave the browser's form state until that person presses
their own Save button, which goes through the ordinary permission-checked, audited route.
The MODEL's claim about what is writable is a different thing entirely: it is generated
text derived from untrusted screen content, and OWASP GenAI LLM Top 10 2026 LLM01 #4 says
in as many words to hold state-change capability in application code rather than in the
model. So `service.validate_fill` re-checks every item against THIS document and refuses
the whole fill if one fails.

`extra="forbid"` on every model, per this repo's convention: an undeclared key in a
request body is either a client that has drifted from the contract or somebody probing,
and both are worth a 422 rather than a shrug.

EVERY LIST AND EVERY STRING IS BOUNDED. `core/middleware.MAX_BODY_BYTES` (2 MiB) is the
outer wall, and it is the wrong instrument on its own: a 2 MiB body of five-character
field ids is ~40,000 fields, every one of which would be rendered into a prompt and paid
for by the token. The ceilings below are sized at "a screen a human is looking at" and
each one is stated where a reader can see it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

#: How a form control behaves, in the browser's own vocabulary. `select` is the one that
#: earns a schema `enum` (see `prompt.set_fields_tool`), which is the single strongest
#: anti-invention lever this design has.
CopilotFieldType = Literal["text", "number", "select", "bool", "date", "textarea"]

#: A scalar a form field can hold. A closed union and deliberately NOT `Any`: `Any` here
#: would be a free-form passthrough, and the copilot's whole state-change surface is "one
#: of these values reaches one of those fields".
#:
#: `int` IS IN THE UNION, and it was left out first on a belief that turned out to be
#: wrong: that Pydantic would widen an integer to `float` anyway, so one numeric type on
#: the wire was one fewer thing for the browser to branch on. Pydantic v2's smart union
#: preserves the exact type (checked: `12` round-trips as `12`, `12.5` as `12.5`, `True`
#: as `true`), and WITHOUT `int` a seat count of twelve reaches the browser as `12.0` and
#: is written into a number input as "12.0". `bool` sits after the numerics for the same
#: reason `_value_is_legal` tests it first — `isinstance(True, int)` is True in Python, and
#: smart-union resolution is what keeps a JSON `true` from arriving as `1`.
#:
#: Money never travels on this wire — hard rule 7 keeps rupees in `NUMERIC` columns and out
#: of form state — so float's imprecision has nothing here to spend.
CopilotValue = str | int | float | bool | None

_MAX_ID = 200
_MAX_LABEL = 200
_MAX_TEXT = 2_000

#: A screen with more controls than this is not a screen a person is asking a question
#: about. The widest form in this console is the agent intake, and it is well under a
#: hundred controls including every repeated group.
MAX_FIELDS = 200

#: Read-only context the browser volunteers ("this tenant's vertical is `clinic`"). A
#: handful per screen; the ceiling is generous because each one is a short pair.
MAX_FACTS = 50

#: Conversation turns the browser replays into the request. Ten is five exchanges, which
#: is the length at which a person opens a new question instead. NOTHING IS PERSISTED —
#: this list IS the whole memory of the conversation, and it dies with the response.
MAX_HISTORY = 10

#: Options on one `select`. Longer than any picker this console renders (the voice
#: catalogue is the largest) and short enough that the enum it becomes stays a prompt and
#: not a document.
MAX_OPTIONS = 100


class CopilotOption(BaseModel):
    """One choice on a `select`. `value` is what may be written; `label` is what the
    person sees, and is what the model needs in order to map "Telugu" onto `te-IN`."""

    model_config = ConfigDict(extra="forbid")

    value: Annotated[str, Field(max_length=_MAX_ID)]
    label: Annotated[str, Field(max_length=_MAX_LABEL)]


class CopilotField(BaseModel):
    """One form control as the browser sees it.

    `writable` DEFAULTS TO FALSE, which is the one default in this file that is a security
    decision rather than a convenience. A field the browser forgot to describe is a field
    the copilot may not touch; the opposite default would make an omission in the browser
    half into a write the server permits.

    `redacted` says the browser has substituted a placeholder for a value it considers
    personal and will substitute the real one back locally. It is a DECLARATION, not a
    permission: `sanitize.assert_redacted` re-runs `redact()` over the whole payload and
    refuses it if anything still matches, so a field the browser forgot to mark is caught
    by the guard rather than by nothing (D-127 G-2, the same belt `run_assist` wears at
    `workers/extraction.py`).
    """

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1, max_length=_MAX_ID)]
    label: Annotated[str, Field(max_length=_MAX_LABEL)]
    type: CopilotFieldType
    value: CopilotValue = None
    #: Present only on a `select`. `None` and `[]` mean different things and both are
    #: refused a fill: a select whose options nobody declared has no value this server can
    #: prove is legal, so `validate_fill` refuses it rather than passing the model's word
    #: through.
    options: Annotated[list[CopilotOption], Field(max_length=MAX_OPTIONS)] | None = None
    writable: bool = False
    help: Annotated[str, Field(max_length=_MAX_TEXT)] | None = None
    redacted: bool = False


class CopilotScreen(BaseModel):
    """Where the person is. Used for the prompt and for the audit row — never for
    authorization, which is `requires("org:manage")`'s job and is decided from the
    session, not from a body a caller composes."""

    model_config = ConfigDict(extra="forbid")

    #: `route` IS THE ONE FIELD ON THIS WIRE THAT REACHES A DURABLE COLUMN. `routes.py`
    #: writes it to `audit_log.object_id`, and `audit_log` is in `APPEND_ONLY_TABLES` and
    #: hash-chained — nothing in this product can edit or delete what lands there, DPDP
    #: erasure included. So it is shaped rather than free: it must look like a route (a
    #: leading `/`) and it may not carry a control character, which is what would let a
    #: caller forge a line break inside a log record. It is NOT restricted further,
    #: because the values screens actually declare carry spaces, braces and em dashes
    #: ("/admin/new (step 2 — business intake)") and a charset guess would break them.
    #: What keeps a PERSONAL value out of that column is the redaction guard: `route` is
    #: inside `render_screen`'s output, which `routes.py` refuses if `redact()` changes it.
    route: Annotated[str, Field(max_length=_MAX_ID, pattern=r"^/[^\x00-\x1f\x7f]*$")]
    title: Annotated[str, Field(max_length=_MAX_LABEL)]
    realm: Literal["client", "admin"]


class CopilotFact(BaseModel):
    """One read-only fact about the screen that is not a form control."""

    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, Field(max_length=_MAX_ID)]
    label: Annotated[str, Field(max_length=_MAX_LABEL)]
    value: Annotated[str, Field(max_length=_MAX_TEXT)]


class CopilotTurn(BaseModel):
    """One earlier turn of this conversation, replayed by the browser.

    `role` admits `user` and `assistant` and NOT `tool` or `system`: a caller who could
    inject a `system` turn could rewrite the platform rules the static prompt states, and
    a caller who could inject a `tool` turn could claim a fill already succeeded.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: Annotated[str, Field(max_length=_MAX_TEXT)]


class CopilotAskIn(BaseModel):
    """`POST /v1/copilot/ask`."""

    model_config = ConfigDict(extra="forbid")

    screen: CopilotScreen
    question: Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]
    fields: Annotated[list[CopilotField], Field(max_length=MAX_FIELDS)] = []
    facts: Annotated[list[CopilotFact], Field(max_length=MAX_FACTS)] = []
    history: Annotated[list[CopilotTurn], Field(max_length=MAX_HISTORY)] = []


# --- what goes back out, one model per SSE event ------------------------------------
#
# These are the runtime serializers, not OpenAPI response models — an SSE route has no
# single response body for FastAPI to declare, and the event contract is written out in
# the route's `description` where a reader of the schema will find it. They exist as
# models rather than as dict literals so that the shape has ONE definition and
# `copilot/wire_test.py` can pin it.


class CopilotTextEvent(BaseModel):
    """`event: text` — one fragment of the answer, already stripped of invisible
    characters (`sanitize.strip_invisible`)."""

    model_config = ConfigDict(extra="forbid")

    delta: str


class CopilotFillItem(BaseModel):
    """One field the copilot is asking the browser to write. Validated server-side against
    the request's own `fields` before it ever reaches this model."""

    model_config = ConfigDict(extra="forbid")

    field_id: str
    value: CopilotValue


class CopilotFillEvent(BaseModel):
    """`event: fill` — ONE event carrying every field, never one event per field.

    That is the shape of the tool (`set_fields`, an array) and it is the shape of the
    consequence: one atomic apply, one Undo, one audit row. OpenAI's own function-calling
    guidance documents rare incorrectness in parallel tool calls, so N parallel
    `set_field` calls would also be N chances to half-apply a change a person then has to
    unpick by hand.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[CopilotFillItem]


class CopilotDoneEvent(BaseModel):
    """`event: done` — the turn is over.

    `disclosure` is `AssistCapability.disclosure` (D-127 G-6): non-null exactly when a
    model other than the preferred one answered, and it MUST be shown. `metered` is
    `AssistMetering.metered` — False is a real outcome (a free fallback leg, or an answer
    the provider did not count), not a failure.
    """

    model_config = ConfigDict(extra="forbid")

    disclosure: str | None = None
    metered: bool = False


__all__ = [
    "MAX_FACTS",
    "MAX_FIELDS",
    "MAX_HISTORY",
    "MAX_OPTIONS",
    "CopilotAskIn",
    "CopilotDoneEvent",
    "CopilotFact",
    "CopilotField",
    "CopilotFieldType",
    "CopilotFillEvent",
    "CopilotFillItem",
    "CopilotOption",
    "CopilotScreen",
    "CopilotTextEvent",
    "CopilotTurn",
    "CopilotValue",
]
