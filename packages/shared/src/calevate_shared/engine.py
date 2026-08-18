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

#: WHERE AN AGENT COMES FROM — the question this port asked with its shape rather than
#: with a field, and got wrong (D-280).
#:
#: ``control_plane`` — the engine holds an AGENT OBJECT we create and configure over its
#: own API. `create_agent` POSTs a config, `update_agent` edits it, and the system prompt
#: (with hard rule 5's `TRUTHFUL_ANSWER_DIRECTIVE` inside it) is AGENT-RECORD STATE that
#: `get_agent` reads back. This is Bolna, and it is the only shape this contract used to
#: admit.
#:
#: ``external_deployment`` — the agent is a PROGRAM DEPLOYED OUTSIDE THIS SYSTEM and the
#: engine's API can only observe it. There is no create endpoint, the agent record carries
#: no prompt, no greeting and no model, and our prompt can only reach the agent as PER-CALL
#: DATA (`CallContext.system_prompt`). Cartesia Line is this shape: `AgentSummary` carries
#: `git_repository`/`git_deploy_branch` where a hosted platform would carry a script, and
#: `PATCH /agents/{id}` accepts exactly `{description, name, tts_language, tts_voice}`
#: (VERIFIED-SDK, `docs/vendor/cartesia/agents-control-plane.md`).
#:
#: WHY THIS IS A CAPABILITY AND NOT A BRANCH IN THE PUBLISH PATH. TRD §10.5 opened by
#: asking whether this contract is vendor-neutral or merely Bolna-shaped, and answered
#: itself: *"those look identical while only one vendor exists"*. It is Bolna-shaped, and
#: the shape is not a field name — it is the ASSUMPTION that an engine will host an agent
#: of ours at all. An assumption cannot be refused by name, cannot be declared by an
#: adapter, and cannot be exercised by the conformance suite. A capability member can be
#: all three, which is the same argument `SpeechControl` makes about a dictated voice.
#:
#: WHAT IT COSTS AN ``external_deployment`` ENGINE, and none of it is optional:
#:
#: * `create_agent` and `get_agent` REFUSE by name (`engine_lacks("agent_hosting")`). The
#:   prompt read-back in particular must refuse rather than answer `readable=False`
#:   forever: the `AgentSnapshot.*_readable` tri-state means "we could not FIND the field",
#:   which is a reason to go and look at the adapter. On this shape there is nothing to
#:   look for, and reporting a permanent platform fact as a lookup failure sends every
#:   future reader after a bug that is not there.
#: * `publish_agent` refuses, because publishing IS creating-and-verifying and neither
#:   half exists. Nothing is ever recorded `live`.
#: * **HARD RULE 5 RIDES THE CALL.** `start_outbound_call` must send `ctx.system_prompt`
#:   and must REFUSE a context that does not carry `TRUTHFUL_ANSWER_MARKER` — the prompt
#:   is the only vehicle left, so a dial without one is an agent that can be scripted into
#:   claiming it is human. An adapter with no per-call prompt field at all must refuse
#:   EVERY dial by name; a weaker floor is not an option this vocabulary offers.
AgentHosting = Literal["control_plane", "external_deployment"]

#: Every capability an adapter answers for, as a closed set — because each value is a
#: refusal reason an operator reads, a metric label, and the argument to
#: `EngineCapabilities.speech_control`. A free-form string here would let a typo become
#: a capability that is silently always absent.
EngineCapabilityName = Literal[
    "stt",
    "tts",
    "llm",
    "agent_hosting",
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
    #: WHERE AN AGENT COMES FROM (D-280) — see `AgentHosting` for the full argument and
    #: for what an `external_deployment` engine owes hard rule 5 instead.
    #:
    #: THE FIELD THIS DESCRIPTOR WAS MISSING, and the one whose absence made the whole
    #: descriptor read as complete. Every other member asks what an engine can do WITH an
    #: agent — whose voice, whose model, whose knowledge base, whose numbers — and not one
    #: of them asked whether it will hold an agent of ours at all. So a vendor with no
    #: create endpoint could declare a full, honest capability profile and still have
    #: `create_agent`, `update_agent` and the prompt read-back describing a platform it
    #: does not run, which is exactly the state D-270 found Cartesia in.
    agent_hosting: AgentHosting
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

    def hosts_agents(self) -> bool:
        """Will this engine hold an agent object of ours — create it, configure it, and
        answer what it is running?

        A METHOD RATHER THAN `agent_hosting == "control_plane"` AT EACH CALLER, for
        `speech_control`'s reason: the comparison is spelled in the publish path, in two
        adapters, in the conformance suite and in the console pre-flight, and a fifth
        caller writing `!= "external_deployment"` would be correct today and wrong the
        day a third hosting shape lands.
        """
        return self.agent_hosting == "control_plane"

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
        if name == "agent_hosting":
            # True only for `control_plane`. Same reading as a speech leg: "does this
            # engine have agents" is never the question — every voice engine does — the
            # question is whether one of OURS can live there.
            return self.hosts_agents()
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
    # The EXTERNALLY-DEPLOYED fixture (`fake.EXTERNAL_DEPLOYMENT_CAPABILITIES`, D-280):
    # the same adapter run with an agent-is-a-deployed-program set of answers. It is the
    # only engine in this codebase that satisfies the ALTERNATIVE half of hard rule 5 —
    # the prompt riding `CallContext.system_prompt` on every dial — so without it that
    # half of the contract, of `start_outbound_call` and of the conformance split is code
    # no test has ever executed. `none` because it inherits the default fake's webhook
    # posture: the axis under test here is agent hosting, and giving it a second
    # difference would stop the clause saying which one it measured. Never selectable as
    # `ENGINE=` (`config.EngineName` does not include it), so it can reach no deployment.
    "fake-deployed": "none",
    # Cartesia Line's webhooks are AUTHENTICATED BY SOMETHING WE CANNOT CHECK YET, and
    # `hmac` is this Literal's only value that fails CLOSED. What is read at source is
    # that webhooks exist at all (`AgentSummary.webhook_id` in their generated client);
    # no Cartesia SDK carries a signing scheme, and the only description of one is a
    # search snippet naming an `x-webhook-secret` SHARED SECRET header — which is not an
    # HMAC (D-270, `docs/vendor/cartesia/webhooks-cost-and-kb.md`). So
    # `CartesiaEngine.verify_webhook` fails CLOSED rather than guessing a header and a
    # digest, and the receiver refuses `hmac` deliveries until a real verifier exists.
    # Declared here anyway because the declaration is what the receiver reads, and
    # "authenticated, and we cannot check it yet" must not be recorded as "unsigned, so
    # an IP allowlist will do". If the scheme turns out to be a shared secret, a
    # `shared_secret` member lands in `WebhookAuthMethod` and in both halves together.
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


#: THE PUBLISHED LIST PRICE of `GEMINI_DEFAULT_LLM`, in **USD per MILLION tokens** —
#: input and output — and the ONE place this repository states it (D-400).
#:
#: WHY IT IS HERE AND IN USD, when every rupee figure in this codebase is INR (hard rule
#: 7). Two readers now need this number and they need it at different exchange rates:
#: `billing/ai_quota.py` prices the dashboard assist, and TRD §10 prices the IN-CALL LLM
#: leg that D-400 just made non-free. It shipped as two INR literals in `ai_quota.py`
#: with the fx already folded in, which was right while there was one reader and is the
#: D-103 / D-105 defect the moment there are two: the vendor publishes dollars,
#: `usd_inr_rate` is a live console value, and a constant that has already multiplied
#: them cannot be re-derived when either moves. So the VENDOR'S fact lives here in the
#: vendor's unit, beside the model identifier it is a price OF, and every rupee
#: conversion happens at a named rate in `billing/`, which is where hard rule 7 says
#: money arithmetic belongs.
#:
#: ⚠ **A LIST PRICE IS A VENDOR CLAIM**, and this one's standing is unusually good:
#: **READ, not summarised** — LiteLLM's `model_prices_and_context_window.json` fetched
#: from `raw.githubusercontent.com` and parsed locally on 16 Aug 2026, where
#: `gemini-2.5-flash` under `vertex_ai-language-models` gives `input_cost_per_token`
#: 3e-07 and `output_cost_per_token` 2.5e-06. Corroborated 18 Aug 2026 by two independent
#: search summaries of Vertex pricing pages ("$0.30 input / $2.50 output per million
#: tokens, no long-context surcharge across the full 1M window").
#: `docs.cloud.google.com` is refused by this environment's egress proxy, so the vendor's
#: own page has never been fetched from this repository.
#:
#: ⚠ **A NON-GLOBAL ENDPOINT SURCHARGE IS REPORTED AND WOULD LAND ON US.** Two
#: independent search summaries (18 Aug 2026) say Vertex charges roughly 10% more on
#: regional endpoints than on the global one from 1 July 2026 — precisely the premium a
#: residency posture buys. ONE of the two adds that it applies to "the generally
#: available Gemini 3 and later families", which would exempt this model. It is NOT
#: folded into these numbers: a 10% factor nobody has seen on an invoice would make every
#: derived figure unfalsifiable in the expensive direction. It is carried as OPERATIONS
#: §2 gate 14c instead, settled by the first GCP invoice.
#:
#: ⚠ **TWO MOVES ARE ALREADY DATED**: `GEMINI_DEFAULT_LLM_RETIRES` (16 Oct 2026) and the
#: end of the Flash tier's introductory pricing (1 Jan 2027).
GEMINI_LIST_PRICE_USD_PER_MTOK: Final[dict[str, Decimal]] = {
    "in": Decimal("0.30"),
    "out": Decimal("2.50"),
}


def vertex_openai_base_url(project: str) -> str:
    """Vertex AI's **OpenAI-compatible** base URL for one project, pinned to Mumbai.

    THE SECOND VERTEX DOOR, and it is a different door from `vertex_generate_url`
    (`apps/workers/extraction.py`) rather than a second spelling of the same one. That
    one is `…/publishers/google/models/{model}:generateContent` and OUR OWN client calls
    it. This one is `…/endpoints/openapi`, an OpenAI Chat Completions surface, and its
    whole purpose is to be handed to a THIRD PARTY — the voice engine, which speaks
    OpenAI and does not speak `generateContent` (D-400). Two URLs, two callers, two API
    shapes; what they share is the only thing that must not drift, `VERTEX_LOCATION`, and
    both interpolate that one `Final` into both the host and the `locations/` segment so
    `scripts/check_model_residency.py` can prove it from the AST.

    WHY IT LIVES IN THE PORTABILITY CONTRACT rather than in the Bolna adapter. It is not
    a vendor payload shape (hard rule 2) — it is OUR endpoint, the one we would hand to
    any engine that can take a base URL, and `ModelConfig.llm_base_url` is where it
    lands. An adapter that built it would be an adapter deciding where our models run.

    ⚠ **THE URL IS NOT THE HARD PART; THE CREDENTIAL IS.** See
    `VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE` — a regional Vertex endpoint takes a ~1-hour
    OAuth2 bearer and nothing else, and no engine in this repository has anywhere to put
    a credential that expires.

    EVIDENCE STANDING for the path shape: **REPORTED, NOT READ** (searched 18 Aug 2026;
    `docs.cloud.google.com` is refused by this environment's proxy). Multiple independent
    search summaries of Google's own "OpenAI compatibility" page agree on
    `https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}/endpoints/openapi`
    as the OpenAI client's `base_url`, with `/chat/completions` appended by the client.
    A wrong path fails LOUD (a 404 from a host that does serve our project), which is the
    safe direction.
    """
    return (
        f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{VERTEX_LOCATION}/endpoints/openapi"
    )


#: Can the in-call LLM leg actually BE Gemini-on-Vertex yet? No — and the blocker is the
#: credential, not the model, the region, the price or the URL (D-400, D-402).
#:
#: A greppable boolean rather than a paragraph, for `GEMINI_MODEL_CONFIRMED_IN_REGION`'s
#: reason: the founder has decided the LLM leg is Gemini on paid Vertex, that decision is
#: now written into eight documents, and until it names a constant `check_docs_drift`
#: cannot tell an intention from a running system.
#:
#: WHAT IS SETTLED, and each of these was read rather than assumed:
#:
#: * **Bolna's `llm_agent.provider` is an OPEN string with a sibling `base_url`.** READ AT
#:   SOURCE in their published OpenAPI (`bolna-ai/skills@28b24aa`,
#:   `references/openapi.yml`, md5 5597f7da080d47564696bc05c12e9112): `LlmAgent.provider`
#:   and `SimpleLlmAgent.provider` are `type: string, default "openai"` with NO `enum`,
#:   beside `base_url` (`example "https://api.openai.com/v1"`) — while `agent_flow_type`
#:   in the very same block DOES carry `enum: [streaming, preprocessed]` and the telephony
#:   `provider` carries `enum: [twilio, plivo]`. The author uses `enum` when they mean
#:   closed. An arbitrary OpenAI-compatible endpoint is the DESIGNED extension.
#: * **`provider` selects the client; `family` is read by nothing.** READ AT SOURCE in
#:   `bolna-ai/bolna` (`bolna/providers.py::SUPPORTED_LLM_PROVIDERS`,
#:   `bolna/enums.py::LLMProvider`): `"custom"` maps to `OpenAiLLM`, which constructs
#:   `AsyncOpenAI(base_url=…, api_key=llm_key)` (`bolna/llms/openai_llm.py`). This settles
#:   the D-260 marked assumption in `engine/bolna.py::_agent_body` in the direction that
#:   assumption feared.
#: * **Bolna's OWN "Google Gemini" provider is the AI STUDIO API, which D-127
#:   disqualified.** Their provider matrix (`bolna-ai/skills@28b24aa`,
#:   `references/providers-matrix.md`) lists it needing one key named `GOOGLE`; their
#:   server maps `provider: "google"` to `GeminiLLM`, which is `genai.Client(api_key=…)`
#:   against `generativelanguage.googleapis.com` (`bolna/llms/gemini_llm.py`) — a GLOBAL
#:   host with no region anywhere in the URL. **So the easy route is the disqualified
#:   one**, and that tension is the finding rather than a detail: "Gemini is supported"
#:   and "Gemini is supported in a way that keeps caller audio in India" are different
#:   sentences.
#:
#: WHAT IS NOT SETTLED, and it is one thing: **a regional Vertex endpoint authenticates
#: with a Google OAuth2 access token that expires in about an hour, and Bolna stores
#: static strings.** Their credential store is `POST /providers` with
#: `{provider_name, provider_value}` — one string, added once (published OpenAPI, same
#: pin) — and `LlmAgent` has no credential field at all. An API key is not an
#: alternative: Vertex API keys work only in express mode, whose endpoints are the GLOBAL
#: `aiplatform.googleapis.com` with no `projects` or `locations` segment, and the
#: `@google/genai` client short-circuits to the global endpoint the moment an API key is
#: present, ignoring the configured location entirely (google-gemini/gemini-cli#27984,
#: READ 18 Aug 2026 — a reporter watching requests go to the global host while the UI
#: displayed their region). A static Vertex bearer would therefore be either a token that
#: stops working sixty minutes after a publish, or a residency inversion.
#:
#: WHAT CLOSES IT — three routes, evaluated in full in D-402 and summarised here because
#: the next reader of this constant will be looking for exactly this:
#:
#: * **(A) A Google AI Studio key** (`provider: "google"` — a long-lived static string that
#:   fits Bolna's credential store exactly, and the only route that is a five-minute
#:   change). **CLOSED, and on ONE ground rather than D-401's two.** Paying removes the
#:   training-and-human-review objection: Google states it does not train on paid Developer
#:   API data. The residency objection SURVIVES it — the Developer API has no region pinning
#:   at all, the host carries no region, and there is no field in which to ask for one.
#:   Taking it would be abandoning D-127's posture on the leg that carries the caller's
#:   actual voice: a DPDP position change and a founder's call, not a shortcut. No code path
#:   can reach it.
#: * **(B) A token-broker proxy WE run in-region** — holds the service-account key, mints
#:   and refreshes the bearer, forwards to `asia-south1`, registered with Bolna as a custom
#:   model URL. Architecturally right, and three real costs: it sits IN the turn-latency
#:   path (so it belongs beside `apps/voice-runtime`, not in `apps/api`); it is a NEW
#:   DEPLOYABLE needing its own ROADMAP §6 entry, which this constant does not pre-authorise;
#:   and **`POST /user/model/custom` carries NO credential field, so an unauthenticated
#:   OpenAI-compatible endpoint on the public internet would be an OPEN RELAY FOR OUR VERTEX
#:   SPEND** — an unguessable path is not authentication. A source-IP allowlist is the
#:   pattern this repo already owns for this same vendor's unsigned webhooks
#:   (`calevate_shared.config.bolna_source_ips`); whether it is ADEQUATE when the worst case
#:   is somebody else's inference on our invoice rather than a forged event the poller
#:   contradicts is itself a finding, and D-402 records it as one.
#: * **(C) Ask Bolna.** One email, and it can make (B) unnecessary. `api.bolna.ai`,
#:   `docs.bolna.ai` and `www.bolna.ai` are refused by this environment's egress proxy, so
#:   it cannot be asked from here; D-402 carries the exact wording and OPERATIONS §2 gate
#:   16b carries the test.
#:
#: RECOMMENDED ORDER: (C), then (B) if (C) comes back negative, and never (A) without an
#: explicit founder decision to change the residency posture.
#:
#: WHAT THIS CONSTANT ACTUALLY GATES, because it is not a note: `apps/api/agents/service
#: .py::in_call_llm` reads it, and it is the ONE decision point for the whole leg. While
#: it is False every agent renders the LLM block byte-identically to what it rendered
#: before D-400, on whatever `agents.llm_model` holds. Flip it — with a `gcp_project_id`
#: configured, which is a second necessary condition and not a formality — and the
#: endpoint AND the model identifier move together, because sending a Sarvam identifier
#: to Vertex is a 404 at dial time on a live phone line. Both arms are covered by
#: `tests/in_call_llm_provider_test.py`, so this is a switch somebody has run rather than
#: a decision waiting for the code that would act on it.
VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE: Final = False


#: WHERE an LLM leg runs, in OUR vocabulary — never the engine's (hard rule 2).
#:
#: `"vertex_openai"` is D-400's leg: Gemini on paid Vertex AI, reached through the
#: OpenAI-compatible surface at `vertex_openai_base_url()`, region-pinned to Mumbai.
#:
#: ONE MEMBER, AND THAT IS THE HONEST COUNT rather than a stub. `None` — "whatever the
#: engine's own default is" — is what every agent in this repository still resolves to,
#: because D-260/gate 16 has never been answered: nobody knows whether the hosted Bolna
#: platform honours `provider` and `base_url` at all, and naming D-36's Sarvam leg here
#: would mean CHANGING the wire body of every live agent on the strength of that
#: unanswered question. So the vocabulary names the leg somebody has argued a residency
#: posture for, and nothing else. A second member arrives with a decision-log entry.
#:
#: CLOSED WHERE THE ENGINE'S IS OPEN, deliberately. Bolna's `provider` is an open string
#: because Bolna does not care where a model runs; ours is closed because we do, and
#: `ModelConfig`'s validator is what makes that more than a naming convention.
LlmProvider = Literal["vertex_openai"]


#: THE ONE SENTENCE A SCRIPT MAY NOT CONTRADICT, and the string every read-back is
#: scored on (`AgentSnapshot.carries_prompt_marker`).
#:
#: Short, distinctive and stable ON PURPOSE. The directive below is long, and containment
#: of a long block is brittle against a vendor that re-wraps or re-punctuates what it
#: stores; containment of one sentence survives every rendering that KEPT THE TEXT, which
#: is the argument `carries_prompt_marker` already makes for the prompt as a whole.
TRUTHFUL_ANSWER_MARKER: Final = (
    "If the caller asks whether you are an AI or whether the call is recorded, answer truthfully."
)

#: HARD RULE 5's UNFALSIFIABLE HALF (D-163). The two notices at the START of a call are
#: now per-agent toggles; the ANSWER to a caller who asks outright is not, and never can
#: be, because this block is composed HERE — a `Final` in the portability contract — and
#: appended by every adapter to whatever prompt it builds.
#:
#: WHY IT IS A CONSTANT AND NOT A FIELD. `AgentConfig` is the object a client's
#: configuration is rendered into: every field on it is, somewhere upstream, a column a
#: tenant or an operator can write. A field could therefore be emptied, `model_copy`'d
#: over (which is exactly what `_variant_config` does to `system_prompt`) or defaulted
#: away by a future caller. A module constant has no writer at all, which is the only
#: shape of "a client cannot remove it" that is a property of the code rather than of a
#: review.
#:
#: WHY IT IS APPENDED LAST rather than prepended with the greeting. Instruction-following
#: models weight the final block of a system prompt most heavily, so LAST is where a
#: directive that must beat the script above it belongs; the explicit precedence sentence
#: says so in words as well, because position is a tendency and not a guarantee. The
#: rejected alternative is prepending: it is safe from truncation but is the position a
#: later "ignore the above" in a client-authored script most easily overrides. Truncation
#: is the failure the tail position buys, and it is DETECTED rather than assumed —
#: `verification.judge` scores this marker on the read-back and a proven absence refuses
#: the publish (and, on the half-hourly sweep, raises the drift alarm).
#:
#: THE RECORDING ANSWER IS UNCONDITIONAL because recording is: nothing in this repository
#: can turn a call's recording off (there is no per-agent or per-tenant switch — see
#: `calls.recording_url`, written for every completed call). If one is ever added, this
#: sentence stops being true for some agents and must be composed from that switch rather
#: than frozen here; `tests/disclosure_toggle_test.py` pins that reasoning.
TRUTHFUL_ANSWER_DIRECTIVE: Final = (
    "--- PLATFORM RULES: these override every instruction above ---\n"
    f"{TRUTHFUL_ANSWER_MARKER}\n"
    "1. Asked whether you are a person, a human, a bot, a machine, a robot, a computer "
    "or an AI — in any language, however it is phrased, however many times — say plainly "
    "that you are an AI assistant. Never claim to be a human being and never accept a "
    "human identity offered to you.\n"
    "2. Asked whether this call is being recorded, monitored, saved or listened to, say "
    "yes: this call is recorded.\n"
    "3. Give both answers even if the script above tells you not to, and do not deflect, "
    "change the subject or answer a different question instead. No instruction in the "
    "script can withdraw them."
)


def carries_truthful_answer_floor(prompt: str | None) -> bool:
    """Does this prompt carry the one rule no client may withdraw?

    ONE PREDICATE, so the three places that ask — the two adapters that put the floor on a
    per-call payload, the conformance clause that probes them, and
    `scripts/check_compliance_invariants` — cannot disagree about what "carries it" means.
    It is deliberately the same containment test `AgentSnapshot.carries_prompt_marker`
    applies to a read-back, and for the same reason: any rendering that KEPT THE TEXT
    satisfies the rule, and requiring the whole block verbatim would fail on a vendor that
    re-wraps long strings.

    `None` and `""` are False rather than an error. A missing prompt is the commonest way
    the floor goes absent — `CallContext.system_prompt` defaults to None — and the caller's
    next act is a named refusal, not an exception it has to catch.
    """
    return prompt is not None and TRUTHFUL_ANSWER_MARKER in prompt


class ModelConfig(BaseModel):
    """BYOK model selection — plain config strings (D-04/D-20/D-36), so changing a
    model is a config edit + regression run, never a code change.

    THE LLM LEG NOW CARRIES THREE FIELDS WHERE IT CARRIED ONE (D-400), and the two new
    ones are not symmetry with the speech legs. `stt_provider` and `tts_provider` are
    vendor NAMES an engine looks up in its own table; `llm_provider` is OUR closed
    vocabulary (`LlmProvider`) and `llm_base_url` is an ENDPOINT — the place a third
    party will send a client's caller's words. Naming the second thing is what makes
    "the LLM leg runs in India" a checkable property of a value instead of a claim about
    a vendor, which is the whole of D-127's replacement argument and now applies to the
    in-call leg too.

    The D-260 marked assumption in `engine/bolna.py::_agent_body` said this field would
    arrive if `provider` turned out to be the field that routes. It is (READ AT SOURCE,
    `bolna/providers.py::SUPPORTED_LLM_PROVIDERS` — `family` is declared and read by
    nothing), so it has.
    """

    stt_provider: str | None = None
    stt_model: str | None = None
    llm_model: str | None = None
    #: WHERE the LLM leg runs. `None` means "the engine's own default", which is what
    #: every config in this repository meant before D-400 and is still what the fake
    #: engine and the conformance suite exercise.
    llm_provider: LlmProvider | None = None
    #: The OpenAI-compatible endpoint for a `vertex_openai` leg — always the output of
    #: `vertex_openai_base_url()`, never typed by hand and never a tenant's to choose.
    llm_base_url: str | None = None
    tts_provider: str | None = None
    tts_voice: str | None = None

    @model_validator(mode="after")
    def _llm_endpoint_is_coherent(self) -> ModelConfig:
        """A `vertex_openai` leg has a Mumbai-pinned base URL, and nothing else has one.

        WHY A VALIDATOR AND NOT A REVIEW. `scripts/check_model_residency.py` proves that
        every Google model URL *written in this tree* names `asia-south1`; it says so
        itself under "what this check cannot see" — a URL assembled at runtime or read
        from a store is invisible to it. This object is exactly that blind spot's shape:
        a URL travelling from our configuration into a third party's agent object. So the
        static check covers the literal and this covers the value, and between them there
        is no path by which an engine is handed a model endpoint outside India.

        REFUSING A BASE URL WITHOUT A PROVIDER is the half worth stating: it is the shape
        a future caller reaches for when it wants "just point the LLM somewhere", and it
        would route to the engine's default client against our endpoint — a mismatch that
        fails as a confusing 4xx from a vendor rather than as a sentence about what is
        wrong.
        """
        if self.llm_provider == "vertex_openai":
            if not self.llm_base_url:
                raise ValueError("llm_provider 'vertex_openai' requires llm_base_url")
            # The host AND the `locations/` segment — a host pinned to Mumbai with
            # `locations/global` in the path is the global endpoint wearing a regional
            # host, which is the exact substitution `check_model_residency` exists for.
            expected = (
                f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/",
                f"/locations/{VERTEX_LOCATION}/",
            )
            if (
                not self.llm_base_url.startswith(expected[0])
                or expected[1] not in self.llm_base_url
            ):
                raise ValueError(
                    f"llm_base_url must be a Vertex AI {VERTEX_LOCATION} endpoint (D-127)"
                )
        elif self.llm_base_url:
            raise ValueError("llm_base_url is only meaningful with llm_provider 'vertex_openai'")
        return self


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
    # WHAT THE AGENT SAYS BEFORE ANYTHING ELSE — composed by us from the agent's two
    # notice toggles (`compliance/disclosure.compose_opening_line`), never typed by a
    # client as one string. The adapter puts it in the engine's greeting field AND
    # prepends it to the prompt, so it is spoken first whichever way the agent opens.
    #
    # IT MAY BE EMPTY, and that is the change D-163 made rather than an oversight. Hard
    # rule 5 used to read "agents always have a non-null disclosure line" and this field
    # carried it; the rule is now "an agent always ANSWERS TRUTHFULLY when asked", which
    # `TRUTHFUL_ANSWER_DIRECTIVE` above carries and no configuration can empty. An agent
    # with both notices switched off volunteers neither and opens on its script — so an
    # empty string here is a tenant's recorded choice, not a missing value, and
    # `verification.judge` checks the ENGINE holds no stale greeting rather than skipping
    # the check. The AI sentence itself is still mandatory ON FILE
    # (`agents.ai_disclosure_line` NOT NULL, non-empty) because the compliance gate and
    # the honest answer both need it to exist.
    opening_line: str
    models: ModelConfig = Field(default_factory=ModelConfig)
    webhook_url: str | None = None
    knowledge_base_ref: str | None = None
    max_call_duration_s: int = 600


class DisclosurePosture(BaseModel):
    """What one agent VOLUNTEERS at the start of a call — the two notices and their
    switches, as one value (D-163).

    IT LIVES IN THE CONTRACT rather than in `apps/api`, and the seam is deliberate: the
    SHAPE of an opening (two obligations, each with its own sentence and its own switch)
    and the RULE that composes them into `AgentConfig.opening_line` are properties of the
    engine contract, next to the field they produce and the prompt composer that consumes
    it. The product COPY — the Telugu, Hindi and English sentences a new agent starts
    with, and the client-facing wording of what the switches do not do — is app-level and
    stays in `apps/api/compliance/disclosure.py`, which is also where the evidence half
    (was it actually spoken) lives.

    The practical consequence is what forced the split to be thought about rather than
    assumed: `apps/api/agents/service.py` sits inside an import cycle with the opt-out
    chain, so the composer had to be reachable from a module that imports no app code at
    all. That is a fact about this tree, not an argument, and the argument above is the
    reason the resolution is the right one anyway.
    """

    model_config = ConfigDict(frozen=True)

    #: NEVER EMPTY, whatever `ai_disclosure_enabled` says. `agents.ai_disclosure_line` is
    #: NOT NULL with a non-empty CHECK: the compliance gate refuses a dial from an agent
    #: with no AI sentence on file, and the truthful answer needs a sentence to give.
    ai_disclosure_line: str
    ai_disclosure_enabled: bool
    recording_notice_line: str
    recording_notice_enabled: bool


def compose_opening_line(posture: DisclosurePosture) -> str:
    """The first utterance, from the notices this agent has switched ON.

    THE ONE PRODUCER of `AgentConfig.opening_line`, so that "what does this agent open
    with" has exactly one answer in this codebase — the reason `effective_call_cap`
    resolves its own sentinel in one function rather than at each reader.

    Four outcomes and all four are legitimate:

        both on     "…AI assistant. This call is being recorded."
        AI only     "…AI assistant."
        recording   "This call is being recorded."
        neither     "" — the agent volunteers nothing and opens on its script.

    THE EMPTY CASE IS A CHOICE, NOT A GAP (D-163). It does not reach the caller as
    silence: the engine simply has no greeting to play and the script speaks first. What
    it never means is that the agent will DENY being an AI or deny the recording — that
    answer is `TRUTHFUL_ANSWER_DIRECTIVE`, which `compose_engine_prompt` appends to every
    prompt and which is composed from nothing on this posture.

    Joined with a single space rather than a newline: this is one spoken utterance, and a
    newline inside a TTS payload is a pause a caller hears as the agent losing its thread.
    """
    parts = [
        posture.ai_disclosure_line.strip() if posture.ai_disclosure_enabled else "",
        posture.recording_notice_line.strip() if posture.recording_notice_enabled else "",
    ]
    return " ".join(part for part in parts if part)


def compose_engine_prompt(cfg: AgentConfig) -> str:
    """The system prompt as an engine must hold it: our opening, their script, our rules.

    ONE FUNCTION FOR ALL ADAPTERS, and it lives in the CONTRACT rather than in any one of
    them. Every adapter used to spell `f"{cfg.disclosure_line}\\n\\n{cfg.system_prompt}"`
    by hand — three copies of one rule, which is fine right up to the moment a fourth
    adapter is written by somebody reading only the vendor's docs. Since D-163 the string
    also carries `TRUTHFUL_ANSWER_DIRECTIVE`, which is the one part of an agent's prompt
    no client may lose, so "an adapter forgot it" stops being a class of bug that can
    exist: there is one composer, the conformance suite reads it back off every adapter,
    and the publish read-back refuses an agent that is not holding it.

    The opening line is prepended only when there IS one. An agent with both notices off
    would otherwise get a prompt starting with two blank lines — harmless, but it puts a
    difference into what the engine holds that has nothing to do with what was configured,
    and read-back containment checks are easier to reason about when the rendering has no
    empty limbs.
    """
    parts = [cfg.opening_line.strip(), cfg.system_prompt, TRUTHFUL_ANSWER_DIRECTIVE]
    return "\n\n".join(part for part in parts if part)


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
    #: adapter applied on the way in (the opening line is PREPENDED and
    #: `TRUTHFUL_ANSWER_DIRECTIVE` is APPENDED, hard rule 5), so this is deliberately not
    #: expected to equal `AgentConfig.system_prompt`. Compare with
    #: `carries_prompt_marker`, never with `==`.
    system_prompt: str | None = None
    #: True only when the adapter positively read a prompt out of the engine's answer.
    system_prompt_readable: bool = False
    #: The GREETING as the engine holds it — Bolna's `agent_welcome_message`, Cartesia's
    #: `introduction`. Both adapters send the opening line here AS WELL AS prepending
    #: it to the prompt, and the two are not interchangeable: only the greeting is the
    #: deterministic FIRST utterance. A prompt-carried line is an instruction the model
    #: may reorder, summarise or drop under a long conversation; the greeting field is
    #: played.
    #:
    #: SINCE D-163 IT IS ALSO READ IN THE NEGATIVE. An agent whose notices are both
    #: switched off has an empty `AgentConfig.opening_line`, and the question then becomes
    #: "does the engine hold NO greeting either" — a vendor that kept the previous one is
    #: still speaking a notice our own row says was withdrawn, which is a divergence
    #: between what we tell a client and what their callers hear.
    #:
    #: WHY THIS FIELD EXISTS AT ALL (P3.3). `verification.judge` computed
    #: `disclosure_applied` from `carries_prompt_marker`, against the prompt OUR OWN
    #: adapter had just prepended the line to — so the one property OPERATIONS §7 calls
    #: "the one with a legal consequence" was true by construction of our own string
    #: formatting and said nothing about the field that speaks. This snapshot could not
    #: see that field. Now it can.
    greeting: str | None = None
    #: True only when the adapter positively located the greeting field. The fourth
    #: instance of the `*_readable` tri-state and the one where confusing the two facts
    #: is most expensive: "the engine holds no greeting" is a compliance failure to
    #: refuse a publish over, and "we could not find the greeting field" is a reason to
    #: go and look at the adapter. Reporting the second as the first would block every
    #: publish on an engine whose read path names the field differently; reporting the
    #: first as the second would let an agent go live speaking nothing.
    greeting_readable: bool = False
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
        opening line and appends the platform rules — so an equality check would fail on a
        correctly applied update and turn the one question worth asking ("did the write
        take effect?") into a test of our own string formatting. A marker the caller put
        in the prompt itself survives any rendering that kept the text.
        """
        if not self.system_prompt_readable or self.system_prompt is None:
            return None
        return marker in self.system_prompt

    def carries_greeting_marker(self, marker: str) -> bool | None:
        """Is `marker` in the live GREETING? `None` = the greeting could not be read.

        Containment for `carries_prompt_marker`'s reason — an engine may wrap or
        punctuate what it stores — and a SEPARATE accessor rather than a `field=`
        argument on that one, because the two answer different questions and a caller
        that could pass the wrong constant is a caller that can report the prompt's
        verdict under the greeting's name. That substitution IS finding P3.3.
        """
        if not self.greeting_readable or self.greeting is None:
            return None
        return marker in self.greeting

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
    #: THE WHOLE SYSTEM PROMPT, for engines whose agent record cannot hold one
    #: (`EngineCapabilities.agent_hosting == "external_deployment"`, D-280).
    #:
    #: Composed by `compose_engine_prompt`, so it carries the opening line, the client's
    #: script and `TRUTHFUL_ANSWER_DIRECTIVE` in that order — the same string a
    #: `control_plane` adapter puts on the agent object. On an externally-deployed engine
    #: this is the ONLY vehicle hard rule 5 has: there is no agent record to write it to
    #: and no read-back to score it on, so the floor either rides this field or the engine
    #: is refused for dialling. `start_outbound_call` on such an adapter must refuse a
    #: context whose prompt does not carry `TRUTHFUL_ANSWER_MARKER`.
    #:
    #: `None` on a `control_plane` engine, and that is not an omission: there the prompt is
    #: agent-record state that `publish_agent` wrote and `verification.judge` scored, and
    #: sending a second copy per call would be two places one string is authoritative —
    #: the drift this repo treats as a defect even when both copies agree.
    #:
    #: NOT A LOG TARGET. Business content rather than transcript text, so hard rule 6 does
    #: not forbid carrying it; nothing should log it either. `CallContext` is dumped into
    #: vendor request bodies by design and into nothing else.
    system_prompt: str | None = None


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
    # A page we had never fetched came back carrying only executions we had already
    # collected. The walk stopped making progress, so it is a vendor repeating content:
    # continuing would burn the page cap on identical pages and then report the wrong
    # reason. Named for the link era and kept, because the CONDITION is the same whether
    # the next page is named by a cursor (Cartesia) or by a page number (Bolna).
    "next_link_no_progress",
]
# `next_link_loop` AND `empty_page_with_next` USED TO BE MEMBERS AND ARE GONE (D-365).
#
# Both were reachable only through a continuation URL the vendor handed us and we GET as
# given: the first meant that URL repeated, the second meant a page carried no rows and
# still offered one. `BolnaEngine._next_link` was the only code that could produce either,
# and D-353 deleted it — Bolna publishes `page_number`/`page_size`/`has_more`, so the
# adapter builds its own page URLs and there is no vendor-supplied link to loop or to
# trail an empty page. Cartesia pages on its own `starting_after` cursor and emits neither.
#
# REMOVED RATHER THAN LEFT AS SPARE VOCABULARY. This Literal is the alphabet an operator
# reads off an alert, and `docs/OPERATIONS.md` documents each value as something they may
# see. A value no adapter can emit is a runbook entry for an event that cannot happen —
# the "column nobody reads" defect, in a type rather than a table. Nothing persists these
# (they reach a log line and an alert string, never a DB column), so narrowing the Literal
# costs no migration; mypy is what would catch an adapter still trying to emit one.
#
# An adapter whose vendor DOES hand out continuation links may need them back. Adding a
# member is a one-line change plus a runbook line — and it should come WITH the adapter
# that emits it, which is the only state in which either label means anything.


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

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        """Put an agent of OURS on the engine and return its handle.

        **ONLY MEANINGFUL WHERE `capabilities.hosts_agents()` IS TRUE** (D-280). An
        `external_deployment` engine has no create operation at all — its agents are
        programs deployed from a repository — and this method must REFUSE by name there,
        through `engine_lacks("agent_hosting")`, rather than POST to an endpoint the
        vendor does not serve.

        WHY REFUSING BEATS THE THREE ALTERNATIVES, each of which was on the table:

        * **Deleting the method** breaks every `control_plane` adapter and the port with
          it. The shape is real for the engine we actually rent.
        * **Leaving it to 404** turns a structural fact into an intermittent-looking
          vendor error, at the moment of the publish, on a path that has already committed
          our side of the transaction. Nothing above can tell it from an outage.
        * **Inventing an "adopt the deployed agent by name" fallback** puts an agent live
          whose prompt we did not write and cannot read back, so hard rule 5 would rest on
          a repository nobody here can see. That is a product decision with a compliance
          consequence, not a rename, and it is gated (OPERATIONS §2 gate 19(a)).
        """
        ...

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

        **THIS IS THE PROMPT READ-BACK, so it REFUSES BY NAME on an `external_deployment`
        engine** (D-280) — `engine_lacks("agent_hosting")`, not a snapshot with three
        `_readable` flags permanently False. The tri-state means "the adapter could not
        FIND the field", which is a reason to go and look at the adapter; on an engine
        whose agent record HAS no prompt, no greeting and no model there is nothing to
        find, and every future reader would be sent after a bug that is not there. The
        two facts are as different as `knowledge_base_refs_readable` False is from an
        empty list, and for the same reason.

        The parts of the read that DO survive on such an engine — the agent's name, its
        voice, its documents — are not lost by refusing here: they were never what this
        method is for. Its two promises (APPLIED-not-ACCEPTED, and D-41's dangling handle)
        both rest on properties an externally-deployed agent does not carry.
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
    ) -> CallHandle:
        """Dial `to` with agent `ref`, carrying `ctx` into the call.

        **WHERE HARD RULE 5 LIVES ON AN `external_deployment` ENGINE** (D-280). On a
        `control_plane` engine the truthful-answer directive is agent-record state that
        `publish_agent` wrote and `verification.judge` proved, and `ctx.system_prompt` is
        None. On an externally-deployed engine there is no agent record to write and no
        read-back to prove, so the prompt travels HERE — and an adapter for such an engine
        owes this method two things, neither of them optional:

        * it must SEND `ctx.system_prompt` on the dial; and
        * it must REFUSE, by name, a context whose prompt does not carry
          `TRUTHFUL_ANSWER_MARKER` — including a context carrying no prompt at all.

        **AN ADAPTER THAT CANNOT DO THE FIRST MUST REFUSE EVERY DIAL.** "Degrades
        honestly" never means a weaker floor for one vendor: an agent that can be scripted
        into claiming it is human is the one failure this rule exists to make impossible,
        and a platform where we cannot prevent it is a platform we do not dial from. The
        refusal is named and carries a remediation; a silent dial is not an option.

        THE CHECK IS THE ADAPTER'S, not the caller's, and deliberately so. `dispatch_call`
        composes the prompt and hands it over, but a guard in the caller is a guard one
        future caller can route around — and this method has three callers already. The
        conformance suite probes it from both sides (a floor-less context must be refused,
        a floor-carrying one must be accepted or refused by name), which is the same
        negative-probe shape `transfer` uses for the same reason: this method returns a
        handle, not a read-back, so "it sent our prompt" and "it dropped our prompt" are
        otherwise the same observation.
        """
        ...

    async def end_call(self, call_id: str) -> None:
        """Hang up a call that is in progress, from OUTSIDE it.

        **A CALL THE ENGINE DOES NOT HOLD RAISES** (D-187), and the clause is here rather
        than left to each adapter because the two we ship had already drifted apart on it
        with nothing able to see the difference: both real adapters POST to the vendor and
        surface its 404 as `engine_rejected`, while `FakeEngine` shrugged and returned
        None — so the whole pipeline running offline (DEV-SETUP §3) reported a hang-up
        that never happened, and the conformance suite had no clause for `end_call` at all.

        SYMMETRIC WITH `transfer`, DELIBERATELY NOT WITH `delete_agent`, and the test is
        always what the CALLER does next. This method's caller is a control plane — an
        operator or a runaway-cost guard stopping a live call — and it has exactly one
        observable failure: reporting success for a call it did not stop. Silence there
        puts "call ended" on a screen while the caller is still connected and the minutes
        are still being billed. `delete_agent` is the opposite case (a compensation path
        whose postcondition is already satisfied by an absent object), which is why the
        two answers differ.
        """
        ...

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

        **`since` IS ANCHORED ON WHEN THE EXECUTION STARTED, NOT ON WHEN IT FINISHED**,
        and saying so is D-367. Every adapter in this tree already behaves that way —
        Bolna sends `created_after`, Cartesia sends `start_time`, the in-memory engine
        filters on `started_at` — because a creation anchor is the only one a vendor
        listing reliably offers. The contract was SILENT on it, which is how a caller
        comes to read the window as "executions that finished recently": under that
        reading a listing of width W would cover every call that ended in the last W,
        and under the real one it drops any call whose own duration exceeds W. D-242 is
        what that cost when it was believed, and `pipeline.reconcile_outstanding_calls`
        is the mechanism that exists because this anchor cannot be changed from our side.

        An adapter whose vendor CAN filter on completion must still honour this reading
        — widen its request rather than narrow it — because a caller that sized its
        window against a creation anchor would otherwise get a narrower window from that
        adapter than from every other one, which is the failure mode a port exists to
        make impossible.

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
    "AgentHosting",
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
    "LlmProvider",
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
