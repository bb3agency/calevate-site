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

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

#: How a webhook from this engine is proved authentic. Shared with `WebhookVerdict.method`
#: on purpose: what an adapter DECLARES and what it REPORTS are the same vocabulary, so
#: the conformance suite can compare them (an adapter that claims `hmac` and answers
#: `none` is caught by a `==`, not by a reviewer).
WebhookAuthMethod = Literal["hmac", "source_ip", "none"]

#: Who chooses one speech/model leg.
#:
#: ``ours`` — BYOK. Our provider and model strings reach the vendor and run on OUR key,
#: so `ModelConfig` is meaningful and a catalogue of ours is a real choice set.
#:
#: ``engine`` — the engine DICTATES the provider. Its own speech product is the only one
#: available, and our `ModelConfig` value for that leg addresses nothing. The adapter
#: must REFUSE such a value rather than drop it: dropping it silently is what produces a
#: picker offering a voice the caller will never hear, which is worse than a 422 because
#: nothing downstream can detect it. (A choice may still exist on the engine's side —
#: its own voice ids — but that is the engine's catalogue, and we do not hold it. Ours
#: is not offered.)
SpeechControl = Literal["ours", "engine"]

#: Every capability an adapter answers for, as a closed set — because each value is a
#: refusal reason an operator reads, a metric label, and the argument to
#: `EngineCapabilities.speech_control`. A free-form string here would let a typo become
#: a capability that is silently always absent.
EngineCapabilityName = Literal[
    "stt",
    "tts",
    "llm",
    "campaigns",
    "knowledge_base",
    "numbers",
    "transfer",
]

#: The speech legs, in the order a call uses them. Derived from the type so a leg added
#: to `SpeechLeg` cannot be forgotten by the conformance suite.
SpeechLeg = Literal["stt", "llm", "tts"]


class EngineCapabilities(BaseModel):
    """What ONE engine can actually do, declared by its adapter (D-93).

    WHY THIS EXISTS. "Switching engines is a config change" was true of the METHODS —
    every adapter implements the same Protocol — and false of the ANSWERS. Bolna is BYOK
    on all three speech legs, owns campaign objects and a built-in knowledge base, signs
    nothing, and fronts Indian telephony. An engine that dictates its own TTS, has no
    knowledge base and signs its webhooks implements exactly the same Protocol and
    disagrees with almost every one of those. Until this type existed those differences
    were expressed as `raise` inside individual adapter methods — discoverable only by
    calling and failing, which means a screen could offer a control the engine will
    refuse, and did.

    So each adapter DECLARES, and every site that used to hard-code Bolna's answer asks
    instead. Two rules make the declaration worth trusting:

    * **An absent capability produces a named refusal, not a crash and not a silent
      no-op.** `apps/api/engine/capabilities.py` holds the one selector and the one
      refusal, in the shape `payment_capability`/`lead_retrieval_capability`/
      `get_sheets_transport` already established.
    * **A claimed capability is exercised by the conformance suite.** A descriptor an
      adapter can lie in is worse than none, because it turns a runtime failure into a
      confident wrong answer — the same defect `CostBreakdown.currency_stated` and
      `AgentSnapshot.*_readable` were introduced to kill.

    NO DEFAULTS, deliberately. Every field is required, so a new adapter must answer
    every question in writing rather than inherit today's engine's answers by omission —
    which is exactly how a Bolna-shaped assumption got everywhere in the first place.
    Frozen because a capability that can be mutated at runtime is a capability two
    callers can disagree about.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Speech-to-text: ours to choose (BYOK) or the engine's to dictate.
    stt: SpeechControl
    #: Text-to-speech. THE field the voice catalogue asks: under `engine` our Sarvam
    #: Bulbul catalogue is not a choice set, it is a list of voices that engine cannot
    #: speak, and offering it is a screen that lies.
    tts: SpeechControl
    #: The LLM. `ours` wherever the engine takes `model=` + `api_key=`.
    llm: SpeechControl
    #: Does the engine hold CAMPAIGN objects of its own? False does not mean campaigns
    #: are impossible — ours are dispatched entirely from `apps/api/campaigns` and
    #: `apps/workers` — it means there is nothing engine-side to configure or reconcile.
    #: The Protocol has no campaign method, so a True here is currently unfalsifiable and
    #: the conformance suite refuses it outright; see the clause for what has to land
    #: with the day it becomes True.
    campaigns: bool
    #: Does the engine have a BUILT-IN knowledge base — `attach_kb`/`detach_kb`/`list_kb`
    #: addressing real engine-side documents (Bolna: `rag_id`)? Under False all three
    #: must refuse by name, and the T3 retrieval tier has no engine behind it.
    knowledge_base: bool
    #: The number classes this engine can PROVISION. Empty = it provisions none, which is
    #: Bolna's answer today (numbers come from the telephony vendor directly). The
    #: 140/160 series are Indian DLT classes; an engine with no Indian telephony path
    #: cannot offer them even if it can sell a number somewhere else.
    number_series: frozenset[NumberSeries]
    #: Will `VoiceEngine.transfer` — a CONTROL-PLANE command issued from outside the call
    #: — actually work? False ⇒ it must refuse by name.
    #:
    #: NOT "does this vendor have a transfer feature". The distinction is not pedantic: it
    #: is the one this field was first got wrong on. An engine whose transfer is initiated
    #: by the agent DURING the call has a real transfer feature and no answer to this
    #: method, and a True on the strength of the feature would put an escalation control
    #: on the console that refuses every time a caller needs a human.
    transfer: bool
    #: How this engine's webhooks are proved authentic. Must equal what `verify_webhook`
    #: actually reports, and must equal `WEBHOOK_AUTH_BY_ENGINE[name]` — the receiver in
    #: `apps/voice-runtime` reads that table rather than importing an adapter (hard rule
    #: 3 forbids the heavy import), so the two must be provably the same answer.
    webhook_auth: WebhookAuthMethod

    def speech_control(self, leg: SpeechLeg) -> SpeechControl:
        """Who chooses `leg`. One accessor so no caller re-derives it from three fields
        and gets the mapping subtly wrong on the one leg it uses least."""
        return {"stt": self.stt, "llm": self.llm, "tts": self.tts}[leg]

    def is_ours(self, leg: SpeechLeg) -> bool:
        """Is `leg` BYOK — i.e. is our `ModelConfig` value for it meaningful at all?"""
        return self.speech_control(leg) == "ours"

    def provisions(self, series: NumberSeries) -> bool:
        """Can this engine provision a number in `series`? Asked per SERIES rather than
        as one boolean because "can buy a number" and "can buy a 140-series number" are
        different facts, and the campaign launch gate matches on the series."""
        return series in self.number_series

    def has(self, name: EngineCapabilityName) -> bool:
        """The generic ask, for callers that hold a capability NAME rather than a field.

        Speech legs answer True when they are OURS: "does this engine have STT" is never
        the question — every voice engine has STT — the question is always whether it is
        ours to configure, and a caller that gets a bare True for a dictated leg would
        go on to send a provider string the engine refuses.
        """
        if name in ("stt", "llm", "tts"):
            return self.is_ours(name)
        if name == "campaigns":
            return self.campaigns
        if name == "knowledge_base":
            return self.knowledge_base
        if name == "numbers":
            return bool(self.number_series)
        return self.transfer


#: The webhook authenticity method of each engine we ship, as DATA — one definition, two
#: readers, exactly the doctrine `calevate_shared.config.bolna_source_ips` established
#: for the allowlist ("ONE ALLOWLIST, TWO READERS").
#:
#: The second reader is `apps/voice-runtime/engine_intake.py`, which must decide how to
#: authenticate a delivery WITHOUT importing an adapter: hard rule 3 forbids the heavy
#: import on the ack path, and the receiver runs as its own deployable. It used to answer
#: with `if engine == "bolna"` — a vendor name hard-coded into the receiver, so a signed
#: engine meant editing the latency-critical service.
#:
#: The conformance suite asserts `adapter.capabilities.webhook_auth == this[adapter.name]`
#: for every adapter, so the table cannot drift from the adapters it describes.
WEBHOOK_AUTH_BY_ENGINE: dict[str, WebhookAuthMethod] = {
    # Bolna signs nothing (D-31, TRD §5): a source-IP allowlist plus execution-id dedupe,
    # payloads as hints, the List-Executions poller as truth.
    "bolna": "source_ip",
    # The fake engine verifies NOTHING by design, which is how the pipeline runs offline.
    # `method="none"` is what stops a caller mistaking it for evidence.
    "fake": "none",
    # The capability-restricted fixture (`fake.DICTATED_SPEECH_CAPABILITIES`): the same
    # adapter run with an engine-dictates-speech, no-knowledge-base, SIGNED-webhook set of
    # answers. It is listed here for one reason worth the line — it is the only engine in
    # this codebase that authenticates with a signature, so without it the `hmac` branch
    # of this table, of `WebhookVerdict` and of the receiver is code no test has ever
    # executed. It is never selectable as `ENGINE=` (`config.EngineName` does not include
    # it), so it can reach no deployment.
    "fake-restricted": "hmac",
    # Cartesia Line signs its webhooks (TRD §10.5). The SCHEME is not sourced — their docs
    # are egress-blocked — so `CartesiaEngine.verify_webhook` fails CLOSED rather than
    # guessing a header and a digest, and the receiver refuses `hmac` deliveries until a
    # real verifier exists. Declared here anyway because the declaration is what the
    # receiver reads, and "signed, and we cannot check it yet" must not be recorded as
    # "unsigned, so an IP allowlist will do".
    "cartesia": "hmac",
}


#: The D-36 canonical LLM, as the vendor spells it (D-105).
#:
#: WHY THIS IS A CONSTANT AND NOT A STRING AT TWO CALL SITES. It was
#: `model: str = "sarvam-m"` in `workers/extraction.py` and `llm_model="sarvam-m"` in
#: `scripts/pilot/gates_api.py`, and **Sarvam retired `sarvam-m`** — their changelog says
#: a Chat Completions request carrying it FAILS. So post-call extraction was aimed at a
#: model that no longer answers, and pilot gate 1 would have configured a live agent with
#: a dead LLM. Neither site was wrong when it was written; there was simply nowhere for
#: the correction to land once, and two places for it to be missed.
#:
#: It is also what TRD §10 has always PRICED — the ₹0.00 LLM leg is "Sarvam 105B, free per
#: token", never the 24B — so the code and the cost model disagreed about which model was
#: running, on the one leg the margin depends on being free.
#:
#: EVIDENCE STANDING: **REPORTED, NOT READ.** `docs.sarvam.ai` is refused by this
#: environment's egress proxy (CONNECT → 403), so this is two independent search summaries
#: of their changelog agreeing, not a page anyone here has fetched. Both report the same
#: three facts: `sarvam-m` is deprecated and rejected; `sarvam-30b` is deprecated in turn
#: with `sarvam-105b` as the migration target; and the fixed-context variants
#: `sarvam-30b-16k` / `sarvam-105b-32k` were retired when the base models grew to their
#: full 64K/128K windows. A wrong identifier fails LOUD — the vendor 400s and
#: `extraction.py`'s error ladder records it — which is the safe direction to be wrong in
#: and the reason this is shipped rather than gated.
SARVAM_DEFAULT_LLM: Final = "sarvam-105b"

#: Identifiers the vendor has RETIRED. Kept as data rather than deleted, because the
#: failure they cause is a 400 from a third party at post-call time — the point in the
#: pipeline furthest from anyone watching — and "why is extraction empty" is a much harder
#: question than "this name is dead". `tests/sarvam_model_identifier_test.py` fails on any
#: of these appearing in shipped code.
SARVAM_RETIRED_LLMS: Final = frozenset(
    {"sarvam-m", "sarvam-30b", "sarvam-30b-16k", "sarvam-105b-32k"}
)


#: THE Vertex AI region, and the only one D-127 permits. Mumbai.
#:
#: WHY IT IS A `Final` HERE AND NOT A `Settings` FIELD, which is the half a reviewer would
#: wave through. `platform_config.managed_fields()` derives the ops console's editable set
#: from `Settings.model_fields` minus the bootstrap keys minus credential-shaped names, so
#: a field called `vertex_location` would be editable from a web form the day it was
#: declared — and a residency posture invertible by a click at 3am is not a posture. Same
#: doctrine `check_bootstrap_keys` applies to `APP_ENV` (D-95 §4), applied to the one other
#: value whose change is a compliance event wearing a config diff.
#:
#: It lives beside `SARVAM_DEFAULT_LLM` because this is where the repo already keeps the
#: facts about which model runs where, and because `scripts/check_model_residency.py`
#: names this file as the home in its own failure text. That guardrail enforces four
#: things about this constant: it is the only spelling of `asia-south1` in shipped code,
#: every `*-aiplatform.googleapis.com` host resolves to it, the `locations/…` path segment
#: interpolates it and nothing else, and no `Settings` field can carry a region at all.
#:
#: The region appears TWICE in a Vertex URL — in the host and in the path — and the two
#: can disagree. One constant is what makes them unable to.
VERTEX_LOCATION: Final = "asia-south1"

#: The Gemini model the dashboard-AI path sends (D-127; PLAN Part 13).
#:
#: **2.5 Flash, and it is the FOUNDER'S CALL taken with the retirement date in front of
#: them** — the trade is stated here rather than in a commit nobody re-reads. D-134 chose
#: `gemini-3.1-flash-lite` to get out from under BRD R-04's 16 Oct 2026 date; D-142 then
#: found that nothing places any 3.x model in `asia-south1` (global plus the `us`/`eu`
#: multi-region REP endpoints only) while the 2.5 class IS reported in Mumbai. So the two
#: candidates were: a model with a long life that the only permitted region may not serve,
#: or a model the region serves that dies on a date. D-127 will not move the REGION — that
#: is the residency leg the whole product rests on — so the choice is between a feature
#: that 404s and a feature with a deadline, and a deadline is a thing an operator can meet.
#:
#: WHAT IT COSTS, AND WHERE THAT COST IS RECORDED: this leg is now exposed to BRD R-04 for
#: real. `GEMINI_DEFAULT_LLM_RETIRES` below is that date as DATA, the build goes red with
#: runway to spare (`tests/sarvam_model_identifier_test.py`), and OPERATIONS §2 gate 14
#: carries the operator-facing version. 3.x would have avoided all of it; it may also have
#: 404'd on the first call.
#:
#: NOT Flash-LITE, which was the founder's stated fallback and is not needed: search
#: places `gemini-2.5-flash` itself in Mumbai, and the fallback exists for the case where
#: only the Lite tier is served there. If gate 14 comes back 404 on this identifier, that
#: fallback — `gemini-2.5-flash-lite`, same family, same retirement date — is the next
#: thing to try, and it has to come out of `GEMINI_RETIRED_LLMS` when it does.
#:
#: EVIDENCE STANDING: **REPORTED, NOT READ**, searched 16 Aug 2026. Every host that would
#: settle it is refused by this environment's egress proxy — `docs.cloud.google.com`,
#: `discuss.ai.google.dev`, `modelavailability.com`, `innfactory.ai`, `gcloud-compute.com`,
#: `openrouter.ai`, `pricepertoken.com` were each ATTEMPTED and each returned
#: EGRESS_BLOCKED — so what follows is independent search summaries agreeing, never a page
#: fetched here:
#:
#: * Google's own data-residency table is summarised as listing, for Mumbai
#:   (`asia-south1`), Gemini 2.5 Flash (1M and 128k), 2.5 Pro, 2.5 Flash-Lite, 2.5 Flash
#:   Image, 2.0 Flash and 2.0 Flash-Lite — with ML processing in-region. That is the same
#:   list a separate search returned before this decision was taken.
#: * A Google developer-forum thread is titled "Is there any model available (or planned)
#:   in the `asia-south1` region on Vertex AI that is MORE CAPABLE than Gemini 2.5 Flash?"
#:   — a user treating 2.5 Flash as the region's ceiling, which is corroboration of a
#:   different kind from a docs summary and points the same way.
#: * Nothing found in either search places a 3.x model in `asia-south1`.
#:
#: The one thing actually READ from this repository is the PRICE, and only because
#: `raw.githubusercontent.com` is not blocked: LiteLLM's `model_prices_and_context_window.
#: json` (main, fetched 16 Aug 2026) gives `gemini-2.5-flash` under `vertex_ai-language-
#: models` as `input_cost_per_token` 3e-07 and `output_cost_per_token` 2.5e-06 — $0.30 and
#: $2.50 per 1M. The same file gives `gemini-3.1-flash-lite` as $0.25/$1.50, which is
#: exactly what `billing/ai_quota.py` priced from, so the table is the right one.
#:
#: ⚠ WHETHER `VERTEX_LOCATION` SERVES IT is STILL a separate fact with its own constant —
#: `GEMINI_MODEL_CONFIRMED_IN_REGION` below, and it is still False. A search summary is
#: not a 200. Read that before believing this one works.
GEMINI_DEFAULT_LLM: Final = "gemini-2.5-flash"

#: The day `GEMINI_DEFAULT_LLM` stops answering — BRD R-04's retirement of the Gemini 2.5
#: family, 16 Oct 2026.
#:
#: A `date` RATHER THAN A SENTENCE, and that is the entire point of the line. The cost of
#: the decision above is a deadline, and a deadline recorded in prose is a deadline whose
#: enforcement is "whoever read it last" — the failure mode CLAUDE.md's hard rule 4 note
#: and this file's own D-105 history are both about. As data it can be asserted on:
#: `tests/sarvam_model_identifier_test.py::test_the_shipped_gemini_model_has_runway_left`
#: turns the build red `RETIREMENT_RUNWAY_DAYS` before it, which is the only mechanism in
#: this repository that will speak up on a day when nobody is thinking about Gemini.
#:
#: WHEN IT FIRES the fix is one constant and one call, in this order: run OPERATIONS §2
#: gate 14 against the newest Gemini `asia-south1` serves, then move `GEMINI_DEFAULT_LLM`
#: to it and this date with it. NOT a region change, and not `locations/global` —
#: `check_model_residency` refuses both and D-127 is why.
#:
#: EVIDENCE STANDING: **REPORTED, NOT READ** — the 16 Oct 2026 date is the one fact D-134,
#: D-142 and this decision have all inherited from search summaries of Google's deprecation
#: schedule rather than from the page. A wrong date here fails SAFE in one direction only:
#: too early and the build asks for a migration nobody needed, too late and the assist 404s
#: with `vertex_model_not_served_in_region` in the log (`workers/extraction.py`) and a
#: disclosed Sarvam fallback carrying the work (G-6). That asymmetry is why the runway
#: below is generous rather than tight.
GEMINI_DEFAULT_LLM_RETIRES: Final = date(2026, 10, 16)

#: Has anyone confirmed that `VERTEX_LOCATION` serves `GEMINI_DEFAULT_LLM`? No.
#:
#: A greppable boolean rather than a paragraph, for `GEMINI_EXTRACTION_DEFAULT`'s reason
#: and `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA`'s shape: the claim "Gemini 3.x Flash-Lite
#: runs on Vertex AI `asia-south1`" is currently in eight documents, and until it names a
#: constant `check_docs_drift` §5 cannot tell those eight sentences from the truth.
#:
#: EVIDENCE STANDING: **REPORTED, NOT READ**, re-searched 16 Aug 2026 with the model
#: changed under it. `docs.cloud.google.com`, `discuss.ai.google.dev`,
#: `modelavailability.com`, `innfactory.ai`, `gcloud-compute.com`, `openrouter.ai` and
#: `pricepertoken.com` were each attempted from this repository and each refused by the
#: egress proxy, so what follows is independent search summaries agreeing, never a page
#: fetched here:
#:
#: * The evidence about the SHIPPED model has REVERSED, and that is why this constant did
#:   not change with it. When `GEMINI_DEFAULT_LLM` was `gemini-3.1-flash-lite`, search
#:   placed the 3.x family on the GLOBAL endpoint and the `us`/`eu` multi-region REP
#:   endpoints and nowhere near Mumbai — the flag was False AND the news was bad. Now that
#:   the shipped model is `gemini-2.5-flash`, search places it squarely in Mumbai (a
#:   summary of Google's data-residency table listing 2.5 Flash, 2.5 Pro, 2.5 Flash-Lite,
#:   2.5 Flash Image, 2.0 Flash and 2.0 Flash-Lite there with ML processing; a developer
#:   forum thread asking for anything in `asia-south1` "more capable than Gemini 2.5
#:   Flash"). The flag is False and the news is GOOD.
#: * **A better expectation is not a confirmation, and the difference is this constant's
#:   whole job.** D-142 minted it precisely because a search summary of an unreadable page
#:   is not evidence a request will succeed; flipping it now on a summary of the SAME
#:   unreadable page, merely because the summary is flattering this time, would be that
#:   argument run backwards. Nothing has been read, nothing has been called.
#:
#: WHAT SURVIVED THE RE-SEARCH, and it is the leg D-127 actually rests on: `asia-south1`
#: is in Vertex's own ML-processing-location table (with Tokyo, Singapore, Sydney, Seoul),
#: and Google states ML processing occurs in the region the request is made in for the
#: regions that table lists. The REGION is not in doubt; the MODEL is. That asymmetry is
#: why this constant is about the model and `VERTEX_LOCATION` above carries no such flag.
#:
#: WHY THE ANSWER IS NOT "USE THE GLOBAL ENDPOINT". Google's own words on it are "you
#: can't control or know which region your ML processing requests are sent to", which is
#: the exact sentence D-127 disqualifies AI Studio over. `check_model_residency` refuses
#: `locations/global` for that reason and must keep refusing it.
#:
#: WHAT CLOSES IT, and NOTHING ELSE DOES: one `generateContent` against
#: `vertex_generate_url(project, GEMINI_DEFAULT_LLM)` with a service-account bearer,
#: returning 200 — OPERATIONS §2 gate 14, on the day the GCP project exists. That project
#: is the external blocker, by name: a Google Cloud account and a service-account key.
#: There is no engineering work between here and the answer. A 404 is the answer "no", and
#: it is a LOUD answer — `VertexGeminiExtractor` logs `vertex_model_not_served_in_region`
#: naming this constant, `assist_capability()` answers `provider_unavailable`, and G-6's
#: disclosed Sarvam fallback carries the work meanwhile. If the answer is no, the decision
#: is a MODEL change (`gemini-2.5-flash-lite` first — the founder's stated fallback, same
#: family, same retirement date — then the newest Gemini `asia-south1` does serve) and
#: never a REGION change: the second is the residency inversion this whole guardrail exists
#: to prevent, and it is nine characters away at all times.
GEMINI_MODEL_CONFIRMED_IN_REGION: Final = False

#: Gemini identifiers no shipped module may name. `tests/sarvam_model_identifier_test.py`
#: scans for them for the reason it scans for the Sarvam ones.
#:
#: MOST OF THESE ARE DATED RATHER THAN ALREADY DEAD, which is the difference from
#: `SARVAM_RETIRED_LLMS`: 16 Oct 2026 is a date somebody has to act before, and the only
#: cheap moment to act is the one where the identifier is being written. A name that dies
#: on a schedule and is caught on the day it dies costs a pipeline returning empty answers
#: with a 404 nobody is watching for.
#:
#: `gemini-2.5-flash` IS NO LONGER IN THIS SET, and the omission is the founder's decision
#: rather than an oversight: it is `GEMINI_DEFAULT_LLM`, so a set that both banned it and
#: shipped it would be incoherent (`test_the_gemini_default_is_not_itself_retired` says so
#: by failing). What the set therefore stopped guarding — a stray `"gemini-2.5-flash"`
#: literal somewhere other than this file — is guarded instead by
#: `test_no_shipped_module_spells_the_gemini_default`, and the DATE it stopped guarding is
#: carried by `GEMINI_DEFAULT_LLM_RETIRES` above. Neither half was dropped on the floor.
#: Its Lite sibling stays banned because it is not what we ship; if gate 14 makes it the
#: fallback, it moves out of here in that same change.
GEMINI_RETIRED_LLMS: Final = frozenset(
    {
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
    }
)


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
    #: The speech/model selections THE ENGINE HOLDS, in our own `ModelConfig` vocabulary —
    #: the read half of the BYOK claim in `EngineCapabilities`. Same type going in and
    #: coming out on purpose: a separate "snapshot of models" shape would be a second way
    #: to say one thing, and the two would drift on the leg nobody reads.
    #:
    #: Only legs the descriptor calls `ours` are expected here. A leg the ENGINE dictates
    #: has no value of ours to report and stays None — reporting the engine's own product
    #: name would smuggle a vendor string across the boundary (hard rule 2) and would
    #: read, to every caller above, exactly like a BYOK selection that had been applied.
    models: ModelConfig | None = None
    #: True only when the adapter positively read the selections out of the engine's
    #: answer — the third instance of the `*_readable` tri-state, for the third time for
    #: the same reason. False means "we could not find them", never "none are set": an
    #: adapter that could not locate the synthesizer block must not report the same thing
    #: as an agent genuinely carrying no voice, because the first is a reason to go
    #: looking and the second is a reason to publish.
    models_readable: bool = False
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

    def holds_speech(self, leg: SpeechLeg) -> str | None:
        """What the engine holds for one BYOK leg, or None when it could not be read.

        `stt`/`llm` answer with the MODEL, `tts` with the VOICE — those are the fields an
        operator picks and the ones a catalogue is written in. The provider is not the
        interesting half: it is implied by the model string in every catalogue we ship,
        and a leg whose provider matched while its model did not is the failure this
        accessor exists to expose.
        """
        if not self.models_readable or self.models is None:
            return None
        return {
            "stt": self.models.stt_model,
            "llm": self.models.llm_model,
            "tts": self.models.tts_voice,
        }[leg]


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
    #: The vendor's OWN answer for this execution, serialized — the ONE thing in this
    #: contract that is not in our vocabulary, and the reason it is `bytes`.
    #:
    #: **WHY IT EXISTS.** D-126 built the erasure arm for an archive of raw vendor
    #: documents (`storage.archive_payload`, `calls.engine_payload_ref`) and deliberately
    #: built it BEFORE the producer, because after the producer the unreachable objects
    #: already exist. The producer needs a raw document, and there was no way for one to
    #: reach a worker: `get_execution` returns this model, this model was entirely
    #: normalized, and hard rule 2 forbids the worker importing an adapter to go and get
    #: the payload itself. So the archive had no caller, the erasure guarded an object
    #: nothing created, and TRD §5's "raw vendor payloads go to object storage refs"
    #: described a store that was always empty.
    #:
    #: **WHY BYTES AND NOT `dict[str, Any]`.** A dict crosses the boundary carrying the
    #: vendor's field NAMES, and `payload["telephony_data"]` needs no import for anyone to
    #: write — which is exactly the leak an import-linter contract cannot see. Bytes carry
    #: the same information and offer no key to read: the only thing a caller can do with
    #: them is store them, which is the only thing a caller is allowed to do with them.
    #: (`tests/engine_audit_test.py` scans the tree for vendor key reads, so the type makes
    #: the leak awkward and the guard makes it caught. Neither alone is enough.)
    #:
    #: **NOT DUMPED AND NOT REPR'D**, and that is hard rule 6 rather than tidiness: this
    #: document holds the caller's number and the transcript verbatim. `exclude=True`
    #: keeps it out of `model_dump()`/`model_dump_json()`, so a snapshot serialized into a
    #: span, a job payload or a log line cannot carry it; `repr=False` keeps it out of the
    #: exception messages a repr ends up inside. It still travels through `model_copy`,
    #: which is how the pipeline receives it.
    #:
    #: Absent (`None`) is a legitimate answer for a LISTING snapshot — the poller does not
    #: archive, and holding a document per row for twenty pages would be a cost with no
    #: reader. `get_execution` is the path the archive runs on, and the conformance suite
    #: requires one there.
    raw_document: bytes | None = Field(default=None, repr=False, exclude=True)


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
    #:
    #: **NO DEFAULT, deliberately, for `EngineCapabilities`' reason.** This field carried
    #: `= True`, so `ExecutionListing(snapshots=rows)` — the shortest thing anyone writes —
    #: minted the exact claim the docstring above forbids: completeness asserted because
    #: nothing was checked. A required field makes an adapter answer the question in
    #: writing, which is the only version of "never the fallback for 'we did not look'"
    #: that a type can enforce.
    complete: bool
    incomplete_reason: ListingIncompleteReason | None = None
    #: How many responses were read. 1 for a single-page vendor; >1 proves the
    #: continuation path actually ran, which is the only way a pilot can see it work.
    #: At least 1: an adapter that returns a listing read something.
    pages_fetched: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _verdict_and_reason_agree(self) -> ExecutionListing:
        """The two fields are one answer, so they may not contradict each other.

        Both directions cost something real and neither is caught anywhere else:

        * `complete=False` with NO reason leaves `reconcile_executions` alerting
          `unknown` — and the reason is a closed enum precisely so the alert has a stable
          deduplication key an operator can route on (BACKEND-PATTERNS §8). "Possibly
          truncated, cause unstated" is the one alert nobody can act on.
        * `complete=True` WITH a reason is an adapter that found evidence of truncation
          and published the all-clear anyway. The poller reads `complete` and stays
          silent, so the reason it did record is seen by nobody — which is worse than not
          having noticed, because it looks like diligence.
        """
        if not self.complete and self.incomplete_reason is None:
            raise ValueError(
                "an incomplete listing must name its reason: the poller alerts on it and "
                "the enum is the alert's deduplication key"
            )
        if self.complete and self.incomplete_reason is not None:
            raise ValueError(
                f"a listing reported complete may not also carry `{self.incomplete_reason}` — "
                "the poller reads `complete` and would stay silent about it"
            )
        return self


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

    #: What this engine can do (D-93). An ATTRIBUTE rather than a method because it is a
    #: fact about the adapter, not a question it goes and asks: every caller — including
    #: a screen deciding whether to render a control — must be able to read it without an
    #: await and without a network round trip. Business code reaches it through
    #: `apps.api.engine.engine_capabilities()`, never by touching an adapter.
    capabilities: EngineCapabilities

    #: The environment keys this adapter reads for its credentials, in the order an
    #: operator should set them (D-104). Empty for an adapter that IS its own vendor.
    #:
    #: This is the NAME half of `holds_credentials`, and it lives here for the same reason
    #: `capabilities` does: "Bolna needs `BOLNA_API_KEY`" is a fact about a vendor, and
    #: hard rule 2 says only `apps/api/engine/` may hold one. It used to live in
    #: `core/settings.py` as `if cfg.engine == "bolna"`, which is why `/healthz/ready` was
    #: green on a credential-less Cartesia deployment — the second vendor arrived and the
    #: hardcoded first one still answered for it.
    #:
    #: It must name what `holds_credentials` actually gates on and nothing more: a key the
    #: adapter merely PREFERS (Cartesia's `CARTESIA_FROM_NUMBER_ID`, needed to dial out but
    #: not to reach the vendor) belongs to the refusal that needs it, not to readiness —
    #: reporting it here would hold a whole deployment down for a control that refuses
    #: cleanly on its own.
    credential_env_keys: tuple[str, ...]

    def holds_credentials(self) -> bool:
        """Can this adapter actually talk to its vendor?

        DERIVED FROM THE ADAPTER, never from a second read of settings — the argument
        `lead_retrieval_capability` makes with `holds_credential_for`: a credential is not
        a statement that a capability exists, and two independent reads of the same
        settings eventually disagree, at which point a screen offers what a route refuses.

        Separate from `capabilities` because they answer different questions and are wrong
        in different ways. `capabilities` is what this engine COULD do for anyone;
        this is whether THIS DEPLOYMENT can reach it at all. An engine with a built-in
        knowledge base and no API key still has a built-in knowledge base.

        Synchronous and cheap: it inspects what the adapter was constructed with. It must
        never make a network call — a screen deciding whether to render a control asks it.
        """
        ...

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

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        """Remove the agent from the engine. **IDEMPOTENT BY CONTRACT.**

        THE HOLE THIS CLOSES. `create_agent` is a side effect at a third party and the
        write of `engine_agent_ref` is a side effect in our database, with no transaction
        spanning the two. D-121 closed the common CAUSE of a failure in that window (the
        create/create race, with a row lock) and could not clean up after the ones that
        remain: a read-back that proves `not_applied` on a create, and a soft-delete
        landing mid-publish, both roll OUR half back and leave THEIRS standing. Until
        this method existed the only remedy was a log line naming a ref and a human in a
        vendor dashboard, which is a remedy the way a note on the fridge is a fire alarm.

        **IDEMPOTENT, and that is the whole reason it is stated here rather than left to
        each adapter.** The caller is a compensation path — the one place in the system
        that runs precisely because something already failed, and therefore the one most
        likely to be retried. A ref the engine does not hold is this method's POST-
        CONDITION already satisfied, not an error: raising there would DLQ a compensation
        job whose work is done, and leave an operator hunting an orphan that no longer
        exists. RFC 9110 §9.2.2 gives the same answer for HTTP DELETE, and an adapter
        whose vendor disagrees is the adapter's problem to absorb, not the caller's.

        Deliberately NOT symmetric with `detach_kb`, which RAISES on a handle the engine
        does not hold. The asymmetry is the difference in what the caller does next:
        `detach_kb`'s caller is about to publish a replacement and is entitled to know
        whether the old text is really gone, while this method's caller wants the object
        gone and has no next step that depends on who removed it.

        IT MUST BE REAL. An adapter that accepts the call and removes nothing turns the
        compensation path into a log line with extra steps, so the conformance suite
        observes the removal through `get_agent` rather than trusting the call.

        WHAT IT COSTS AT THE VENDOR IS NOT THIS CONTRACT'S TO PROMISE. Bolna documents
        that deleting an agent destroys all of its batches and executions; whether every
        engine does is a fact about each engine and is recorded in each adapter. That is
        why nothing in this repo calls it on an agent a human soft-deleted — the only
        caller is the orphan compensator, whose subject is an agent created seconds ago
        that has never taken a call.
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
        """The authenticated read. This — not the webhook — is what we persist.

        **IT MUST CARRY `raw_document`.** The post-call pipeline archives the vendor's own
        answer for the call (D-126), and this is the only method that has one to give: the
        webhook payload is a hint the receiver throws away, and the poller's listing rows
        are summaries. An adapter that returns `None` here does not merely skip a debug
        aid — it makes `calls.engine_payload_ref` a column nothing writes and
        `retention._erase_engine_payloads` an erasure arm guarding nothing, which is the
        state D-126 shipped and this clause exists to keep closed.

        The document is the VENDOR'S, not a re-rendering of the snapshot above: an adapter
        that serialized its own `ExecutionSnapshot` would archive our normalization and
        lose the one thing the archive is for — reading what the vendor actually said when
        our mapping turns out to be wrong.
        """
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
    "WEBHOOK_AUTH_BY_ENGINE",
    "AgentConfig",
    "AgentSnapshot",
    "CallContext",
    "CallHandle",
    "CostBreakdown",
    "EngineAgentRef",
    "EngineCapabilities",
    "EngineCapabilityName",
    "EngineKBRef",
    "ExecutionListing",
    "ExecutionSnapshot",
    "KBSourceRef",
    "ListingIncompleteReason",
    "ModelConfig",
    "NumberSeries",
    "NumberSpec",
    "ProvisionedNumber",
    "SpeechControl",
    "SpeechLeg",
    "VoiceEngine",
    "WebhookAuthMethod",
    "WebhookVerdict",
]
