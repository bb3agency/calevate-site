"""`fake` adapter — the second implementation that keeps the first one honest.

Two jobs, both real:

1. **Local development runs offline and deterministic** (DEV-SETUP §3): `ENGINE=fake`
   means the whole pipeline — dispatch, webhook, post-call, lead — works with no
   vendor account, no network and no spend.
2. **It is the conformance control.** A behaviour that only the Bolna adapter has is
   either mapped into the contract or is not allowed to leak upward; running the same
   suite against both is how that stays true (TRD §5).

It is deliberately NOT a mock: calls have a lifecycle, transcripts are Telugu-first
code-mixed samples of the shape Saaras actually returns, and costs come out of the
verified rate card (TRD §10) so metering code meets realistic numbers.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, NotRequired, TypedDict, get_args
from uuid import UUID

from calevate_shared.engine import (
    E164,
    AccountKBListing,
    AccountKBObject,
    AgentConfig,
    AgentSnapshot,
    CallContext,
    CallHandle,
    CallLatency,
    CostBreakdown,
    EngineAgentRef,
    EngineCapabilities,
    EngineKBRef,
    ExecutionListing,
    ExecutionSnapshot,
    KBSourceRef,
    LlmCredentialPlacement,
    LlmProvider,
    ModelConfig,
    NumberSpec,
    ProvisionedNumber,
    RecallOutcome,
    TurnLatency,
    WebhookAuthMethod,
    WebhookVerdict,
    compose_engine_prompt,
)
from calevate_shared.events import (
    TERMINAL_STATUSES,
    CallDirection,
    CallEvent,
    CallStatus,
    Speaker,
    TranscriptTurn,
)

from apps.api.billing.rates import ROUNDING
from apps.api.core.errors import ProblemError
from apps.api.engine.capabilities import (
    require_call_compliance_floor,
    require_capability,
    require_speech_leg,
)
from apps.api.engine.document import engine_document


# A short code-mixed exchange: Telugu with English clinical terms, which is what
# real calls sound like and what the extraction fixtures must cope with.
#
# **The CALLER asks to book, in so many words, and that is load-bearing.** This sample
# is what the pipeline tests classify, and one of them asserts the call comes out a hot
# lead — `intent = book` is a HOT_LEAD_FIELD_TRIGGER. Until the extractor learned who
# was speaking, that verdict came from the AGENT's closing line ("book chesanu"): the
# fixture was hot because the extractor attributed the agent's words to the caller, and
# the test measured the fabrication bug rather than the behaviour it named.
#
# Making the extractor speaker-aware correctly dropped this call to no intent at all,
# because the caller had never actually said it. The repair belongs HERE, not in the
# extractor: a caller ringing a clinic to book an appointment is exactly what this
# fixture is meant to depict, so the caller now says so. Five turns, deliberately —
# `smoke_pipeline_test` counts them to prove transcript turns upsert on (call_id, idx)
# rather than duplicating.
class _StoredCall(TypedDict):
    """The fake's own call record — a TypedDict rather than `dict[str, Any]`.

    `Any` is where a wrong value hides. `_snapshot_from` feeds `status` and `direction`
    straight into `ExecutionSnapshot`, whose fields are `CallStatus`/`CallDirection`, and
    with `Any` in between neither mypy nor Pyrefly could see a typo — it surfaced as a
    Pydantic `ValidationError` inside the poller instead, which on a real engine is a call
    record lost rather than a red squiggle. Declaring the store is what makes the two
    writers below (`start_outbound_call`, `seed_inbound_call`) checkable at the line that
    would make the mistake.
    """

    agent_ref: str
    direction: CallDirection
    status: CallStatus
    started_at: datetime
    ended_at: datetime
    duration_s: int
    from_e164: str
    to_e164: str
    #: Written by `start_outbound_call` only; `seed_inbound_call` stages a call that was
    #: never dialled through us and so has neither.
    context: NotRequired[dict[str, Any]]
    system_prompt: NotRequired[str | None]
    #: Written by `transfer` only, and only after the capability check passed — the
    #: read-back that lets a test prove the escalation reached the engine.
    transferred_to: NotRequired[E164]
    transfer_warm: NotRequired[bool]


#: Raw status → ours, the same shape both real adapters use (`bolna._STATUS_MAP`,
#: `cartesia._STATUS_MAP`) so all three normalize by one mechanism rather than two. The
#: fake IS its own vendor, so the map is the IDENTITY — and it is DERIVED from the
#: Literal rather than retyped, which is the point: the hand-written `set[str]` it
#: replaces was an eighth copy of `CallStatus` that a new member would have silently
#: left out, normalizing a status we had just invented to `failed`. Deriving also
#: retires the `# type: ignore[assignment]` the old membership test needed — a dict
#: lookup narrows, a set membership test does not.
_STATUS_MAP: Final[dict[str, CallStatus]] = {status: status for status in get_args(CallStatus)}

SAMPLE_TURNS: tuple[tuple[Speaker, str], ...] = (
    ("agent", "Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi."),
    ("caller", "Namaskaram, naaku appointment kavali."),
    ("agent", "Tappakunda. Ee roju evening 6 gantalaku doctor available unnaru."),
    ("caller", "Sare, appointment book cheyandi. Naa peru Ravi, number 9876543210."),
    ("agent", "Thank you Ravi garu, mee appointment 6 PM ki book chesanu."),
)

#: What this engine says its own pipeline cost, per turn. A fake vendor still has to answer
#: the questions the real one answers, and the post-call pipeline's latency stage would
#: otherwise be exercised only against a transport stub — the same argument `raw_document`
#: makes below.
#:
#: THE NUMBERS ARE DELIBERATELY BELOW THE ALARM AND DELIBERATELY SPREAD. Below the alarm
#: (`_LLM_TTFT_ALARM_MS` is the vendor's 1000ms) because a fake that pages on every offline
#: call teaches developers to ignore the alarm. They are NOT inside our own budget any more
#: and were not adjusted to be: `LLM_TTFT_BUDGET_MS` fell from 350ms to 150ms with the
#: 500ms voice-to-voice target (TRD §4), and a fixture edited to sit under a target it has
#: no way of meeting would teach the opposite lesson — that the pipeline comfortably makes
#: it. Spread because a distribution over identical samples
#: hides every statistic that reads it — break the median and nothing moves. Turn 1 is the
#: slowest, which is what a real payload does (connection setup rides on it).
#:
#: `region="in"` is a CLAIM ABOUT THE FAKE, not about Bolna: this engine runs in the same
#: process as its caller. It is populated so the grouping the gate-4 report does has two
#: sides to group by offline.
_SAMPLE_LATENCY: Final[CallLatency] = CallLatency(
    region="in",
    time_to_first_audio_ms=910.0,
    turns=[
        TurnLatency(turn=1, stt_ms=210.0, llm_ttft_ms=340.0, tts_ttfa_ms=280.0),
        TurnLatency(turn=2, stt_ms=190.0, llm_ttft_ms=260.0, tts_ttfa_ms=250.0),
        TurnLatency(turn=3, stt_ms=205.0, llm_ttft_ms=295.0, tts_ttfa_ms=265.0),
    ],
)

# Per-minute INR from the verified rate card (TRD §10.1, D-35/D-36): all-Sarvam BYOK.
_COST_PER_MIN = {
    "platform": Decimal("1.7500"),
    "network": Decimal("0.6000"),
    "stt": Decimal("0.5000"),
    # STILL ZERO, AND NOW FOR A DIFFERENT REASON (D-400, re-aimed by D-410). It was zero
    # because the LLM leg WAS free — Sarvam 105B, free per token (D-35). The founder has
    # moved that leg to a PAID model, so "free" is no longer the reason; what keeps this
    # at zero is that on a BYOK leg the ENGINE pays nothing and therefore reports
    # nothing, and this dict is the engine's own cost breakdown. That spend lands on OUR
    # model provider's invoice — Azure OpenAI since D-410, which superseded D-400's
    # Vertex leg and took the GCP invoice with it — which the engine has never seen
    # (`billing/rates.py::llm_cost_inr_per_minute` is where that side is modelled). A
    # non-zero figure here would be this adapter inventing a vendor charge that no vendor
    # makes.
    "llm": Decimal("0.0000"),
    "tts": Decimal("1.2000"),
}


# What the fake engine claims by default: BYOK on every leg, a built-in knowledge base,
# no campaign objects of its own, no number provisioning, no transfer, no signature.
#
# It is deliberately BOLNA-SHAPED on the axes that matter, because the fake engine's
# first job is to stand in for the engine we actually run (DEV-SETUP §3) — a default that
# diverged from the primary would make local development exercise a system we do not
# ship. Where it differs from Bolna it differs HONESTLY rather than aspirationally:
# `campaigns=False` because our dispatch is ours (see the field's docstring), and
# `number_series=frozenset()`/`transfer=False` because the fake used to answer both of
# those with a cheerful success while Bolna raised — two adapters disagreeing about what
# the platform can do, with nothing able to detect it. That divergence is the single
# clearest piece of evidence that this descriptor needed to exist.
DEFAULT_FAKE_CAPABILITIES = EngineCapabilities(
    stt="ours",
    tts="ours",
    llm="ours",
    # Bolna's shape: this engine holds the agent, and the prompt (with hard rule 5's
    # directive inside it) is agent-record state a publish writes and a read-back scores.
    agent_hosting="control_plane",
    campaigns=False,
    knowledge_base=True,
    number_series=frozenset(),
    # Bolna's shape again: the caller ID is a per-call field and inbound routing is an API
    # call, so the default fake is what exercises both halves of D-420 offline.
    caller_id=True,
    inbound_binding=True,
    transfer=False,
    # Bolna's shape for a third time (D-533): the agent hands off from inside the call to
    # a number fixed at publish, so the default fake is what exercises the handoff seam
    # offline -- the publish carrying it, and the read-back proving the engine holds it.
    in_call_handoff=True,
    webhook_auth="none",
)

# THE SECOND SHAPE, and the reason this adapter takes its capabilities as an argument.
#
# Doctrine says a seam is only proven by a second implementation; doctrine also says an
# adapter written against an imagined API is worse than none, because it looks finished.
# Both are true, and together they rule out a speculative adapter for the alternative
# engine on the table. What they do NOT rule out is running the existing, honest adapter
# with the alternative's ANSWERS — an engine that dictates its own speech, has no
# knowledge base, no campaign objects, provisions no Indian number class and signs its
# webhooks. Every one of those is a capability difference, not an API difference, so it
# needs no vendor contract to express and no line of imagined vendor JSON.
#
# What this catches is exactly what a speculative adapter would have hidden: code that
# only works because today's engine says yes. It is used by the conformance suite (which
# runs every clause against it) and by `tests/engine_capability_test.py`.
#
# NOT named for a vendor. It is a SHAPE — the set of answers — and naming it after a
# company would invite someone to treat it as a description of that company's API, which
# is the mistake the whole arrangement exists to avoid.
DICTATED_SPEECH_CAPABILITIES = EngineCapabilities(
    # The LLM stays ours: an engine can dictate its speech stack and still take
    # `model=` + `api_key=` for the model, and the one on the table does exactly that.
    # Making every leg `engine` here would have been the easier fixture and a worse test,
    # because it would never exercise a MIXED engine — which is the realistic case and
    # the one where a per-leg descriptor earns its keep over a single boolean.
    stt="engine",
    tts="engine",
    llm="ours",
    # Still `control_plane`: this fixture's axis is SPEECH, and giving it a second
    # difference would stop any clause it fails from saying which one it measured. The
    # agent-hosting axis has its own profile below, for the same reason.
    agent_hosting="control_plane",
    campaigns=False,
    knowledge_base=False,
    number_series=frozenset(),
    # Unchanged from the default, deliberately: this fixture's axis is SPEECH. Giving it a
    # telephony difference too would stop any clause it fails from saying which one it
    # measured — the same argument the `agent_hosting` line above makes.
    caller_id=True,
    inbound_binding=True,
    transfer=True,
    # Unchanged from the default for the reason the lines above give: this fixture's axis
    # is SPEECH, and a second difference would stop a failing clause saying which one it
    # measured.
    in_call_handoff=True,
    webhook_auth="hmac",
)

# THE THIRD SHAPE, and the one that keeps the OTHER half of hard rule 5 executable
# (D-280/D-282).
#
# `DICTATED_SPEECH_CAPABILITIES` above exists because a capability difference needs no
# vendor contract to express. This exists for the same reason and about a bigger
# difference: an engine that does not host an agent of ours at all. Its agents are
# programs deployed somewhere else, there is no create endpoint, the agent record carries
# no prompt, and our script can only reach the agent as per-call data. That is Cartesia
# Line, read at source (`docs/vendor/cartesia/agents-control-plane.md`) — and it is a
# SHAPE rather than a vendor, which is why it is not named after one.
#
# **WHAT ONLY THIS FIXTURE CAN PROVE.** The real adapter with this shape (`cartesia`)
# cannot carry our prompt on a dial: its outbound body has no field for one, so it
# refuses every call, which is the correct answer and also a branch that exercises
# nothing. So without this profile, the ALTERNATIVE contract — the prompt riding
# `CallContext.system_prompt` all the way onto a call, and a dial without it being refused
# — would be code no test has ever run, on the one rule a client may not switch off. It
# needs no account and no network, which is the whole argument for the fake engine.
#
# Every other answer matches the default deliberately: the axis under test is where the
# agent comes from, and a fixture that differed on five axes could not tell a reader which
# one a failure was about. The three speech legs are the exception that is forced rather
# than chosen — see `EXTERNAL_DEPLOYMENT_SPEECH_IS_NOT_OURS` in the conformance suite for
# why an engine with no agent record can have no BYOK leg either.
EXTERNAL_DEPLOYMENT_CAPABILITIES = EngineCapabilities(
    stt="engine",
    tts="engine",
    llm="engine",
    agent_hosting="external_deployment",
    campaigns=False,
    knowledge_base=True,
    number_series=frozenset(),
    # **THE ONE PROFILE THAT REFUSES BOTH TELEPHONY CAPABILITIES, and it is forced rather
    # than chosen** (D-420). This shape is Cartesia Line: its outbound body names ONE
    # `from_number_id` read from adapter-wide config — one number for the whole platform,
    # on a product where each tenant's Principal Entity has its own registered header — so
    # it cannot present a caller ID WE name per dial, and there is no agent object of ours
    # for a number to be bound to. Without this profile the refusal branches of
    # `require_capability("caller_id")` and `require_capability("inbound_binding")` would be
    # contract no test has ever run: the real `cartesia` adapter refuses every dial one step
    # earlier, on the compliance floor, so its caller-id refusal is unreachable there.
    caller_id=False,
    inbound_binding=False,
    transfer=False,
    # **AND THE ONE PROFILE THAT REFUSES THE HANDOFF** (D-533), forced by the same fact:
    # there is no agent object of ours on this shape to hang an in-call tool on. Without
    # it, `require_capability("in_call_handoff")`'s refusal branch would be contract no
    # test has ever run.
    in_call_handoff=False,
    webhook_auth="none",
)


# The header and key the SIGNING fake instance uses. Both are ours and both are inert:
# the header is `X-Calevate-`-prefixed so it can never read as a captured vendor
# contract, and the key is a fixture constant that is never a secret — this adapter runs
# only in tests and in offline local development (hard rule: real secrets come from the
# secrets manager, never a committed file, and this is neither).
FAKE_SIGNATURE_HEADER = "X-Calevate-Fake-Signature"
FAKE_WEBHOOK_SECRET = "fake-engine-webhook-secret"


class FakeEngine:
    """Implements `VoiceEngine` entirely in memory."""

    #: Overridable per instance. The capability-restricted fixture is a DIFFERENT engine
    #: to everything that keys on a name — `WEBHOOK_AUTH_BY_ENGINE`, the receiver's route
    #: segment, `CallEvent.engine` — and two instances answering to one name while
    #: declaring different webhook authentication would make that table ambiguous.
    name = "fake"

    #: Empty, and permanently so: this adapter IS its own vendor, so there is no key an
    #: operator could set. `holds_credentials()` is always True, so readiness never reads
    #: this — but an empty tuple states the fact, where omitting the attribute would
    #: leave the Protocol unsatisfied and the reason unrecorded.
    credential_env_keys: tuple[str, ...] = ()

    #: How many executions one `list_executions` call will return. Real vendors cap
    #: their listings; a fake that returns everything forever would let a caller that
    #: ignores `ExecutionListing.complete` pass the conformance suite. 100 keeps local
    #: development unaffected (no dev tenant places 100 calls in a poll window) while
    #: leaving the truncated branch reachable — the suite lowers it.
    DEFAULT_LISTING_PAGE_SIZE = 100

    def __init__(
        self,
        *,
        listing_page_size: int = DEFAULT_LISTING_PAGE_SIZE,
        capabilities: EngineCapabilities = DEFAULT_FAKE_CAPABILITIES,
        webhook_secret: str = FAKE_WEBHOOK_SECRET,
        name: str | None = None,
    ) -> None:
        if name is not None:
            self.name = name
        self.listing_page_size = listing_page_size
        self._webhook_secret = webhook_secret
        #: Per-INSTANCE, not per-class: the whole point is that one adapter can be run
        #: with another engine's answers. Every method below reads `self.capabilities`
        #: and refuses what it does not have, so the restricted instance is a genuinely
        #: different engine to every caller rather than a differently-labelled one.
        self.capabilities = capabilities
        self._agents: dict[str, AgentConfig] = {}
        self._calls: dict[str, _StoredCall] = {}
        self._kb: dict[str, list[KBSourceRef]] = {}
        #: The ACCOUNT's knowledge bases, which is a different object from the agent
        #: linkage above and outlives it — see `list_account_kb` and `delete_agent`.
        self._account_kb: dict[EngineKBRef, AccountKBObject] = {}
        #: `engine_number_ref → agent ref` — the engine's inbound routing table (D-420).
        self._inbound: dict[str, EngineAgentRef] = {}
        #: The rotating LLM credential (D-404), modelled as REPLACE-IN-PLACE — one slot,
        #: last write wins. That is the semantics the real store is hoped to have and the
        #: one a caller may rely on; the append case is a vendor defect the Bolna adapter
        #: raises on, so there is nothing here for a fake to imitate.
        #:
        #: HELD, not discarded, because the conformance clause has to be able to ask what
        #: the engine ENDED UP with — an adapter that accepted the write and kept nothing
        #: would pass a "did it raise" test while proving nothing about the rotation.
        self._llm_credentials: dict[LlmProvider, str] = {}

    def holds_credentials(self) -> bool:
        """Always True: this adapter IS its own vendor, so there is nothing to configure.

        Not a stub. The fake engine's whole job is that the pipeline runs offline with no
        vendor account (DEV-SETUP §3), so "we can reach the vendor" is genuinely and
        permanently true here — which is what makes it usable as `ENGINE=fake` in local
        development while a credential-less real adapter refuses everything.
        """
        return True

    # --- deterministic ids ---------------------------------------------------

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]
        return f"{prefix}_{digest}"

    # --- agent lifecycle -----------------------------------------------------

    def _assert_speech_is_ours(self, cfg: AgentConfig) -> None:
        """Refuse a BYOK selection for any leg this instance says the ENGINE dictates.

        Both write paths go through it, because an engine that refused a voice on create
        and accepted one on update would leave the agent's second publish silently
        wrong — and update is the path an operator uses far more often.
        """
        require_speech_leg("stt", engine=self, value=cfg.models.stt_model)
        require_speech_leg("llm", engine=self, value=cfg.models.llm_model)
        require_speech_leg("tts", engine=self, value=cfg.models.tts_voice)

    def _assert_this_engine_hosts_agents(self) -> None:
        """Refuse the three agent-write/read methods when this instance says its agents
        are deployed elsewhere (D-280).

        All three go through it, in the order a publish uses them, because an engine that
        refused a create and accepted an update would let a caller reach the second by
        supplying a ref it invented — and on this shape every ref IS invented, since
        nothing here mints one.
        """
        require_capability("agent_hosting", engine=self)

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        self._assert_this_engine_hosts_agents()
        self._assert_speech_is_ours(cfg)
        ref = self._stable_id("fakeagent", cfg.tenant_id, cfg.agent_id)
        self._agents[ref] = cfg
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        self._assert_this_engine_hosts_agents()
        self._assert_speech_is_ours(cfg)
        self._agents[ref] = cfg

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        """Forget the agent AND its knowledge LINKAGE — but not the account's objects.

        `_kb` is dropped in the same act because the Protocol's "what it costs at the
        vendor" note is a real property here too: a fake that removed the agent and kept
        its attached sources would leave `list_kb(ref)` answering about an agent that no
        longer exists, which is the phantom `get_agent` raises to avoid.

        **`_account_kb` IS DELIBERATELY NOT DROPPED, AND THAT IS A CHOICE THIS FAKE HAS TO
        MAKE HONESTLY (D-519).** Whether deleting an agent also deletes the knowledge
        bases it referenced is UNKNOWN — the primary engine's docs do not state it, and
        OPERATIONS §2 gate 43f is the live probe that settles it. A fake must do
        *something*, so it does the WORSE thing: the account keeps the object and it
        becomes an orphan nothing references. Code that is correct against this fake is
        correct under either answer, because the cascade branch only ever means our later
        cleanup finds less than it expected — while the orphan branch means a client's
        document lives on a shared vendor account with nothing pointing at it, which is
        the outcome that has to be survivable. Modelling the comfortable branch would let
        a test prove a property the vendor has never promised.

        `pop(..., None)` rather than `del`: deleting a ref this engine never held is the
        postcondition already satisfied, and the conformance suite deletes twice.
        """
        self._agents.pop(ref, None)
        self._kb.pop(ref, None)

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """Read back what this engine actually HOLDS for `ref` — never what it was last
        handed.

        Two details make this a real second implementation rather than a mirror:

        * it reads `self._agents[ref]`, so it answers about the agent asked for. An
          adapter that echoed the most recent `create_agent`/`update_agent` argument
          would agree with every caller and detect nothing, which is why the conformance
          suite reads two agents back;
        * it renders the prompt through `compose_engine_prompt`, exactly as both real
          adapters do (hard rule 5) — opening line prepended, platform rules appended.
          Storing `cfg.system_prompt` verbatim would make the fake the only engine where a
          read-back equals what was sent, and a caller could then write an equality check
          that passes here and fails against every real vendor.

        An unknown ref raises, mirroring the vendor's 404: the caller that reads back an
        agent nobody created must not be handed a snapshot that quietly disagrees.

        **AND IT REFUSES BY NAME on an instance whose agents are deployed elsewhere**
        (D-280): there is no agent record to read, so the prompt read-back is not a lookup
        that failed — it is a question this platform does not answer. `CartesiaEngine.
        get_agent` carries the argument for why that is not the same as `readable=False`.
        """
        self._assert_this_engine_hosts_agents()
        cfg = self._agents.get(ref)
        if cfg is None:
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform does not hold that agent.",
            )
        return AgentSnapshot(
            engine_agent_ref=ref,
            name=cfg.name,
            system_prompt=compose_engine_prompt(cfg),
            system_prompt_readable=True,
            # The greeting, held SEPARATELY from the prompt exactly as both real adapters
            # send it — `agent_welcome_message` on Bolna, `introduction` on Cartesia. The
            # fake storing only the prompt is what would let a caller write a disclosure
            # check that passes here and proves nothing against a vendor, which is the
            # substitution finding P3.3 records. It follows the CURRENT config, so an
            # agent republished with both notices off reads back with no greeting — which
            # is what makes D-163's "the vendor actually cleared it" check testable.
            greeting=cfg.opening_line,
            greeting_readable=True,
            # The fake engine's agent really does reference its attached sources, so this
            # is readable — and it is the ONLY place D-41's dangling-handle logic gets
            # exercised until the pilot settles where Bolna keeps the reference.
            knowledge_base_refs=[
                self._kb_handle(ref, source.kb_id) for source in self._kb.get(ref, [])
            ],
            # An engine with no knowledge base references none, and KNOWS it references
            # none — which is a genuinely readable answer, not a "cannot tell". The
            # distinction matters: `readable=False` would send D-41's dangling-handle
            # check looking for a field on an engine that has no such concept.
            knowledge_base_refs_readable=True,
            # Only the legs this instance actually owns. A dictated leg reports None
            # rather than the engine's own product name (`AgentSnapshot.models`): the
            # engine's voice id is a vendor string, and a caller comparing it against our
            # catalogue would find no match and conclude the write had been dropped.
            #
            # THE LLM LEG ROUND-TRIPS ITS PROVIDER AND ENDPOINT, NOT ONLY ITS MODEL, and
            # that is what makes this fake a truthful stand-in rather than a mirror that
            # flatters every adapter. A real `control_plane` adapter (BolnaEngine) reads
            # `llm_provider` and `llm_base_url` back off the agent object — the endpoint is
            # the leg's residency proof — so a fake that dropped them let the conformance
            # suite pass an adapter that dropped them too. It gates on `is_ours("llm")` for
            # the same reason `llm_model` does: a dictated LLM leg has no selection of ours
            # to report, and reporting one would read exactly like an applied BYOK choice.
            models=ModelConfig(
                stt_provider=cfg.models.stt_provider if self.capabilities.is_ours("stt") else None,
                stt_model=cfg.models.stt_model if self.capabilities.is_ours("stt") else None,
                llm_model=cfg.models.llm_model if self.capabilities.is_ours("llm") else None,
                llm_provider=cfg.models.llm_provider if self.capabilities.is_ours("llm") else None,
                llm_base_url=cfg.models.llm_base_url if self.capabilities.is_ours("llm") else None,
                tts_provider=cfg.models.tts_provider if self.capabilities.is_ours("tts") else None,
                # THE TTS LEG IS A PAIR NOW (D-358), and both halves are gated together.
                # A real adapter reads the model and the speaker back out of two vendor
                # keys, so a fake that round-tripped only the speaker would let the
                # conformance suite pass an adapter that dropped the model — the same
                # argument the LLM endpoint above makes one line up.
                tts_model=cfg.models.tts_model if self.capabilities.is_ours("tts") else None,
                tts_voice=cfg.models.tts_voice if self.capabilities.is_ours("tts") else None,
            ),
            models_readable=True,
            engine=self.name,
        )

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        """Place a call, and — on the externally-deployed shape — CARRY THE PROMPT ON IT.

        THE ONLY PLACE THE ALTERNATIVE HALF OF HARD RULE 5 RUNS (D-282). On a
        `control_plane` instance the guard is a no-op and `ctx.system_prompt` is None: the
        directive is agent-record state that `get_agent` reads back and
        `verification.judge` scores. On an `external_deployment` instance there is no
        agent record, so the guard refuses a context that does not carry the truthful-
        answer rule, and the prompt that DOES carry it is stored on the call — which is
        what a real adapter of this shape would put in its request body.

        Storing it is not decoration. `start_outbound_call` returns a handle and nothing
        else, so "the adapter sent our prompt" and "the adapter dropped it" are otherwise
        the same observation — the identical hole `transfer` has, and the reason that
        clause probes a call the engine does not hold. Here the fake IS the vendor, so the
        round trip can be observed directly (`call_prompt`), and
        `tests/engine_capability_test.py` observes it.
        """
        # THE ADAPTER'S OWN VALUE, not the context it was handed — `ctx.system_prompt` is
        # both what the guard checks and what the line below stores, so an edit that stops
        # storing it stops passing the guard in the same breath.
        require_call_compliance_floor(engine=self, prompt_on_the_wire=ctx.system_prompt)
        # REFUSE A CALLER ID THIS ENGINE CANNOT PRESENT, never drop it (D-420). Same
        # doctrine as `require_speech_leg`: dropping produces a dial that succeeds while the
        # callee's handset shows a number nobody gated, and nothing downstream can detect it.
        if ctx.from_e164:
            require_capability("caller_id", engine=self)
        handle = self._stable_id("fakecall", ref, to, ctx.lead_id or "", str(len(self._calls)))
        now = datetime.now(UTC)
        self._calls[handle] = {
            "agent_ref": ref,
            "direction": "outbound",
            "status": "completed",
            "started_at": now,
            "ended_at": now + timedelta(seconds=95),
            "duration_s": 95,
            # THE CALLER ID THIS DIAL PRESENTED (D-420). It is `ctx.from_e164` when the
            # caller named one, and only then does it fall back to a fixture constant —
            # storing the constant unconditionally is what would let an adapter that drops
            # the caller ID pass the clause that checks it reached the wire.
            "from_e164": ctx.from_e164 or "+911140000000",
            "to_e164": to,
            "context": ctx.model_dump(),
            # The per-call prompt AS THIS ENGINE RECEIVED IT, kept beside the call rather
            # than only inside `context`: it is the thing a compliance question is asked
            # about, and burying it in a dumped model would make the read that answers
            # that question look like a peek at an internal.
            "system_prompt": ctx.system_prompt,
        }
        return handle

    def call_prompt(self, call_id: CallHandle) -> str | None:
        """What prompt this engine is running for `call_id` — the read-back that makes the
        per-call compliance floor observable.

        A TEST AFFORDANCE, like `seed_inbound_call`, and deliberately NOT a `VoiceEngine`
        method. No real vendor of this shape publishes such a read-back — Cartesia's call
        object (`AgentCall`) carries no prompt — so putting it on the Protocol would mint a
        contract exactly one implementation could ever satisfy, and every other adapter
        would answer None. A method every real engine must stub out is a method that
        proves nothing about any of them.

        What it IS good for is the one thing the port cannot do: proving that an adapter
        which ACCEPTED a floor-carrying dial actually carried it, rather than checking the
        context and throwing it away.
        """
        call = self._calls.get(call_id)
        if call is None:
            return None
        stored = call.get("system_prompt")
        return stored if isinstance(stored, str) else None

    async def end_call(self, call_id: str) -> RecallOutcome:
        call = self._calls.get(call_id)
        if call is None:
            # RAISES, mirroring both real adapters' 404 (D-187). This used to return
            # quietly, which is the `get_execution` and `transfer` divergence a third
            # time: `BolnaEngine` POSTs `/executions/{id}/stop` and `CartesiaEngine`
            # POSTs `/agents/calls/{id}/end`, and each surfaces the vendor's refusal —
            # so the offline pipeline reported a hang-up nobody performed. `end_call`
            # has ONE observable failure (claiming to have stopped a call it did not),
            # and an adapter that shrugs has removed it.
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform does not hold that call.",
            )
        # THE FAKE IS ITS OWN VENDOR, so unlike the two real adapters it can answer the
        # verdict from fact rather than from a response body: it knows whether this dial
        # had left the queue. A dial still `queued` is caught before it rings; anything
        # else was already running, which is the race D-428 names and the one an offline
        # pipeline must be able to reproduce (DEV-SETUP §3). Answering `PREVENTED`
        # unconditionally would make the DNC job's own tests unable to see that case.
        caught_in_queue = call.get("status") == "queued"
        call["status"] = "completed"
        call["ended_at"] = datetime.now(UTC)
        return RecallOutcome.PREVENTED if caught_in_queue else RecallOutcome.ALREADY_RUNNING

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        # Used to succeed unconditionally while the Bolna adapter raised. Two adapters
        # disagreeing about whether the platform can transfer a call, with no instrument
        # that could see it — the descriptor is now that instrument.
        require_capability("transfer", engine=self)
        call = self._calls.get(call_id)
        if call is None:
            # Mirrors the vendor's 404, and for `detach_kb`'s reason. `transfer` returns
            # nothing and has no read-back, so a transfer that quietly did not happen is
            # a caller sitting in silence while every one of our screens reports an
            # escalation — the ONE observable failure this method has is refusing a call
            # it cannot act on, and an adapter that shrugs here has no way left to be
            # caught claiming a transfer it cannot perform.
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform does not hold that call.",
            )
        call["transferred_to"] = to
        call["transfer_warm"] = warm

    async def set_llm_credential(
        self, secret: str, *, provider: LlmProvider
    ) -> LlmCredentialPlacement:
        """Hold the in-call LLM bearer, replacing whatever was there (D-404).

        REFUSES ON A DICTATED LLM LEG, and that arm is the reason this is not a one-liner.
        `EXTERNAL_DEPLOYMENT_CAPABILITIES` declares `llm="engine"`, so the conformance
        suite drives a real engine shape whose model is not ours to credential — and the
        failure this catches is a refresher that reports success forever against an engine
        that never wanted a credential, which is silent by construction.

        The EMPTY-SECRET refusal is here rather than only in the caller for the reason
        `require_speech_leg` gives about dropping a value: an adapter that accepted `""`
        would let a minting bug install a blank bearer, and the leg would fail on the next
        call with a vendor 401 that names nothing on our side.

        **HELD PER LEG, WHICH IS WHAT MAKES THE FAKE WORTH ANYTHING HERE.** The posture
        declares three legs and an operator installs a key for each; a fake that kept one
        string would pass a conformance suite while modelling the exact bug the Protocol's
        required `provider` argument exists to prevent — one leg's rotation silently
        overwriting another's. A dict costs nothing and makes the separation checkable.
        """
        require_capability("llm", engine=self)
        if not secret:
            raise ProblemError(
                kind="validation",
                code="engine_credential_empty",
                title="No credential to install",
                detail="An empty credential was offered to the voice platform.",
            )
        self._llm_credentials[provider] = secret
        # Always replace-in-place: a dict has no append semantics to model, which is the
        # HAPPY vendor behaviour `set_llm_credential`'s three-call dance exists to detect.
        return LlmCredentialPlacement(replaced_in_place=True)

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        # Per SERIES, not per capability: an engine may sell an ordinary number and have
        # no path to a 140-series DLT class at all, and the campaign launch gate matches
        # on the series. A single boolean here would let a 140-series request through on
        # the strength of a standard-number capability.
        if not self.capabilities.provisions(spec.series):
            require_capability("numbers", engine=self)
            raise ProblemError(
                kind="dependency",
                code="engine_capability_absent",
                title="The voice platform cannot do that",
                detail=f"The voice platform in use does not provide numbers in: {spec.series}.",
                remediation=(
                    "Numbers are taken on the client's own operator account — Calevate "
                    "does not supply them."
                ),
            )
        e164 = "+9111" + self._stable_id("n", spec.series, spec.purpose or "")[-8:].replace(
            "abcdef", "123456"
        )
        digits = "".join(c for c in e164 if c.isdigit())[:12].ljust(12, "0")
        return ProvisionedNumber(
            e164=f"+{digits}",
            provider=spec.provider or "fake-telco",
            engine_number_ref=self._stable_id("fakenum", digits),
            series=spec.series,
        )

    # --- inbound routing (D-420) ---------------------------------------------
    #
    # STATEFUL, for the reason `_kb` is: a fake that answered every bind with None would
    # let an adapter that routes nothing pass the conformance clause, which is the one
    # defect that clause exists to catch. `inbound_agent_for` is the read-back that makes
    # "the number now answers to this agent" observable — a test affordance, like
    # `call_prompt`, and deliberately not a Protocol method: no vendor publishes such a
    # read (Bolna's inbound routes answer with a URL and the number's id, not a mapping we
    # could re-read), so putting it on the port would mint a contract exactly one
    # implementation could satisfy.

    def _number_key(self, number: ProvisionedNumber) -> str:
        """The engine's own handle, refusing a number it has never been told about.

        THE SAME REFUSAL THE REAL ADAPTER MAKES, and it is here rather than left to Bolna
        because it is a property of the CONTRACT: `bind_inbound_number` addresses a number
        by `engine_number_ref`, so an engine handed None has nothing to bind. A fake that
        cheerfully bound on the E.164 would make the conformance suite prove a shape no
        adapter can implement.
        """
        if number.engine_number_ref:
            return number.engine_number_ref
        raise ProblemError(
            kind="dependency",
            code="engine_number_not_linked",
            title="This number is not known to the voice platform",
            # No E.164 in the message (hard rule 6) — see the Bolna twin.
            detail=(
                "The voice platform has no record of this phone number, so no agent can be "
                "set to answer it."
            ),
            remediation=(
                "Connect the number to the voice platform account first, then assign the "
                "agent again."
            ),
        )

    async def bind_inbound_number(self, ref: EngineAgentRef, number: ProvisionedNumber) -> None:
        require_capability("inbound_binding", engine=self)
        # LAST WRITE WINS, matching what the Protocol promises: re-pointing a number at a
        # different agent is a legitimate re-bind, not a conflict, because
        # `phone_numbers.agent_id` is the authority on which agent owns a number.
        self._inbound[self._number_key(number)] = ref

    async def unbind_inbound_number(self, number: ProvisionedNumber) -> None:
        require_capability("inbound_binding", engine=self)
        # ABSENT IS SUCCESS (the Protocol's clause): the postcondition is "nothing of ours
        # answers this number", which an unbound number already satisfies. `pop` with a
        # default rather than a membership test, so the two cannot drift apart.
        self._inbound.pop(self._number_key(number), None)

    def inbound_agent_for(self, engine_number_ref: str) -> EngineAgentRef | None:
        """Which agent this engine would hand an incoming call on that number to."""
        return self._inbound.get(engine_number_ref)

    # --- knowledge base ------------------------------------------------------
    #
    # `_kb` holds what the agent would actually retrieve from, so the KB tests can read
    # it the way a caller would hear it. Handles are derived from (agent ref, our
    # kb_id) rather than stored, which keeps them stable across a re-attach — a real
    # engine mints a fresh id instead, and no caller may assume either, which is why
    # the handle is opaque in the contract.

    def _kb_handle(self, ref: EngineAgentRef, kb_id: str) -> EngineKBRef:
        return self._stable_id("fakekb", ref, kb_id)

    @staticmethod
    def _claimed_source(kb_id: str) -> UUID | None:
        """`KBSourceRef.kb_id` as a source id, or None when it is not one.

        The real adapters recover this from a file name THEY wrote; this engine is handed
        the id directly, so the only failure mode left is a caller (a test, usually)
        passing something that is not a uuid — and inventing an attribution for it would
        be exactly the guess `AccountKBObject.claimed_source_id` documents itself as never
        making.
        """
        try:
            return UUID(kb_id)
        except ValueError:
            return None

    async def attach_kb(
        self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None
    ) -> EngineKBRef:
        # `agent` IS IGNORED HERE, AND THAT IS THE HONEST ANSWER RATHER THAN AN OVERSIGHT
        # (D-488). It exists for engines that hold the knowledge linkage as agent state
        # and can only rewrite it with a full-replacement PUT; this engine's KB store is
        # keyed on the agent ref directly, so there is no second object to keep in step.
        # Accepting and ignoring it is what keeps the fake a fair stand-in: a fake that
        # REQUIRED it would make the parameter look load-bearing everywhere.
        require_capability("knowledge_base", engine=self)
        attached = self._kb.get(ref, [])
        # Re-attaching the SAME source replaces it. Appending a second copy would make
        # the fake engine the one place where a duplicate is normal, and the duplicate
        # is precisely the defect the rest of this file has to be able to expose.
        self._kb[ref] = [s for s in attached if s.kb_id != source.kb_id] + [source]
        handle = self._kb_handle(ref, source.kb_id)
        # THE ACCOUNT-LEVEL OBJECT, recorded beside the linkage rather than instead of it.
        # An attach on the primary engine is two writes to two objects (a create at the
        # account, then a reference on the agent), and a fake with only the second half
        # cannot express the state every failure in this feature leaves behind: an object
        # the account holds that no agent references.
        self._account_kb[handle] = AccountKBObject(
            handle=handle,
            claimed_source_id=self._claimed_source(source.kb_id),
            state="ready",
            created_at=datetime.now(UTC),
        )
        return handle

    async def detach_kb(
        self, ref: EngineAgentRef, kb: EngineKBRef, *, agent: AgentConfig | None = None
    ) -> None:
        require_capability("knowledge_base", engine=self)
        attached = self._kb.get(ref, [])
        remaining = [s for s in attached if self._kb_handle(ref, s.kb_id) != kb]
        if len(remaining) == len(attached):
            # Mirrors the vendor's 404 on `DELETE /knowledgebase/{rag_id}`. A fake that
            # shrugged here would let the publisher believe it had removed text that is
            # still being read out on live calls.
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform does not hold that knowledge base.",
            )
        self._kb[ref] = remaining
        # Both halves, in the order the real detach performs them: the reference goes,
        # then the account's object. A fake that unlinked without deleting would report an
        # orphan on every routine republish.
        self._account_kb.pop(kb, None)

    async def list_account_kb(self) -> AccountKBListing:
        """Every knowledge base this ACCOUNT holds, referenced or not.

        Complete by construction — there is no page to miss in a dict — so `complete` is
        True here and that is a fact rather than the optimistic default the type refuses.
        """
        require_capability("knowledge_base", engine=self)
        return AccountKBListing(
            objects=sorted(self._account_kb.values(), key=lambda o: str(o.handle)),
            complete=True,
        )

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        # Refuses rather than returning `[]`. An empty list is a POSITIVE claim that the
        # agent holds no documents, and `kb/service._reconcile_engine_state` reads exactly
        # that claim to decide whether the engine is serving text our rows cannot account
        # for. On an engine with no knowledge base the honest answer is "that question
        # does not apply here", and the caller must be made to notice.
        require_capability("knowledge_base", engine=self)
        return [self._kb_handle(ref, source.kb_id) for source in self._kb.get(ref, [])]

    # --- reading the truth ---------------------------------------------------

    def _cost_for(self, duration_s: int) -> CostBreakdown:
        # `rounding=ROUNDING` (half-up), never the ambient `decimal` context. This is
        # FIXTURE money, not a client's, and the mode is still explicit for the reason
        # `billing/rates.py` gives: `Decimal.quantize()` with no mode reads
        # `decimal.getcontext()`, which is process-global and mutable by any library in
        # the image, so a leg price here could move because something else imported.
        # It matters more than "fixture" suggests — this breakdown is what every
        # pipeline and conformance test meters, so a fake that rounds differently from
        # the real write path (`pipeline._unit_price`) makes the suite agree with a
        # policy production does not use.
        minutes = Decimal(duration_s) / Decimal(60)
        legs = {
            k: (v * minutes).quantize(Decimal("0.0001"), rounding=ROUNDING)
            for k, v in _COST_PER_MIN.items()
        }
        total = sum(legs.values(), Decimal("0"))
        return CostBreakdown(
            total_inr=total.quantize(Decimal("0.0001"), rounding=ROUNDING),
            platform_inr=legs["platform"],
            network_inr=legs["network"],
            llm_inr=legs["llm"],
            tts_inr=legs["tts"],
            stt_inr=legs["stt"],
            source_currency="INR",
            source_amount=total,
            fx_rate=Decimal("1"),
        )

    def _snapshot_from(self, call_id: str, call: _StoredCall) -> ExecutionSnapshot:
        status = call["status"]
        duration = call.get("duration_s") or 0
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=call.get("agent_ref") or None,
            # `call["direction"]`, not `.get(..., "inbound")`. The key is required, so
            # mypy resolves `.get` to the value type and NEVER type-checks the default —
            # a `.get("direction", "inboud")` typo is invisible to both checkers AND
            # unreachable at runtime, which is the worst of both. Subscripting says what
            # is true (both writers set it) and is the only form a checker can guard.
            direction=call["direction"],
            # The fake IS its own vendor and stores OUR enum, so the normalized status
            # and the raw one are the same string — no map, unlike the two real adapters.
            status=status,
            raw_status=status,
            # `TERMINAL_STATUSES`, not a retyped tuple of the same five members: the
            # shared constant is what the pipeline branches on, and a fake that decided
            # terminality from its own copy could disagree with production about when a
            # call is over while every test still passed.
            terminal=status in TERMINAL_STATUSES,
            billable_ready=status == "completed",
            started_at=call.get("started_at"),
            ended_at=call.get("ended_at"),
            duration_s=duration,
            from_e164=call.get("from_e164"),
            to_e164=call.get("to_e164"),
            recording_url=f"https://fake-engine.local/recordings/{call_id}.wav",
            transcript=[
                TranscriptTurn(call_id=call_id, idx=i, speaker=speaker, text=text)
                for i, (speaker, text) in enumerate(SAMPLE_TURNS)
            ],
            cost=self._cost_for(duration) if status == "completed" else None,
            engine_extracted={},
            latency=_SAMPLE_LATENCY if status == "completed" else None,
            engine=self.name,
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        call = self._calls.get(call_id)
        if call is None:
            # RAISES, and the comment that used to sit here said it did while the code
            # fabricated a `status="failed"` snapshot instead (P2.6). Two adapters then
            # disagreed about the same input — `BolnaEngine` 404s, so `_request` raises
            # `engine_rejected` — which is verbatim the divergence the conformance suite
            # exists to prevent, and it went unnoticed because there was no clause for
            # `get_execution` on an unknown id (there are explicit ones for `get_agent`
            # and `detach_kb`).
            #
            # A FABRICATED "failed" IS THE WORST OF THE AVAILABLE ANSWERS, because it is
            # indistinguishable from a real failed call: the poller would record a repair
            # for a phantom execution, and `_pipeline_settled` would judge artefacts for
            # a call the engine has never heard of. The same argument
            # `test_reading_an_agent_the_engine_never_created_is_reported` makes one
            # method up.
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform could not complete this operation.",
                failure_stage="CORE_LOGIC",
            )
        # THE DOCUMENT IS THIS ENGINE'S OWN ANSWER, and this adapter IS its own vendor —
        # so the archive is exercised offline (DEV-SETUP §3) rather than only against a
        # transport stub. It carries the execution id because a document that is identical
        # for two different calls is an archive that describes neither, which the
        # conformance suite refuses; `_calls` alone does not hold the id.
        return self._snapshot_from(call_id, call).model_copy(
            update={
                "raw_document": engine_document({"execution_id": call_id, **call}, engine=self.name)
            }
        )

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """TRUNCATES for real, because a fake that never truncates cannot keep the
        contract honest. (It does not PAGE — there is no continuation to follow in
        memory, and `pages_fetched` stays an honest 1. Its predecessor's first line said
        "paginates", which describes a mechanism this adapter does not have and would
        make `pages_fetched == 1` read as a bug rather than as the truth.)

        The whole point of the second adapter is that a behaviour the contract requires
        gets exercised somewhere other than the vendor's imagination. `ExecutionListing.
        complete` is a claim the poller acts on (it alerts when it is False), so the fake
        must be able to produce BOTH answers: it returns at most `listing_page_size`
        snapshots and reports `complete=False` when it had to cut the window short.

        It does NOT invent a continuation for the caller to follow: paging is the
        adapter's private business and the contract exposes no cursor (hard rule 2), so
        a truncated window here is exactly what the caller must cope with from any
        adapter that cannot see past page one.

        **THE REASON IS `page_cap_reached`, NOT `full_page_suspected`, and the difference
        is what an operator does next.** `full_page_suspected` means "nothing PROVES
        truncation; the adapter refuses to claim completeness" — a heuristic, which is the
        honest answer for a vendor that publishes no pagination contract. This engine is
        its own vendor and enumerated its own store, so truncation here is not suspected,
        it is KNOWN: our own bound stopped a walk that had more to give, which is exactly
        what `page_cap_reached` is defined as. Reporting the weaker label would make the
        one adapter that cannot be wrong about this the one adapter that understates it,
        and each reason is a distinct alert an operator routes on.
        """
        rows = [
            self._snapshot_from(cid, call)
            for cid, call in self._calls.items()
            if (call.get("started_at") or datetime.now(UTC)) >= since
        ]
        if len(rows) <= self.listing_page_size:
            return ExecutionListing(snapshots=rows, complete=True)
        return ExecutionListing(
            snapshots=rows[: self.listing_page_size],
            complete=False,
            incomplete_reason="page_cap_reached",
        )

    # --- webhooks ------------------------------------------------------------

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """Report the method THIS INSTANCE declared, and actually enforce it.

        Under the default descriptor (`webhook_auth="none"`) this accepts everything, as
        it always has: the fake engine exists to exercise the code AFTER verification,
        and `method="none"` plus a `reason` is what stops a caller mistaking it for
        evidence. `test_a_claimed_verification_method_actually_rejects_somebody` permits
        exactly that, and only that.

        Under a descriptor declaring `hmac` it must genuinely reject somebody, or that
        same clause fails it — which is the contract working: a label nothing enforces is
        the "public write endpoint wearing the word verified" the clause was written to
        catch. So the signing instance verifies a real HMAC-SHA256 over the RAW body,
        constant-time compared.

        **THE SCHEME BELOW IS OURS, AND IS NOT A GUESS ABOUT ANY VENDOR.** The header
        name is deliberately `X-Calevate-...` so it can never be mistaken for a captured
        vendor contract, and nothing here should be copied into a real adapter — a real
        signing engine's header, canonical string and digest are things to READ IN THEIR
        DOCS, not to infer from this fixture. What this exists to prove is only that our
        side of a signed relationship works at all: until now no adapter claimed `hmac`,
        so every `hmac` branch in the contract, in `WebhookVerdict` and in the receiver
        was unreachable code that had never once been executed.
        """
        method: WebhookAuthMethod = self.capabilities.webhook_auth
        if method != "hmac":
            return WebhookVerdict(ok=True, method=method, reason="fake engine")
        presented = headers.get(FAKE_SIGNATURE_HEADER) or headers.get(FAKE_SIGNATURE_HEADER.lower())
        if not presented:
            return WebhookVerdict(ok=False, method="hmac", reason="signature header absent")
        expected = self.sign(body)
        # `compare_digest`, not `==`: a byte-at-a-time comparison leaks the correct
        # prefix through timing, and a signature check that can be walked one character
        # at a time is not a signature check.
        if not hmac.compare_digest(presented, expected):
            return WebhookVerdict(ok=False, method="hmac", reason="signature mismatch")
        return WebhookVerdict(ok=True, method="hmac")

    def sign(self, body: bytes) -> str:
        """The signature this instance expects for `body` — so a test can produce a
        VALID delivery without restating the construction and drifting from it."""
        return hmac.new(self._webhook_secret.encode(), body, hashlib.sha256).hexdigest()

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        status = str(payload.get("status") or "completed")
        normalized = _STATUS_MAP.get(status, "failed")
        return CallEvent(
            call_id=str(payload.get("id") or payload.get("execution_id") or ""),
            engine_agent_ref=str(payload["agent_id"]) if payload.get("agent_id") else None,
            direction="inbound" if payload.get("direction") == "inbound" else "outbound",
            status=normalized,
            raw_status=status,
            from_e164=payload.get("from_number"),
            to_e164=payload.get("to_number"),
            recording_url=payload.get("recording_url"),
            engine=self.name,
        )

    # --- test affordances ----------------------------------------------------

    def seed_inbound_call(
        self,
        *,
        call_id: str,
        agent_ref: str,
        from_e164: str,
        to_e164: str,
        duration_s: int = 95,
    ) -> None:
        """Used by the smoke test and the regression harness to stage a call that the
        webhook receiver will then 'discover'."""
        now = datetime.now(UTC)
        self._calls[call_id] = {
            "agent_ref": agent_ref,
            "direction": "inbound",
            "status": "completed",
            "started_at": now - timedelta(seconds=duration_s),
            "ended_at": now,
            "duration_s": duration_s,
            "from_e164": from_e164,
            "to_e164": to_e164,
        }


__all__ = [
    "DEFAULT_FAKE_CAPABILITIES",
    "DICTATED_SPEECH_CAPABILITIES",
    "EXTERNAL_DEPLOYMENT_CAPABILITIES",
    "FAKE_SIGNATURE_HEADER",
    "FAKE_WEBHOOK_SECRET",
    "SAMPLE_TURNS",
    "FakeEngine",
]
