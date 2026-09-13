# Voice-engine port: contract inventory (13 Sep 2026)

**Purpose.** A precise, citable inventory of the `VoiceEngine` port so a SECOND adapter can
be written against it without reading the first one. Everything here is cited `file:line`
against the working tree at the date in the title.

**Evidence class: REPO-INTERNAL (read this session).** Every claim below is a claim about
THIS repository's source, read at the cited line. Where a line quotes a VENDOR fact (a
Bolna endpoint shape, a Cartesia field list) that fact carries the evidence class its own
citation gives it — usually VERIFIED-VENDOR-DOCS via `bolna-findings/mirror/` — and is
reproduced here as "what our source says", not re-verified against the vendor.

**Scope note.** `apps/api/compliance/`, `apps/api/campaigns/`, `apps/api/agents/service.py`,
`apps/api/db/registry.py` and `alembic/versions/` were being edited by another agent while
this was written. They are READ here, never written, and line numbers in those files may
have moved.

---

## 1. THE PROTOCOL

`packages/shared/src/calevate_shared/engine.py:4567-5197` — `@runtime_checkable class
VoiceEngine(Protocol)`.

The module docstring states the whole rule (`engine.py:1-11`): *"Nothing outside `engine/`
may import a vendor SDK or see a vendor payload shape… Everything an adapter ACCEPTS and
everything it RETURNS is defined here, in our vocabulary."*

`runtime_checkable` means `isinstance(x, VoiceEngine)` checks member PRESENCE only, never
signatures — the conformance suite is what actually checks behaviour (§4).

### 1.0 Attributes (not methods — read without `await`)

| Member | Type | Contract |
|---|---|---|
| `name` | `str` | `engine.py:4569`. The registry key (§6). |
| `capabilities` | `EngineCapabilities` | `engine.py:4571-4576`. Deliberately an ATTRIBUTE, not a method: *"a fact about the adapter, not a question it goes and asks: every caller — including a screen deciding whether to render a control — must be able to read it without an await and without a network round trip."* Business code reaches it through `apps.api.engine.engine_capabilities()`, never by touching an adapter. |
| `credential_env_keys` | `tuple[str, ...]` | `engine.py:4578-4593`. The env keys this adapter reads for credentials, *"in the order an operator should set them (D-104). Empty for an adapter that IS its own vendor."* It is the NAME half of `holds_credentials`. It must name what `holds_credentials` GATES ON and nothing more — a key the adapter merely PREFERS (Cartesia's `CARTESIA_FROM_NUMBER_ID`, needed to dial but not to reach the vendor) belongs to the refusal that needs it, not to readiness. Historical defect it closed: this lived in `core/settings.py` as `if cfg.engine == "bolna"`, so `/healthz/ready` was green on a credential-less Cartesia deployment. |

### 1.1 Methods, in declaration order

Twenty-five methods. Signature, return contract, raises, and the guarantees the docstring
states. `...` bodies throughout — this is a Protocol, no implementation.

#### `holds_credentials(self) -> bool` — `engine.py:4595-4611`
Synchronous. *"Can this adapter actually talk to its vendor?"*
- DERIVED FROM THE ADAPTER, never from a second read of settings: *"a credential is not a statement that a capability exists, and two independent reads of the same settings eventually disagree, at which point a screen offers what a route refuses."*
- Separate from `capabilities` because they answer different questions: `capabilities` is what this engine COULD do for anyone, this is whether THIS DEPLOYMENT can reach it. *"An engine with a built-in knowledge base and no API key still has a built-in knowledge base."*
- **MUST NEVER MAKE A NETWORK CALL** — it inspects what the adapter was constructed with; a screen deciding whether to render a control asks it.
- Raises: nothing.

#### `async create_agent(self, cfg: AgentConfig) -> EngineAgentRef` — `engine.py:4613-4634`
Put an agent of OURS on the engine and return its handle.
- **ONLY MEANINGFUL WHERE `capabilities.hosts_agents()` IS TRUE** (D-280). On an `external_deployment` engine it must REFUSE BY NAME through `engine_lacks("agent_hosting")` rather than POST to an endpoint the vendor does not serve.
- The docstring records the three rejected alternatives: deleting the method (breaks every `control_plane` adapter and the port), letting it 404 (*"turns a structural fact into an intermittent-looking vendor error, at the moment of the publish, on a path that has already committed our side of the transaction"*), and an "adopt the deployed agent by name" fallback (*"puts an agent live whose prompt we did not write and cannot read back, so hard rule 5 would rest on a repository nobody here can see"* — gated at OPERATIONS §2 gate 19(a)).
- Returns: the engine's opaque handle (`EngineAgentRef = str`, `engine.py:31`).

#### `async update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None` — `engine.py:4636`
No docstring. Full replacement of the agent's configuration. Its verification counterpart
is `get_agent` (*"the counterpart without which `update_agent` is a write into the dark"*,
`engine.py:4674`).

#### `async override_call_script(self, ref: EngineAgentRef, *, opening_line: str, system_prompt: str) -> None` — `engine.py:4638-4670`
Keyword-only after `ref`. *"Replace what a PUBLISHED agent SAYS, without rewriting what it IS (D-544)."*
- The narrow write planned maintenance needs: agent keeps its voice, number, KB, model and webhook and starts saying something else.
- `update_agent` is the wrong instrument *in both directions* — it is a full replacement (so it must first read the agent back to avoid wiping engine-side state it does not model), and it takes an `AgentConfig`, which is our RECORD of what the agent IS. *"A maintenance script is not that record and must never be written into it."*
- **THE RESTORE IS NOT THIS METHOD.** Coming out of a window, `agents.service.publish_agent` re-publishes from our own row through the verified path. The asymmetry is deliberate: *"the override is temporary and unverified-by-design, the restore is permanent and verified."*
- REFUSES BY NAME when `capabilities.script_override` is False — `engine_lacks("script_override")` — rather than silently doing nothing.
- Hard rule 5 still binds: both arguments are composed by `workers/maintenance.py`, the composed script carries the truthful-answer directive and the disclosure lines, and `check_compliance_invariants` reads the COMPOSER, not this signature.

#### `async get_agent(self, ref: EngineAgentRef) -> AgentSnapshot` — `engine.py:4672-4712`
Read ONE agent's current configuration back out of the engine.
- Two promises: **APPLIED, not merely ACCEPTED** (*"A 2xx on the update says the vendor took the bytes. Whether the agent is now RUNNING that prompt is a different claim, and it is the one a client's compliance disclosure depends on."*); and **D-41's dangling handle** (`detach_kb` deletes the KB, whether the AGENT stops referencing it is a fact about the agent object — `list_kb` reads the ACCOUNT's KB list, a different object — gate 8).
- **MUST ANSWER ABOUT THIS `ref` AND NO OTHER.** *"An adapter that echoes back the config it was last handed satisfies every naive test and measures nothing: it agrees with the caller by construction."* The conformance suite therefore reads TWO agents back and requires each to carry its own prompt.
- **An unknown ref MUST RAISE**, not return an empty snapshot.
- **REFUSES BY NAME on an `external_deployment` engine** — `engine_lacks("agent_hosting")`, NOT a snapshot with three `_readable` flags permanently False. The tri-state means "the adapter could not FIND the field", which is a reason to go and look at the adapter; on an engine whose agent record HAS no prompt there is nothing to find.

#### `async delete_agent(self, ref: EngineAgentRef) -> None` — `engine.py:4714-4752`
**IDEMPOTENT BY CONTRACT.**
- The hole it closes: `create_agent` is a side effect at a third party and the write of `engine_agent_ref` is a side effect in our database, with no transaction spanning the two. D-121 closed the create/create race with a row lock and could not clean up after the rest.
- **A ref the engine does not hold is this method's POST-CONDITION ALREADY SATISFIED, not an error.** Raising there would DLQ a compensation job whose work is done. Cites RFC 9110 §9.2.2 for HTTP DELETE; *"an adapter whose vendor disagrees is the adapter's problem to absorb, not the caller's."*
- Deliberately NOT symmetric with `detach_kb`, which RAISES on an absent handle. The test is what the caller does next.
- **IT MUST BE REAL** — the conformance suite observes the removal through `get_agent` rather than trusting the call.
- What it costs at the vendor is not this contract's to promise (Bolna documents that deleting an agent destroys all of its batches and executions). Nothing in the repo calls it on a human-soft-deleted agent; the only caller is the orphan compensator.

#### `async start_outbound_call(self, ref: EngineAgentRef, to: E164, ctx: CallContext) -> CallHandle` — `engine.py:4754-4795`
Dial `to` with agent `ref`, carrying `ctx` into the call.
- **WHERE HARD RULE 5 LIVES ON AN `external_deployment` ENGINE** (D-280). On `control_plane` the directive is agent-record state `publish_agent` wrote and `verification.judge` proved, and `ctx.system_prompt` is None. On external deployment the adapter MUST (a) SEND `ctx.system_prompt` on the dial and (b) REFUSE BY NAME a context whose prompt does not carry `TRUTHFUL_ANSWER_MARKER`, including a context carrying no prompt at all.
- **AN ADAPTER THAT CANNOT DO THE FIRST MUST REFUSE EVERY DIAL.** *"'Degrades honestly' never means a weaker floor for one vendor."*
- **`ctx.from_e164` MAY NOT BE DROPPED** (D-420). Where `capabilities.caller_id` is True the adapter SENDS it as outbound caller ID; where False it REFUSES a context carrying one via `engine_lacks("caller_id")`. The defect: *"the campaign gate certifies a DLT-registered 140/160-series header, the vendor dials from its own pool, and the callee's handset shows a number nobody gated."*
- **THE CHECK IS THE ADAPTER'S, NOT THE CALLER'S** — *"a guard in the caller is a guard one future caller can route around — and this method has three callers already."* Conformance probes both sides.
- Returns `CallHandle = str` (`engine.py:32`). Not a read-back, which is why the checks are here: *"'it sent our prompt' and 'it dropped our prompt' are otherwise the same observation."*

#### `async end_call(self, call_id: str) -> RecallOutcome` — `engine.py:4797-4835`
Stop a dial the engine is holding, from OUTSIDE it — **and say what that achieved.**
- **IT RETURNS A VERDICT, AND IT USED TO RETURN `None`.** Bolna's route stops a call that has NOT started (*"cannot stop a call already in progress"*) — the queued case the campaign path needs, not a hang-up on a live caller. After the fact nothing can distinguish them, because `_STATUS_MAP` folds their `stopped` into our `failed` beside `canceled`, `error` and a real post-ring failure. The verdict is decided IN THE ADAPTER because the evidence for it is a vendor payload shape (hard rule 2).
- A caller may ignore it: the outbound halt does, best-effort by decision (D-428). The DNC path does not, *"because a suppression is the one place somebody may later have to prove a number was not called."*
- **A CALL THE ENGINE DOES NOT HOLD RAISES** (D-187) — stated here because the two shipped adapters had drifted: both real adapters surface the vendor 404 as `engine_rejected`, `FakeEngine` shrugged and returned None, so the whole offline pipeline reported a hang-up that never happened.
- SYMMETRIC WITH `transfer`, deliberately NOT with `delete_agent`: this caller is a control plane and its one observable failure is reporting success for a call it did not stop.
- **AN ADAPTER THAT CANNOT TELL RETURNS `UNKNOWN`.** Returning `PREVENTED` from a bare 200 is an unearned claim.

#### `async transfer(self, call_id: str, to: E164, warm: bool) -> None` — `engine.py:4837`
No docstring at the Protocol. Its negative-probe shape is referenced from
`start_outbound_call` (`engine.py:4791`) as the model for probing a method that returns no
read-back. Gated by `capabilities.transfer` / `in_call_handoff`.

#### `async search_numbers(self, query: NumberSearch) -> Sequence[AvailableNumber]` — `engine.py:4839-4859`
*"What could this engine sell us right now (D-537)?"*
- **THE METHOD THE PORT WAS MISSING**: Bolna's buy endpoint requires the exact E.164 (`buy.md:74-77`), which only their search can tell us. *"A port with a buy and no search is a port that can only be used by somebody who already has a number, i.e. by nobody."*
- **READ-ONLY AND SPENDS NOTHING.** An adapter must never buy from here.
- REFUSES BY NAME where `capabilities.number_series` is empty, through `require_capability("numbers")` — the same refusal `provision_number` gives, from the same descriptor.
- **An empty sequence is a legitimate answer and is NOT an error** — the vendor has no matching inventory today; the caller must say that to a person rather than retrying.

#### `async provision_number(self, spec: NumberSpec) -> ProvisionedNumber` — `engine.py:4861-4876`
- **SPENDS REAL MONEY AND IS NOT IDEMPOTENT** — no client-supplied key on Bolna's buy endpoint, so a retry buys a SECOND number and a second rental. `campaigns/number_supply.py` is the only caller and takes an advisory lock plus a pre-check for exactly that reason.
- **RETURNS WHAT THE VENDOR SAID, NOT WHAT WAS ASKED FOR.** The returned `e164` is the authority. `engine_number_ref` is the handle `bind_inbound_number` needs — *"an adapter that cannot produce one has not finished the purchase."*

#### `async release_number(self, number: ProvisionedNumber) -> None` — `engine.py:4878-4900`
- **THE OTHER END OF A RECURRING COST** — *"A number bought and never released renews every month for ever… the margin leak that has no incident, no alarm and no bound."*
- **UNBIND FIRST IS THE CALLER'S JOB.** `numbers.release_number` unbinds, then releases, and records the release even if the unbind was a no-op.
- **ABSENT IS SUCCESS** (postcondition is "we are not being billed for this number").
- **REFUSES a number we did not buy** (`engine_owned` false) — releasing a client's own carrier number at the engine would do nothing there and delete our only record of it here.

#### `async list_engine_numbers(self) -> Sequence[ProvisionedNumber]` — `engine.py:4902-4912`
Every number the engine currently holds for this account (D-537). Answers the one question
no other method can: *"is there a number we are paying for that our database has forgotten?"*
`workers/number_rental.py::reconcile_engine_numbers` walks this against `phone_numbers` and
alarms on either direction.

#### `async bind_inbound_number(self, ref: EngineAgentRef, number: ProvisionedNumber) -> None` — `engine.py:4914-4952`
Make agent `ref` the one that ANSWERS `number` — at the engine (D-420).
- The half of the product that *"reached our database and stopped"*: the console wrote `phone_numbers.agent_id` and ended, so the number went on answering with whatever was last set in the vendor's dashboard. `engine_agent_routes` is the OPPOSITE direction (`engine_agent_ref → (tenant, agent)` for attributing an INCOMING webhook) and *"cannot make a phone ring"*.
- **IT TAKES A `ProvisionedNumber`, NOT AN `E164`, AND THAT IS THE WHOLE INTERFACE DECISION.** An engine addresses a number by ITS OWN handle — Bolna's `POST /inbound/setup` takes `{agent_id, phone_number_id}`. The E.164 travels too because an engine may key on it instead, *"and because an adapter that has neither must say which one it wanted."*
- **A NUMBER THE ENGINE HAS NEVER HEARD OF IS A NAMED REFUSAL, NOT A BIND** — `engine_number_ref` None means the number was bought from the telephony vendor directly (D-05) and never introduced to the engine: an onboarding step a person has to do, not an error to retry.
- **IDEMPOTENT BY INTENT**: the vendor's "already linked" is success. Re-binding a number held by a DIFFERENT agent is a legitimate re-point, not a conflict — `phone_numbers.agent_id` is the authority and this method's job is to make the engine agree with it.
- REFUSES BY NAME where `capabilities.inbound_binding` is False.

#### `async unbind_inbound_number(self, number: ProvisionedNumber) -> None` — `engine.py:4954-4968`
- NOT optional symmetry: *"A number that keeps answering after the client is offboarded, the agent is deleted or the number is released is a stranger reaching an AI that will collect their details."* Bolna's is `POST /inbound/unlink {phone_number_id}`.
- **ABSENT IS SUCCESS**, unlike `end_call` and like `delete_agent`.

#### `async set_llm_credential(self, secret: str, *, provider: LlmProvider) -> LlmCredentialPlacement` — `engine.py:4970-5024`
Install the secret ONE declared LLM leg authenticates with, replacing whatever the engine held for that leg (D-404).
- **`provider` IS REQUIRED AND KEYWORD-ONLY, AND THE ABSENCE OF A DEFAULT IS THE POINT.** A default would mean "the incumbent leg", so a caller rotating the wrong key would *"overwrite the Azure one with an OpenAI secret — a leg taken down by a call that returned success."*
- The leg is named in OUR vocabulary (`LlmProvider`); the engine's own entry names are the adapter's business — *"Bolna alone wants four entries for Azure and one each for the other two."*
- **THE CREDENTIAL IS NOT AGENT CONFIG** — pushing it through the agent path would re-publish the whole fleet (a compliance-gated write) to rotate one string.
- **ONLY MEANINGFUL WHERE `capabilities.is_ours("llm")` IS TRUE**, and that is the same gate rather than a new flag on purpose. Where the leg is dictated this must REFUSE BY NAME, never no-op.
- WHAT `secret` IS is deliberately unstated (static key for one engine, short-lived bearer for another). How long it lives is the CALLER's problem.
- **NOT IDEMPOTENT IN THE `delete_agent` SENSE**: twice with the same secret leaves the engine holding it once, but each call is a real write.
- **RAISES rather than returning a failure** — every caller's response to "the credential did not land" is the same (page, leave the old key in place) and *"a returned `False` is a thing a caller can forget to read."*

#### `async attach_kb(self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None) -> EngineKBRef` — `engine.py:5026-5051`
Push an approved source and return the engine's handle for it.
- Returning the handle is *"the whole reason a superseded version can ever be removed: the engine names its copy, we do not. An adapter that has nothing to return is an adapter whose KB can only ever grow."*
- **`agent` IS THE AGENT'S OWN CONFIGURATION AND IT IS NOT OPTIONAL EVERYWHERE (D-488).** Where the knowledge linkage is AGENT STATE and the only route that writes it is a FULL REPLACEMENT (Bolna `PUT /v2/agent/{id}`; `PATCH` updates a closed list that excludes `tasks` and *"Any other field in the body is ignored"* — `bolna-findings/mirror/pages/api-reference/agent/v2/patch_update.md:9,20`), the adapter cannot build the body from a read-back: the vendor's `AgentV2` response declares neither `agent_welcome_message` nor `webhook_url` (`.../agent/v2/get.md:54-97`), so a PUT assembled from a GET would silently drop the spoken notice and the event webhook.
- `None` is legal and means *"this engine does not need it"*. An adapter that DOES need it and is handed `None` must refuse by name — **never guess a body.**

#### `async detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef, *, agent: AgentConfig | None = None) -> None` — `engine.py:5053-5078`
- Without it, FLOWS §7's "supersede" only ever happened in OUR tables, so the agent kept answering from v1 — *"the published KB diverging from the approved one, which is the single thing the approval gate exists to prevent. (After a rollback it was worse: every version was live at once.)"*
- **IT MUST BE REAL** — conformance observes the removal through `list_kb`.
- **Detaching a handle the engine does not have MUST RAISE** — the publisher's next step is to attach the replacement and is entitled to know the old text is gone.
- `agent` has `attach_kb`'s meaning and the same standing.

#### `async list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]` — `engine.py:5080-5088`
The handles currently attached to this agent. *"The engine — not our table — is what the
caller actually hears."* Also the only adapter-independent way to prove a `detach_kb` did
anything.

#### `async list_account_kb(self) -> AccountKBListing` — `engine.py:5090-5113`
Every knowledge base on the ENGINE ACCOUNT, whoever it belongs to.
- **THE ONE QUESTION `list_kb` CANNOT ANSWER.** `list_kb` reads what an AGENT references, so an object no agent references is invisible — and that is the residue every failure leaves (lost create response, crash between upload and agent write, failed COMMIT after a successful attach, failed cleanup, agent deleted while still referencing knowledge). Such an object *"is billed for as long as the account exists and holds a client's document — plausibly with their customers' names and numbers in it — with nothing anywhere saying whose it is."*
- It is the only instrument that can ask *"what is here that nobody claims?"*, which a DPDP erasure must be able to answer. `kb/orphans.py` is the caller; it cross-checks our claim rows and REPORTS. **Nothing deletes on the strength of this listing.**
- An adapter with no KB REFUSES (`require_capability`): *"an empty listing is a positive claim about the account."*

#### `async list_voices(self) -> EngineVoiceListing` — `engine.py:5115-5139`
Every TTS voice THIS ENGINE ACCOUNT will accept, for the models we offer.
- **THE CATALOGUE IS THE ENGINE'S, NOT THE MODEL VENDOR'S, AND THAT DISTINCTION IS A LIVE 400.** `agents/voices.py` compiled its speaker list from Sarvam's own SDK enum; the engine's Sarvam provider offers a different subset and publishing a wider-list voice fails at agent CREATE — *"Provided voice: Anushka is not available for the provider: sarvam"* (live publish, 11 Sep 2026).
- The ONLY way a CLONED voice can be offered: it arrives with `is_custom=True` and reaches the picker through the cache (`agents/voice_sync.py`).
- An adapter whose TTS leg is not ours REFUSES (`require_capability("tts")`).
- `complete` is part of the answer, not a detail.

#### `async get_execution(self, call_id: str) -> ExecutionSnapshot` — `engine.py:5141-5157`
**The authenticated read. This — not the webhook — is what we persist.**
- **IT MUST CARRY `raw_document`.** An adapter returning `None` there makes `calls.engine_payload_ref` a column nothing writes and `retention._erase_engine_payloads` an erasure arm guarding nothing (D-126).
- The document is **the VENDOR'S**, not a re-rendering of the snapshot: *"an adapter that serialized its own `ExecutionSnapshot` would archive our normalization and lose the one thing the archive is for."*

#### `async list_executions(self, *, since: datetime) -> ExecutionListing` — `engine.py:5159-5187`
Keyword-only `since`. Backs the reconciliation poller (D-31: guarantee of record, not a safety net).
- **`since` IS ANCHORED ON WHEN THE EXECUTION STARTED, NOT ON WHEN IT FINISHED** (D-367). Bolna sends `created_after`, Cartesia sends `start_time`, the in-memory engine filters on `started_at`. Under the wrong reading a window of width W would cover everything that ENDED in the last W; under the real one it drops any call whose duration exceeds W (what D-242 cost). `pipeline.reconcile_outstanding_calls` exists because this anchor cannot be changed from our side.
- **An adapter whose vendor CAN filter on completion must still honour this reading — widen its request rather than narrow it.**
- **MUST REPORT COMPLETENESS, NOT JUST ROWS.** An adapter that read page one of a paginated listing was indistinguishable from one that read a quiet window — *"and the calls in the gap are exactly the ones whose webhook was lost, i.e. the ones this method exists to find."* An adapter that cannot rule out a further page returns `complete=False` with a reason; the poller alerts on it.

#### `def verify_webhook(self, headers: dict[str, str], body: bytes, source_ip: str) -> WebhookVerdict` — `engine.py:5189-5193`
Synchronous. *"HMAC where the engine signs; source-IP allowlist where it does not."*

#### `def parse_webhook(self, payload: dict[str, Any]) -> CallEvent` — `engine.py:5195-5197`
Synchronous. *"Vendor payload → OUR normalized event. The isolation boundary."*

### 1.2 Domain aliases (`engine.py:29-45`)

```python
E164            = str      # :30
EngineAgentRef  = str      # :31
CallHandle      = str      # :32
EngineKBRef     = str      # :37 — the engine's own handle for ONE attached source
                           #       (Bolna: `rag_id`). Our `kb_sources.id` cannot serve:
                           #       the engine has never seen it (:33-36).
NumberSeries       = Literal["140", "160", "standard"]   # :39
WebhookAuthMethod  = Literal["hmac", "source_ip", "none"] # :45
```

`WebhookAuthMethod` is shared with `WebhookVerdict.method` **on purpose** (`engine.py:40-44`):
what an adapter DECLARES and what it REPORTS are the same vocabulary, *"so the conformance
suite can compare them (an adapter that claims `hmac` and answers `none` is caught by a
`==`, not by a reviewer)."*

---

## 2. THE TYPES IN THOSE SIGNATURES

All in `packages/shared/src/calevate_shared/engine.py` unless noted. Pydantic v2
`BaseModel` unless marked. `model_config` shown where set — `frozen=True, extra="forbid"`
is the house pattern for value objects an adapter constructs.

### 2.1 `AgentConfig` — `engine.py:2814-2878`
What WE hand an engine to create or replace an agent. No `model_config`; mutable, extra allowed.

| Field | Type | Default |
|---|---|---|
| `tenant_id` | `str` | required (`:2818`) |
| `agent_id` | `str` | required (`:2819`) |
| `name` | `str` | required (`:2820`) |
| `direction` | `Literal["inbound","outbound","both"]` | required (`:2821`) |
| `language_primary` | `str` | `"te-IN"` (`:2822`) |
| `languages_extra` | `list[str]` | `Field(default_factory=list)` (`:2823`) |
| `system_prompt` | `str` | required (`:2824`) |
| `opening_line` | `str` | required (`:2840`) |
| `models` | `ModelConfig` | `Field(default_factory=ModelConfig)` (`:2841`) |
| `webhook_url` | `str \| None` | `None` (`:2842`) |
| `knowledge_base_ref` | `str \| None` | `None` (`:2843`) |
| `max_call_duration_s` | `int` | `600` (`:2844`) |
| `action_tools` | `tuple[ActionToolSpec, ...]` | `()` (`:2850`) |
| `caller_memory_enabled` | `bool` | `False` (`:2864`) |
| `handoff` | `HandoffSpec \| None` | `None` (`:2877`) |

The prompt an adapter sends is NOT `system_prompt` raw — it is
`compose_engine_prompt(cfg, caller_memory=...)` (`engine.py:2984`), which assembles
`PLATFORM_RULES_PREAMBLE` / `CLIENT_SCRIPT_OPEN`…`CLIENT_SCRIPT_CLOSE` / the truthful-answer
directive, and `carries_truthful_answer_floor(prompt)` (`engine.py:2448`) is the predicate
that scores it. `compose_opening_line(posture)` (`engine.py:2925`) builds the greeting from
a `DisclosurePosture`.

### 2.2 `ModelConfig` — `engine.py:2466-2679`
The three legs, in our vocabulary. All fields optional; `None` means "engine default".

| Field | Type | Default |
|---|---|---|
| `stt_provider` | `str \| None` | `None` (`:2485`) |
| `stt_model` | `str \| None` | `None` (`:2486`) |
| `stt_autodetect` | `bool` | `False` (`:2522`) |
| `llm_model` | `str \| None` | `None` (`:2532`) |
| `llm_provider` | `LlmProvider \| None` | `None` (`:2536`) |
| `llm_base_url` | `str \| None` | `None` (`:2542`) |
| `llm_traps` | `tuple[LlmModelTrapName, ...]` | `()` (`:2561`) |
| `tts_provider` | `str \| None` | `None` (`:2562`) |
| `tts_model` | `str \| None` | `None` (`:2577`) |
| `tts_voice` | `str \| None` | `None` (`:2587`) |
| `tts_voice_label` | `str \| None` | `None` (`:2604`) |

`@model_validator(mode="after") _llm_endpoint_is_coherent` (`:2606-2679`) enforces, and a
second adapter inherits these refusals for free:
- `llm_base_url` without `llm_provider` → ValueError (`:2643-2647`): *"the engine uses its own default client and our endpoint addresses nothing"*.
- A provider whose declared leg has `in_call_endpoint_is_ours == False` may carry NO base URL (`:2650-2661`).
- A provider whose leg IS ours REQUIRES one (`:2663-2664`).
- `azure_openai` → must parse as an Azure v1 endpoint from `azure_openai_base_url()` (`:2665-2671`).
- otherwise → must equal `openai_base_url()` exactly (`:2672-2678`).

`llm_traps` is read at the wire by `engine/bolna.py::_llm_trap_settings` — the mechanism
that stops the adapter sending `temperature: 0.1` to a GPT-5 model that rejects it.

### 2.3 `ActionToolParam` — `engine.py:2703-2726` (frozen, extra=forbid)
`name: str` · `fill: ActionParamFill = "ai"` (`Literal["ai","context"]`, `:2696`) ·
`type: ActionParamType = "string"` (`Literal["string","integer","number","boolean"]`, `:2700`) ·
`description: str = ""` · `required: bool = False` · `context_ref: str | None = None`.

### 2.4 `ActionToolSpec` — `engine.py:2729-2759` (frozen, extra=forbid)
`name: str` · `description: str` · `pre_call_message: str | None = None` ·
`method: Literal["POST"] = "POST"` · `url: str` · `params: tuple[ActionToolParam, ...] = ()`.

### 2.5 `HandoffSpec` — `engine.py:2762-2811` (frozen, extra=forbid)
`destination_e164: E164` · `trigger: str` · `spoken_line: str` · `brief_url: str | None = None`.

### 2.6 `DisclosurePosture` — `engine.py:2880-2922` (frozen)
`ai_disclosure_line: str` · `ai_disclosure_enabled: bool` · `recording_notice_line: str` ·
`recording_notice_enabled: bool` · `caller_memory_notice_line: str = ""` ·
`caller_memory_enabled: bool = False`. Input to `compose_opening_line`. Hard rule 5 / D-163:
the two disclosures are separate obligations under separate regimes, separately switchable.

### 2.7 `AgentSnapshot` — `engine.py:3057-3313`
The read-back. **Its defining feature is the `*_readable` TRI-STATE**: a field is
`None`/empty AND a boolean says whether the adapter could FIND it, so "the engine holds
nothing" never masquerades as "we could not look".

| Field | Type | Default |
|---|---|---|
| `engine_agent_ref` | `EngineAgentRef` | required (`:3087`) |
| `name` | `str \| None` | `None` (`:3088`) |
| `system_prompt` | `str \| None` | `None` (`:3094`) |
| `system_prompt_readable` | `bool` | `False` (`:3096`) |
| `alternate_prompts` | `tuple[str, ...]` | `()` (`:3125`) |
| `greeting` | `str \| None` | `None` (`:3145`) |
| `greeting_readable` | `bool` | `False` (`:3153`) |
| `knowledge_base_refs` | `list[EngineKBRef]` | `Field(default_factory=list)` (`:3157`) |
| `knowledge_base_refs_readable` | `bool` | `False` (`:3160`) |
| `models` | `ModelConfig \| None` | `None` (`:3170`) |
| `models_readable` | `bool` | `False` (`:3177`) |
| `handoff_destinations` | `tuple[E164, ...]` | `()` (`:3191`) |
| `handoff_destinations_readable` | `bool` | `False` (`:3198`) |
| `engine` | `str` | `"fake"` (`:3199`) |

Derived readers — each returns `None` for "could not look", which callers must NOT collapse
to False:
- `carries_prompt_marker(marker) -> bool | None` (`:3201`)
- `every_prompt_carries(marker) -> bool | None` (`:3215`) — base prompt AND every `alternate_prompts` entry
- `carries_greeting_marker(marker) -> bool | None` (`:3244`)
- `references_kb(kb) -> bool | None` (`:3257`)
- `holds_speech(leg)` — `@overload`ed (`:3268-3313`): `Literal["stt","llm"] -> str | None`, `Literal["tts"] -> HeldVoice | None`

### 2.8 `HeldVoice` — `engine.py:3025-3054` — `@dataclass(frozen=True, slots=True)`
`provider: str | None` · `model: str | None` · `voice: str | None` ·
`@property holds_anything -> bool` (`:3051`, any of the three truthy).

### 2.9 `CallContext` — `engine.py:3316-3403`
What rides INTO one dial.

| Field | Type | Default |
|---|---|---|
| `lead_id` | `str \| None` | `None` (`:3320`) |
| `lead_name` | `str \| None` | `None` (`:3321`) |
| `context_note` | `str \| None` | `None` (`:3322`) |
| `fields` | `dict[str, str]` | `Field(default_factory=dict)` (`:3333`) |
| `caller_memory` | `tuple[str, ...]` | `()` (`:3351`) |
| `from_e164` | `E164 \| None` | `None` (`:3382`) |
| `system_prompt` | `str \| None` | `None` (`:3402`) |

Two notes a second adapter must read:
- **`from_e164` (`:3352-3382`)** is *"THE NUMBER THIS DIAL MUST PRESENT TO THE CALLEE — the client's own DLT-registered header, resolved from the `phone_numbers` row bound to the agent (D-420)."*
- **`system_prompt` (`:3383-3402`)** is *"THE WHOLE SYSTEM PROMPT, for engines whose agent record cannot hold one"*. Composed by `compose_engine_prompt`. `None` on a `control_plane` engine **and that is not an omission** — *"sending a second copy per call would be two places one string is authoritative."* **NOT A LOG TARGET**; `CallContext` is dumped into vendor request bodies by design and into nothing else.
- There is deliberately **NO `prior_call_summary`** (`:3323-3332`): it was declared, read by the Bolna adapter, and written by nothing — deleted rather than wired, because `crm.service.plan_callback` already folds a redacted summary into `context_note`, and *"a second channel for transcript-derived text into the prompt is a second channel that can forget the redaction."*

### 2.10 `NumberSearch` — `engine.py:3405-3438` (frozen, extra=forbid)
`country: Literal["IN","US"] = "IN"` · `pattern: str | None = Field(default=None, min_length=1, max_length=8)` ·
`provider: str | None = Field(default=None, max_length=32)`.

### 2.11 `AvailableNumber` — `engine.py:3441-3468` (frozen, extra=forbid)
`e164: E164` · `provider: str | None = None` · `region: str | None = None` ·
`locality: str | None = None` · `monthly_price_usd: Decimal | None = None`.
The docstring (`:3505-3507`) marks these quotes as *"the vendor's quote in transit"* — hard
rule 7 governs what is STORED and BILLED, and `billing` is the only place they become rupees.

### 2.12 `NumberSpec` — `engine.py:3471-3496`
`series: NumberSeries = "standard"` · `country: Literal["IN","US"] = "IN"` ·
`e164: E164 | None = None` · `provider: str | None = None` · `region: str | None = None` ·
`purpose: str | None = None`.

### 2.13 `ProvisionedNumber` — `engine.py:3499-3521`
`e164: E164` · `provider: str | None = None` · `engine_number_ref: str | None = None` ·
`series: NumberSeries = "standard"` · `purchase_price_usd: Decimal | None = None` ·
`monthly_rental_usd: Decimal | None = None` — *"the figure that compounds silently if nothing
meters it (`billing/number_rental.py`)"* — · `engine_owned: bool | None = None`, i.e. *"did we
buy it through them? False/None means the number came from somewhere else and releasing it at
the engine would release nothing."*

### 2.14 `KBSourceRef` — `engine.py:3524-3575`
`kb_id: str` · `title: str` · `text: str` · `language: str = "te-IN"` ·
`document: bytes | None = None` · `content_sha256: str | None = None` ·
`source_url: str | None = None`.

### 2.15 `EngineKBRef` — `engine.py:37`
`= str`. The ENGINE's handle for one attached source (Bolna: `rag_id`). Our `kb_sources.id`
cannot serve — *"the engine has never seen it, so it addresses nothing on their side"* (`:33-36`).

### 2.16 `AccountKBObject` — `engine.py:4393-4428` (frozen, extra=forbid)
`handle: EngineKBRef | None` (required, nullable — *"None when the vendor has not minted one
yet. A pending object HAS no reference-able id on the primary engine, and inventing one would
make an unattachable object look attached"*) · `claimed_source_id: UUID | None = None` (a
CLAIM, not a fact) · `state: AccountKBState = "unknown"` · `created_at: datetime | None = None`.
`AccountKBState = Literal["ready","pending","failed","unknown"]` (`:4390`).

### 2.17 `AccountKBListing` — `engine.py:4431-4445`
`objects: list[AccountKBObject] = Field(default_factory=list)` · `complete: bool` (required) ·
`incomplete_reason: ListingIncompleteReason | None = None` · `pages_fetched: int = Field(default=1, ge=1)`.

### 2.18 `EngineVoice` — `engine.py:4448-4504` (frozen, extra=forbid)
`voice_id: str` · `label: str` · `tts_model: str` · `languages: tuple[str, ...] = ()` ·
`is_custom: bool = False` (the only route by which a CLONED voice can ever be offered).

### 2.19 `EngineVoiceListing` — `engine.py:4507-4523`
`voices: list[EngineVoice] = Field(default_factory=list)` · `complete: bool` (required) ·
`incomplete_reason: ListingIncompleteReason | None = None`. No `pages_fetched`.

### 2.20 `ExecutionSnapshot` — `engine.py:4176-4258`
The authenticated per-call read; **what we persist**.

| Field | Type | Default |
|---|---|---|
| `engine_call_id` | `str` | required (`:4183`) |
| `engine_agent_ref` | `str \| None` | `None` (`:4187`) |
| `direction` | `CallDirection` | `"inbound"` (`:4188`) |
| `status` | `CallStatus` | required (`:4189`) |
| `raw_status` | `str` | required (`:4190`) |
| `terminal` | `bool` | required (`:4191`) |
| `billable_ready` | `bool` | required (`:4192`) |
| `started_at` | `datetime \| None` | `None` (`:4193`) |
| `ended_at` | `datetime \| None` | `None` (`:4194`) |
| `duration_s` | `int \| None` | `None` (`:4195`) |
| `from_e164` | `str \| None` | `None` (`:4196`) |
| `to_e164` | `str \| None` | `None` (`:4197`) |
| `recording_url` | `str \| None` | `None` (`:4198`) |
| `transcript` | `list[TranscriptTurn]` | `Field(default_factory=list)` (`:4199`) |
| `transcript_lines_unparsed` | `int` | `0` (`:4205`) |
| `cost` | `CostBreakdown \| None` | `None` (`:4206`) |
| `billable_ready_at` | `datetime \| None` | `None` (`:4213`) |
| `engine_extracted` | `dict[str, Any]` | `Field(default_factory=dict)` (`:4214`) |
| `latency` | `CallLatency \| None` | `None` (`:4220`) |
| `engine` | `str` | `"fake"` (`:4221`) |
| `raw_document` | `bytes \| None` | `Field(default=None, repr=False, exclude=True)` (`:4254`) |
| `handoff` | `HandoffLeg \| None` | `None` (`:4258`) |

`raw_document` is `repr=False, exclude=True` — it never renders into a log line and never
serializes into a response. It is the VENDOR's own document (D-126), archived to object
storage and pointed at by `calls.engine_payload_ref`.

### 2.21 `CostBreakdown` — `engine.py:3578-3623`
`total_inr: Decimal` · `platform_inr`/`network_inr`/`llm_inr`/`tts_inr`/`stt_inr`: `Decimal | None = None` ·
`source_currency: str = "USD"` · **`currency_stated: bool = False`** — *"True only when the
PAYLOAD named that currency. False = house assumption"* (`:3602-3603`), the canonical
example in this file of a field that stops an adapter agreeing with the caller by
construction · `source_amount: Decimal | None = None` · `fx_rate: Decimal | None = None` ·
`fx_source: str | None = None` · `fx_as_of: date | None = None`.

### 2.22 `HandoffLeg` — `engine.py:4118-4173`
`outcome: HandoffLegOutcome` (`Literal["connected","unreached","in_progress","unknown"]`, `:4115`) ·
`raw_status: str` · `duration_s: int | None = None` · `recording_present: bool = False` ·
`recording_url: str | None = None` · `cost_reported: bool = False`.

### 2.23 `CallLatency` / `TurnLatency` / `LatencyBudget` — `engine.py:3910-4101`
- `LatencyBudget` (frozen, `:3910-3997`): `endpointing_ms`, `stt_ms`, `llm_ttft_ms`, `tts_ttfa_ms`, `retrieval_ms`, `india_us_transit_floor_ms`, `inherited_turn_detection_ms`, `voice_to_voice_p50_ms`, `voice_to_voice_p95_ms`, each defaulting to a module constant. Computed fields: `turn_ms`, `pipeline_ms`, `voice_to_voice_floor_ms`, `voice_to_voice_headroom_p50_ms`, `composes`. Singleton `LATENCY_BUDGET: Final[LatencyBudget]` at `:4001`.
- `TurnLatency` (`:4004-4045`): `turn: int` · `stt_ms`/`llm_ttft_ms`/`tts_ttfa_ms`: `float | None = None` · `@property component_sum_ms -> float | None` (None if any part missing).
- `CallLatency` (`:4048-4101`): `region: str | None = None` · `time_to_first_audio_ms: float | None = None` · `turns: list[TurnLatency]` · `parse_warnings: list[str]` · `@property llm_ttft_samples`, `@property llm_ttft_over_budget`.

### 2.24 `ExecutionListing` — `engine.py:4310-4371`
`snapshots: list[ExecutionSnapshot] = Field(default_factory=list)` · `complete: bool`
(required) · `incomplete_reason: ListingIncompleteReason | None = None` ·
`pages_fetched: int = Field(default=1, ge=1)`.

`@model_validator(mode="after") _verdict_and_reason_agree` (`:4346-4371`) makes the two
contradictory states unconstructible: incomplete without a reason raises (*"the poller
alerts on it and the enum is the alert's deduplication key"*), and complete WITH a reason
raises (*"the poller reads `complete` and would stay silent about it"*).

`ListingIncompleteReason` — `engine.py:4265-4289`, five members, each a distinct CONDITION:
`"explicit_more"` (payload said more exists, no followable link) · `"full_page_suspected"`
(no pagination metadata and row count is exactly a conventional page size — nothing PROVES
truncation, so the adapter refuses to claim completeness) · `"page_cap_reached"` ·
`"next_link_no_progress"` (a never-fetched page returned only rows already collected) ·
`"partial_fan_out"` (the listing was assembled from per-agent sub-reads and one failed —
added with `list_account_kb`, D-519).
`"next_link_loop"` and `"empty_page_with_next"` **were members and are GONE (D-365)** —
removed rather than left as spare vocabulary, because *"a value no adapter can emit is a
runbook entry for an event that cannot happen"*. **An adapter whose vendor hands out
continuation links may need them back; the member should land WITH the adapter that emits it.**

### 2.25 `RecallOutcome` — `engine.py:3626-3661` — `StrEnum`
`PREVENTED = "prevented"` (`:3655`) · `ALREADY_RUNNING = "already_running"` (`:3658`) ·
`UNKNOWN = "unknown"` (`:3661`). Returned by `end_call`; an adapter that cannot tell returns
`UNKNOWN`.

### 2.26 `WebhookVerdict` — `engine.py:4374-4381`
`ok: bool` · `method: Literal["hmac","source_ip","none"]` · `reason: str | None = None`.
`method` deliberately shares `WebhookAuthMethod`'s alphabet so an adapter that DECLARES
`hmac` and REPORTS `none` is caught by `==` (`engine.py:40-44`).

### 2.27 `LlmCredentialPlacement` — `engine.py:4526-4565` (frozen, extra=forbid)
`replaced_in_place: bool` (required) · `superseded_removed: int = Field(default=0, ge=0)`.
`@model_validator _verdict_and_count_agree` (`:4554-4565`) rejects `replaced_in_place` with
`superseded_removed > 0`: *"the store either replaced the entry or it appended beside it."*

### 2.28 `LlmProvider` and the model catalogue — `engine.py:720-1300`
`LlmProvider = Literal["azure_openai","openai","google"]` (`:720`) — the three declared legs
(D-456). Supporting frozen slotted dataclasses: `Evidence` (`:723-748`), `LlmModelTrap`
(`:758`), `LlmPrice` (`:1130-1174`, a CATALOGUE REFERENCE with no path to `unit_cost_paid`),
`LlmModelSpec` (`:1176-1226`, carries `traps`). Model Literals: `AzureOpenAIModel` (`:931`),
`OpenAIDirectModel` (`:967`), `GoogleDirectModel` (`:1023`), union `LlmModelName` (`:1072`).
`LlmModelTrapName` at `:751`. Residency plumbing: `azure_openai_base_url()` (`:1625`),
`openai_base_url()` (`:1677`), `google_openai_compat_base_url()` (`:1713`), `PostureLeg`
(`:1771-1834`), `ResidencyPosture` (`:1983-2022`), `ModelBinding` (`:2069`),
`leg_for_model()` (`:2096`), `bind_model()` (`:2121`).

### 2.29 Normalized events — `packages/shared/src/calevate_shared/events.py`
These are the types `parse_webhook` returns and the transcript rows `ExecutionSnapshot`
carries. **Nothing outside `engine/` sees anything else.**

- `CallDirection = Literal["inbound","outbound"]` (`events.py:19`)
- `CallStatus = Literal["queued","ringing","in_progress","completed","failed","no_answer","busy","voicemail"]` (`events.py:20-29`)
- `Speaker = Literal["agent","caller"]` (`events.py:30`)
- `TERMINAL_STATUSES: frozenset[CallStatus] = {"completed","failed","no_answer","busy","voicemail"}` (`events.py:36-38`)
- **`CallEvent`** (`events.py:41-67`): `call_id: str` · `engine_agent_ref: str | None = None` · `tenant_id: UUID | None = None` · `agent_id: UUID | None = None` · `direction: CallDirection` · `status: CallStatus` · `raw_status: str | None = None` · `started_at`/`ended_at`: `datetime | None = None` · `from_e164`/`to_e164`: `str | None = None` · `recording_url: str | None = None` · `cost_raw: str | None = None` · `engine: str` (required) · `engine_payload_ref: str | None = None` · `@property is_terminal` (`:65-67`).
- **`TranscriptTurn`** (`events.py:70-84`): `call_id: str` · `idx: int = Field(ge=0)` · `speaker: Speaker` · `text: str` · `text_redacted: str | None = None` · `lang: str | None = None` · `start_ms`/`end_ms`: `int | None = None`. Hard rule 5: API responses default to `text_redacted`.

---

## 3. CAPABILITIES

### 3.1 `EngineCapabilities` — `engine.py:127-330` (frozen, `extra="forbid"`)

**NO DEFAULTS, deliberately** (`engine.py:152-155`): *"Every field is required, so a new
adapter must answer every question in writing rather than inherit today's engine's answers
by omission — which is exactly how a Bolna-shaped assumption got everywhere in the first
place."* Frozen *"because a capability that can be mutated at runtime is a capability two
callers can disagree about."*

Two rules make the declaration worth trusting (`engine.py:143-151`): an absent capability
produces a **named refusal**, not a crash and not a silent no-op; and **a claimed
capability is exercised by the conformance suite** — *"a descriptor an adapter can lie in
is worse than none."*

| Field | Type | Line | What it asks |
|---|---|---|---|
| `stt` | `SpeechControl` | `:162` | ours (BYOK) or the engine's to dictate |
| `tts` | `SpeechControl` | `:166` | *"THE field the voice catalogue asks: under `engine` our Sarvam Bulbul catalogue is not a choice set, it is a list of voices that engine cannot speak, and offering it is a screen that lies."* |
| `llm` | `SpeechControl` | `:168` | *"`ours` wherever the engine takes `model=` + `api_key=`."* |
| `agent_hosting` | `AgentHosting` | `:179` | **The field the descriptor was missing** — every other member asks what an engine can do WITH an agent and *"not one of them asked whether it will hold an agent of ours at all"* (D-280, the state D-270 found Cartesia in) |
| `campaigns` | `bool` | `:186` | Does the engine hold campaign objects of its own? False ≠ campaigns impossible; ours dispatch from `apps/api/campaigns` + `apps/workers`. **The Protocol has no campaign method, so a `True` is currently unfalsifiable and the conformance suite refuses it outright** |
| `knowledge_base` | `bool` | `:190` | Built-in KB (Bolna `rag_id`)? Under False all of `attach_kb`/`detach_kb`/`list_kb` must refuse by name and T3 has no engine behind it |
| `number_series` | `frozenset[NumberSeries]` | `:195` | Which classes it can PROVISION. Empty = none (Bolna's answer: numbers come from the telephony vendor directly, D-05) |
| `caller_id` | `bool` | `:215` | *"Will this engine present a caller ID **WE NAME, PER CALL**"* (`CallContext.from_e164`, D-420). **NOT "does this engine have a caller ID"** — every telephony platform has one, the question is whose. **ADAPTER-WIDE CONFIGURATION IS `False`, NOT `True`**: Cartesia's single platform-wide `from_number_id` looks like caller-ID support and is not |
| `inbound_binding` | `bool` | `:225` | Can it be told which agent answers which number? **SEPARATE FROM `numbers`**, which is about PROVISIONING — *"Bolna provisions none of ours and still routes them, so one boolean for both would have made the engine that can do the half we need look like the engine that can do neither"* |
| `transfer` | `bool` | `:234` | Will `VoiceEngine.transfer` — a CONTROL-PLANE command from OUTSIDE the call — work? **NOT "does this vendor have a transfer feature"** |
| `in_call_handoff` | `bool` | `:250` | Can the AGENT, mid-call, hand the caller to a human at a number WE NAME at publish time (`AgentConfig.handoff`, D-533)? The other half of `transfer` — *"Bolna answers no to the first and yes to the second."* Under False a publish carrying a `handoff` must REFUSE, never drop |
| `script_override` | `bool` | `:267` | Can a PUBLISHED agent's first line and task prompt be replaced alone (D-544)? Under False the maintenance window still runs; callers just do not get the message, and `workers/maintenance.py` says so in the operator's alert |
| `webhook_auth` | `WebhookAuthMethod` | `:272` | *"Must equal what `verify_webhook` actually reports, and must equal `WEBHOOK_AUTH_BY_ENGINE[name]`"* — the receiver reads that table rather than importing an adapter (hard rule 3 forbids the heavy import) |

Accessors:
- `speech_control(leg: SpeechLeg) -> SpeechControl` (`:274-277`) — one accessor so no caller re-derives it from three fields
- `is_ours(leg) -> bool` (`:279-281`)
- `hosts_agents() -> bool` (`:283-293`) — `agent_hosting == "control_plane"`
- `provisions(series: NumberSeries) -> bool` (`:295-299`)
- `has(name: EngineCapabilityName) -> bool` (`:301-330`) — the total dispatch over the closed `EngineCapabilityName` set

### 3.2 `BOLNA_CAPABILITIES` — `apps/api/engine/bolna.py:3614-3635`

```python
BOLNA_CAPABILITIES = EngineCapabilities(
    stt="ours",                              # :3615
    tts="ours",                              # :3616
    llm="ours",                              # :3617
    agent_hosting="control_plane",           # :3618
    campaigns=False,                         # :3619
    knowledge_base=True,                     # :3620
    number_series=frozenset({"standard"}),   # :3621
    caller_id=True,                          # :3622
    inbound_binding=True,                    # :3623
    transfer=False,                          # :3624
    in_call_handoff=True,                    # :3625
    script_override=True,                    # :3634
    webhook_auth="source_ip",                # :3635
)
```
Bound at `bolna.py:3643` (`capabilities = BOLNA_CAPABILITIES`), alongside
`name = "bolna"` (`:3641`) and `credential_env_keys: tuple[str, ...] = ("BOLNA_API_KEY",)`
(`:3648`). **The annotation on `credential_env_keys` is load-bearing** (`:3644-3647`):
without it mypy infers `tuple[str]` (a ONE-element tuple type), and a Protocol's mutable
attributes are invariant, so the adapter would stop satisfying `VoiceEngine` the moment a
second key is added. **Same for every adapter.**

Grounds worth carrying into a second adapter:
- `script_override=True` is justified from `patch_update.md:19,24,30,116-124` — `PATCH /v2/agent/{id}`'s CLOSED attribute list contains BOTH halves (`agent_welcome_message` and top-level `agent_prompts` keyed `task_1`) — the same page `update_agent` cites for why PATCH cannot do the FULL replacement (`bolna.py:3626-3633`).
- `inbound_binding=True` is a **MARKED ASSUMPTION — OPERATIONS §2 GATE 25** (`bolna.py:3604-3613`): the vendor also writes *"Inbound Agent functionality using APIs currently requires connecting your **Twilio account**"* while Plivo carries our 160-series numbers. *"`True` is the claim that the ROUTE exists and that this adapter calls it correctly"*; it fails LOUD (a vendor 400 surfaced as `engine_rejected` and alarmed), which is the safe direction.

### 3.3 `WEBHOOK_AUTH_BY_ENGINE` — `engine.py:345-386`

One definition, two readers — the doctrine `config.bolna_source_ips` established. The second
reader is `apps/voice-runtime/engine_intake.py`, which must decide how to authenticate a
delivery WITHOUT importing an adapter. It used to answer with `if engine == "bolna"`, *"a
vendor name hard-coded into the receiver, so a signed engine meant editing the
latency-critical service"* (`engine.py:337-341`).

| Key | Method | Why |
|---|---|---|
| `"bolna"` | `"source_ip"` | signs nothing (D-31, TRD §5): allowlist + execution-id dedupe, payloads as hints, poller as truth |
| `"fake"` | `"none"` | verifies NOTHING by design; `method="none"` is what stops a caller mistaking it for evidence |
| `"fake-restricted"` | `"hmac"` | `fake.DICTATED_SPEECH_CAPABILITIES`. **The only engine in this codebase that authenticates with a signature** — without it the `hmac` branch of this table, of `WebhookVerdict` and of the receiver is code no test has ever executed. Never selectable as `ENGINE=` |
| `"fake-deployed"` | `"none"` | `fake.EXTERNAL_DEPLOYMENT_CAPABILITIES` (D-280). The only engine satisfying the ALTERNATIVE half of hard rule 5 (prompt on `CallContext.system_prompt`). `none` deliberately, so the clause says which axis it measured |
| `"cartesia"` | `"hmac"` | **AUTHENTICATED BY SOMETHING WE CANNOT CHECK YET**, and `hmac` is the Literal's only value that FAILS CLOSED. No SDK carries a signing scheme; the only description is a search snippet naming an `x-webhook-secret` SHARED SECRET header, which is not an HMAC. *"'Authenticated, and we cannot check it yet' must not be recorded as 'unsigned, so an IP allowlist will do'"* |

**The conformance suite asserts `adapter.capabilities.webhook_auth == WEBHOOK_AUTH_BY_ENGINE[adapter.name]` for every adapter** (`engine.py:343-344`), so the table cannot drift.

### 3.4 `SOURCE_IP_ALLOWLIST_BY_ENGINE` — `packages/shared/src/calevate_shared/config.py:1667-1669`

```python
SOURCE_IP_ALLOWLIST_BY_ENGINE: dict[str, Callable[[Settings], frozenset[str]]] = {
    "bolna": bolna_source_ips,
}
```
- `WEBHOOK_AUTH_BY_ENGINE` says which METHOD; **this says which addresses that method reads** (P2.6). Before it existed the method was per engine and the addresses were always Bolna's, so a second unsigned engine's deliveries would have been authenticated against *Bolna's* egress (`config.py:1645-1652`).
- **AN ABSENT ENTRY REFUSES.** No fall-back to the single entry that happens to exist; the receiver returns a distinct reason so an operator reads *"this engine has no allowlist"* rather than *"this address is not allowlisted"* (`config.py:1654-1657`).
- **RESOLVERS, NOT ADDRESS SETS** (`config.py:1665-1667`): an operator rotating `BOLNA_WEBHOOK_SOURCE_IPS` during a vendor renumber must move the answer without a redeploy.
- It lives in `config.py` and NOT in the receiver because `tests/engine_name_drift_test.py` forbids `apps/voice-runtime/engine_intake.py` from spelling an engine name in a collection at all (D-103) (`config.py:1659-1663`).

### 3.5 How `apps/api/engine/capabilities.py` gates (341 lines)

*"The fourth instance of a shape this repo has already settled three times"* —
`billing/payments.payment_capability`, `ingest/meta.lead_retrieval_capability`,
`workers/sheets_sync.get_sheets_transport`, `campaigns/provisioning.number_provisioning_capability`.
What differs: the other three answer *"is anything wired up at all?"*; this answers *"what
can the wired-up thing DO?"*, because a voice engine is never absent and never uniformly
capable — so availability is asked PER CAPABILITY, from a descriptor the ADAPTER declares.

Surface:

| Symbol | Line | Contract |
|---|---|---|
| `ENGINE_CAPABILITY_ABSENT: Final = "engine_capability_absent"` | `:58` | **ONE machine code for every capability.** The rejected alternative was `engine_lacks_tts`-style per-capability codes: `code` becomes the last segment of the problem `type` URL, so that would mint seven problem types for one condition |
| `_REMEDIATION: Final[dict[EngineCapabilityName, str]]` | `:65-127` | One authored operator sentence per capability. **Authored, not generated** — *"'this engine does not do X' is useless without 'so do Y instead'"*, and the Y differs per capability. All twelve `EngineCapabilityName` members are keyed, so a new member is a `KeyError` at construction |
| `EngineCapabilityAbsentError(ProblemError)` | `:130-165` | `kind="dependency"`, `code=ENGINE_CAPABILITY_ABSENT`, carries `.capability` and `.engine` as ATTRIBUTES so a test, a metric and an operator read the same token. **No vendor name and no vendor prose crosses this boundary** (hard rule 2). **NOT raised for a capability that merely has not been VERIFIED** — that stays `engine_capability_unverified` in the adapter waiting on the evidence |
| `engine_lacks(capability, *, engine) -> EngineCapabilityAbsentError` | `:168-176` | **Builds AND logs.** Returns the exception for the caller to `raise` |
| `NO_CREDENTIALS_REASON: Final = "no_engine_credentials"` | `:190` | A LOG reason, not a response field. The `EngineAvailability`/`engine_availability()` that also read it was deleted (P2.6) as an uncalled second answer; the wired one is `engine.missing_engine_credential_keys` |
| `engine_not_configured(reason) -> ProblemError` | `:193-209` | The ONE deployment-side refusal. `code="engine_not_configured"`. The authored reason is LOGGED, never returned |
| `_selected_engine() -> VoiceEngine` | `:212-218` | Imports `get_engine` INSIDE the function — `apps.api.engine.__init__` imports this module for the refusal type, so a module-scope import back would be a cycle |
| `engine_capabilities(engine: VoiceEngine \| None = None) -> EngineCapabilities` | `:221-233` | **THE selector.** Nothing reads an adapter's attribute directly. The optional override exists so the publish path and the KB publish path check the capability of *the adapter they are about to call* |
| `require_capability(capability, *, engine: VoiceEngine) -> None` | `:236-244` | Raises `engine_lacks(...)` unless `engine.capabilities.has(capability)`. **Takes the adapter rather than looking one up** — *"a guard that checked a different instance from the one about to be called is a guard that passes on the wrong evidence"* |
| `require_speech_leg(leg, *, engine, value: str \| None) -> None` | `:247-263` | **The guard that makes `SpeechControl` mean something.** `value is None` PASSES (an agent naming no voice asserts nothing). Otherwise refuses when `not engine.capabilities.is_ours(leg)` — dropping instead produces *"an operator picks Bulbul v3, the row saves, the publish succeeds, and the caller hears the engine's own voice"* |
| `ENGINE_COMPLIANCE_FLOOR_ABSENT: Final = "engine_compliance_floor_absent"` | `:277` | **Its own code, not `engine_capability_absent`** — an absent capability is a platform fact an operator can only accept; this is a request that arrived without the thing that makes it legal to place. It is in `DIAL_NOT_PLACED_CODES` (`agents/service.py`) because it raises BEFORE any HTTP request leaves the process, so the contact keeps its place on the ladder |
| `require_call_compliance_floor(*, engine, prompt_on_the_wire: str \| None) -> None` | `:280-331` | No-op where `capabilities.hosts_agents()`. Otherwise requires `carries_truthful_answer_floor(prompt_on_the_wire)`. **`prompt_on_the_wire` IS WHAT THE ADAPTER IS ABOUT TO SEND, NOT WHAT IT WAS HANDED, and the difference is the whole reason the argument is not `ctx`** — an adapter that receives `CallContext.system_prompt` and has no request field for it would pass a context-shaped check and dial anyway. Each adapter passes the expression it puts in its body; one with no such field passes `None` and is refused every time (`CartesiaEngine.start_outbound_call` is that case) |

Deleted and worth not re-adding: `provisionable_series()` (`capabilities.py:334-338`) — it
existed, was exported, had no callers, and its docstring claimed the campaign gate matches
on the ENGINE's series, when the gate matches on OUR `phone_numbers.series`.

---

## 4. THE CONFORMANCE SUITE

`packages/shared/tests/engine_conformance/` — `conftest.py` (1087 lines) +
`contract_test.py` (2698 lines) + `fixtures/` (`MANIFEST.json`, `README.md`).

*"The exit door. If a rented engine fails us (R-02) the cost of leaving must be one new
adapter, not a rewrite — and that is only true if every adapter is held to identical,
checkable behaviour"* (`contract_test.py:1-8`). Marker: `pytestmark = [pytest.mark.conformance]`
(`contract_test.py:49`). Run with `make conformance` / `uv run pytest -m conformance`.

**It lives in `packages/shared` on purpose** — it tests the CONTRACT, not an
implementation. *"Neither test touches the network — `make conformance` must be runnable
on a plane"* (`conftest.py:1-9`).

### 4.1 How a new adapter joins

> *"Adding an engine = adding one entry to `ENGINE_IDS` and a factory below. If the new
> adapter cannot pass unchanged, the contract is wrong or the adapter is leaking."*
> — `conftest.py:8-9`

- `ENGINE_IDS = ["fake", "fake-restricted", "fake-deployed", "bolna", "cartesia"]` (`conftest.py:59`)
- `make_engine(engine_id, *, listing_rows=1) -> VoiceEngine` (`conftest.py:975-1020`) — the factory; a new branch goes here.
- Fixtures parametrised over the roster: `engine` (`:1022`), `saturated_engine` (`:1069`), `engine_id` (`:1086`), `declared_agent_hostings` (`:1074`), plus the transport-ladder fixtures `ladder` (`:951`, parametrised over `TRANSPORT_RECIPES`), `transport_recipe_ids` (`:957`), `http_speaking_engine_ids` (`:963`).
- `saturated(engine)` (`conftest.py:1027-1067`) is a **function as well as a fixture**, because `tests/engine_audit_test.py` runs these clauses against SABOTEUR adapters outside pytest's fixture machinery — *"a clause it cannot set up is a clause no saboteur can ever fail."* It rebuilds a FRESH instance carrying **the original's capabilities and name**, so a saboteur cannot hide in the one clause whose subject is constructed rather than passed in.
- `TRANSPORT_RECIPES: dict[str, Callable[[VendorHandler], VoiceEngine]]` (`conftest.py:926-948`) — one recipe per HTTP-speaking adapter, because the credential, base URL and version pin are the per-vendor half `engine/vendor_http.py` deliberately does not hold. Each call builds a FRESH adapter.
- A non-default-fake instance **must take its own `name`** (`conftest.py:981-985`): `WEBHOOK_AUTH_BY_ENGINE` is keyed by name and the voice-runtime receiver reads that table, so two instances answering to one name while declaring different capabilities make it ambiguous.

### 4.2 The roster and why each subject exists (`conftest.py:28-58`)

- **`bolna`** — real adapter over `httpx.MockTransport` fed payload shapes captured from the vendor mirror.
- **`cartesia`** — *"the second real vendor and the first that DISAGREES with us: it dictates its own STT and TTS, signs its webhooks, and provisions no Indian number class. It is what makes 'the contract is vendor-neutral' a measurement rather than a hope."* Its stub proves OUR mapping, *"it proves nothing about Cartesia."*
- **`fake`** — runs as itself.
- **`fake-restricted`** (`DICTATED_SPEECH_CAPABILITIES`) — the FAST TEST DOUBLE for the dictated-speech/no-KB/signed-webhook profile, *"and it keeps the `hmac` branch executable with a verifier that actually verifies (the Cartesia adapter's fails closed, by design)."*
- **`fake-deployed`** (`EXTERNAL_DEPLOYMENT_CAPABILITIES`) — *"the only one that satisfies the ALTERNATIVE half of hard rule 5 (D-280/D-282)."* Cartesia is the same SHAPE and cannot do the second half (no prompt field on its outbound body, so it refuses every dial) — *"so without this fixture the branch where an externally-deployed engine actually dials would be contract nothing executes."*

Vendor fixtures carry their own hard-won corrections, each a lesson for a new stub:
- `BOLNA_COMPLETED` (`conftest.py:71-105`): `telephony_data.call_type` IS THE DIRECTION; a top-level `"direction"` was **invented here at the same time as the adapter's read of it, from the same guess, so the stub and the adapter agreed and this suite confirmed the agreement while every real inbound call would have normalized as outbound** (D-359). Likewise `updated_at`, NOT `ended_at` (D-361). **The old keys are deliberately NOT kept: a fixture that carries both cannot tell which one the adapter read.**
- `_cartesia_completed` (`conftest.py:108-150`): every key is read at source in the vendor's generated client. **What is ABSENT is as load-bearing as what is present** — no cost (account-level credit meter), no duration (derived), no recording URL, no direction. `start_time` is minted RELATIVE TO NOW because the vendor offers no server-side time filter, *"a fixture frozen in the past would put every row outside every window and make the listing clauses pass vacuously."* A `system` transcript row is present precisely so something proves the adapter refuses to file instrumentation as a caller utterance.
- `_bolna_handler` (`conftest.py:173+`): the agent store carries the knowledge reference at `tasks[].tools_config.llm_agent.llm_config.vector_store.provider_config.vector_ids` (`bolna-findings/mirror/pages/api-reference/agent/v2/get.md:806-817,1164-1195`). **The `PUT` replaces the whole object**, which is what makes `update_agent`'s read-then-write provable. The KB routes are **STATEFUL on purpose**: *"a stub that answered every `POST /knowledgebase` with the same `rag_id` and every `DELETE` with 200 would let an adapter that never detaches anything sail through."* The first read answers `processing` with no `vector_id`, per the vendor's own create response.
- Saturation sizes are DERIVED, never typed: `BOLNA_SATURATION_ROWS = bolna_module._LISTING_PAGE_SIZE * bolna_module._LISTING_MAX_PAGES + 1` (`conftest.py:170`) — *"a hand-copied number stops saturating the moment either constant moves, and a saturation fixture that no longer saturates fails nothing."* `FULL_LISTING_PAGE = 10` for the fake (`conftest.py:153-155`).

### 4.3 Shared helpers a new adapter is measured through

- `_VOICE_TIERS` (`contract_test.py:65-77`) — `("sarvam","bulbul:v3","anushka")` and `("cartesia","sonic-3.5","conformance-placeholder-not-a-real-voice-id")`. **The Cartesia speaker is explicitly a fixture string and NOT a voice id** — nobody in this tree has read a real one, *"so inventing one that LOOKED real would be the laundering hard rule 11 forbids, dressed as a test fixture."*
- `_byok_models(engine, *, tier=0)` (`contract_test.py:80-105`) — the canonical stack reduced to the legs THIS engine lets us choose; a dictated leg is left `None` deliberately, because `require_speech_leg` refuses a value for a dictated leg.
- `_dial_context(engine, cfg, **fields)` (`contract_test.py:~190-205`) — `prompt = None if engine.capabilities.hosts_agents() else compose_engine_prompt(cfg)`. **The fixture makes the same decision `agents/service._call_prompt_for` makes in production, from the same capability** — *"a fixture that made it differently would be testing a system we do not run."*
- `_place_call(engine)` (`contract_test.py:208-224`) — dials, or returns `None` when the adapter refuses by name; it ASSERTS the refusal code is exactly `engine_compliance_floor_absent`, so a refusal for some other reason is a failure.
- `_assert_cost_is_re_derivable(cost)` (`contract_test.py:227-245`) — hard rule 7 as a checkable property: `source_currency`, `source_amount`, `fx_rate > 0` must all be present AND `source_amount * fx_rate` must reproduce `total_inr` within `Decimal("0.01")`. *"A total with no source amount and no fx rate satisfies the type and breaks the promise."*

### 4.4 The asserted behaviours, grouped by protocol method

**Protocol shape**
- `test_adapter_satisfies_the_protocol` (`:248`) — `isinstance` against the runtime-checkable Protocol: *"only checks method NAMES — which is exactly the check that catches a half-written adapter being wired into config."*

**`create_agent` / `update_agent`**
- `test_create_and_update_agent_returns_a_stable_ref` (`:255`) — the ref is the join key between their world and ours; instability breaks webhook→tenant resolution for every existing agent.

**`get_agent`**
- `test_agent_read_back_reports_the_agent_it_was_asked_about` (`:271`) — the clause that makes `update_agent` mean something (gate 2). TWO agents, each must carry its OWN prompt.
- `test_a_read_back_carries_the_opening_line_the_engine_was_given` (`:346`) — hard rule 5 scored on the ENGINE, not on our request body.
- `test_every_adapter_puts_the_truthful_answer_rule_on_the_engine` (`:414`) — hard rule 5's unfalsifiable half, on every adapter (D-163).
- `test_an_agent_with_no_opening_notice_still_carries_the_truthful_answer_rule` (`:462`) — the toggles change what is VOLUNTEERED, never the floor.
- `test_reading_an_agent_the_engine_never_created_is_reported` (`:499`) — an unknown ref must RAISE, never answer.
- `test_agent_read_back_answers_or_declines_the_kb_reference_question` (`:615`) — D-41's dangling handle, and the right to answer `None` ("I cannot tell") via the tri-state (gate 8).

**`delete_agent`**
- `test_delete_agent_removes_exactly_the_agent_it_names_and_is_idempotent` (`:545`) — removal observed through `get_agent`; a second delete must not raise; the OTHER agent must survive.

**`start_outbound_call`**
- `test_outbound_call_returns_a_handle` (`:670`) — a placed dial answers with a handle and the context reaches it.
- `test_a_declared_caller_id_reaches_the_dial_or_is_refused_by_name` (`:1954`) — D-420, both directions.
- `test_agent_hosting_decides_where_the_truthful_answer_rule_lives` (`:2260`) — the split DERIVED from the capability (D-280/D-282), not declared per vendor.

**`end_call`**
- `test_ending_a_call_the_engine_does_not_hold_is_reported` (`:694`) — D-187; the clause was missing while the adapters actively disagreed.
- `test_a_stop_says_what_it_caught_and_never_overclaims` (`:724`) — the return must be a `RecallOutcome` a caller can branch on; the DNC recall reads it to decide whether a number may be recorded as not called.

**`get_execution`**
- `test_reading_an_execution_the_engine_never_placed_is_reported` (`:520`) — `get_agent`'s clause one method along (P2.6).
- `test_execution_snapshot_is_fully_normalized` (`:751`) — hard rule 2: OUR shape, OUR status vocabulary, OUR currency.
- `test_get_execution_carries_the_vendors_own_document_for_the_archive` (`:772`) — keeps D-126's erasure arm pointed at something.
- `test_billable_ready_implies_terminal` (`:848`) — Bolna's cost/recording/transcript are null until `completed` (~2-3 min after disconnect); a pipeline triggering on "terminal" would meter zeros.
- `test_transcript_turns_are_ordered_and_speaker_tagged` (`:861`) — extraction, redaction and the call-detail view all index by `idx` and switch on `speaker`.
- `test_unknown_vendor_status_degrades_to_failed` (`:1001`) — fail closed on the unknown.

**`list_executions`**
- `test_list_executions_backs_the_reconciliation_poller` (`:882`) — same normalized shape.
- `test_a_full_listing_page_tells_the_caller_it_may_be_truncated` (`:903`, uses `saturated_engine`) — *"THE CLAUSE THE POLLER'S ENTIRE GUARANTEE RESTS ON (D-31)."*

**`verify_webhook` / `parse_webhook`**
- `test_webhook_verification_reports_its_method` (`:935`) — an adapter may not dress an unsigned event up as verified.
- `test_a_claimed_verification_method_actually_rejects_somebody` (`:944`) — *"the clause the label above is worthless without."* Uses `ALLOWLISTED_SOURCE_IP = "13.203.39.153"` and `UNKNOWN_SOURCE_IP = "203.0.113.9"` (RFC 5737 documentation range, *"so it can never accidentally become someone's real address"*, `contract_test.py:56-62`).
- `test_the_declared_webhook_method_is_the_one_actually_reported` (`:1310`) — `capabilities.webhook_auth` == `verify_webhook().method` == `WEBHOOK_AUTH_BY_ENGINE[name]`.
- `test_webhook_parses_into_our_event` (`:973`) — **`parse_webhook` may not invent `tenant_id`/`agent_id`** — a vendor cannot know them, and a guessed tenant is a cross-tenant write (hard rule 1).

**`attach_kb` / `detach_kb` / `list_kb` / `list_account_kb`**
- `test_attach_kb_accepts_our_source_ref_and_returns_a_handle` (`:1037`)
- `test_detach_kb_actually_removes_exactly_the_source_it_names` (`:1057`) — observed through `list_kb`.
- `test_the_account_listing_sees_what_no_agent_references` (`:1102`) — `list_account_kb` must see an object `list_kb` cannot.
- `test_a_detach_that_did_not_happen_is_reported_rather_than_swallowed` (`:1164`) — detaching an absent handle RAISES.
- `test_an_engine_without_a_knowledge_base_refuses_all_three_kb_methods` (`:1679`) — `knowledge_base=False` must mean a refusal, never an empty success.

**`list_voices`**
- `test_the_voice_catalogue_comes_from_the_engine_or_is_refused_by_name` (`:1195`) — *"never with `[]`."*
- `test_a_cloned_voice_keeps_a_label_nothing_could_derive` (`:1250`) — a custom voice's LABEL crosses as data.

**Capability descriptor**
- `test_the_adapter_declares_a_complete_capability_descriptor` (`:1290`) — every adapter answers every question; there is no "unset".
- `test_a_byok_speech_leg_is_accepted_and_a_dictated_one_is_refused_by_name` (`:1335`)
- `test_a_byok_leg_that_can_be_read_back_holds_what_we_sent` (`:1394`)
- `test_every_voice_tier_round_trips_or_is_refused_by_its_own_name` (`:1481`) — both `_VOICE_TIERS`; the third outcome (a tier that neither round-trips nor is refused) is the one that bites.
- `test_the_llm_leg_round_trips_its_provider_and_endpoint` (`:1599`) — same provider, same endpoint back off the engine.
- `test_an_externally_deployed_engine_claims_no_byok_leg` (`:2369`) — DERIVED: `ModelConfig` reaches an engine through the agent object, so no agent object means no BYOK leg.
- `test_every_agent_hosting_shape_is_exercised_by_the_roster` (`:2399`, sync, uses `declared_agent_hostings`) — *"a hosting shape no subject declares is a branch of the contract nothing runs."*
- `test_an_engine_side_campaign_object_is_not_claimable_yet` (`:2421`) — **`campaigns=True` is REFUSED OUTRIGHT**: the one capability with no method behind it, and therefore no way to lie safely.

**`set_llm_credential`**
- `test_the_llm_credential_seam_matches_the_declaration_either_way` (`:1718`) — installs where the LLM is ours, refuses by name where it is not (D-404).

**`transfer`**
- `test_transfer_matches_the_declaration_either_way` (`:1767`) — *"a transfer that silently does nothing is a caller left on hold forever."*

**Numbers**
- `test_number_provisioning_matches_the_declared_series` (`:1825`) — per SERIES, iterating `NUMBER_SERIES_VALUES` derived from the `NumberSeries` Literal (`contract_test.py:53-55`), never retyped.
- `test_a_purchase_without_a_chosen_number_is_refused` (`:1864`) — search → pick → buy; the middle step is not optional (D-537).
- `test_searching_is_offered_exactly_where_buying_is` (`:1887`) — *"a search that works beside a buy that refuses is a screen that teaches a lie."*
- `test_a_bought_number_can_be_given_back` (`:1916`) — and absent-is-success on the second call.
- `test_inbound_binding_matches_the_declaration_either_way` (`:2189`) — D-420.

**`override_call_script`**
- `test_a_script_override_changes_the_words_and_nothing_else` (`:2100`) — D-544: voice, number, KB, model and webhook must survive.

**`AgentConfig.handoff`**
- `test_a_declared_handoff_reaches_the_engine_or_is_refused_by_name` (`:2025`) — D-533.

**Transport ladder — every HTTP-speaking adapter (`ladder` fixture)**
These exist because the two real adapters had drifted on all of them (D-240):
- `test_a_throttled_vendor_is_retried_rather_than_reported_as_a_failure` (`:2508`) — a 429 states the request was REFUSED, not performed: the one status where a repeat cannot dial a person twice.
- `test_an_exhausted_throttle_is_transient_rather_than_a_rejection` (`:2536`) — `apps.workers.pipeline.TRANSIENT_ENGINE_CODES` and `apps.api.agents.service` both dispatch on `engine_rate_limited` **by name**.
- `test_a_success_the_adapter_cannot_read_never_becomes_an_answer` (`:2560`) — *"THE CLAUSE THIS SECTION EXISTS FOR (D-240)"*: `cartesia` turned an unparseable 2xx into `{}` and built an `ExecutionSnapshot` out of nothing.
- `test_a_redirect_is_never_treated_as_an_answer` (`:2596`) — *"a 3xx is a status BELOW 400, which is how it got in."*
- `test_a_vendor_error_body_is_never_echoed_to_our_caller` (`:2628`) — hard rule 6 (vendor error bodies quote the request, and our requests carry callers' numbers) plus BACKEND-PATTERNS §3. **The STATUS is the evidence and the body is not.**
- `test_a_vendor_that_never_answers_is_reported_as_unreachable` (`:2652`) — refused socket, DNS failure and read timeout are one fact; `engine_unreachable` is read by name in `apps.workers.pipeline.TRANSIENT_ENGINE_CODES`.
- `test_every_adapter_that_speaks_http_is_held_to_the_transport_clauses` (`:2679`, sync) — **the opt-out check**: `transport_recipe_ids` must cover `http_speaking_engine_ids`, so a new vendor cannot skip the ladder by simply not adding a recipe.

### 4.5 Skips and xfails

**There are no `xfail`s and no `pytest.mark.skip` decorators.** Three runtime `pytest.skip`
calls, each conditional on a declared capability rather than on an adapter name:

| Line | Condition | Stated reason |
|---|---|---|
| `contract_test.py:743` | `_place_call` returned `None` (the adapter refused the dial by name) | *"this adapter places no dial, so it holds nothing to stop"* — stopping a fabricated id *"would measure the D-187 clause above a second time instead of this one"* |
| `contract_test.py:2057` | `not caps.hosts_agents()` (handoff clause) | *"no agent record on this shape; `agent_hosting` covers it"* — `create_agent` refuses one step earlier, and *"a refusal naming the wrong capability is not evidence about this one"* |
| `contract_test.py:2134` | `not caps.hosts_agents()` (script-override clause) | same |

A new adapter therefore cannot silence a clause by declaring a capability it does not have
— the capability-matched clause (`..._matches_the_declaration_either_way`,
`..._or_is_refused_by_name`) runs in BOTH directions.

---

## 5. THE FAKE ADAPTER — `apps/api/engine/fake.py` (1386 lines)

**The structural reference.** It is an in-memory adapter with no transport, so every line
is contract-shaped rather than vendor-shaped; a new adapter that resembles it method-for-
method will pass §4.

### 5.1 Class surface

```python
class FakeEngine:                                          # :402
    name = "fake"                                          # :409  (overridable via __init__)
    credential_env_keys: tuple[str, ...] = ()              # :415  — "an adapter that IS its own vendor"
    DEFAULT_LISTING_PAGE_SIZE = 100                        # :422
    def __init__(self, *, listing_page_size: int = DEFAULT_LISTING_PAGE_SIZE,
                 capabilities: EngineCapabilities = DEFAULT_FAKE_CAPABILITIES,
                 webhook_secret: str = FAKE_WEBHOOK_SECRET,
                 name: str | None = None) -> None:         # :424-431
```
State (`:441-468`): `_agents: dict[str, AgentConfig]`, `_calls: dict[str, _StoredCall]`,
`_kb: dict[str, list[KBSourceRef]]`, `_account_kb: dict[EngineKBRef, AccountKBObject]`,
`_inbound: dict[str, EngineAgentRef]`, `_numbers: dict[str, ProvisionedNumber]`,
`_llm_credentials: dict[LlmProvider, str]`, `_tts_credential: str | None`.
`capabilities` is an **instance** attribute here (`:440`) precisely so one class can run
three profiles.

**Three capability profiles in one file** — the mechanism by which the suite reaches
branches no real vendor exercises:
- `DEFAULT_FAKE_CAPABILITIES` (`:212-237`) — all speech ours, `control_plane`, `knowledge_base=True`, `number_series={"standard"}`, `caller_id=True`, `inbound_binding=True`, `transfer=False`, `in_call_handoff=True`, `script_override=True`, `webhook_auth="none"`.
- `DICTATED_SPEECH_CAPABILITIES` (`:257-296`) — `stt="engine"`, `tts="engine"`, `llm="ours"`, `knowledge_base=False`, `number_series=frozenset()`, `transfer=True`, `in_call_handoff=False`, `script_override=False`, **`webhook_auth="hmac"`**.
- `EXTERNAL_DEPLOYMENT_CAPABILITIES` (`:322-351`) — all three legs `"engine"`, `agent_hosting="external_deployment"`, `knowledge_base=True`, everything else off, `webhook_auth="none"`.

Module constants: `FAKE_SIGNATURE_HEADER = "X-Calevate-Fake-Signature"` (`:359`),
`FAKE_WEBHOOK_SECRET` (`:360`), `SAMPLE_TURNS` (`:135-141`, five Telugu turns),
`_SAMPLE_LATENCY` (`:161-169`), `_COST_PER_MIN` (`:172-188`),
`FAKE_ENGINE_VOICES` (`:376-399`, four voices — two Bulbul, one `is_custom=True`, one
`sonic-3.5`, so both voice tiers and the cloned-voice clause have something to bite on),
`_STATUS_MAP` derived from `get_args(CallStatus)` (`:133`), `_StoredCall` TypedDict (`:95-122`).

### 5.2 Two private guards every method routes through

```python
def _assert_speech_is_ours(self, cfg: AgentConfig) -> None:      # :489-504
    require_speech_leg("stt", engine=self, value=cfg.models.stt_model)
    require_speech_leg("llm", engine=self, value=cfg.models.llm_model)
    require_speech_leg("tts", engine=self, value=cfg.models.tts_voice)
    if cfg.handoff is not None:
        require_capability("in_call_handoff", engine=self)

def _assert_this_engine_hosts_agents(self) -> None:              # :506-515
    require_capability("agent_hosting", engine=self)
```
**A new adapter should copy this shape**: capability checks are named private asserts
called at the top of the public method, never inlined conditions.

### 5.3 Method by method

| Method | Line | Implementation |
|---|---|---|
| `holds_credentials` | `:470-478` | `return True` — it IS its own vendor |
| `_stable_id(prefix, *parts)` | `:482-485` | `sha256(...)[:24]` — **deterministic handles**, which is what makes `test_create_and_update_agent_returns_a_stable_ref` measurable |
| `create_agent` | `:517-522` | hosts-agents guard → speech guard → `_stable_id("fakeagent", tenant_id, agent_id)` → store `cfg` |
| `update_agent` | `:524-527` | same two guards, overwrite `_agents[ref]` |
| `override_call_script` | `:529-555` | `require_capability("script_override")`; unknown ref → `ProblemError(code="engine_agent_missing")`; then `cfg.model_copy(update={"opening_line":…, "system_prompt":…})` — **only the two fields move**, which is what the "nothing else" half of the clause checks |
| `delete_agent` | `:557-581` | `self._agents.pop(ref, None)` + `self._kb.pop(ref, None)` — **idempotent because `pop` with a default is**; notably it does NOT take the hosting guard |
| `get_agent` | `:583-683` | hosts-agents guard; unknown ref → `ProblemError(code="engine_rejected")`. Returns `system_prompt=compose_engine_prompt(cfg)` (**the COMPOSED prompt, not `cfg.system_prompt` — this is what puts hard rule 5's floor in the read-back**), `greeting=cfg.opening_line`, KB handles from `_kb`, `handoff_destinations` gated on the capability, and a `ModelConfig` **rebuilt leg by leg through `self.capabilities.is_ours(leg)`** so a dictated leg reads back `None`. All four `*_readable` flags True except `handoff_destinations_readable=self.capabilities.in_call_handoff` |
| `start_outbound_call` | `:685-736` | `require_call_compliance_floor(engine=self, prompt_on_the_wire=ctx.system_prompt)` → `if ctx.from_e164: require_capability("caller_id")` → store the call with `context=ctx.model_dump()` and `system_prompt=ctx.system_prompt`. Returns a `_stable_id("fakecall", …)` |
| `call_prompt(call_id)` | `:738-757` | **Not on the Protocol** — a test affordance letting a clause prove the prompt actually reached the dial |
| `end_call` | `:759-784` | absent call → `ProblemError(code="engine_rejected")` (D-187: *this used to return None*). `PREVENTED` when the stored status was `queued`, else `ALREADY_RUNNING` |
| `transfer` | `:786-806` | `require_capability("transfer")`; absent call raises; records `transferred_to`/`transfer_warm` |
| `set_llm_credential` | `:808-841` | `require_capability("llm")`; empty secret → `ProblemError(kind="validation", code="engine_credential_empty")`; stores **per provider**; returns `LlmCredentialPlacement(replaced_in_place=True)` |
| `set_tts_credential` | `:843-869` | **Not on the Protocol** — the TTS twin, same shape |
| `provision_number` | `:871-918` | `capabilities.provisions(spec.series)` false → `require_capability("numbers")` first (so a no-numbers engine refuses on the capability) then a per-SERIES `engine_capability_absent`. `spec.e164` absent → `ProblemError.business_rule("number_not_chosen", …)`. Returns a `ProvisionedNumber` with `engine_number_ref`, prices, `engine_owned=True` |
| `search_numbers` | `:920-958` | `require_capability("numbers")`; mints three offers, skips ones already held, and **filters on `series_for_e164(e164) not in (None, PURCHASABLE_SERIES)`** so it can never offer a number the buy path would refuse |
| `release_number` | `:960-967` | `require_capability("numbers")`; `pop(..., None)` on BOTH `_numbers` and `_inbound` — absent is success |
| `list_engine_numbers` | `:969-971` | `require_capability("numbers")`; returns the store |
| `_number_key(number)` | `:984-1008` | `engine_number_ref` or **raise `ProblemError(code="engine_number_not_linked")`** — the named refusal `bind_inbound_number` owes a number the engine never heard of |
| `bind_inbound_number` | `:1010-1015` | `require_capability("inbound_binding")` → `_inbound[key] = ref`. Idempotent by assignment |
| `unbind_inbound_number` | `:1017-1022` | same guard → `pop(key, None)`. Absent is success |
| `inbound_agent_for(ref)` | `:1024-1026` | **Not on the Protocol** — test affordance |
| `_kb_handle(ref, kb_id)` | `:1036-1037` | `_stable_id("fakekb", ref, kb_id)` |
| `_claimed_source(kb_id)` | `:1039-1052` | `UUID(kb_id)` or `None` — how an account object carries OUR claim |
| `attach_kb` | `:1054-1081` | `require_capability("knowledge_base")`; replaces any same-`kb_id` entry; **also registers into `_account_kb`** with `state="ready"`, which is what makes `list_account_kb` able to see what `list_kb` cannot |
| `detach_kb` | `:1083-1103` | same guard; **if nothing was removed, RAISE `engine_rejected`**; removes from both `_kb` and `_account_kb` |
| `list_kb` | `:1137-1144` | same guard; handles derived from `_kb[ref]` |
| `list_account_kb` | `:1105-1115` | same guard; sorted by handle, `complete=True` |
| `list_voices` | `:1117-1135` | **`require_capability("tts")`** — refuses on a dictated-TTS engine; `EngineVoiceListing(voices=list(FAKE_ENGINE_VOICES), complete=True)` |
| `_cost_for(duration_s)` | `:1148-1174` | per-leg `Decimal` × minutes, quantized with `billing.rates.ROUNDING`; stamps `source_currency="INR"`, `source_amount=total`, `fx_rate=Decimal("1")` — **which is what satisfies `_assert_cost_is_re_derivable`** |
| `_snapshot_from(call_id, call)` | `:1176-1212` | `terminal = status in TERMINAL_STATUSES`, **`billable_ready = status == "completed"`** (strictly narrower than terminal, per §4's clause), cost and latency only when completed |
| `get_execution` | `:1214-1247` | absent → `ProblemError(code="engine_rejected", failure_stage="CORE_LOGIC")`. Attaches `raw_document=engine_document({"execution_id": call_id, **call}, engine=self.name)` via `model_copy` — **the D-126 archive** |
| `list_executions` | `:1249-1288` | filters `started_at >= since` (**the creation anchor, D-367**); at or under `listing_page_size` → `complete=True`; over → truncate and `complete=False, incomplete_reason="page_cap_reached"` |
| `verify_webhook` | `:1292-1330` | **Dispatches on `self.capabilities.webhook_auth`**, so one implementation serves all three profiles: non-`hmac` → `WebhookVerdict(ok=True, method=method, reason="fake engine")`; `hmac` → header absent → `ok=False, reason="signature header absent"`; mismatch under `hmac.compare_digest` → `"signature mismatch"`; else `ok=True` |
| `sign(body)` | `:1332-1335` | **Not on the Protocol** — HMAC-SHA256 hex, so the suite can construct a valid delivery |
| `parse_webhook` | `:1337-1350` | `_STATUS_MAP.get(status, "failed")` (**fail closed on the unknown**); reads `id`/`execution_id`, `agent_id`, `direction`, `from_number`, `to_number`, `recording_url`; `engine=self.name`. **Never sets `tenant_id`/`agent_id`** |
| `seed_inbound_call(...)` | `:1354-1375` | **Not on the Protocol** — how `saturated()` fills a listing |

`__all__` (`:1378-1386`) exports the three capability profiles, the signature header and
secret, `SAMPLE_TURNS` and `FakeEngine`.

### 5.4 What a new adapter should take from it
1. **Capability checks first, in a named private assert.** Every refusal goes through `require_capability` / `require_speech_leg` / `require_call_compliance_floor` from `engine/capabilities.py` — never a bare `raise` and never a silent drop.
2. **Compose, do not echo.** `get_agent` returns `compose_engine_prompt(cfg)`, and the read-back rebuilds `ModelConfig` through `is_ours(leg)` rather than handing back what it was given.
3. **Absent-is-success vs absent-raises is per method**, and the fake spells both: `pop(..., None)` for `delete_agent`/`release_number`/`unbind_inbound_number`, an explicit raise for `get_agent`/`get_execution`/`end_call`/`detach_kb`/`transfer`.
4. **Stamp the FX evidence at capture** — a `CostBreakdown` without `source_amount` and `fx_rate` type-checks and fails §4.
5. **Extra methods are fine and are clearly not the Protocol** (`call_prompt`, `sign`, `seed_inbound_call`, `inbound_agent_for`, `set_tts_credential`) — the Protocol is a floor, not a ceiling.

---

## 6. THE REGISTRY — `apps/api/engine/__init__.py` (175 lines)

*"Hard rule 2 in one sentence: everything else consumes the normalized models in
`calevate_shared` and reaches an engine through `get_engine()`, so swapping vendors is a
change in this directory and nowhere else. The import-linter contract in `pyproject.toml`
enforces it in CI"* (`__init__.py:1-19`).

### 6.1 Which `Settings` field names the engine

`Settings.engine: EngineName = "fake"` — `packages/shared/src/calevate_shared/config.py:361`.
Default `fake` *"so the whole pipeline runs offline (DEV-SETUP.md §3)"*.

`EngineName = Literal["fake", "bolna", "cartesia"]` — `config.py:85`. **THE ONE DEFINITION
OF WHAT `ENGINE=` MAY BE (D-103).** A `Literal` *"because pydantic validates the setting
against it and mypy checks every comparison against it, and neither can be done with a
runtime set."*
`SELECTABLE_ENGINES: frozenset[str] = frozenset(get_args(EngineName))` — `config.py:103`,
*"`get_args` on the Literal, never a second tuple beside it"*, and a `frozenset` so no
caller can mutate the answer another is about to read.

Per-engine credential settings live beside it: `bolna_api_key: str | None = None`
(`config.py:364`, with the note that Bolna webhooks are UNSIGNED so there is deliberately
no webhook secret), `cartesia_api_key` (`:368`), `cartesia_from_number_id` (`:373`, absent
⇒ outbound REFUSES rather than dialling from whatever number the vendor picks — *"a
promotional campaign leaving on a service-series number is a TCCCPR breach we would
discover from a complaint"*).

### 6.2 Selection and caching

```python
_instances: dict[str, VoiceEngine] = {}                              # :38

def build_engine(cfg: Settings) -> VoiceEngine:                      # :41-77
    name: EngineName = cfg.engine
    if name == "bolna":   ... BolnaEngine(api_key=cfg.bolna_api_key, fx_rate=cfg.usd_inr_rate)
    if name == "cartesia": ... CartesiaEngine(api_key=cfg.cartesia_api_key,
                                              from_number_id=cfg.cartesia_from_number_id)
    ... FakeEngine()                                                 # the fall-through

def get_engine(settings: Settings | None = None) -> VoiceEngine:     # :80-86
    cfg = settings or get_settings()
    name = cfg.engine
    if name not in _instances:
        _instances[name] = build_engine(cfg)
    return _instances[name]
```

- **`build_engine` is THE branch, and the only one.** Adapter imports are INSIDE the
  branches, so selecting `fake` never imports `httpx`-heavy vendor modules.
- **The cache keys on the engine NAME alone** (`:83-85`). That is right for the request
  path — *"one process serves one deployment, and `bolna_api_key` is classified
  `on_restart` precisely because the adapter copies it at construction"* — and WRONG for a
  caller that hands in a `Settings` it built itself, which would get back an adapter built
  from a different one and never know. That is why `build_engine` was split out (D-104);
  `runtime_config_missing_keys` is exactly that caller.
- **The `EngineName` annotation on `name` is load-bearing** (`:54-58`): it was widened to
  `str` while `cartesia` was missing from the Literal, and mypy's `warn_unreachable` now
  proves the `else` is reachable only by `fake` — *"so a name added to `EngineName` without
  a branch here is a type error rather than a silently-fake engine."*
- `reset_engine_cache()` (`:159-161`) — *"Tests switch engines between cases; production
  never calls this."*

### 6.3 Readiness

- `missing_engine_credential_keys(cfg) -> tuple[str, ...]` (`:89-112`) — builds an UNCACHED adapter from `cfg` and returns `()` if `holds_credentials()` else `adapter.credential_env_keys`. The defect it replaces (D-104): `runtime_config_missing_keys` carried `if cfg.engine == "bolna" and not cfg.bolna_api_key` in `core/settings.py`, so *"`/healthz/ready` was GREEN on a credential-less `ENGINE=cartesia` deployment: a box that cannot place a single call, reporting itself fit to take traffic."* Readiness needs the NAME, not just the verdict — *"'not ready' without the key an operator must set is a red light with no next step."*
- `all_credential_env_keys() -> tuple[str, ...]` (`:115-156`) — every env var ANY adapter reads a credential from, DERIVED: it builds `by_name = {adapter.name: adapter for adapter in (BolnaEngine, CartesiaEngine, FakeEngine)}` and **asserts `set(get_args(EngineName)) - set(by_name)` is empty**, so an engine added to `EngineName` without an adapter here is an `AssertionError`. It is keyed off each adapter's own `name` and **never a literal set of engine names** — the first draft wrote one and `tests/engine_name_drift_test.py` failed it immediately. Its one caller is `tests/conftest._no_ambient_credentials`. It needs no `Settings` and no constructed engine because `credential_env_keys` is a class-level attribute with a default on all three adapters.

### 6.4 The drift guard a new adapter must not trip

`tests/engine_name_drift_test.py` (`:1-110`) is an AST scanner, not a list of places to
check: *"A test that asserts `engine_intake.KNOWN_ENGINES == frozenset(WEBHOOK_AUTH_BY_ENGINE)`
pins the copy we know about. It says nothing about the copy somebody writes next month."*

- **TWO QUESTIONS, TWO HOMES** (`:17-30`): *which names may `ENGINE=` be* → `config.EngineName`/`SELECTABLE_ENGINES`; *which names have an authenticity story* → `engine.WEBHOOK_AUTH_BY_ENGINE`. The second is a superset; the gap is exactly the unselectable conformance fixtures. `test_every_selectable_engine_has_an_authenticity_story` keeps the containment, *"because the direction that hurts is the missing one: a selectable engine absent from the table is a deployment whose every webhook is answered `unknown engine`."*
- `CANONICAL_HOMES` (`:61-68`) — the only two files allowed to spell engine names in a collection. `SCANNED_TREES = ("apps", "packages/shared/src", "scripts")` (`:77`); `tests/` and `alembic/versions` are excluded, the latter because *"a migration is a historical record."*
- `KNOWN_OPEN_COPIES: dict[str, str] = {}` (`:91`) — **an equality assertion, not an exemption list**: adding a copy fails, and FIXING one fails too.
- `_literal_strings` (`:94-...`) flags tuple/list/set, dict keys, and `Literal[...]`. **A `==` comparison against ONE name is deliberately NOT flagged** — *"`apps/api/engine/__init__.py` is a factory and a factory must branch per engine."*

### 6.5 Exactly what a new adapter must register to become selectable

1. **The adapter module** in `apps/api/engine/` implementing all 25 methods plus `name`, `capabilities`, `credential_env_keys` — the last **annotated `tuple[str, ...]`**, or the class stops satisfying `VoiceEngine` (`bolna.py:3644-3647`).
2. **`EngineName`** — add the name to the `Literal` at `config.py:85`. `SELECTABLE_ENGINES` follows automatically, and so does `agents/models.ENGINES = tuple(sorted(SELECTABLE_ENGINES))` (`apps/api/agents/models.py:90`) which renders the `engine_enum` CHECK constraint at `:158`. **That constraint is a real migration**: D-103's `ENGINE=cartesia` failed client creation with an IntegrityError until `d7b1c48a2e93` widened it, so a new engine name needs a widening migration too.
3. **A branch in `build_engine`** (`__init__.py:41-77`) — mypy's `warn_unreachable` makes its absence a type error.
4. **Any credential `Settings` fields**, in `config.py` beside `bolna_api_key`/`cartesia_api_key`.
5. **`WEBHOOK_AUTH_BY_ENGINE[name]`** in `engine.py:345` — must equal `capabilities.webhook_auth` and what `verify_webhook` reports, or §4's clause fails. A selectable engine missing from this table answers every webhook `unknown engine`.
6. **`SOURCE_IP_ALLOWLIST_BY_ENGINE[name]`** in `config.py:1667` **if and only if** the method is `source_ip` — an absent entry REFUSES, with a distinct reason.
7. **`all_credential_env_keys`'s adapter tuple** (`__init__.py:150`) — otherwise the exhaustiveness assertion raises.
8. **`ENGINE_IDS` + a `make_engine` branch** in `packages/shared/tests/engine_conformance/conftest.py:59,975`, and — if it speaks HTTP — **a `TRANSPORT_RECIPES` entry** (`conftest.py:926`), because `test_every_adapter_that_speaks_http_is_held_to_the_transport_clauses` (`contract_test.py:2679`) refuses an opt-out.

---

## 7. CALLERS AND BLAST RADIUS

Every call site OUTSIDE `apps/api/engine/`, by protocol method. (`scripts/pilot/*` is the
OPERATIONS §2 pilot-gate harness — a real caller, and the only one that exercises
`verify_webhook`/`parse_webhook` outside the conformance suite.)

**Beware one false positive**: `apps/api/agents/routes.py:454`, `apps/api/copilot/agent_actions.py:203`
and `apps/api/copilot/adversarial_test.py:241` call `lifecycle.create_agent` / `lifecycle.update_agent`
— OUR row lifecycle, not the protocol. They are not engine calls.

| Method | Call sites |
|---|---|
| `create_agent` | `apps/api/agents/service.py:2181`, `:2444`; `scripts/pilot/gates_api.py:334`, `:603` |
| `update_agent` | `apps/api/agents/service.py:2178`, `:2441`; `scripts/pilot/gates_api.py:374` |
| `override_call_script` | `apps/api/agents/service.py:1628`, `:1950`; **`apps/workers/maintenance.py:362`** |
| `get_agent` | `apps/api/agents/verification.py:433`; `apps/workers/handoff.py:406`; `scripts/pilot/gates_api.py:274`, `:633` |
| `delete_agent` | `apps/api/agents/service.py:1113` (the orphan compensator — the only production caller); `scripts/pilot/gates_api.py:619`, `:648` |
| `start_outbound_call` | `apps/api/agents/service.py:2898` (inside `dispatch_call`, `:2772`); `scripts/pilot/gates_api.py:478`; `scripts/pilot/concurrency.py:802` |
| `end_call` | `apps/workers/dnc_recall.py:141`; `apps/workers/dial_recall.py:180`; `scripts/pilot/concurrency.py:833` |
| `transfer` | **NO CALLER IN THE TREE.** `BOLNA_CAPABILITIES.transfer=False`, so the console control was never built; the capability clause is what keeps it honest |
| `search_numbers` | `apps/api/campaigns/number_supply.py:104` (via `apps/api/admin/number_routes.py:201`); `scripts/pilot/gates_api.py:411` |
| `provision_number` | `apps/api/campaigns/number_supply.py:201` — **the only caller, and it takes an advisory lock plus a pre-check because the method is not idempotent** |
| `release_number` | `apps/api/campaigns/number_supply.py:317` (via `apps/api/admin/number_routes.py:354`) |
| `list_engine_numbers` | `apps/workers/number_rental.py:202` (`reconcile_engine_numbers`) |
| `bind_inbound_number` | `apps/api/agents/service.py:1269` |
| `unbind_inbound_number` | `apps/api/agents/service.py:1272`; `apps/api/campaigns/number_supply.py:316` (unbind-then-release, in that order) |
| `set_llm_credential` | `scripts/probe_bolna_providers.py:110` — **the only call site in the tree.** Its caller is now a person rotating a key, not a cron (D-410) |
| `attach_kb` | `apps/api/kb/service.py:1216`, `:1690`; `scripts/pilot/knowledge.py:390`, `:391`, `:579` |
| `detach_kb` | `apps/api/kb/service.py:1166`, `:1260`; `scripts/pilot/knowledge.py:524`, `:538`, `:580` |
| `list_kb` | `apps/api/kb/service.py:1077`; `apps/workers/kb_reconciliation.py:262`; `scripts/pilot/knowledge.py:403`, `:404`, `:594` |
| `list_account_kb` | `apps/workers/kb_orphans.py:75` — the only caller; it cross-checks our claim rows and REPORTS. **Nothing deletes on its strength** |
| `list_voices` | `apps/api/agents/voice_sync.py:251`; `apps/api/agents/voice_admission.py:275` (via `apps/workers/voice_catalogue.py:88`) |
| `get_execution` | `apps/workers/pipeline.py:472`, `:1081`, `:3609`, `:3829`; `apps/workers/callbacks.py:90`; `apps/workers/handoff.py:521`; `apps/workers/optout.py:86`; `scripts/pilot/gates_api.py:490`, `:819`; `scripts/pilot/fidelity.py:451` |
| `list_executions` | `apps/workers/pipeline.py:3961` (the reconciliation poller); `scripts/pilot/gates_api.py:1193` |
| `verify_webhook` | `scripts/pilot/gates_api.py:720`, `:739`, `:758` **only** — see §8 for why voice-runtime does NOT call it |
| `parse_webhook` | `scripts/pilot/gates_api.py:808`, `:894` **only** — same reason |
| `holds_credentials` | `apps/workers/dial_recall.py:146`; `apps/workers/engine_violations.py:138`; plus `apps/api/engine/__init__.py:111` |

### 7.1 By module

**`apps/api/agents/service.py`** (being edited concurrently — line numbers may have moved)
is the single densest caller: `create_agent`/`update_agent`/`delete_agent`,
`override_call_script`, `bind_inbound_number`/`unbind_inbound_number`, and
`start_outbound_call` inside `dispatch_call` (`:2772`). Two structural facts:
- **`agents/service.py::in_call_llm` is the ONE place the in-call LLM leg is decided for an agent**, and `_call_prompt_for` (`:1026`) is the one place the per-call prompt decision is made — from `capabilities.hosts_agents()`, the same expression the conformance fixture uses.
- `DIAL_NOT_PLACED_CODES` (`:202`, exported `:3507`) is the set of failure codes meaning *no line was seized*, so the contact keeps its place on the retry ladder. `ENGINE_COMPLIANCE_FLOOR_ABSENT` is a member because it raises before any HTTP request leaves the process.
- `engine` is passed as a PARAMETER rather than re-fetched inside (`:912`), for `engine_capabilities`' reason — a second `get_engine()` is a second read that can disagree.

**`apps/api/campaigns/`** (concurrently edited) touches the port in exactly one module,
`number_supply.py`: `search_numbers` (`:104`), `provision_number` (`:201`),
`unbind_inbound_number` (`:316`) then `release_number` (`:317`). The campaign DISPATCH path
reaches the engine only through `agents.service.dispatch_call`.

**`apps/api/compliance/`** (concurrently edited) **calls no protocol method at all.** Its
only contact with the port is a type import: `caller_data_routes.py:72` imports
`CALLER_MEMORY_VARIABLE` and `render_caller_memory` from `calevate_shared.engine`. The
compliance gate operates on OUR rows (`phone_numbers.series`, `dlt_status`, the DNC
ledger); the engine learns its outcome only by being dialled or not.

**`apps/api/kb/service.py`** owns the whole KB seam: `list_kb` (`:1077`), `detach_kb`
(`:1166`, `:1260`), `attach_kb` (`:1216`, `:1690`). It reads the process-wide `get_engine()`
(`:625-637`) rather than `agents.engine`.

**`apps/workers/`** is where the read paths live: `pipeline.py` (`get_execution` ×4,
`list_executions`), `callbacks.py`, `optout.py`, `handoff.py` (`get_agent` + `get_execution`),
`kb_orphans.py` (`list_account_kb`), `kb_reconciliation.py` (`list_kb`),
`number_rental.py` (`list_engine_numbers`), `dnc_recall.py` / `dial_recall.py` (`end_call`),
`maintenance.py` (`override_call_script`), `voice_catalogue.py` (`list_voices`),
`engine_reconciliation.py`, `engine_violations.py`.
`apps.workers.pipeline.TRANSIENT_ENGINE_CODES` reads `engine_rate_limited` and
`engine_unreachable` **by name** — which is why §4's transport-ladder clauses exist.

**`apps/voice-runtime/`** calls **NO protocol method**. Its single import from the port is
`from calevate_shared.engine import WEBHOOK_AUTH_BY_ENGINE, WebhookAuthMethod`
(`engine_intake.py:22`), plus `SOURCE_IP_ALLOWLIST_BY_ENGINE` from `calevate_shared.config`
(`:21`). **That is hard rule 3 made structural**: the ack path may not take the heavy
import, so the receiver reads the DATA TABLE the adapters are checked against instead of an
adapter. See §8.

**Blast radius summary.** Adding an adapter touches: `apps/api/engine/` (the new module +
`__init__.build_engine`), `calevate_shared/config.py` (`EngineName`, credential fields,
`SOURCE_IP_ALLOWLIST_BY_ENGINE`), `calevate_shared/engine.py` (`WEBHOOK_AUTH_BY_ENGINE`), one
alembic migration (the `engine_enum` CHECK), and the conformance `conftest.py`. **No
business module changes** — every caller above goes through `get_engine()` and the
normalized types. That property IS the port's purpose, and §4 is what proves it still holds.

---

## 8. WEBHOOK INTAKE

### 8.1 `apps/voice-runtime/engine_intake.py` (374 lines) — the "voice-runtime twin"

*"Deliberately tiny. The receiver has one job — decide whether an event is authentic and
what its dedupe key is — and hard rule 3 forbids paying for anything else on this path: no
HTTP client, no cost arithmetic, no transcript parsing, no ORM… The payload is a HINT
(D-31); the worker's authenticated Get Execution is the truth"* (`engine_intake.py:1-11`).

**It imports no adapter.** Its only port imports are `WEBHOOK_AUTH_BY_ENGINE` and
`WebhookAuthMethod` (`:22`) and `SOURCE_IP_ALLOWLIST_BY_ENGINE` (`:21`) — *"reaching
`EngineCapabilities` through `apps.api.engine` would pull httpx and the vendor client into
the ack path"* (`:135-138`).

Surface:
- `KNOWN_ENGINES: frozenset[str] = frozenset(WEBHOOK_AUTH_BY_ENGINE)` (`:74`). **`WEBHOOK_AUTH_BY_ENGINE` and not `SELECTABLE_ENGINES`**, because the question is *"does this name have an authenticity story"*, not *"may an operator select it"* — `fake-restricted` is the case that separates them. What the set BOUNDS is *"anything the URL's `{engine}` segment is allowed to become — a metric label, in particular."* This file used to define its own `EngineName = Literal["bolna", "fake"]`, which drifted when `cartesia` landed (D-103).
- `engine_label(engine) -> str` (`:93-95`) — `engine` if known else `"unknown"`. It exists because the URL segment is **an unauthenticated stranger's string on every refusal path**: measured, *"414 characters of attacker-chosen text, newline included, on `calevate.alert`'s record, at request rate, from any source address."*
- `IntakeVerdict` (`:98-106`, frozen slots) — `ok: bool` · `method: WebhookAuthMethod` · `reason: str | None = None`. **It reuses `WebhookAuthMethod` rather than a local Literal** — *"Two spellings of one vocabulary is how the receiver ends up reporting a method the adapter cannot express."*
- `IntakeEvent` (`:109-115`, frozen slots) — `execution_id: str` · `raw_status: str` · `engine_agent_ref: str | None`. **Three fields, and it refuses to interpret the rest.**
- `verify_source(engine, source_ip) -> IntakeVerdict` (`:118-201`).
- `_MAX_KEY_FIELD = 128` (`:212`) and `_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")` (`:217`) — the ceiling is NOT cosmetic: both fields are concatenated into `webhook_inbox_events.event_key` under a UNIQUE btree index, so an over-long value makes Postgres answer *"index row size N exceeds btree version 4 maximum"* and the ack becomes a 500. *"At an endpoint whose vendor delivers at-most-once and never retries (D-31), that 500 is a lost call."*
- `_keyable(value)` (`:230-243`) — strips surrounding whitespace rather than rejecting it, because `"exec_1 "` and `"exec_1"` were **two units of work for one transition** — two inbox rows, two jobs, a pipeline run twice on a call whose `usage_events` are append-only (hard rule 4, *"where a double charge is uncorrectable by construction"*).
- `scalar_hint(value)` (`:246-...`) — **NOT `str(value)`.** `str()` is total, so `{"code": 3}` became the raw_status `"{'code': 3}"` in a dedupe key, an ARQ job id and `webhook_deliveries.event_type`, and on the tool route the same input became the words a caller used to withdraw consent, in the append-only `consent_ledger`. Accepts `str`, `int`, `float`; **refuses `bool`** (*"`status: true` is not the status `\"True\"`"*); no recursion, no allocation on a container.
- `_EXECUTION_ID_FIELDS = ("execution_id", "id", "call_id")` (`:~280`) and `execution_key(payload)` — **each spelling is TRIED**, not `a or b or c` then one type check, which answered `unkeyable` for `{"execution_id": 12345, "call_id": "exec_abc"}`.
- `extract(payload) -> IntakeEvent | None` — returns `None` when no keyable execution id. An unreadable STATUS is treated as ABSENT (`"unknown"`), not as a refusal; an implausible `agent_id` is dropped and the event still flows, *"otherwise a junk field could suppress a real call's event entirely."*

### 8.2 What `WEBHOOK_AUTH_BY_ENGINE` and `SOURCE_IP_ALLOWLIST_BY_ENGINE` require

`verify_source` (`engine_intake.py:140-201`) is a total dispatch on
`WEBHOOK_AUTH_BY_ENGINE.get(engine)`:

| Declared method | Behaviour |
|---|---|
| `"source_ip"` | Looks up `SOURCE_IP_ALLOWLIST_BY_ENGINE.get(engine)`. **A missing resolver REFUSES** (`reason="no source ip allowlist for this engine"`) and does NOT fall back to the one entry that exists — *"a second such engine would have been authenticated against Bolna's egress… inert today, which is exactly why it was invisible."* Otherwise `source_ip in resolver(get_settings())` → `ok=True, method="source_ip"` — **still reported as `source_ip`, never `hmac`: the caller must keep treating it as a hint.** Two distinct failure reasons, `"source ip not allowlisted"` (a vendor renumber → rotate `BOLNA_WEBHOOK_SOURCE_IPS`) vs `"client ip not established"` (the EDGE is broken) — *"Two very different runbook entries, and an unsigned engine cannot afford them to look alike."* |
| `"hmac"` | **ALWAYS REFUSES**: `reason="signature verification not implemented"`. Declared by an adapter, not implemented here, and refused rather than waved through. *"The previous comment here said this was unreachable — 'no signing engine is selectable as `ENGINE=`' — and that stopped being true when D-93 put `cartesia` in `config.EngineName`."* `CartesiaEngine.verify_webhook` fails closed for the identical reason, *"so the receiver and the adapter refuse together rather than one of them deciding to be helpful."* **Why the refusal must outlive the temptation to soften it**: `webhook_routes` derives `signature_valid` from `verdict.method == "hmac"`, so a wave-through *"would not merely accept a forgery — it would FILE one as signed."* Cost of refusing is bounded (401s, the 10-minute poller stays the guarantee of record); the other direction is not bounded at all |
| `"none"` | Open **only where that engine IS this deployment's engine**: `if get_settings().engine == engine`. Matched against the declared method and the requested name, never the literal `"fake"` — otherwise, on a prod box running `ENGINE=bolna`, `/hooks/v1/engine/fake` would hand any stranger an inbox claim, a forensic row and an ARQ job |
| absent | `IntakeVerdict(ok=False, method="none", reason="unknown engine")` |

The allowlist is enforced **at nginx AND here** — *"nginx config drifts, this does not"*
(`engine_intake.py:26-27`). The SET is not defined in this file: it resolves through
`calevate_shared.config.bolna_source_ips`, the ONE resolver the adapter's `verify_webhook`
also reads, so an operator rotating the variable during a renumber moves both answers
together. Resolution stays O(1) per delivery (`get_settings` and the parse are both cached).

### 8.3 `apps/voice-runtime/webhook_routes.py` (934 lines) — the request path

Route: `@router.post("/engine/{engine}", status_code=202, response_model=WebhookAckOut,
response_model_exclude_none=True)` (`:641-650`), wrapped by `measured(...)` (`:328`) so every
exit — including a raised refusal — is metered.

1. **Step 1 — WHO** (`:669-684`). `client_ip(request.client.host, request.headers, app_env=...)` then `verify_source(engine, source_ip)`. **It reads no body**: *"on a public, unsigned endpoint that ordering is the difference between a rejection and a memory-exhaustion primitive."* On refusal it alerts `webhook_source_rejected` with `engine=engine_label(engine)` (bounded) and `source_ip` (included deliberately — *"the vendor renumbers, every webhook starts 401ing… an alert that says only 'not allowlisted' leaves the operator running tcpdump"*; a machine caller's address is not PII under hard rule 6 and never appears in the response body), then raises `ProblemError.unauthorized`.
2. **Step 2 — RAW BYTES**, bounded, `_read_bounded` (`:535`), read once and never re-parsed downstream. *"An engine that does [sign] will need the exact bytes (its signature check belongs right here, as a SECOND gate after the source check), and retro-fitting raw-body preservation into a live receiver is miserable."* Over-size → alert `webhook_payload_too_large` + 413.
3. **Step 3 — PARSE DEFENSIVELY** (`:713-727`). `json.loads` catches `(ValueError, RecursionError)`; a non-dict document is `readable=False`. *"Bolna delivers at most once and swallows errors, so a receiver that crashes on one hostile POST is indistinguishable from one that crashes on the real call arriving in the same second."*
4. **Step 4 — `extract(payload)`** (`:728`). `None` → **ACK ANYWAY** with `{"status":"ignored","reason":"unusable execution key" | "unreadable payload"}` and alert `webhook_unkeyable`; the poller picks the call up. The reason string does not distinguish the two cases *"on purpose: it is read by the vendor's logs."*
5. **Step 5 — fast-path dedupe** (`:750-757`): `redis_key = f"calevate:wh:{engine}:{event.execution_id}:{event.raw_status}"` plus a body digest → `{"status":"duplicate", …}`.
6. **Step 6 — `_claim_and_enqueue(engine, event, signed=verdict.method == "hmac")`** (`:766`, `:838-931`), ONE transaction: `claim_inbox_event(provider=engine, …)`, then the forensic `webhook_deliveries` row (`direction='in'`, `source=engine`, `event_type=event.raw_status`, **`signature_valid=signed`** — *"records what evidence we actually had, so a later investigation can tell an IP-allowlisted event from a signed one"*), then `enqueue(INGEST_JOB, {...}, job_id=job_id_for(INGEST_JOB, engine, execution_id, raw_status))`, then `mark_inbox_enqueued`.

**THE UNIT OF WORK IS THE TRANSITION, NOT THE EXECUTION** (`:860-870`). Bolna fires one
webhook per status change with the same execution id; keying the inbox on the execution
alone meant the FIRST transition claimed and enqueued and `completed` — *"the only
transition where cost, recording and transcript exist"* — came back `duplicate` and
enqueued nothing.

**Nothing on this path calls `parse_webhook`.** The normalized `CallEvent` is produced
later, in the worker, from the AUTHENTICATED `get_execution` read. The receiver forwards
only `{engine, execution_id, raw_status, engine_agent_ref, inbox_row_id}`.

### 8.4 ⚠ Pipecat: what has no counterpart here

**Pipecat is a framework WE run, not a vendor that calls us.** Under it there is no
third-party origin, no vendor egress, no vendor payload, and no vendor-owned execution
record. Almost everything in §8.1-8.3 exists to defend a boundary that no longer exists —
and the parts that survive change owner, not shape.

| Intake element | Under a framework we run |
|---|---|
| `verify_source` / `WEBHOOK_AUTH_BY_ENGINE` / `SOURCE_IP_ALLOWLIST_BY_ENGINE` | **NO COUNTERPART.** There is no external caller to authenticate. What replaces it is ORDINARY SERVICE-TO-SERVICE AUTH between our own processes — a first-party credential, not an allowlist — and the honest declaration for such an adapter is a NEW `WebhookAuthMethod` member (the file already contemplates one: *"If the scheme turns out to be a shared secret, a `shared_secret` member lands in `WebhookAuthMethod` and in both halves together"*, `engine.py:382-385`). **Declaring `"none"` would be wrong**, because `"none"` currently means *"the fake engine, unauthenticated by design"* and is gated on `get_settings().engine == engine` |
| `verify_webhook` / `WebhookVerdict` | **NO COUNTERPART as authentication.** `signature_valid` in `webhook_deliveries` becomes meaningless or always-true; the forensic distinction it records (IP-allowlisted vs signed) has no third term for "we generated this ourselves" |
| `parse_webhook` | **NO COUNTERPART.** There is no vendor payload shape to normalize. The runtime EMITS `CallEvent` directly, because `calevate_shared.events` is already our vocabulary. The isolation boundary the method names has nothing on its far side |
| `extract`, `scalar_hint`, `_keyable`, `_MAX_KEY_FIELD`, `_CONTROL_CHARS`, `_EXECUTION_ID_FIELDS` | **MOSTLY NO COUNTERPART, and this is the subtle one.** Every one of them defends against a payload we did not author — three spellings of an id because the shape is unverified, a control-character filter because the field is a stranger's, a length ceiling because a btree index will 500. When WE mint the execution id, it is a uuid_v7 by construction and the three spellings collapse to one. **What must NOT be dropped is the dedupe**: the reason `_keyable` strips whitespace is that two spellings of one transition double-metered an append-only ledger, and that hazard is about OUR retry behaviour, not the vendor's |
| The at-most-once / no-retry premise (D-31) | **INVERTED.** The whole "ack anyway, alert, let the poller be the truth" posture exists because Bolna delivers once and swallows errors. A transport we own can retry, so a failure can be a real failure rather than a lost call — **but the inbox claim and the transition-keyed job id must stay**, because retries make duplicates MORE likely, not less |
| `list_executions` + the reconciliation poller | **THE BIGGEST CHANGE, and the one that needs a deliberate decision rather than a default.** D-31 promotes the poller from safety net to *guarantee of record* precisely because the vendor's own listing is an independent authority we can reconcile against. Under a framework we run, our database IS the record: a poller that reads our own store and compares it with our own store is *"asking the code whether it agrees with itself."* Either the runtime keeps its own durable execution store (and `list_executions`/`get_execution` read THAT, preserving the property), or the guarantee of record moves and D-31's argument has to be re-made |
| `get_execution.raw_document` | **CHANGES MEANING.** *"The document is the VENDOR'S, not a re-rendering of the snapshot above"* — under a framework we run there is no vendor document. An adapter that serialized its own `ExecutionSnapshot` there is exactly what the clause forbids, so either the runtime archives a genuinely lower-level artefact (the raw pipeline trace / turn log) or the field is honestly `None` and **`calls.engine_payload_ref` plus `retention._erase_engine_payloads` must be reconsidered rather than left pointing at nothing** (the D-126 state this clause exists to keep closed) |
| `engine_label`, the metric-label bound, the alert bound, `_read_bounded`, the defensive `json.loads` | **STILL REQUIRED IF THE ENDPOINT IS HTTP AT ALL**, but their threat model shrinks from "a stranger who found the URL" to "our own process misbehaving". They are cheap and should not be removed on the strength of the shrink |
| voice-runtime's 500ms ack budget and hard rule 3 | **UNCHANGED, AND MORE BINDING.** Under a rented engine the latency-critical work happens at the vendor; under a framework WE run, the in-call pipeline is ours, which is exactly what `apps/voice-runtime` was isolated for |

---

## 9. WHAT IS BOLNA-SHAPED

The port already asks this question of itself. TRD §10.5 opened by asking whether this
contract is vendor-neutral or merely Bolna-shaped *"and answered itself: 'those look
identical while only one vendor exists'. It is Bolna-shaped, and the shape is not a field
name — it is the ASSUMPTION that an engine will host an agent of ours at all"*
(`engine.py:74-82`). D-280 fixed one axis of that (`AgentHosting`). This section names the
rest, on the premise of a **framework WE run** (e.g. Pipecat): our process, our pipeline,
our vendor accounts on each leg.

The unifying test: **a method is Bolna-shaped when its contract is a defence against a
third party who might not have done what we asked.**

### 9.0 The headline: `AgentHosting` has no member for this shape

`AgentHosting = Literal["control_plane", "external_deployment"]` (`engine.py:101`) is a
two-valued answer to *where an agent comes from*:
- `control_plane` — **the ENGINE holds an agent object we create over ITS OWN API**, and the prompt is agent-record state `get_agent` reads back.
- `external_deployment` — **the agent is a program deployed OUTSIDE this system** and the engine can only observe it; the prompt rides `CallContext.system_prompt` per dial.

A framework we run is **neither**. We hold the agent record AND we run the program. Both
existing members are wrong in a way that matters:
- Declaring `control_plane` makes `get_agent` a read-back of our own configuration — which is exactly the defect its docstring forbids: *"An adapter that echoes back the config it was last handed satisfies every naive test and measures nothing: it agrees with the caller by construction"* (`engine.py:4692-4695`). Gate 2's whole property (APPLIED, not merely ACCEPTED) becomes unfalsifiable.
- Declaring `external_deployment` makes `create_agent`, `get_agent` and `publish_agent` refuse (`engine.py:83-91`), so **nothing would ever be recorded `live`** — and the reason given (*"there is no agent record to write and no read-back to prove"*) is false of a framework we run.

**A third member is the honest answer** — and by the file's own standard it *"should come
WITH the adapter that emits it"* (`engine.py:4305-4307`, the `ListingIncompleteReason`
argument). It also has to say what replaces the read-back, which is §9.2.

### 9.1 Methods that become a no-op or a named refusal

| Method | Why it is Bolna-shaped | What it becomes |
|---|---|---|
| `set_llm_credential` | Its entire purpose is **pushing OUR key into THE ENGINE'S credential store** — *"which entry name the engine's own store keeps it under is the adapter's business… Bolna alone wants four entries for Azure and one each for the other two"* (`engine.py:4984-4986`). `LlmCredentialPlacement.replaced_in_place` / `superseded_removed` exist only to describe a foreign store that might APPEND BESIDE rather than replace (`engine.py:4554-4565`) | **NO-OP / REFUSAL.** A framework we run reads its keys from our secrets manager at process start. There is no second store to supersede. Note the gate is `capabilities.is_ours("llm")`, which would be TRUE here — so the existing gate gives the WRONG answer and the refusal needs a different ground |
| `attach_kb` / `detach_kb` / `list_kb` / `list_account_kb` | The engine holds account-level documents (Bolna's `rag_id`). `list_account_kb` exists because *"on an engine whose knowledge base is an account-level object with no owner field, such an object is billed for as long as the account exists and holds a client's document… with nothing anywhere saying whose it is"* (`engine.py:5100-5105`). The `agent: AgentConfig \| None` parameter on both (D-488) is a **pure artifact of Bolna's `PUT /v2/agent/{id}` replacing the whole object while `PATCH` ignores `tasks`** | **`knowledge_base=False` and all four refuse by name.** Retrieval is already ours in the dashboard/CRM paths (D-502, pgvector in the Postgres we already run). The orphan hunt becomes a SQL query, not a vendor listing — and a `list_account_kb` over our own store *"would be asking the code whether it agrees with itself"*. ⚠ **BUT `tests/kb_tiers_test.py` pins voice-runtime's route inventory as an EQUALITY and CLAUDE.md says in-call retrieval is T0, the engine's own KB, and MUST NOT change** — so moving T0 is a decision, not a consequence |
| `search_numbers` / `provision_number` / `release_number` / `list_engine_numbers` | Bolna RESELLS telephony. `ProvisionedNumber.engine_owned` is literally *"Bolna's `bolna_owned` / `rented`"* (`engine.py:3517-3520`), and `provision_number` *"SPENDS REAL MONEY AND IS NOT IDEMPOTENT"* because their buy endpoint has no client-supplied key | **`number_series=frozenset()` and all four refuse** — the answer Bolna itself already gives today (`BOLNA_CAPABILITIES.number_series = {"standard"}` is the exception, D-05 says our numbers come from the telephony vendor directly). We would hold the carrier account, so `engine_owned` has no meaning and `monthly_rental_usd` is billed to us by the carrier, not by the engine |
| `override_call_script` | Justified entirely by the cost of Bolna's full replacement: *"Doing it through the full-replacement write would mean sending a whole agent body twice per window per agent, with the KB-preservation read that write needs"* (`engine.py:262-266`) | **Trivially `script_override=True`, and the method collapses into `update_agent`** — writing two columns in our own row costs nothing. The narrow method becomes the second way to do one thing that the quality bar forbids; keeping it is a deliberate choice, not a default |
| `transfer` | Already has NO caller in the tree and `BOLNA_CAPABILITIES.transfer=False` | **Becomes genuinely implementable** (a control-plane command against a pipeline we own), so `transfer=True` is the first honest True this field has ever carried — and §4's clause is then exercised for the first time |
| `parse_webhook` / `verify_webhook` / `WebhookVerdict` | §8 | **No counterpart.** The runtime emits `CallEvent` directly |

### 9.2 Methods whose CONTRACT survives but whose EVIDENCE CLASS collapses

This is the dangerous category: they keep working and stop meaning anything.

- **`get_agent` / `AgentSnapshot` / the five `*_readable` tri-states.** The read-back exists for two promises (`engine.py:4676-4687`): APPLIED-not-ACCEPTED, and D-41's dangling handle. Both are about **a third party's state diverging from our record** — `handoff_destinations` is read back specifically because *"the engine's console offers the same tool as a form anybody with a login can fill in, which is precisely the class of change a read-back sees and a request body cannot"* (`engine.py:3182-3186`), and `greeting` exists because `verification.judge` was computing `disclosure_applied` *"against the prompt OUR OWN adapter had just prepended the line to — so the one property OPERATIONS §7 calls 'the one with a legal consequence' was true by construction of our own string formatting"* (`engine.py:3161-3167`). **Under a framework we run there is no console, no second writer, and no independent copy — so a read-back reproduces exactly that defect.** All five `*_readable` flags become permanently, uselessly True. `alternate_prompts` (Bolna's multi-task per-language prompts) has no referent at all.
  **What replaces it:** hard rule 5 stops being VERIFIED and starts being STRUCTURAL — one composer (`compose_engine_prompt`), one path to the pipeline, and `check_compliance_invariants` reading the composer. The port already states this pattern for `override_call_script`: *"the composed script carries the truthful-answer directive… and `check_compliance_invariants` reads the composer, not this signature"* (`engine.py:4667-4669`). **That is a genuinely stronger guarantee than a read-back, but it is a DIFFERENT guarantee, and OPERATIONS §2 gate 2 and `agents/verification.py:433` both have to be re-aimed rather than quietly passing.**
- **`ExecutionListing.complete` / `incomplete_reason` / `pages_fetched` and the whole `ListingIncompleteReason` vocabulary.** Every member describes walking a VENDOR's paginated listing: `explicit_more`, `full_page_suspected`, `page_cap_reached`, `next_link_no_progress`, `partial_fan_out` (`engine.py:4265-4289`). Over our own store a listing is one query and completeness is knowable, so `complete=True` always and **the entire Literal becomes unreachable vocabulary — precisely what D-365 deleted two members for** (*"a value no adapter can emit is a runbook entry for an event that cannot happen"*). The poller's alert has nothing left to fire on.
- **`list_executions(since=…)` and the reconciliation poller.** D-31 promotes the poller from safety net to **guarantee of record** because the vendor's listing is an INDEPENDENT authority. Under a framework we run, our database is the record; a poller reading our store and comparing it with our store is self-agreement. Either the runtime keeps its OWN durable execution store that `get_execution`/`list_executions` read (preserving the independence), or **D-31's argument must be re-made, not inherited.** The `since` anchor (D-367, creation not completion) is a vendor-listing artifact and becomes a free choice.
- **`ExecutionSnapshot.billable_ready` / `billable_ready_at`.** These exist because *"Bolna's cost/recording/transcript are null until `completed` (~2-3 min after disconnect). A pipeline that triggered on 'terminal' would meter zeros"* (`contract_test.py:848-851`). In our own runtime everything exists at hang-up, so `billable_ready == terminal` — the field is vacuous, the clause still passes, and nothing warns you it stopped measuring anything.
- **`raw_status`.** *"The vendor's own string"* — under our runtime it equals `status`, which is exactly what `FakeEngine._snapshot_from` already does (`fake.py:1190-1191`).
- **`end_call` → `RecallOutcome`.** The three-valued return and the `UNKNOWN` escape hatch exist because Bolna's route *"stops a call that has not started"* and `_STATUS_MAP` folds their `stopped` into our `failed` (`engine.py:4801-4809`). **A pipeline we own knows whether it was ringing or connected**, so `PREVENTED`/`ALREADY_RUNNING` become determinable and `UNKNOWN` should never be returned. The DNC path's evidentiary need is fully met for the first time.
- **`engine_agent_ref` / `CallHandle` as opaque vendor strings**, and the `engine_agent_routes` table that maps `engine_agent_ref → (tenant, agent)` so an incoming webhook can be attributed (`agents/service.py:1182`, `:2271`). With no incoming webhook and ids we mint, **the attribution table is redundant** — tenancy is known at dial time. It is also a tenant-scoped table under hard rule 1, so removing it is a migration with an RLS story, not a deletion.

### 9.3 Types whose shape is Bolna's, not the domain's

- **`CostBreakdown` and hard rule 7's producer.** The type models *"the vendor's quote in transit"* (`engine.py:3505-3507`): ONE vendor total in ONE `source_currency` (default `"USD"`) with ONE `fx_rate`, plus `currency_stated` to record whether the PAYLOAD named the currency. Under a framework we run **there is no single vendor total at all** — cost is the sum of our own per-leg bills (Sarvam characters, Cartesia characters, Azure/OpenAI/Google tokens, carrier minutes), each from a different vendor, several in different currencies, and all computed BY US rather than reported. `total_inr` becomes derived, `currency_stated` is meaningless (we are the payload), and `fx_rate` is per leg. §4's `_assert_cost_is_re_derivable` would still pass on a single synthesised rate while measuring nothing. **This is the most load-bearing change in the whole section, because hard rule 7 governs `unit_cost_paid` and `usage_events` is append-only — a wrong cost cannot be corrected, only compensated.**
- **`ExecutionSnapshot.engine_extracted: dict[str, Any]`** — the VENDOR's own extraction pass. No counterpart; our extraction is `apps/workers/extraction.py` and stays on Sarvam by decision.
- **`AgentConfig.webhook_url` and `action_tools` (`ActionToolSpec.url`, `method: Literal["POST"]`, `ActionToolParam.fill="ai"|"context"`)** — these describe a REMOTE engine calling back into `apps/voice-runtime/tool_routes.py` over HTTP. In-process, a tool is a function call. The `url`/`method` fields become an internal dispatch key or dead. ⚠ **The 100ms in-call RAG budget is the reason this seam exists at all** (CLAUDE.md: *"except the in-call RAG tool endpoint which has a 100ms budget — measure it"*), and in-process it gets easier, not harder — but `tests/kb_tiers_test.py`'s route-inventory equality is what would fail first.
- **`AgentConfig.knowledge_base_ref`, `AgentSnapshot.knowledge_base_refs`, `EngineKBRef`** — the engine names its copy, we do not (`engine.py:33-37`, `engine.py:5030-5033`). With our own store we name the copy, and the whole handle-round-trip disappears.
- **`ModelConfig.llm_traps` / `engine/bolna.py::_llm_trap_settings`** — the traps exist because THE ENGINE builds the request and sends `temperature: 0.1` unconditionally. In-process we build the request, so the traps are still REAL (a GPT-5 model still rejects it) but they stop travelling through an agent config and belong to our own client.
- **`ModelConfig` as a whole, and `SpeechControl`.** `"ours"` means *"our provider and model strings reach the vendor and run on OUR key"* (`engine.py:47-50`). Under a framework we run, every leg is ours by construction and `SpeechControl` stops discriminating — its whole job is to describe what a VENDOR dictates.
- **`EngineVoiceListing` / `list_voices`.** The method exists because *"THE CATALOGUE IS THE ENGINE'S, NOT THE MODEL VENDOR'S, AND THAT DISTINCTION IS A LIVE 400"* — the engine's Sarvam provider offers a narrower subset than Sarvam's SDK enum (`engine.py:5117-5123`). **Calling Sarvam and Cartesia directly deletes the distinction and the 400 with it.** The method does NOT become a no-op though: cloned voices still exist nowhere in our source, so it becomes a call to each TTS vendor's own list endpoint, fanning out across two vendors — which is exactly the `partial_fan_out` condition, on the one listing type (`EngineVoiceListing`) that has no `pages_fetched`.
- **`HandoffLeg.cost_reported` / `recording_present`** — both are hedges about what a vendor's payload happened to include.
- **`holds_credentials() -> bool` and `credential_env_keys`.** The doc says *"Empty for an adapter that IS its own vendor"* (`engine.py:4579`), which is `FakeEngine`. A framework we run is ALMOST that case but needs the DOWNSTREAM keys (STT, TTS, LLM, carrier) — so `credential_env_keys` grows to four or more vendors and **a single boolean loses the resolution readiness needs**: *"an engine with a built-in knowledge base and no API key still has a built-in knowledge base"* generalises to "an engine that can transcribe and cannot synthesise", which this signature cannot say.

### 9.4 What survives intact, and is therefore the real port

These are the parts that are about the DOMAIN rather than about a vendor, and a second
adapter should treat them as fixed:

- `CallEvent`, `TranscriptTurn`, `CallStatus`, `CallDirection`, `TERMINAL_STATUSES` (`events.py`) — our vocabulary already.
- `AgentConfig`, `DisclosurePosture`, `compose_engine_prompt`, `compose_opening_line`, `carries_truthful_answer_floor`, `TRUTHFUL_ANSWER_MARKER` — hard rule 5's machinery, which gets STRONGER in-process.
- `CallContext` (minus the `control_plane`/`external_deployment` split on `system_prompt`) — `from_e164`, `caller_memory`, `fields`, `context_note` are all domain facts. **`from_e164`'s DLT obligation is unchanged and is if anything more ours to get right**, since we would hold the carrier account.
- `EngineCapabilities` as a MECHANISM — a declared descriptor, one selector, one named refusal, and a conformance suite that exercises every claim. The values change; the shape is correct and is the reason this migration is describable at all.
- `ExecutionSnapshot`'s core (ids, instants, `duration_s`, `transcript`, `recording_url`, `latency`), `CallLatency`/`TurnLatency`/`LatencyBudget` — and the budget becomes directly measurable rather than inferred, which is the point of running the pipeline.
- `capabilities.py`'s error ladder: `EngineCapabilityAbsentError` with the capability as an ATTRIBUTE, `_REMEDIATION` authored per capability, `require_capability` / `require_speech_leg` / `require_call_compliance_floor` taking the ADAPTER rather than looking one up.
- The registry (§6) and the drift guard — unchanged in shape.

### 9.5 The three decisions this spec has to make explicitly

Each is a decision-log entry, not a consequence:

1. **A third `AgentHosting` member**, with a stated answer to "what replaces the read-back" — and a re-aiming of OPERATIONS §2 gate 2, `agents/verification.py`, and the drift sweep, rather than letting them pass vacuously (§9.0, §9.2).
2. **Where the guarantee of record lives** once `list_executions` no longer reads an independent authority (D-31 re-made, §9.2).
3. **Who produces `unit_cost_paid`** when there is no vendor total to convert (hard rule 7 against an append-only ledger, §9.3).

Everything else in §9 follows from a capability declaration plus a named refusal, which is
what the port was built to absorb.
