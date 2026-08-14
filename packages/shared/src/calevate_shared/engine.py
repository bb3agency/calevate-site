"""The VoiceEngine portability contract (TRD §5).

Nothing outside `engine/` may import a vendor SDK or see a vendor payload shape.
Both the `bolna` and `fake` adapters must satisfy this Protocol and pass the
conformance suite — the second adapter exists to keep the first one honest.
(ThinnestAI was retired by D-31 before any adapter was written.)

Everything an adapter ACCEPTS and everything it RETURNS is defined here, in our
vocabulary. That is the whole trick: a second engine changes one package, not the
codebase. Where a vendor has no equivalent of one of these fields, the adapter maps
or omits it — it never leaks its own shape upward.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from calevate_shared.events import CallDirection, CallEvent, CallStatus, TranscriptTurn

# Domain aliases.
E164 = str
EngineAgentRef = str
CallHandle = str
# The engine's own handle for ONE attached knowledge source — opaque to us, exactly
# like `EngineAgentRef`. It is the vendor's id (Bolna: `rag_id`), so only an adapter
# ever interprets it; everything above stores it and hands it back. Our `kb_sources.id`
# cannot serve here: the engine has never seen it, so it addresses nothing on their side.
EngineKBRef = str

NumberSeries = Literal["140", "160", "standard"]


class ModelConfig(BaseModel):
    """BYOK model selection — plain config strings (D-04/D-20/D-36), so changing a
    model is a config edit + regression run, never a code change."""

    stt_provider: str | None = None
    stt_model: str | None = None
    llm_model: str | None = None
    tts_provider: str | None = None
    tts_voice: str | None = None


class AgentConfig(BaseModel):
    """What an agent IS, in our terms. The adapter renders this into the vendor's
    agent object."""

    tenant_id: str
    agent_id: str
    name: str
    direction: Literal["inbound", "outbound", "both"]
    language_primary: str = "te-IN"
    languages_extra: list[str] = Field(default_factory=list)
    system_prompt: str
    # Compliance invariant (hard rule 5): never None, never empty. The adapter
    # prepends it to the greeting so it is spoken FIRST on every call.
    disclosure_line: str
    models: ModelConfig = Field(default_factory=ModelConfig)
    webhook_url: str | None = None
    knowledge_base_ref: str | None = None
    max_call_duration_s: int = 600


class AgentSnapshot(BaseModel):
    """What an agent currently IS **on the engine**, in our terms — the read half of
    `create_agent`/`update_agent`.

    WHY IT EXISTS. Writing was the whole contract: an adapter could create an agent and
    update one, and nothing could ask what the engine actually held afterwards. So
    "update the prompt" could only ever be scored ACCEPTED (the vendor took the write),
    never APPLIED (the vendor is using it), and D-41's second question — after
    `DELETE /knowledgebase/{rag_id}`, does the AGENT still point at the dead handle? —
    had no instrument at all (OPERATIONS §2, gates 2 and 8). Both are questions about the
    engine's state, and a system that can only write cannot ask them.

    TWO `_readable` FLAGS, FOR THE `CostBreakdown.currency_stated` REASON. A missing
    field and an empty value are different facts, and the difference is the whole answer
    here: an adapter that could not FIND the prompt in the response must not report the
    same thing as an agent whose prompt is genuinely empty, and an adapter that could not
    find any KB reference field must not report "the agent references nothing" — which is
    exactly the answer that would make a dangling `rag_id` invisible and close D-41 with a
    green tick nobody measured. Absent-and-unreadable therefore reads as `None` through
    the two accessors below, never as `False`.

    NO VENDOR SHAPE CROSSES THIS (hard rule 2): the vendor's agent object, its wrapper,
    its task list and its own field names stay inside the adapter. What comes out is the
    prompt as TEXT, the handles we already hand around as `EngineKBRef`, and two verdicts
    about what could be read.

    Not a log target. The prompt is business content, not transcript text, so hard rule 6
    does not forbid carrying it — but nothing should log it either; log the verdicts.
    """

    engine_agent_ref: EngineAgentRef
    name: str | None = None
    #: The system prompt AS THE ENGINE HOLDS IT — including whatever rendering the
    #: adapter applied on the way in (the disclosure line is PREPENDED, hard rule 5), so
    #: this is deliberately not expected to equal `AgentConfig.system_prompt`. Compare
    #: with `carries_prompt_marker`, never with `==`.
    system_prompt: str | None = None
    #: True only when the adapter positively read a prompt out of the engine's answer.
    system_prompt_readable: bool = False
    #: The knowledge handles the AGENT ITSELF references. Not the account's KB list —
    #: that is `list_kb`, a different object, and conflating the two is what makes D-41
    #: question (b) unanswerable.
    knowledge_base_refs: list[EngineKBRef] = Field(default_factory=list)
    #: True only when the adapter positively located the agent's KB reference field.
    #: False means "we do not know what this agent references", not "it references none".
    knowledge_base_refs_readable: bool = False
    engine: str = "fake"

    def carries_prompt_marker(self, marker: str) -> bool | None:
        """Is `marker` in the live prompt? `None` = the prompt could not be read.

        CONTAINMENT, NOT EQUALITY, and that is a design choice rather than laziness.
        Every engine renders our `AgentConfig` into its own object — ours prepends the
        disclosure line — so an equality check against what we sent would fail on a
        correctly applied update and turn the one question worth asking ("did the write
        take effect?") into a test of our own string formatting. A marker the caller put
        in the prompt itself survives any rendering that kept the text.
        """
        if not self.system_prompt_readable or self.system_prompt is None:
            return None
        return marker in self.system_prompt

    def references_kb(self, kb: EngineKBRef) -> bool | None:
        """Does the agent still point at this handle? `None` = we could not tell.

        The tri-state is the point (D-41): "the agent does not reference it" and "we
        could not find the field that would say" lead to opposite conclusions about
        whether `detach_kb` needs a second call, and only one of them is evidence.
        """
        if not self.knowledge_base_refs_readable:
            return None
        return kb in self.knowledge_base_refs


class CallContext(BaseModel):
    """Per-call variables rendered into the prompt (Bolna: `user_data`). This is OUR
    mechanism for lead callbacks and the D-21 "call this lead" note."""

    lead_id: str | None = None
    lead_name: str | None = None
    context_note: str | None = None
    prior_call_summary: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class NumberSpec(BaseModel):
    series: NumberSeries = "standard"
    provider: str | None = None
    region: str | None = None
    purpose: str | None = None


class ProvisionedNumber(BaseModel):
    e164: E164
    provider: str | None = None
    engine_number_ref: str | None = None
    series: NumberSeries = "standard"


class KBSourceRef(BaseModel):
    """A knowledge source we have already parsed, chunked and approved. Under BYOK the
    KB is NOT a model slot (D-33) — the engine's built-in KB serves in-call retrieval
    in v1, so this is a pointer plus the text, not an embedding."""

    kb_id: str
    title: str
    text: str
    language: str = "te-IN"


class CostBreakdown(BaseModel):
    """Money is NUMERIC INR, never floats (hard rule 7).

    Vendors quote in their own currency (Bolna: USD cents); the ADAPTER converts at
    capture and stamps the rate it used, so a ledger row can always be re-derived.

    `currency_stated` is what separates a fact from a house assumption, and it exists
    because the two were indistinguishable. `source_currency` was defaulted to `"USD"`
    and Bolna's adapter set the same literal, so a reader — including pilot gate 7,
    whose whole job is to check the currency — could only ever read our own guess back
    and agree with it (OPERATIONS §2). Now `source_currency` still says which currency
    the conversion ASSUMED, and `currency_stated` says whether the vendor said so:
    False means nobody has confirmed it, and if the guess is wrong every INR row is out
    by the exchange rate, in the direction that flatters our margin.
    """

    total_inr: Decimal
    platform_inr: Decimal | None = None
    network_inr: Decimal | None = None
    llm_inr: Decimal | None = None
    tts_inr: Decimal | None = None
    stt_inr: Decimal | None = None
    #: The currency the conversion treated the vendor's number as.
    source_currency: str = "USD"
    #: True only when the PAYLOAD named that currency. False = house assumption.
    currency_stated: bool = False
    source_amount: Decimal | None = None
    fx_rate: Decimal | None = None


class ExecutionSnapshot(BaseModel):
    """The authenticated fetch that is the TRUTH (D-31: webhooks are hints).

    Bolna populates cost/recording/extracted data only at `completed`, roughly 2-3
    min after disconnect — so `terminal` alone is not "ready", `billable_ready` is.
    """

    engine_call_id: str
    # Their agent id — the ONLY bridge to our tenant (agents.engine_agent_ref). The
    # reconciliation poller has no webhook payload to read it from, so the snapshot
    # must carry it or every repaired call is unmappable.
    engine_agent_ref: str | None = None
    direction: CallDirection = "inbound"
    status: CallStatus
    raw_status: str
    terminal: bool
    billable_ready: bool
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_s: int | None = None
    from_e164: str | None = None
    to_e164: str | None = None
    recording_url: str | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    #: Transcript lines the adapter could NOT turn into a turn. Zero is the normal
    #: answer and the only one that means anything: a parser that silently drops what it
    #: does not recognise reports an empty transcript and a healthy call identically, so
    #: gate 7 could only ever see a TOTAL parse failure. Counted rather than kept —
    #: transcript TEXT is hard rule 6, and a count is not text.
    transcript_lines_unparsed: int = 0
    cost: CostBreakdown | None = None
    #: When the engine says the execution reached its billable-ready state. Bolna
    #: populates cost, recording and extracted data only at `completed`, ~2-3 min after
    #: disconnect, and NOTHING recorded that instant — so gate 7's time-to-`completed`
    #: had no post-hoc route and the 2-minute lead SLO was un-auditable after the fact.
    #: `now - ended_at` is deliberately not a substitute: it grows with how long the
    #: operator took to look.
    billable_ready_at: datetime | None = None
    engine_extracted: dict[str, Any] = Field(default_factory=dict)
    engine: str = "fake"


#: Why an adapter could not promise the listing was the whole window. Values are a
#: closed set because each one is a stable alert/metric label (BACKEND-PATTERNS §8: the
#: code IS the deduplication key), and because a free-form string here would be a vendor
#: message crossing the engine boundary.
ListingIncompleteReason = Literal[
    # The payload itself said more exists (a `has_more`/`next`/`total` the adapter could
    # read) and the adapter could not follow it — no self-describing link to GET.
    "explicit_more",
    # No pagination metadata at all, and the row count is exactly a conventional page
    # size. Nothing PROVES truncation; the adapter refuses to claim completeness.
    "full_page_suspected",
    # We followed continuations until our own bound stopped us. There is more.
    "page_cap_reached",
    # A continuation pointed back at a page we had ALREADY fetched. The URLs repeat, so
    # walking on would re-read the same page forever; we stopped and the window is not
    # fully covered. Kept narrow on purpose: an operator reading this goes looking for
    # two identical continuation URLs and must find them.
    "next_link_loop",
    # A continuation we had never seen before came back carrying only executions we had
    # already collected. Not a loop — the URLs differ — but the walk stopped making
    # progress, so it is a vendor repeating content rather than a broken link.
    "next_link_no_progress",
    # The response held NO executions at all and still offered a continuation. Nothing was
    # re-served and nothing looped: either the window is genuinely empty and the vendor
    # hands out a `next` regardless, or it pages in a shape we do not understand.
    # `pages_fetched` says which page it was — 1 means the FIRST page came back empty.
    "empty_page_with_next",
]


class ExecutionListing(BaseModel):
    """What `list_executions` returns: the snapshots AND whether they are all of them.

    THIS TYPE EXISTS BECAUSE THE GUARANTEE OF RECORD MUST BE ABLE TO SAY "I DID NOT SEE
    EVERYTHING". D-31 makes the List-Executions poller — not the webhook — the mechanism
    that recovers every execution whose at-most-once delivery was lost. A bare
    `list[ExecutionSnapshot]` cannot distinguish "the window held 40 calls" from "the
    vendor handed back the first 40 of 900", and the executions in the difference are
    precisely the ones no other mechanism will ever mention. So completeness is part of
    the answer, not something the caller infers from a length.

    `complete=True` is a POSITIVE claim by the adapter: nothing in the response suggested
    another page. It is never the fallback for "we did not look" — an adapter that cannot
    tell says so with `complete=False` and a reason, and the poller alerts on it.

    No vendor cursor, page number or continuation URL appears here (hard rule 2): paging
    is the adapter's business, and what crosses the boundary is our verdict plus counts.
    """

    snapshots: list[ExecutionSnapshot] = Field(default_factory=list)
    #: True only when the adapter has positive grounds to believe it read the whole
    #: window. False means "possibly truncated" — never "definitely".
    complete: bool = True
    incomplete_reason: ListingIncompleteReason | None = None
    #: How many responses were read. 1 for a single-page vendor; >1 proves the
    #: continuation path actually ran, which is the only way a pilot can see it work.
    pages_fetched: int = 1


class WebhookVerdict(BaseModel):
    """Per-engine authenticity result. Bolna signs nothing (D-31), so `method` is how
    we say what evidence we actually have — an unsigned event is accepted only as a
    HINT, and the poller remains the guarantee of record."""

    ok: bool
    method: Literal["hmac", "source_ip", "none"]
    reason: str | None = None


@runtime_checkable
class VoiceEngine(Protocol):
    name: str

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef: ...

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None: ...

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """Read ONE agent's current configuration back out of the engine.

        The counterpart without which `update_agent` is a write into the dark. Two
        promises rest on it and neither is decorative:

        * **APPLIED, not merely ACCEPTED.** A 2xx on the update says the vendor took the
          bytes. Whether the agent is now RUNNING that prompt is a different claim, and
          it is the one a client's compliance disclosure depends on. Pilot gate 2 could
          only ever score the first (OPERATIONS §2).
        * **D-41's dangling handle.** `detach_kb` deletes the knowledge base; whether the
          AGENT stops referencing it is a fact about the agent object. `list_kb` cannot
          answer it — it reads the account's KB list, a different object — so without
          this method the question "does detach need a second call?" has no instrument
          (gate 8).

        It must answer about THIS `ref` and no other. An adapter that echoes back the
        config it was last handed satisfies every naive test and measures nothing: it
        agrees with the caller by construction, which is the same defect
        `CostBreakdown.currency_stated` was introduced to kill. The conformance suite
        therefore reads TWO agents back and requires each to carry its own prompt.

        An unknown ref must RAISE, not return an empty snapshot. A caller reading back an
        agent that does not exist is a caller about to record "prompt not applied" for an
        agent it never created — or worse, "no dangling reference" about a phantom.
        """
        ...

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle: ...

    async def end_call(self, call_id: str) -> None: ...

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None: ...

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber: ...

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        """Push an approved source and return the engine's handle for it.

        Returning the handle is the whole reason a superseded version can ever be
        removed: the engine names its copy, we do not. An adapter that has nothing
        to return is an adapter whose KB can only ever grow.
        """
        ...

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        """Remove ONE attached source — the counterpart without which `attach_kb` is a
        one-way door.

        FLOWS §7 makes a knowledge version a governed object: a human approves it, and
        publishing v2 supersedes v1. Without this method "supersede" only ever happened
        in OUR tables, so the agent kept answering from v1 — the published KB diverging
        from the approved one, which is the single thing the approval gate exists to
        prevent. (After a rollback it was worse: every version was live at once.)

        It must be REAL. An adapter that accepts the call and does nothing turns the
        publish path into a silent lie, and nothing downstream can detect it — which is
        why the conformance suite observes the removal through `list_kb` rather than
        trusting the call to have happened.

        Detaching a handle the engine does not have must RAISE, not pass quietly: the
        publisher's next step is to attach the replacement, and it is entitled to know
        whether the old text is really gone before it does.
        """
        ...

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        """The handles currently attached to this agent.

        The engine — not our table — is what the caller actually hears, so "does the
        published KB match what was approved?" is only answerable by reading the engine
        back. It is also the only adapter-independent way to prove a `detach_kb` did
        anything at all.
        """
        ...

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        """The authenticated read. This — not the webhook — is what we persist."""
        ...

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """Backs the reconciliation poller (D-31: guarantee of record, not a safety net).

        MUST report completeness, not just rows. This returned a bare list, so an
        adapter that read page one of a paginated listing was indistinguishable from one
        that read a quiet window — and the calls in the gap are exactly the ones whose
        webhook was lost, i.e. the ones this method exists to find. An adapter that
        cannot rule out a further page returns `complete=False` with a reason; the poller
        alerts on it. Returning `complete=True` because nothing was checked is the defect
        this signature was changed to make impossible to write by accident.
        """
        ...

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """HMAC where the engine signs; source-IP allowlist where it does not."""
        ...

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        """Vendor payload → OUR normalized event. The isolation boundary."""
        ...


__all__ = [
    "E164",
    "AgentConfig",
    "AgentSnapshot",
    "CallContext",
    "CallHandle",
    "CostBreakdown",
    "EngineAgentRef",
    "EngineKBRef",
    "ExecutionListing",
    "ExecutionSnapshot",
    "KBSourceRef",
    "ListingIncompleteReason",
    "ModelConfig",
    "NumberSeries",
    "NumberSpec",
    "ProvisionedNumber",
    "VoiceEngine",
    "WebhookVerdict",
]
