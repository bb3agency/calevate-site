# One inbound call, traced end to end — what breaks (21 Sep 2026)

**Method.** The code was read in call order, not recalled: Plivo's answer request
(`apps/voice-runtime/carrier_routes.py`) → the WebSocket entrypoint
(`apps/voice-worker/bot.py`) → the ringing-time session read (`apps/api/worker/routes.py`,
`service.py`) → pipeline assembly (`voice_worker/pipeline.py`) → the in-call tools
(`voice_worker/call_tools.py`) → settlement and the post-call pipeline
(`voice_worker/sink.py`, `apps/workers/pipeline.py`). Every claim below cites file:line and
was opened, not grepped. Vendor facts are read from the pinned wheel at
`.venv/lib/python3.12/site-packages/pipecat/` (`pipecat-ai==1.10.0`, hash-pinned by
`uv.lock`) — VERIFIED-VENDOR-DOCS. `docs.pipecat.ai`, `www.plivo.com`, `api.plivo.com` and
`platform.bolna.ai` are egress-blocked from this container; nothing was invented to fill a
gap.

**Scope note.** `apps/voice-worker/voice_worker/carrier.py`, `meter.py`,
`apps/api/worker/{routes,service}.py`, `apps/api/engine/pipecat.py`,
`packages/shared/.../worker_api.py` and `apps/workers/settings.py` were being EDITED by
other sessions while this was written. Anything read from them is marked MID-EDIT and is
not reported as final. The three defects already being fixed elsewhere (write-only config
attestation, carrier CDR ingestion, stale runbook/docs claims) are deliberately absent.

---

## 1. The four in-call tools are absent on every real call — PROVEN, not inferred

`apps/voice-worker/voice_worker/runtime.py:309`

```python
tool_api=self._api if isinstance(self._api, CallToolApiClient) else None,
```

The only constructor that builds a `CallToolApiClient` is `WorkerRuntime.from_env`
(`runtime.py:205`). **Nothing in production calls `from_env`.** `bot.py:249` calls
`container()` → `boot.open_runtime` (`boot.py:563`), which builds the client at
`boot.py:598` as a plain `WorkerApiClient.from_config(...)` and hands it to the call runner
at `boot.py:619-620`. So `isinstance(...)` is False and `tool_api` is `None` on every call
this container can ever serve.

Proven by execution, not by reading:

```
$ uv run python -c "... boot.open_runtime(load_worker_config(env), verify=False) ..."
type: WorkerApiClient  is CallToolApiClient: False
```

`pipeline.assemble_call:1404-1419` then advertises `build_knowledge_tool(...)` plus
`build_call_tools(None, ...)`, which contributes nothing. The model is handed ONE tool.

**What breaks.** A caller who says "stop calling me" reaches no `record_do_not_call` — the
comment at `pipeline.py:1401-1403` states the consequence exactly ("a caller saying 'stop
calling me' reaches nothing at all on this leg"). No call-back can be booked or cancelled;
no human handoff can be requested. The model, given no tool, improvises a reassurance.

**Who notices.** Nobody, ever. The caller is told something soothing; no suppression row is
written; the client sees no DNC entry. This is hard rule 5 / SEC-COMP §2.3 territory, and
its failure mode is an agent that sounds compliant and is not.

**Why review missed it.** `tests/voice_worker_tool_wiring_test.py:121-126` asserts the
STRING `"CallToolApiClient.from_config("` appears in `runtime.py`'s source. It does — in
`from_env`, the door production does not use. A source-text assertion cannot see which
constructor runs. `apps/api/engine/pipecat.py:247-255` (MID-EDIT) independently describes
the live state as "the worker, whose only tool is `build_knowledge_tool`", which is exactly
what this path produces.

**Smallest correct fix.** Build the tool client in `boot.open_runtime` — change
`WorkerApiClient.from_config` at `boot.py:598` to `CallToolApiClient.from_config` (it is a
drop-in subclass: same pool, same header, same error type, `call_tools.py:123`). Then
replace the source-text test with one that opens a runtime through `boot.open_runtime` and
asserts the advertised tool NAMES are five, not one — the assertion at
`voice_worker_tool_wiring_test.py:90-93` already exists and needs only to be aimed at the
production constructor.

---

## 2. A call that fails before the pipeline leaves no record anywhere, and the caller hears dead air

`apps/voice-worker/bot.py:260-284`

`bot()` wraps `create_transport` and `run_call` in `try/finally` whose only body is
`registry.release(call_id)`. Nothing catches `UnroutableCallError` (`bot.py:189`, `:196`),
`AgentNotRunnableError` (`config.py:113`, `:118`, `:211`, `:216`),
`WorkerConfigError` from `credentials_for` (`boot.py:257`), the `ValueError`s in
`_build_tts` (`pipeline.py:683`, `:697`, `:714`, `:722`, `:727`) or `_build_llm`
(`pipeline.py:799`, `:836`), or `AtCapacityError` (`lifecycle.py:209`).

Each of these is reachable on a first real call and each produces the same two outcomes:

1. **The caller hears silence on a connected leg.** The Plivo serializer's auto hang-up
   fires only on `EndFrame`/`CancelFrame` (`pipecat/serializers/plivo.py:130-137`), and on
   these paths no pipeline exists to emit one. The answer document sets
   `keepCallAlive="true"` (`carrier_routes.py:474-475`, copied from
   `pipecat/runner/run.py:1435-1438`). **UNKNOWN — what Plivo does with a leg whose stream
   died while `keepCallAlive` is true; `www.plivo.com` is egress-blocked here.** The safe
   reading is that the caller is left on a live, silent, billed call.
2. **No `calls` row is ever written.** The sink is constructed at `runtime.py:270` but
   emits nothing until the pipeline starts; every failure above happens before
   `runner.run()`. So the client's dashboard shows no call at all — not a failed call, no
   call — and nobody can tell a quiet day from a broken agent. The only trace is a loguru
   line inside a container Pipecat Cloud operates.

**Smallest correct fix.** Wrap the body of `bot()` in one `except Exception` that (a) logs
with the ids it has, (b) posts a terminal `CallEvent` with a failure status through a sink
built from the ids it already holds — `HttpEventSink` needs only the four ids
(`boot.py:456-481`), all known before any IO — and (c) closes the transport so the
serializer emits its hang-up. The caller then gets a disconnect instead of silence and the
client gets a row saying the call failed.

---

## 3. The `developer`-role greeting is sent to Google's OpenAI-compat endpoint, which the vendor's own code assumes does not accept it

`voice_worker/pipeline.py:1276-1279` opens every call by adding
`{"role": "developer", "content": "Greet the caller as your instructions direct."}` and
queueing an `LLMRunFrame`. That is the first request of the call, and it is what makes the
agent speak.

In the pinned wheel, `OpenAILLMService.supports_developer_role` defaults to **True**
(`pipecat/services/openai/base_llm.py:87`) and drives
`convert_developer_to_user=not self.supports_developer_role` on every invocation
(`base_llm.py:331`, `:412`). **Every OpenAI-compatible service the vendor ships for a
non-OpenAI provider overrides it to False**: `services/sarvam/llm.py:48`,
`qwen/llm.py:33`, `together/llm.py:34`, `mistral/llm.py:37`, `nebius/llm.py:33`,
`perplexity/llm.py:38`, `ollama/llm.py:34`, `baseten/llm.py:40`, `inception/llm.py:47`.

Our Google leg is exactly that shape and inherits the True:
`pipeline.py:830-835` constructs a bare `OpenAILLMService` against
`google_openai_compat_base_url()`. So the role travels verbatim to
`generativelanguage.googleapis.com/v1beta/openai/chat/completions`.

**UNKNOWN — whether that endpoint accepts `role: "developer"`.** The probe recorded at
`pipeline.py:778-794` tested BODY PARAMETERS (`stream`, `tools`, `tool_choice`,
`zzz_not_a_param`) and says nothing about message roles; the host is not reachable from
here to re-probe. What is not unknown is that the vendor treats this as a
per-provider capability and that we are the only construction of that class in this tree
that leaves it at the OpenAI default.

**Blast radius if it is rejected.** `gemini-2.5-flash-lite` is the platform default model
(CLAUDE.md, `PLATFORM_DEFAULT_LLM_MODEL`), so this is the default leg. A 400 on the first
completion means the greeting never happens: the caller hears a click and then nothing,
on every call, with `ProcessorUnusablePolicy.END` (`pipeline.py:1467`) eventually ending
the call. Nothing distinguishes it from a dead agent.

**Smallest correct fix.** Follow the vendor's own pattern: a two-line subclass setting
`supports_developer_role = False` for the Google leg (and for any future compat leg), so
the adapter converts the message to `user` (`adapters/services/open_ai_adapter.py:255-261`)
— behaviour-identical on the leg that does support it, safe on the one that may not. A
scripted scenario that asserts the agent speaks first would also have caught it.

---

## 4. Hard rule 6: the LLM leg logs tool-call arguments at WARNING, and that module is not on the denylist

`voice_worker/vendor_logging.py` is a careful, measured control — a level floor plus a
pinned `(module, line)` denylist. Its own docstring says the list "is only as complete as
the last sweep of the worker's import graph" (`:31-36`), and the sweeps covered the SERVICE
modules and, on 19 Sep, `carrier.py`'s new imports. **The LLM service module was not among
them.**

`pipecat/services/openai/base_llm.py:586`

```python
logger.warning(f"{self}: Failed to parse function call arguments: {arguments}")
```

`arguments` is the raw JSON fragment the model emitted for a tool call. On this product
that fragment carries the caller's own words: the knowledge tool's `question` parameter is
literally what the caller asked, and the opt-out and call-back tools carry a reason and a
requested time. It fires whenever the fragment does not parse — the ordinary cause being a
stream cut off mid-tool-call, which on a phone call is barge-in. It is a WARNING, so the
`VENDOR_LOG_LEVEL = "INFO"` floor (`vendor_logging.py:92`) does not remove it, and
`(pipecat.services.openai.base_llm, 586)` is not in `CONTENT_BEARING_RECORDS`
(`:98-104`). Both `AzureLLMService` (`pipecat/services/azure/llm.py:44`, a subclass) and
the direct/Google legs reach it.

Two nearby lines in the same class are safe and were checked:
`base_llm.py:324-326` (`get_messages_for_logging`) is DEBUG and the floor removes it.

**Who notices.** Nobody — it is one line of stdout inside a vendor-operated container,
which is precisely what hard rule 6 is about.

**Smallest correct fix.** Add `("pipecat.services.openai.base_llm", 586)` to
`CONTENT_BEARING_RECORDS` with its source line in `CONTENT_BEARING_SOURCE`, exactly as the
three existing entries are pinned, and extend the sweep to the LLM service modules the
worker imports. (`pipecat/services/cartesia/stt.py:463` and
`pipecat/services/sarvam/stt.py:1228` are the same shape but unreachable: we build
`SarvamSTTService`, not `SarvamRealtimeSTTService` (`pipeline.py:654`), and no Cartesia STT
at all.)

---

## 5. Caller memory is half-wired on the live path: the agent promised notes it can never recall

`voice_worker/runtime.py:291-311` calls `open_session(...)` and passes neither
`memory_reader` nor `caller_e164`. Both are parameters with `None` defaults
(`session.py:209-210`), so `load_caller_memory` returns `()` at `session.py:195-196` on
every production call. `ApiCallerMemoryReader` (`memory.py:137`) is constructed **nowhere
outside tests** — grep across `apps/` returns no production call site.

This matters because of the gate design recorded at `memory.py:43-52`: the prompt slot's
presence is a PROOF that `compose_opening_line` already appended
`agents.caller_memory_notice_line` — the agent has told the caller, out loud, that it keeps
notes. So a memory-enabled agent on this engine says the sentence and then recalls nothing,
for every caller, for ever. `fill_caller_memory_slot` (`pipeline.py:1378`) renders the
empty block correctly, so there is no error anywhere; it simply never remembers.

The number is available now — `bot.py:280` reads the caller off the stream URL and passes
it to `run_call`.

**Smallest correct fix.** In `run_call`, pass `memory_reader=` (an
`ApiCallerMemoryReader` over the runtime's existing client) and
`caller_e164=caller.e164 if caller is not None else None` into `open_session`. The read is
already concurrent with the pack fetch on the ring (`session.py:258-261`), so it costs no
added latency.

---

## 6. Nothing composes or displays the answer URL an operator must give the carrier

`carrier_routes.py:564` mounts `/carrier/v1/plivo/answer/{ref}`, and nginx proxies it to
voice-runtime through the `hooks.` vhost's catch-all
(`infra/nginx/calevate.conf.template:706-720`), so the route is reachable. But a repo-wide
search for `carrier/v1` or `plivo/answer` outside that file and one comment in
`voice_worker/carrier.py:420` (MID-EDIT) returns **nothing** — no builder, no API field, no
console panel.

Meanwhile both refusals in that handler tell the operator to "Point the number at the
answer URL **the agent's screen shows**" (`carrier_routes.py:614`, `:631`). The agent's
screen shows the ref (`apps/web/src/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page.tsx:618`)
and not the URL. So the one instruction that stands between a published agent and a ringing
phone points at a surface that does not exist, and the operator must assemble
scheme + `hooks.` host + path + a correctly-encoded `pipecat:<uuid7>:<uuid7>` from memory.

**Smallest correct fix.** Compose the URL where the ref is already returned (the publish
response) and render it beside the ref on the same panel, with a copy control — one field,
one line of TSX — then point both remediations at it.

---

## 7. `ENGINE` is not `pipecat` by default, and the worker's boot probe is exempt from the check that would catch it

`calevate_shared/config.py:361` defaults `engine` to `"fake"`. It is absent from
`.env.example` entirely (searched case-insensitively) and is not in `BOOTSTRAP_REQUIRED`
(`apps/api/core/settings.py:69-75`), so it is console-managed and a deployment that never
sets it runs as `fake`.

`apps/api/worker/routes.py:132-134` (MID-EDIT) then refuses every WRITE with 409 —
observations, settlement, attestation and all four tool routes — while
`_admit(authorization, writes=False)` at `:152` deliberately exempts the session read, and
`api_client.probe()` only ever presents that read (`api_client.py:242`). The exemption is
argued at `routes.py:121-127` and is right on its own terms; the consequence is that the
misconfiguration is invisible at boot and surfaces only after a caller has had a full
conversation.

**What a first call looks like.** The answer document is served (no engine check), the
worker boots green, the session read succeeds, the agent talks — and then every
observation flush 409s (`sink.py:362-380` swallows it and retries on a timer), the
settlement 409s, and the call ends with no `calls` row, no transcript, no extraction, no
lead and no usage_event. The caller notices nothing. The client sees nothing. One
`log.warning("worker_api_engine_not_enabled")` per request is the whole signal.

**Smallest correct fix.** Have the boot probe assert the WRITE posture too — a
`GET /v1/worker/session/preflight` cannot, but adding the engine check to a dedicated
preflight route (or letting `probe()` distinguish 404-with-engine-header) turns this into a
container that refuses to start rather than a call that is lost after it happened. Cheaper
still and worth doing anyway: refuse `engine == "fake"` when `app_env != "local"`, which is
the rule `agents/transfer_providers/registry.py:111` already applies to the fake carrier.

---

## 8. Smaller, ranked below anything that costs a call

- **A second, partial assembly path still exists.** `voice_worker/carrier.py:765`
  `start_carrier_call` assembles a call and is referenced only by tests. It is the same
  shape as the duplicate that cost the settlement (`bot.py:233-241`): it builds no meter,
  calls no `settle`, calls no `aclose`. MID-EDIT — not reported as final, but the
  one-way-per-problem rule says it should be deleted or made the one path.
- **`boot.py:111-113`** still reads "today's TTS is Sarvam too, so this key is required on
  every call". D-629 withdrew the Sarvam TTS leg; `SARVAM_API_KEY` is still correctly
  required, but for STT only. Comment-level, no behaviour.
- **The answer route shares the `webhooks` rate zone** (`calevate.conf.template:711`) with
  post-call delivery, keyed on the source address. On a pipecat-only deployment that zone
  is near-empty (nothing external calls us), so the risk is small today; the in-call tools
  got their own zone for exactly this reason (`:682-696`) and the answer document — the one
  request between a ringing number and any audio — did not.
- **`caller_identity` is permanently `unparsed_by_client`.** `CARRIER_ANSWER_CONTRACT`'s
  `calling_party` is empty (`carrier_routes.py:236`) because nobody has read Plivo's page.
  This is a named UNKNOWN, correctly handled, and it is listed here only because it
  compounds finding 1: even with the opt-out tool restored, `apps/api/worker/tools.py:150`
  answers `caller_number_unknown` until one cell of that table is filled.

## Clean — nothing found

- **Tenancy (hard rule 1).** The worker presents a ref and never a tenant; the server
  parses the tenant out of `pipecat:<tenant>:<agent>` and reads under that tenant's RLS
  (`service.py:426-433`, `:375-388`), the session answer's ids are re-checked against the
  route (`config.py:117-122`), and the sink refuses a body that names another call
  (`sink.py:501-527`). A forged ref can only ever reach the tenant it names. The token
  comparison is `hmac.compare_digest` and an unconfigured deployment authenticates nobody
  (`service.py:298-304`).
- **Hard rule 5 on the prompt.** Refused on both sides of the wire, for two separate
  conditions, at the one door every call passes (`config.py:168-219`), and
  `records_audio=False` keeps the recording clause honest on this engine
  (`engine/pipecat.py:231-235`, MID-EDIT).
- **Hard rule 3 on the answer route.** No IO at all: a UUID parse, a dict lookup and an
  ElementTree render; the body is read only once a parameter name is declared, which is
  never today (`carrier_routes.py:554-561`).
- **The ringing-time budget.** `SESSION_FETCH_BUDGET_S = 3.0` under a real wall-clock
  `asyncio.timeout` as well as httpx's per-phase timeout (`api_client.py:254-272`), no
  retry, and the pack fetch and memory read are `gather`ed so their budgets do not add
  (`session.py:258-261`).
- **The buffered-turn sink.** Buffers cleared only after the request returns, failed
  flushes retried, terminal events flushed immediately, `aclose` in a `finally`
  (`sink.py:300-397`, `runtime.py:366-372`).

---

## What a Pipecat scenario suite should assert first

Pipecat ships a headless behavioural eval harness — SCRIPTED (exact turns, with
`text_contains`, `function_call` and `within_ms` assertions) and SIMULATED (an LLM caller
pursuing a goal, judged over the transcript). No real call has ever been placed on this
product, so these are the only instrument that can see a behaviour before a caller does.
**Four scenarios, in this order, would have caught three of the seven findings above.**

1. **"Take me off your list."** Scripted, one turn, asserting a **`function_call` to
   `record_do_not_call`** — not a sentence. This is the single highest-value scenario in the
   suite: it fails today, for finding 1, and a `text_contains` assertion would have passed
   while the tool was missing. Extend it with one turn each for `book_callback`,
   `cancel_callback` and `request_human_handoff` in the same file.
2. **The agent speaks first, and what it says.** Scripted: connect, assert an assistant
   utterance `within_ms` of the connect event, and assert the four D-163 toggle
   combinations — AI disclosure present/absent and recording notice present/absent —
   produce exactly the expected opening. Run it against each declared LLM leg; that is what
   exercises the `developer`-role message and would surface finding 3 as a failed greeting
   rather than as dead air on a live call.
3. **"Am I talking to a person?" and "Is this call being recorded?"** Scripted, asked
   mid-conversation (not at the start, where the opening line would answer by accident),
   asserting a truthful answer to each — and specifically that the recording answer is NO on
   this engine, since nothing in `apps/voice-worker` captures audio. Repeat both in Telugu.
4. **Grounding: one question the pack answers, one it does not.** Scripted, asserting a
   `function_call` to the knowledge tool on both (the agent must search, not recall), the
   honest `not_found` sentence on the second, and `within_ms` against the turn budget. Add
   one variant with the pack unavailable, asserting `temporarily_unavailable` rather than an
   invented answer.

A fifth, simulated, is worth having once those four are green: **a Telugu caller pursuing a
booking**, judged on (a) the reply language matching the caller's, (b) no markdown,
bullets, asterisks, headings or emoji reaching the TTS, and (c) phone numbers and OTPs read
digit by digit — the three properties
`.venv/.../pipecat/cli/agent_templates/AGENTS.md:180` names and
`calevate_shared/engine.py:2722,2748` already instructs.

---

## Every UNKNOWN in this document

1. **UNKNOWN — whether Google's OpenAI-compat endpoint accepts `role: "developer"`.**
   `generativelanguage.googleapis.com` is not reachable from this container and the
   recorded probe tested body parameters only (`pipeline.py:778-794`). Finding 3 is
   written as a capability mismatch against the vendor's own pattern, not as a claim about
   Google's behaviour.
2. **UNKNOWN — what Plivo does with a call leg whose media stream dies while
   `keepCallAlive="true"`.** `www.plivo.com` is egress-blocked (CONNECT tunnel failed, 403;
   re-measured in this tree 19 Sep 2026). Finding 2 states the two outcomes that do not
   depend on the answer.
3. **UNKNOWN — which parameter of Plivo's answer request carries the calling party.**
   Recorded already at `carrier_routes.py:236-242`; one founder reading fills it.
4. **UNKNOWN — whether Pipecat Cloud preserves the WebSocket URL's path and query.**
   Recorded at `bot.py:179-185`. If the path is rewritten, `_route_token` refuses loudly,
   which is the safe direction.
5. **UNKNOWN — the real SIGTERM-to-SIGKILL window on Pipecat Cloud.** `DEFAULT_DRAIN_GRACE_S
   = 20.0` is an assumption with a reasoned floor (`boot.py:169-179`), not a measurement.
6. **UNKNOWN — the round-trip latency from a Pipecat Cloud `ap-south` container to our
   API.** `TOOL_BUDGET_S = 1.5` and `SESSION_FETCH_BUDGET_S = 3.0` are chosen, not timed
   (`call_tools.py:85-89`). What does not depend on the number is that the inner bound is
   smaller than Pipecat's `FUNCTION_CALL_TIMEOUT_SECS`.
