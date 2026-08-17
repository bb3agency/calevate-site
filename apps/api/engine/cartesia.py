"""Cartesia Line adapter — the second REAL vendor, and the first that disagrees with us.

Adopted as a build-for-the-switch exercise under TRD §10.5 ("make switching a
configuration change"), NOT as an adoption decision. D-31 still rents Bolna.

READ THIS BEFORE WIRING IT TO A LIVE ACCOUNT
=============================================
There is no Cartesia account behind this deployment and no request has ever been made
against their API from this repository. `docs.cartesia.ai` and `www.cartesia.ai` are both
refused by this environment's egress proxy (CONNECT → 403), so **their API reference has
not been read by anyone here.** This module therefore follows `apps/api/billing/
payments.py` exactly: what is corroborated is cited at the line, what is not is marked
UNVERIFIED at the line, and nothing is made to look finished that is not.

EVIDENCE LADDER USED THROUGHOUT — three standings, never blurred:

* **READ AT SOURCE** — taken from `github.com/cartesia-ai/line`, Cartesia's own OSS SDK,
  cloned at commit `3062c978a2408152c6338679baf57aa230c63596` (2026-07-06). This is
  Cartesia's published code, so it is strong evidence about the things it actually
  touches: the API host, the version string, the agent-scoped document endpoint, the
  in-call event vocabulary. It is the same standing the Bolna adapter gives
  `bolna-ai/bolna`.
* **REPORTED, NOT READ** — a search engine's summary of a docs page that could not be
  fetched. Weaker: nobody here has seen the page. Bolna's `GET /v2/agent/{agent_id}`
  carries this same standing and says so.
* **INFERRED** — a RESTful sibling of a path that IS sourced. Weakest. Every inference
  below fails LOUDLY (a 404 becomes `engine_rejected`), never quietly.

WHAT THE SDK CHANGED ABOUT OUR OWN UNDERSTANDING — report this upward
----------------------------------------------------------------------
TRD §10.5's capability table says Cartesia Line has **no built-in KB** and lists
"Built-in KB (`rag_id`) | yes (D-33) | no". **The SDK contradicts that.** `line/
knowledge_base.py` is a first-class client for `GET /agents/{agent_id}/documents/query`,
and `line.llm_agent.knowledge_base` is a shipped built-in tool documented in their README
as "Looks up information from the agent's knowledge base via natural-language query". So
Line has agent-scoped documents with retrieval. That is READ AT SOURCE and it is a
material correction to the doc: the "T0 retrieval would need our own path" consequence
does not follow. `CARTESIA_CAPABILITIES.knowledge_base` is True on that evidence.

THE INTEGRATION MODEL IS GENUINELY DIFFERENT, AND THE PORT MOSTLY SURVIVES IT
-----------------------------------------------------------------------------
Bolna is a hosted agent object: POST a JSON config, they run it. Line is a DEPLOYED AGENT
PROGRAM: you write a `VoiceAgentApp` against their SDK, it is deployed, and their harness
opens a websocket to it per call (`CallRequest` is documented in the SDK as "Request body
for the /chats endpoint"). The system prompt still travels as data — `CallRequest.agent.
system_prompt` — so `AgentConfig` still maps; what has no analogue is a vendor-side
"agent object we POST a synthesizer block into", because the speech stack is theirs.

That difference is exactly what `EngineCapabilities` exists to carry, and it is why the
descriptor was written before this file rather than after.

WHAT IS DELIBERATELY NOT HERE
------------------------------
* **No Cartesia SDK dependency.** `cartesia-line` is their in-call agent RUNTIME, meant to
  run inside their harness; it is not a client for the control plane and adding it would
  be a supply-chain decision (hard rule 9) buying nothing this module needs.
* **No invented Indian telephony story.** `number_series` is empty and
  `provision_number` refuses by name. Line's number paths are Cartesia-provisioned,
  imported Twilio, or Voximplant, none of which yields a DLT-registered 140/160-series
  Indian number, and **whether Line accepts BYOC SIP from an Indian carrier is the single
  UNVERIFIED question that decides whether this exit exists at all** (TRD §10.5). It is
  not resolved here by assumption; it is a gate.
* **No invented signature scheme.** Their webhooks are signed, the scheme could not be
  sourced, and `verify_webhook` therefore FAILS CLOSED with an authored reason rather
  than guessing a header and a digest. Wrong-and-fail-closed refuses real deliveries;
  wrong-and-fail-open is an unauthenticated write endpoint wearing the word "verified".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import httpx
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
    WebhookVerdict,
    compose_engine_prompt,
)
from calevate_shared.events import CallEvent, CallStatus, TranscriptTurn

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.engine.capabilities import (
    NO_CREDENTIALS_REASON,
    engine_not_configured,
    require_capability,
    require_speech_leg,
)
from apps.api.engine.document import engine_document

log = get_logger(__name__)

# READ AT SOURCE: `line/knowledge_base.py:13` — `DEFAULT_BASE_URL = "https://api.cartesia.ai"`.
BASE_URL: Final = "https://api.cartesia.ai"

# READ AT SOURCE: `line/voice_agent_app.py:129` — `CARTESIA_VERSION = "2026-04-03"`, which
# their harness sends on every call setup. PINNED DELIBERATELY, and pinned to a constant
# rather than left to the vendor's default: an unpinned date-versioned API is a silent
# breaking change on somebody else's release schedule, and the failure mode is a field
# quietly disappearing from a response we parse rather than an error we can see.
#
# DISCREPANCY, recorded rather than resolved: the outbound-dialing docs page (REPORTED,
# NOT READ) shows `Cartesia-Version: 2026-03-01`. Two different dates from two sources
# means the version is a real, moving axis. The SDK's is used because it was read at the
# source and is the later of the two; if a live account rejects it, the error will name
# the header, which is why it is a header and not a URL segment.
API_VERSION: Final = "2026-04-03"

# REPORTED, NOT READ (search summary of `docs.cartesia.ai/line/integrations/telephony/
# outbound-dialing`): the outbound call request is authenticated with `X-API-Key` and
# carries `Cartesia-Version`. If the auth header name is wrong every request 401s —
# loud, and the safe direction to be wrong in.
API_KEY_HEADER: Final = "X-API-Key"
VERSION_HEADER: Final = "Cartesia-Version"

REQUEST_TIMEOUT_S: Final = 10.0

# A listing this long is assumed to be a page rather than a window. Conventional page
# sizes cluster at 10/20/25/50/100; 20 is chosen as the smallest plausible one so the
# adapter errs toward "possibly truncated", which is the direction that makes the poller
# look harder rather than the direction that loses calls. UNVERIFIED — Line publishes no
# pagination contract we could read.
_LISTING_PAGE_SUSPECT: Final = 20

# Their per-call handle. READ AT SOURCE (`line/voice_agent_app.py`, `StartInput`): a call
# carries BOTH `call_id` and `agent_call_id`. The outbound-dialing summary says the create
# response returns `agent_call_id` per number dialled, so that is what we key on — using
# `call_id` would key on an id the create response may never have shown us.
_CALL_ID_KEYS: Final = ("agent_call_id", "call_id", "id")

# Line's own lifecycle vocabulary is NOT sourced — no status enum appears in the SDK,
# which only ever sees a live websocket. So this map covers the statuses any telephony
# platform emits, and ANYTHING UNMAPPED BECOMES `failed`, which is the safe direction: a
# call we cannot classify must never be billed or shown as a success. UNVERIFIED.
_STATUS_MAP: Final[dict[str, CallStatus]] = {
    "queued": "queued",
    "pending": "queued",
    "ringing": "ringing",
    "initiated": "ringing",
    "in_progress": "in_progress",
    "in-progress": "in_progress",
    "active": "in_progress",
    "completed": "completed",
    "ended": "completed",
    "failed": "failed",
    "error": "failed",
    "no_answer": "no_answer",
    "no-answer": "no_answer",
    "busy": "busy",
    "voicemail": "voicemail",
}

_TERMINAL_RAW: Final = frozenset(
    {"completed", "ended", "failed", "error", "no_answer", "no-answer", "busy", "voicemail"}
)

# Cartesia Line's capability profile (D-93). Each line's evidence:
#
# * `stt="engine"`, `tts="engine"` — READ AT SOURCE. `line/_harness_types.py:132` defines
#   `TTSConfig(voice_id, pronunciation_dict_id, language)` and `STTConfig(language)`.
#   There is NO provider field on either: the speech stack is Cartesia's product (Sonic /
#   Ink), and our Sarvam Bulbul catalogue addresses nothing on this engine. This is the
#   whole reason `SpeechControl` is per-leg.
# * `llm="ours"` — READ AT SOURCE. `line/llm_agent/provider.py:5` routes through LiteLLM
#   ("See https://docs.litellm.ai/docs/providers"), and their README's own quick start is
#   `LlmAgent(model=..., api_key=os.getenv(...))`. Sarvam is a first-class LiteLLM
#   provider, so D-36's free-per-token LLM leg survives the move. One leg of three.
# * `campaigns=False` — no campaign object appears anywhere in the SDK, and ours are
#   dispatched in our own layer through the compliance gate regardless.
# * `knowledge_base=True` — READ AT SOURCE, and a CORRECTION to TRD §10.5 (module
#   docstring). `line/knowledge_base.py` queries `/agents/{agent_id}/documents/query`.
# * `number_series=frozenset()` — Line has no Indian DLT path (TRD §10.5), and whether
#   BYOC SIP from an Indian carrier is even possible is THE open question. Empty is the
#   only answer that is not a guess, and it makes `provision_number` refuse by name.
# * `transfer=False` — and this one was WRONG in a first draft, caught by the conformance
#   suite, and is the best evidence in this slice that the descriptor is worth checking.
#   The draft said True on real evidence: READ AT SOURCE, `transfer_call` is a shipped
#   built-in tool and the agent yields `AgentTransferCall(target_phone_number,
#   interruptible)` (`line/events.py:58`). Line can transfer calls.
#   But `EngineCapabilities.transfer` does not ask "can this vendor transfer a call"; it
#   asks whether `VoiceEngine.transfer(call_id, to, warm)` — a CONTROL-PLANE COMMAND
#   issued from outside the call — will work. On Line the transfer is initiated BY THE
#   DEPLOYED AGENT MID-CALL, and no endpoint to command one from outside is sourced. So
#   through this port the answer is False, and a True would have had the console offer an
#   escalation control that refuses every time.
#   The vendor feature is not lost by saying so: it is reachable the way Line intends,
#   from inside the agent program, which is a different integration and would arrive as a
#   different capability if we ever need it named.
# * `webhook_auth="hmac"` — their webhooks are signed (TRD §10.5). The SCHEME is not
#   sourced, so `verify_webhook` fails closed rather than guessing one.
CARTESIA_CAPABILITIES = EngineCapabilities(
    stt="engine",
    tts="engine",
    llm="ours",
    campaigns=False,
    knowledge_base=True,
    number_series=frozenset(),
    transfer=False,
    webhook_auth="hmac",
)

#: Authored reason for the one thing we know is signed and cannot yet check. Never vendor
#: prose; it names OUR state.
SIGNATURE_UNIMPLEMENTED_REASON: Final = "signature_scheme_unverified"


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _first_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def parse_transcript(raw: Any, call_id: str) -> tuple[list[TranscriptTurn], int]:
    """Their transcript → our turns, AND how many entries we could not place.

    Counted rather than kept: transcript TEXT is hard rule 6, and a count is not text. The
    count is the same instrument `ExecutionSnapshot.transcript_lines_unparsed` gives the
    Bolna adapter — a parser that silently drops what it does not recognise reports an
    empty transcript and a healthy call identically.

    UNVERIFIED shape. A list of `{role, content}` objects is assumed, with `assistant`/
    `agent`/`bot` mapping to our `agent` and everything else to `caller`. The SDK's own
    in-call vocabulary (`line/events.py`) is role-based, which is the basis for the guess,
    but the RETRIEVAL shape is a control-plane response nobody here has seen.
    """
    if not isinstance(raw, list):
        return [], 0
    turns: list[TranscriptTurn] = []
    lost = 0
    for entry in raw:
        if not isinstance(entry, dict):
            lost += 1
            continue
        role = str(entry.get("role") or entry.get("speaker") or "").lower()
        text = entry.get("content") or entry.get("text")
        if not isinstance(text, str) or not text.strip():
            lost += 1
            continue
        speaker = "agent" if role in ("assistant", "agent", "bot") else "caller"
        turns.append(
            TranscriptTurn(call_id=call_id, idx=len(turns), speaker=speaker, text=text.strip())
        )
    return turns, lost


class CartesiaEngine:
    """Implements `VoiceEngine` against Cartesia Line's control plane.

    Constructed per process; the httpx client is reused. Every method states its own
    evidence standing — read those before trusting a response shape.
    """

    name = "cartesia"
    capabilities = CARTESIA_CAPABILITIES
    #: `CARTESIA_API_KEY` only, matching `holds_credentials` exactly.
    #: `CARTESIA_FROM_NUMBER_ID` is deliberately NOT here: without it this adapter can
    #: still reach the vendor and serve every read, and only `start_outbound_call`
    #: refuses — with its own named reason. Listing it would make one missing dialling
    #: detail read as "this deployment cannot take traffic".
    credential_env_keys: tuple[str, ...] = ("CARTESIA_API_KEY",)

    def __init__(
        self,
        *,
        api_key: str | None,
        from_number_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
        api_version: str = API_VERSION,
    ) -> None:
        self._api_key = api_key
        #: The vendor's id for the number outbound calls originate from. Required by the
        #: outbound-dialing shape and NOT derivable from anything we hold: our
        #: `phone_numbers` rows carry E.164 and a DLT series, not a Cartesia number id.
        #: None is the honest default and makes `start_outbound_call` refuse rather than
        #: dial from whatever the account happens to have first.
        self._from_number_id = from_number_id
        self._base_url = base_url
        self._api_version = api_version
        self._client = client

    def holds_credentials(self) -> bool:
        """No `CARTESIA_API_KEY` ⇒ this deployment cannot reach Line at all.

        THE ANSWER TODAY IS FALSE ON EVERY DEPLOYMENT — there is no Cartesia account
        behind this repository. That is the point: the capability seam reports the engine
        unavailable with OUR reason code before any surface offers anything, instead of
        each request discovering it separately at the vendor boundary.
        """
        return bool(self._api_key) or self._client is not None

    # --- plumbing ------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._api_key:
                # The credential check is HERE as well as in readiness, because a
                # deployment can be misconfigured after readiness ran. Through the shared
                # builder for the reason `bolna._http` states (P2.6).
                raise engine_not_configured(f"{NO_CREDENTIALS_REASON}:{self.name}")
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                headers={
                    API_KEY_HEADER: self._api_key,
                    # Pinned on EVERY request, not just the one the docs showed it on:
                    # a date-versioned API that defaults when the header is absent is
                    # exactly how a response shape changes without anybody deploying.
                    VERSION_HEADER: self._api_version,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _request(
        self, method: str, path: str, *, absent_is_success: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        """One round trip. `absent_is_success` is `delete_agent`'s and nothing else's —
        see `BolnaEngine._request`, which carries the argument for why it is opt-in per
        call site rather than a blanket 404 policy."""
        try:
            response = await self._http().request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProblemError(
                kind="dependency",
                code="engine_unreachable",
                title="Voice platform is unreachable",
                detail="The voice platform did not respond.",
            ) from exc
        if absent_is_success and response.status_code == 404:
            # The declared postcondition, already satisfied. See `delete_agent`.
            log.info("cartesia_delete_already_absent", extra={"method": method})
            return {}
        if response.status_code >= 400:
            # The vendor's message is NOT forwarded (hard rule 2 upward, and a client
            # cannot act on it). The status is logged; the code carries the meaning.
            log.warning(
                "cartesia_request_failed",
                extra={"status": response.status_code, "method": method},
            )
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform refused the request.",
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return payload if isinstance(payload, dict) else {"data": payload}

    # --- agent lifecycle -----------------------------------------------------

    def _agent_body(self, cfg: AgentConfig) -> dict[str, Any]:
        """Our `AgentConfig` → their agent object.

        READ AT SOURCE for the two fields that matter most: `line/voice_agent_app.py:88`
        defines the agent payload their harness delivers per call as
        `AgentConfig(id, system_prompt, introduction)`, and their README documents
        `LlmConfig.from_call_request` reading exactly `call_request.agent.system_prompt`
        and `call_request.agent.introduction`. So the prompt and the greeting really are
        the agent's data, under those names.

        UNVERIFIED: that the CREATE endpoint accepts the same names, and `name`/`language`
        at all. The wrapper is flat on the same reasoning — their in-call object is flat.

        HARD RULE 5. The opening line is PREPENDED to the prompt AND is the
        `introduction`, so it is spoken first on every call whichever way the agent opens.
        Sending it only as the introduction would be a compliance control resting on an
        engine field we have never observed; sending it only in the prompt would let a
        model paraphrase it. Both, deliberately. Since D-163 that line is composed from
        the agent's two notice toggles and may be EMPTY — sent as "" rather than omitted,
        because an omitted key leaves the vendor holding the greeting it already has, and
        a withdrawn notice that keeps being spoken is a screen that lies about a phone
        line. `TRUTHFUL_ANSWER_DIRECTIVE` rides at the END of the prompt through
        `compose_engine_prompt` and is not toggleable by anything.

        NO SPEECH CONFIG IS SENT. `TTSConfig`/`STTConfig` take no provider and Sonic/Ink
        are the product, so there is nothing of ours to put there — and `require_speech_leg`
        refuses a caller that tries, rather than dropping it silently.
        """
        require_speech_leg("stt", engine=self, value=cfg.models.stt_model)
        require_speech_leg("llm", engine=self, value=cfg.models.llm_model)
        require_speech_leg("tts", engine=self, value=cfg.models.tts_voice)
        body: dict[str, Any] = {
            "name": cfg.name,
            "system_prompt": compose_engine_prompt(cfg),
            "introduction": cfg.opening_line,
            "language": cfg.language_primary,
        }
        if cfg.models.llm_model:
            # The one BYOK leg. LiteLLM's provider-prefixed form (`sarvam/...`) is the
            # SDK's own `model=` argument, READ AT SOURCE in their README quick start.
            body["model"] = cfg.models.llm_model
        if cfg.webhook_url:
            body["webhook_url"] = cfg.webhook_url
        return body

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        """`POST /agents`.

        **INFERRED**, and this is the weakest claim in the module. Two agent-scoped paths
        ARE sourced — `/agents/{agent_id}/documents/query` (READ AT SOURCE) and
        `/agents/calls` (REPORTED) — so a collection at `/agents` is the RESTful sibling
        of both. Nobody here has read the page that would confirm it.

        If it is wrong, `_request` raises `engine_rejected` on the 404 and publishing an
        agent fails loudly. It never degrades to a fabricated id: an agent ref we invented
        would be stored in `agents.engine_agent_ref`, join no webhook to any tenant, and
        turn a broken integration into a silently broken one.
        """
        data = await self._request("POST", "/agents", json=self._agent_body(cfg))
        ref = _first_str(data, ("id", "agent_id"))
        if ref is None:
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return an agent id.",
            )
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        """`PATCH /agents/{id}`. INFERRED, as `create_agent`.

        PATCH rather than PUT: we send a partial agent (no speech config — it is not ours
        to set), and a PUT that the vendor treats as a replacement could clear fields we
        never named. If PATCH is not their verb this 404s/405s loudly.
        """
        await self._request("PATCH", f"/agents/{ref}", json=self._agent_body(cfg))

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        """`DELETE /agents/{id}`. INFERRED — the RESTful sibling of `create_agent`'s
        `POST /agents`, and it stands or falls with it.

        **MARKED ASSUMPTION, and it is weaker than Bolna's on both halves.** Bolna at
        least publishes the route; a search for a Cartesia Line agent-delete reference
        (2026-08-15) returned NO PUBLIC DOCUMENTATION for it — their published API surface
        covers datasets and voices, and the Line agent control plane is not documented
        outside the OSS SDK, which models the in-call agent rather than its CRUD. "No
        public documentation found" is the finding, recorded rather than papered over.
        ASSUMED: the path exists at `DELETE /agents/{id}` and answers 404 for an id the
        account does not hold, which `_absent_is_success` folds into the Protocol's
        idempotent success.
        FALSIFIED BY: any non-404 refusal on a repeat delete, and by a 404/405 on the
        FIRST delete — which is the same falsifier `create_agent` and `update_agent`
        already carry, and it fails loudly rather than degrading: an orphan we could not
        remove is reported by the compensator exactly as it was before this method
        existed, which is a log line naming the ref, not a claim that it is gone.
        MEASURED BY: OPERATIONS §2 gate 2's `delete_agent` sub-check, run against whichever
        vendor the deployment is configured for.
        """
        await self._request("DELETE", f"/agents/{ref}", absent_is_success=True)

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """`GET /agents/{id}` → our `AgentSnapshot`. INFERRED path, as above.

        ONLY THE LLM LEG IS REPORTED, because only the LLM leg is ours. STT and TTS are
        Cartesia's to dictate, so there is no selection of ours to read back for them, and
        reporting the engine's own `voice_id` would put a vendor string where every caller
        expects one of ours — reading, to everything above, exactly like an applied BYOK
        selection (`AgentSnapshot.models`).

        The LLM leg IS read back, and the conformance suite requires it: an adapter that
        claims a leg is ours and cannot show what the engine holds for it is asserting
        BYOK on faith. `model` is the field `_agent_body` sends (READ AT SOURCE as the
        SDK's own `LlmAgent(model=...)` argument); whether the agent object echoes it under
        that name on a GET is INFERRED, and if it does not, `models_readable` is False and
        the suite fails us — loudly, which is correct, rather than letting the claim stand
        unchecked.

        The prompt half IS attempted, because that is what pilot gate 2's
        ACCEPTED-versus-APPLIED question needs, and `system_prompt_readable` reports
        honestly when the field cannot be found.
        """
        payload = await self._request("GET", f"/agents/{ref}")
        # An `{"agent": {...}}` envelope is tolerated as well as a bare object: their
        # in-call start message wraps the agent (`StartInput.agent`), so a control-plane
        # response that does the same would otherwise read as an agent with no fields —
        # i.e. as "the prompt was never applied", on no evidence.
        inner = payload.get("agent")
        agent: dict[str, Any] = inner if isinstance(inner, dict) else payload
        prompt = agent.get("system_prompt")
        prompt_text = prompt if isinstance(prompt, str) and prompt else None
        # THE GREETING, on the `(value, readable)` pair `bolna._agent_greeting` argues
        # for: a key present and EMPTY is an agent that speaks nothing first — a real
        # compliance failure — while an ABSENT key is us looking in the wrong place, and
        # only the first may fail a publish (P3.3). `introduction` is the field
        # `_agent_body` sends and the SDK's own `AgentConfig(introduction=...)` argument;
        # that the GET echoes it is INFERRED, like the rest of this method.
        greeting_readable = "introduction" in agent
        raw_greeting = agent.get("introduction")
        greeting = None
        if greeting_readable:
            greeting = raw_greeting if isinstance(raw_greeting, str) else ""
        returned_id = _first_str(agent, ("id", "agent_id"))
        name = agent.get("name")
        # UNVERIFIED: that the agent object lists its documents, or under what key. An
        # absent key reads as "we could not tell" (`readable=False`), never as "it
        # references none" — the D-41 tri-state, for the same reason.
        raw_docs = agent.get("documents") or agent.get("document_ids")
        docs_readable = raw_docs is not None
        handles = [str(item) for item in raw_docs if item] if isinstance(raw_docs, list) else []
        held_model = agent.get("model")
        model_text = held_model if isinstance(held_model, str) and held_model else None
        return AgentSnapshot(
            engine_agent_ref=returned_id or ref,
            name=name if isinstance(name, str) and name else None,
            system_prompt=prompt_text,
            system_prompt_readable=prompt_text is not None,
            greeting=greeting,
            greeting_readable=greeting_readable,
            knowledge_base_refs=handles,
            knowledge_base_refs_readable=docs_readable,
            # The LLM leg only. STT/TTS stay None because they are not ours to set — a
            # dictated leg has no selection of ours to report (`AgentSnapshot.models`).
            models=ModelConfig(llm_model=model_text),
            models_readable=model_text is not None,
            engine=self.name,
        )

    # --- calls ---------------------------------------------------------------

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        """`POST /agents/calls`.

        **REPORTED, NOT READ** — a search summary of `docs.cartesia.ai/line/integrations/
        telephony/outbound-dialing`, which the egress proxy refuses. What that summary
        states, and what is implemented below: `from_number_id`, `agent_id`,
        `ringing_timeout_seconds`, and an `outbound_calls` array of `{to_number,
        metadata}`, returning an `agent_call_id` per number.

        `from_number_id` IS REQUIRED BY THAT SHAPE AND WE HAVE NO VALUE FOR IT. The port's
        `start_outbound_call(ref, to, ctx)` carries no caller-id argument — on Bolna the
        number is bound to the agent, so the signature never needed one. Rather than
        invent a field or dial from an arbitrary number, this refuses when no number is
        configured. Which number a tenant dials FROM is a DLT 140/160 decision in our
        schema (`phone_numbers.series`), not something to guess at the vendor boundary.

        `ctx` rides in `metadata`, which the summary names as a per-call object. Only
        non-PII context is sent: `lead_id` is an id, and the note is business text the
        operator wrote. The lead's NAME and NUMBER are not put in metadata (hard rule 6) —
        the number is already the dial target.
        """
        if self._from_number_id is None:
            # ITS OWN CODE, and it did not have one: this reused `engine_not_configured`,
            # which is the credential refusal (P2.6). One code for two causes means an
            # operator reading a problem+json `type` cannot tell "we hold no API key" from
            # "we hold an API key and no outbound number" — different fixes, different
            # people. The remediation was already saying so in prose while the machine
            # field said otherwise.
            raise ProblemError(
                kind="dependency",
                code="engine_caller_id_not_configured",
                title="No caller ID is configured",
                detail="No outbound number is configured for the voice platform.",
                remediation="Contact us to attach a verified outbound number to this account.",
            )
        metadata: dict[str, Any] = {}
        if ctx.lead_id:
            metadata["lead_id"] = ctx.lead_id
        if ctx.context_note:
            metadata["context_note"] = ctx.context_note
        data = await self._request(
            "POST",
            "/agents/calls",
            json={
                "agent_id": ref,
                "from_number_id": self._from_number_id,
                "ringing_timeout_seconds": 30,
                "outbound_calls": [{"to_number": to, "metadata": metadata}],
            },
        )
        rows = data.get("outbound_calls") or data.get("calls") or data.get("data")
        candidate = rows[0] if isinstance(rows, list) and rows else data
        handle = _first_str(candidate, _CALL_ID_KEYS) if isinstance(candidate, dict) else None
        if handle is None:
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a call id.",
            )
        return handle

    async def end_call(self, call_id: str) -> None:
        """`POST /agents/calls/{id}/end`. INFERRED sibling of `/agents/calls`."""
        await self._request("POST", f"/agents/calls/{call_id}/end")

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        """Refuses by name: Line's transfer is the AGENT's to perform, not ours to command.

        READ AT SOURCE: `transfer_call` is a shipped built-in tool and the agent yields
        `AgentTransferCall(target_phone_number, interruptible)` over the live websocket
        (`line/events.py:58`). The vendor feature exists. What does not exist — nothing
        sourced describes one — is a control-plane endpoint to transfer a call from
        OUTSIDE it, which is what this method is.

        So `CARTESIA_CAPABILITIES.transfer` is False and this refuses through the one
        capability refusal, rather than raising a private code that disagreed with the
        descriptor. The whole point is that a caller can ask BEFORE calling and get the
        same answer; a console that offered the control and a method that refused it is
        the divergence D-93 exists to remove.

        WARM transfer is not distinguished by `AgentTransferCall` at all, which is its own
        finding: `warm` has nowhere to go on this engine even from inside the call.
        """
        require_capability("transfer", engine=self)
        raise AssertionError(  # unreachable while `transfer` is False
            "transfer was declared available but no control-plane endpoint is implemented"
        )

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        """Refuses every series, by name.

        Not a gap to be filled later by reading a docs page: Line's number paths are
        Cartesia-provisioned, imported Twilio, or Voximplant, and none of those yields a
        DLT-registered 140/160-series Indian number. **Whether Line accepts BYOC SIP from
        an Indian DLT-registered carrier is the single question that decides whether this
        engine is usable for us at all, and it is UNVERIFIED** (TRD §10.5). Until it is
        answered in writing, an Indian number on this engine is not a feature that is
        missing — it is a premise that has never been established.
        """
        require_capability("numbers", engine=self)
        raise ProblemError(  # unreachable while `number_series` is empty
            kind="dependency",
            code="engine_capability_unverified",
            title="Number provisioning is not available",
            detail="Numbers are provisioned with the telephony provider directly.",
        )

    # --- knowledge base ------------------------------------------------------
    #
    # Agent-scoped documents. The QUERY path is READ AT SOURCE
    # (`line/knowledge_base.py:86`: `GET /agents/{agent_id}/documents/query`); the CRUD
    # siblings under `/agents/{id}/documents` are INFERRED from it. That inference is a
    # good deal stronger than `/agents` above, because the parent collection is the one
    # path in this module a human has actually read in Cartesia's own code.

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        require_capability("knowledge_base", engine=self)
        data = await self._request(
            "POST",
            f"/agents/{ref}/documents",
            json={"title": source.title, "content": source.text, "language": source.language},
        )
        handle = _first_str(data, ("id", "document_id"))
        if handle is None:
            # A document we cannot address is a document that can never be superseded —
            # the KB would only ever grow, and `detach_kb` would have nothing to name.
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a knowledge base id.",
            )
        return handle

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        """No swallowing of a 404: an id we cannot delete is an id we cannot prove is
        gone, and the caller's next act is to publish a replacement."""
        require_capability("knowledge_base", engine=self)
        await self._request("DELETE", f"/agents/{ref}/documents/{kb}")

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        require_capability("knowledge_base", engine=self)
        data = await self._request("GET", f"/agents/{ref}/documents")
        rows = data.get("documents") or data.get("data")
        if not isinstance(rows, list):
            return []
        handles: list[EngineKBRef] = []
        for row in rows:
            if isinstance(row, dict):
                handle = _first_str(row, ("id", "document_id"))
                if handle:
                    handles.append(handle)
        return handles

    # --- reading the truth ---------------------------------------------------

    def _cost(self, payload: dict[str, Any]) -> CostBreakdown | None:
        """Their cost → INR.

        **NOT IMPLEMENTED, DELIBERATELY, AND THIS IS THE HONEST ANSWER.** Nothing sourced
        says what currency Line reports, at what granularity, or under which key. Hard
        rule 7 and `CostBreakdown`'s contract require the adapter to convert at capture
        and STAMP the rate used so a ledger row can be re-derived — and a stamp over a
        guessed currency is worse than no cost at all, because it is a number that looks
        auditable and is not. `CostBreakdown.currency_stated` exists precisely because a
        house assumption once became indistinguishable from a vendor fact.

        Returning None means `charge_for_call` records no cost rows for this engine, which
        is a visible hole rather than a plausible wrong invoice. Pilot gate: capture one
        real completed call and read the cost object off it.
        """
        return None

    def _snapshot(self, payload: dict[str, Any]) -> ExecutionSnapshot:
        raw_status = str(payload.get("status") or "").lower()
        call_id = _first_str(payload, _CALL_ID_KEYS) or ""
        turns, unparsed = parse_transcript(payload.get("transcript"), call_id)
        started = _parse_dt(payload.get("started_at") or payload.get("created_at"))
        ended = _parse_dt(payload.get("ended_at"))
        duration = payload.get("duration_seconds") or payload.get("duration")
        recording = payload.get("recording_url")
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=_first_str(payload, ("agent_id",)),
            direction="outbound" if payload.get("direction") == "outbound" else "inbound",
            status=_STATUS_MAP.get(raw_status, "failed"),
            raw_status=raw_status or "unknown",
            terminal=raw_status in _TERMINAL_RAW,
            # Same as `terminal` for now, and that is a CLAIM about this vendor we cannot
            # yet make well. Bolna's cost/recording/transcript arrive ~2-3 min AFTER the
            # call ends, which is why `billable_ready` exists as a separate flag. Whether
            # Line populates at disconnect or later is unsourced; equating them is the
            # optimistic answer and it is marked so rather than hidden. Since `_cost`
            # returns None regardless, nothing bills on it today.
            billable_ready=raw_status in _TERMINAL_RAW,
            started_at=started,
            ended_at=ended,
            duration_s=int(duration) if isinstance(duration, int | float) else None,
            from_e164=_first_str(payload, ("from_number", "from")),
            to_e164=_first_str(payload, ("to_number", "to")),
            recording_url=recording if isinstance(recording, str) and recording else None,
            transcript=turns,
            transcript_lines_unparsed=unparsed,
            cost=self._cost(payload),
            engine_extracted={},
            engine=self.name,
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        """`GET /agents/calls/{id}`. INFERRED sibling of `/agents/calls`.

        Carries the vendor's own document out as bytes for D-126's archive, on this path
        only — `list_executions` builds no document per row, for `BolnaEngine`'s reason.
        The archive matters MORE for this adapter than for the sourced one: almost every
        field name below is inferred, so the vendor's own answer is the only evidence that
        will settle a mapping we got wrong.
        """
        payload = await self._request("GET", f"/agents/calls/{call_id}")
        return self._snapshot(payload).model_copy(
            update={"raw_document": engine_document(payload, engine=self.name)}
        )

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """`GET /agents/calls`. INFERRED, and the completeness verdict is the point.

        `complete=True` is a POSITIVE claim (`ExecutionListing`), and this adapter is in no
        position to make it: nothing sourced describes Line's pagination — not the cursor,
        not the page size, not whether there is one. So a listing that comes back
        page-shaped is reported as possibly truncated with a reason the poller alerts on,
        and a short one is reported complete. Claiming completeness because nothing was
        checked is the defect `ExecutionListing` was introduced to make impossible.
        """
        data = await self._request(
            "GET", "/agents/calls", params={"start_time": since.astimezone(UTC).isoformat()}
        )
        rows = data.get("calls") or data.get("data")
        snapshots = (
            [self._snapshot(row) for row in rows if isinstance(row, dict)]
            if (isinstance(rows, list))
            else []
        )
        # An explicit "there is more" is honoured wherever the vendor happens to say it;
        # otherwise a page-shaped result is treated as suspect. Both answers are
        # `complete=False` with a reason, because both mean the same thing to the poller.
        if data.get("has_more") is True or data.get("next_page") or data.get("next"):
            return ExecutionListing(
                snapshots=snapshots, complete=False, incomplete_reason="explicit_more"
            )
        if len(snapshots) >= _LISTING_PAGE_SUSPECT:
            return ExecutionListing(
                snapshots=snapshots, complete=False, incomplete_reason="full_page_suspected"
            )
        return ExecutionListing(snapshots=snapshots, complete=True)

    # --- webhooks ------------------------------------------------------------

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """FAILS CLOSED. Their webhooks are signed; the scheme is not sourced.

        This is the one place in this module where guessing would be actively dangerous
        rather than merely wrong. A signature check is three independent guesses — the
        header name, the canonical string, the digest — and getting any of them wrong in
        the OTHER direction produces an endpoint that accepts anything while reporting
        `method="hmac"`, i.e. a public unauthenticated write endpoint wearing the word
        "verified". `test_a_claimed_verification_method_actually_rejects_somebody` exists
        for exactly that failure.

        So: `ok=False`, always, with an authored reason. Every delivery is refused until
        somebody reads their webhook documentation and implements the real scheme. That is
        a visibly unfinished integration — the reconciliation poller remains the guarantee
        of record — rather than a plausible-looking wrong one.

        THE OTHER HALF OF THE REFUSAL IS NOT IN THIS FILE (D-103). This method is what the
        WORKER acts on; the receiver that actually answers the delivery is
        `apps/voice-runtime/engine_intake.verify_source`, which cannot import this module
        (hard rule 3 forbids the heavy import on the ack path) and instead reads
        `WEBHOOK_AUTH_BY_ENGINE["cartesia"] == "hmac"` and refuses on the same grounds. So
        both halves fail closed independently, and neither can be softened by a change to
        the other. `tests/engine_name_drift_test.py` asserts they still agree — including
        the case that matters most, a deployment actually running `ENGINE=cartesia`, where
        the temptation to let the delivery through is at its strongest.

        WHEN THE SCHEME IS SOURCED, both halves change together or the conformance clause
        `test_the_declared_webhook_method_is_the_one_actually_reported` fails: the verifier
        lands here, the receiver grows the matching check, and only then does either stop
        returning `ok=False`.
        """
        return WebhookVerdict(ok=False, method="hmac", reason=SIGNATURE_UNIMPLEMENTED_REASON)

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        """Their event → OUR normalized event. UNVERIFIED field names.

        No tenant_id/agent_id is invented (hard rule 1): a vendor cannot know ours, and a
        guessed tenant is a cross-tenant write. An unknown status degrades to `failed`,
        never to a success.
        """
        raw_status = str(payload.get("status") or payload.get("event") or "").lower()
        return CallEvent(
            call_id=_first_str(payload, _CALL_ID_KEYS) or "",
            engine_agent_ref=_first_str(payload, ("agent_id",)),
            direction="inbound" if payload.get("direction") == "inbound" else "outbound",
            status=_STATUS_MAP.get(raw_status, "failed"),
            raw_status=raw_status or "unknown",
            from_e164=_first_str(payload, ("from_number", "from")),
            to_e164=_first_str(payload, ("to_number", "to")),
            recording_url=_first_str(payload, ("recording_url",)),
            engine=self.name,
        )


__all__ = [
    "API_VERSION",
    "BASE_URL",
    "CARTESIA_CAPABILITIES",
    "SIGNATURE_UNIMPLEMENTED_REASON",
    "CartesiaEngine",
    "parse_transcript",
]
