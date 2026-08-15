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
from typing import Any

from calevate_shared.engine import (
    E164,
    AgentConfig,
    AgentSnapshot,
    CallContext,
    CallHandle,
    CostBreakdown,
    EngineAgentRef,
    EngineCapabilities,
    EngineKBRef,
    ExecutionListing,
    ExecutionSnapshot,
    KBSourceRef,
    ModelConfig,
    NumberSpec,
    ProvisionedNumber,
    WebhookAuthMethod,
    WebhookVerdict,
)
from calevate_shared.events import CallEvent, CallStatus, TranscriptTurn

from apps.api.core.errors import ProblemError
from apps.api.engine.capabilities import require_capability, require_speech_leg

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
SAMPLE_TURNS: tuple[tuple[str, str], ...] = (
    ("agent", "Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi."),
    ("caller", "Namaskaram, naaku appointment kavali."),
    ("agent", "Tappakunda. Ee roju evening 6 gantalaku doctor available unnaru."),
    ("caller", "Sare, appointment book cheyandi. Naa peru Ravi, number 9876543210."),
    ("agent", "Thank you Ravi garu, mee appointment 6 PM ki book chesanu."),
)

# Per-minute INR from the verified rate card (TRD §10.1, D-35/D-36): all-Sarvam BYOK.
_COST_PER_MIN = {
    "platform": Decimal("1.7500"),
    "network": Decimal("0.6000"),
    "stt": Decimal("0.5000"),
    "llm": Decimal("0.0000"),  # Sarvam 105B is free per token (D-35)
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
    campaigns=False,
    knowledge_base=True,
    number_series=frozenset(),
    transfer=False,
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
    campaigns=False,
    knowledge_base=False,
    number_series=frozenset(),
    transfer=True,
    webhook_auth="hmac",
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
        self._calls: dict[str, dict[str, Any]] = {}
        self._kb: dict[str, list[KBSourceRef]] = {}

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

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        self._assert_speech_is_ours(cfg)
        ref = self._stable_id("fakeagent", cfg.tenant_id, cfg.agent_id)
        self._agents[ref] = cfg
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        self._assert_speech_is_ours(cfg)
        self._agents[ref] = cfg

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """Read back what this engine actually HOLDS for `ref` — never what it was last
        handed.

        Two details make this a real second implementation rather than a mirror:

        * it reads `self._agents[ref]`, so it answers about the agent asked for. An
          adapter that echoed the most recent `create_agent`/`update_agent` argument
          would agree with every caller and detect nothing, which is why the conformance
          suite reads two agents back;
        * it renders the prompt the way a real engine holds it — disclosure line
          PREPENDED, exactly as `BolnaEngine._agent_body` sends it (hard rule 5). Storing
          `cfg.system_prompt` verbatim would make the fake the only engine where a
          read-back equals what was sent, and a caller could then write an equality check
          that passes here and fails against every real vendor.

        An unknown ref raises, mirroring the vendor's 404: the caller that reads back an
        agent nobody created must not be handed a snapshot that quietly disagrees.
        """
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
            system_prompt=f"{cfg.disclosure_line}\n\n{cfg.system_prompt}",
            system_prompt_readable=True,
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
            models=ModelConfig(
                stt_provider=cfg.models.stt_provider if self.capabilities.is_ours("stt") else None,
                stt_model=cfg.models.stt_model if self.capabilities.is_ours("stt") else None,
                llm_model=cfg.models.llm_model if self.capabilities.is_ours("llm") else None,
                tts_provider=cfg.models.tts_provider if self.capabilities.is_ours("tts") else None,
                tts_voice=cfg.models.tts_voice if self.capabilities.is_ours("tts") else None,
            ),
            models_readable=True,
            engine=self.name,
        )

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        handle = self._stable_id("fakecall", ref, to, ctx.lead_id or "", str(len(self._calls)))
        now = datetime.now(UTC)
        self._calls[handle] = {
            "agent_ref": ref,
            "direction": "outbound",
            "status": "completed",
            "started_at": now,
            "ended_at": now + timedelta(seconds=95),
            "duration_s": 95,
            "from_e164": "+911140000000",
            "to_e164": to,
            "context": ctx.model_dump(),
        }
        return handle

    async def end_call(self, call_id: str) -> None:
        call = self._calls.get(call_id)
        if call is not None:
            call["status"] = "completed"
            call["ended_at"] = datetime.now(UTC)

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
                remediation="Contact us and we will provision a number for your account.",
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

    # --- knowledge base ------------------------------------------------------
    #
    # `_kb` holds what the agent would actually retrieve from, so the KB tests can read
    # it the way a caller would hear it. Handles are derived from (agent ref, our
    # kb_id) rather than stored, which keeps them stable across a re-attach — a real
    # engine mints a fresh id instead, and no caller may assume either, which is why
    # the handle is opaque in the contract.

    def _kb_handle(self, ref: EngineAgentRef, kb_id: str) -> EngineKBRef:
        return self._stable_id("fakekb", ref, kb_id)

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        require_capability("knowledge_base", engine=self)
        attached = self._kb.get(ref, [])
        # Re-attaching the SAME source replaces it. Appending a second copy would make
        # the fake engine the one place where a duplicate is normal, and the duplicate
        # is precisely the defect the rest of this file has to be able to expose.
        self._kb[ref] = [s for s in attached if s.kb_id != source.kb_id] + [source]
        return self._kb_handle(ref, source.kb_id)

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
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
        minutes = Decimal(duration_s) / Decimal(60)
        legs = {k: (v * minutes).quantize(Decimal("0.0001")) for k, v in _COST_PER_MIN.items()}
        total = sum(legs.values(), Decimal("0"))
        return CostBreakdown(
            total_inr=total.quantize(Decimal("0.0001")),
            platform_inr=legs["platform"],
            network_inr=legs["network"],
            llm_inr=legs["llm"],
            tts_inr=legs["tts"],
            stt_inr=legs["stt"],
            source_currency="INR",
            source_amount=total,
            fx_rate=Decimal("1"),
        )

    def _snapshot_from(self, call_id: str, call: dict[str, Any]) -> ExecutionSnapshot:
        raw_status = str(call["status"])
        duration = int(call.get("duration_s") or 0)
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=str(call.get("agent_ref") or "") or None,
            direction=call.get("direction", "inbound"),
            status=raw_status,  # fake only stores our enum
            raw_status=raw_status,
            terminal=raw_status in ("completed", "failed", "no_answer", "busy", "voicemail"),
            billable_ready=raw_status == "completed",
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
            cost=self._cost_for(duration) if raw_status == "completed" else None,
            engine_extracted={},
            engine=self.name,
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        call = self._calls.get(call_id)
        if call is None:
            # Match the real thing: an unknown execution id is an engine-side 404, and
            # the caller must handle it rather than get a synthesized success.
            call = {
                "agent_ref": "unknown",
                "direction": "inbound",
                "status": "failed",
                "duration_s": 0,
            }
        return self._snapshot_from(call_id, call)

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """Paginates for real, because a fake that never truncates cannot keep the
        contract honest.

        The whole point of the second adapter is that a behaviour the contract requires
        gets exercised somewhere other than the vendor's imagination. `ExecutionListing.
        complete` is a claim the poller acts on (it alerts when it is False), so the fake
        must be able to produce BOTH answers: it returns at most `listing_page_size`
        snapshots and reports `complete=False` when it had to cut the window short.

        It does NOT invent a continuation for the caller to follow: paging is the
        adapter's private business and the contract exposes no cursor (hard rule 2), so
        a truncated window here is exactly what the caller must cope with from any
        adapter that cannot see past page one.
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
            incomplete_reason="full_page_suspected",
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
        known: set[str] = {
            "queued",
            "ringing",
            "in_progress",
            "completed",
            "failed",
            "no_answer",
            "busy",
            "voicemail",
        }
        normalized: CallStatus = status if status in known else "failed"  # type: ignore[assignment]
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
    "FAKE_SIGNATURE_HEADER",
    "FAKE_WEBHOOK_SECRET",
    "SAMPLE_TURNS",
    "FakeEngine",
]
