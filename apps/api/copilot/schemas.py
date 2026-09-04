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

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

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


#: WHICH ASSISTANT IS ANSWERING (D-499). Not a screen property and not a preference: it
#: selects the system prompt, the read-tool registry, the memory table and THE PAYER — the
#: client realm spends the account's own AI allowance, the admin realm spends ours
#: (`billing/platform_ai.py`).
#:
#: **IT IS DERIVED FROM `Principal.realm` AND NEVER FROM `CopilotScreen.realm`**, which is a
#: caller-composed body field used for the prompt and the audit row. The two normally agree;
#: the one that decides is the one the session proves. `CopilotScreen` says the same thing
#: about itself in its own docstring, and this alias exists so the type of the deciding
#: value is not the same type as the type of the claimed one by accident.
CopilotRealm = Literal["client", "admin"]


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


class AdminCopilotAskIn(CopilotAskIn):
    """`POST /v1/admin/copilot/ask` — the client body plus WHICH ACCOUNT IS OPEN (D-499).

    `tenant_id` is the account whose admin page the operator is looking at, or null on a
    platform screen. It scopes three things and nothing else: which tenant the account read
    tools run under, which tenant's live business state is composed, and which memories are
    eligible for recall (`copilot/admin_memory.py`).

    **IT IS NOT AN AUTHORIZATION INPUT AND IT IS NOT A PAYER.** The payer is always the
    platform ledger — an operator never spends a client's allowance (D-499) — so no body
    field here can move anyone's bill. And it widens nothing: every route serving this
    permission is admin-realm, and both admin roles hold `admin:tenants`, so an operator
    naming an account here reaches exactly what the console's own tenant page would show
    them. It is still validated to be a real, undeleted account before it is used, because
    a silently-ignored id would let a screen believe it had scoped the assistant when it
    had not.

    **INSIDE A VIEW-AS SESSION THE HEADER WINS.** `Principal.tenant_id` from an
    impersonation grant is proven by a second factor and audited; this field is a claim in a
    body. The route takes the principal's when there is one and never reconciles the two.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID | None = None


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


class CopilotProposalEvent(BaseModel):
    """`event: proposal` — a described, server-signed intent. NOTHING HAS HAPPENED YET.

    THE FIELDS ARE THE SENTENCE A PERSON APPROVES, and they are separate fields rather than
    one blob of prose because the browser has to be able to render the two halves of the
    decision — `current` beside `proposed` — without parsing English. A dialog that shows
    only what will be set is a dialog that cannot tell somebody the change is a no-op, or
    that they are about to overwrite something they did not know was there.

    `token` is the whole state of this proposal: signed, tenant-bound, actor-bound,
    argument-bound and short-lived (`write_tools.py`'s module docstring). The browser
    stores it, shows this description beside a Confirm button, and posts the token back to
    `POST /v1/copilot/confirm` UNCHANGED. It carries no parameters of its own — anything
    the browser could edit would be something the model's description no longer describes.

    `object_id` is an id and never a name or a number: this model crosses the same wire the
    answer does and lands in the same places (hard rule 6).
    """

    model_config = ConfigDict(extra="forbid")

    token: str
    tool: str
    #: A few words for the dialog's heading ("Pause this campaign").
    title: str
    #: One or two sentences a person can act on, composed by the SERVER from what it read —
    #: never the model's own account of what it is about to do.
    summary: str
    object_type: str
    object_id: str
    #: What the value is NOW. `None` only where the tool has no single current value to
    #: name; every tool shipped so far has one.
    current: str | None
    proposed: str
    #: WHAT IT COSTS, in a sentence, or `None` for "nothing". D-500. A card that names the
    #: change and not its price asks somebody to approve half a decision, and the two
    #: actions this field was added for — publishing an agent, launching a campaign — are
    #: the two where the price is the question. Deliberately NOT a rupee figure: hard rule
    #: 7 keeps money in NUMERIC columns and the per-minute rate is a property of the
    #: account's plan, so the sentence says what is billed and names the screen that holds
    #: the amount.
    cost: str | None
    #: WHETHER IT CAN BE TAKEN BACK, and never `None`. The console already offers an Undo
    #: for a field fill, so a person has been taught that this assistant's changes come
    #: back — and the honest answer for a launch is that the calls it places do not. An
    #: action whose author wrote no reversal sentence is one whose author did not think
    #: about it, which is why `Plan.reversal` is required rather than defaulted.
    reversal: str
    #: When the token stops verifying. The browser disables its own button here rather than
    #: letting a person click into a refusal.
    expires_at: datetime


class CopilotStepEvent(BaseModel):
    """`event: step` — one tool call, as it happens. THE ANSWER IS NOT THE ONLY OUTPUT.

    An assistant that can look things up and change things is one whose most useful frame
    is often not its prose: a person watching "reading your campaigns … 240 ms … 3 found"
    can tell a slow answer from a stuck one, can see WHICH of their data was read, and can
    stop a run that has gone somewhere they did not intend. Showing each call's inputs,
    outputs and elapsed time is the pattern current agentic products converge on, and this
    route already streams, so surfacing the steps costs one more event type rather than an
    architecture.

    TWO FRAMES PER CALL: `running` when it starts, then exactly one of `done` / `refused` /
    `failed` carrying `elapsed_ms`. `id` is stable across the pair so the browser updates
    one row rather than appending two.

    **`args` AND `detail` ARE BOUNDED AND ARE NEVER LOGGED** (hard rule 6). They are the
    caller's own account data on the caller's own screen, which is why they may be SHOWN;
    they are also model-composed and result-derived, which is why they are truncated,
    stripped of invisible characters, and kept out of every log line and every durable
    record. `memory.remember_exchange` stores the answer text and not these.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    tool: str
    status: Literal["running", "done", "refused", "failed"]
    #: The arguments the model sent, as compact JSON, truncated. `""` when there were none
    #: worth showing or the call was not parseable.
    args: str
    #: One line about what came back. `None` while the step is still running.
    detail: str | None = None
    #: Wall time for this call. `None` while it is still running.
    elapsed_ms: int | None = None


class CopilotActionEvent(BaseModel):
    """`event: action` — a TIER 1 action that HAS ALREADY HAPPENED. D-500.

    The opposite promise from `CopilotProposalEvent`, and the two must never be rendered
    the same way: a proposal is an offer with a Confirm button and nothing behind it yet;
    this is a receipt. Everything here is composed server-side from what the executor
    returned, and `reversal` is the field that keeps the receipt honest — the panel's Undo
    belongs to a field fill and does not reach a database write, so the card says in words
    what taking this back would mean and where.

    `object_id` is the row the act produced or acted on, and it is an id rather than a name
    (hard rule 6). It is what lets the browser link to the thing that was made.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str
    title: str
    #: The server's own sentence about what happened — never the model's account of it.
    detail: str
    object_type: str
    object_id: str
    #: False when the world was already in the requested state. A real outcome, not a
    #: failure (D-65), and the person is told which of the two it was.
    applied: bool
    reversal: str
    #: Where the result lives, as a person would find it ("under Agents in your dashboard").
    #: The founder's cross-screen rule: act from wherever they are, then say where it went.
    where: str


class CopilotNavigateEvent(BaseModel):
    """`event: navigate` — OPEN A SCREEN OF THIS CONSOLE. D-524, closing D-523.

    A **Tier 1** frame by `actions.py`'s own test — reversible (the back button), reaching
    no caller, spending nothing — so it is rendered as a RECEIPT and carries no token and no
    Confirm button. It is the ONE event on this stream that is not a description of
    something already settled: the server has decided WHERE, and the browser decides WHEN,
    because only the browser can tell whether the screen being left holds unsaved work.
    `detail` therefore says "Opening…" and never "Opened…".

    `route` IS A ROUTE TEMPLATE AND IS THE ONE FIELD ON THIS STREAM A BROWSER ACTS ON, so it
    is the field whose provenance matters most: it is a CONSTANT read out of
    `screens.CLIENT_SCREENS`, never assembled and never anything the model wrote (the tool
    takes a screen NAME — see `copilot/navigation.py`). It carries the literal `{slug}`
    exactly as a declaring screen sends it, because this server is never told the slug on
    this path; the browser substitutes its own and checks the result against its own nav
    list before moving, so neither half can navigate on the other's word alone.

    `screen` and `where` are the console's own vocabulary for the destination ("Calling
    credit", "Credits & billing, under Settings & account in the left sidebar") and are what a
    person and a screen reader are told. No route path and no identifier is ever spoken.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str
    #: The destination's client-facing NAME, as the sidebar spells it.
    screen: str
    #: The route TEMPLATE, `{slug}` unsubstituted. Never rendered, never spoken.
    route: str
    #: Where it sits, as a person would say it out loud (`screens.where_is`).
    where: str
    #: The server's own sentence about what is happening — never the model's account of it.
    detail: str
    #: How to take it back. Never null, for `CopilotProposalEvent.reversal`'s reason: the
    #: panel's Undo belongs to a field fill, so what applies here has to be said in words.
    reversal: str


class CopilotConfirmIn(BaseModel):
    """`POST /v1/copilot/confirm`. ONE FIELD, and that is the security property.

    Every parameter of the action is inside the signed token, so there is nothing here for
    a caller to tamper with: no lead id, no status, no campaign. A body that also carried
    the target would be a body that could disagree with the description the person read.

    The bound is generous against a JWT carrying a small `args` object — this is not a
    length a legitimate client approaches, it is the wall in front of a caller feeding the
    verifier megabytes.
    """

    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=1, max_length=4_096)]


class CopilotConfirmOut(BaseModel):
    """What the confirmed change did.

    `applied` is False when the world was ALREADY in the requested state — a real outcome,
    not a failure (D-65's distinction, which `set_campaign_status` and the lead executor
    both make). `detail` is the sentence to show; it says which of the two happened,
    because "nothing changed, it was already paused" is the answer a person needs when
    they are watching calls go out.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str
    object_type: str
    object_id: str
    applied: bool
    detail: str


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
    "CopilotActionEvent",
    "CopilotAskIn",
    "CopilotConfirmIn",
    "CopilotConfirmOut",
    "CopilotDoneEvent",
    "CopilotFact",
    "CopilotField",
    "CopilotFieldType",
    "CopilotFillEvent",
    "CopilotFillItem",
    "CopilotNavigateEvent",
    "CopilotOption",
    "CopilotProposalEvent",
    "CopilotScreen",
    "CopilotStepEvent",
    "CopilotTextEvent",
    "CopilotTurn",
    "CopilotValue",
]
