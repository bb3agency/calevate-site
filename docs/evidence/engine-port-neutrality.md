# The `VoiceEngine` port after the neutrality fix (D-280 … D-283)

**Date**: 18 Aug 2026. **Subject**: `packages/shared/src/calevate_shared/engine.py` and
every file that reads it. **Predecessors**:
`docs/evidence/vendor-cartesia-reconciliation.md` (D-270…D-273) and
`docs/evidence/vendor-bolna-reconciliation.md` (D-260…D-262) — read those first; this
records the one piece of engineering they deliberately left, now done.

## The question this closes

TRD §10.5 opened with it:

> *"What has never been tested is whether that contract is vendor-NEUTRAL or merely
> Bolna-shaped — and those look identical while only one vendor exists."*

D-270 answered it: **Bolna-shaped**, evidenced from both of Cartesia's Stainless-generated
clients. There is no `POST /agents`; `AgentSummary` carries `git_repository` /
`git_deploy_branch` and no prompt, greeting or model; `PATCH /agents/{id}` accepts exactly
`{description, name, tts_language, tts_voice}`. On Cartesia Line the agent IS a deployed
repository and the prompt is per-call data.

D-270 could only relabel the methods that assume otherwise, because `EngineCapabilities`
had no way to say *"this engine does not host an agent of ours"*. It has one now.

## What the port expresses that it did not

| Name | Where | What it holds |
|---|---|---|
| `AgentHosting` | `calevate_shared.engine` | `control_plane` \| `external_deployment` — **where an agent comes from** |
| `EngineCapabilities.agent_hosting` | same | required, no default, like every other member |
| `EngineCapabilities.hosts_agents()` | same | the one accessor, so no caller re-derives the comparison |
| `EngineCapabilityName` gains `"agent_hosting"` | same | so `engine_lacks` / `require_capability` can refuse by name |
| `CallContext.system_prompt` | same | the **per-call home** hard rule 5 gets on the second shape |
| `carries_truthful_answer_floor(prompt)` | same | one predicate, three readers, no two definitions of "carries it" |
| `require_call_compliance_floor(engine=, prompt_on_the_wire=)` | `apps/api/engine/capabilities.py` | the one guard, called inside every adapter's dial |
| `ENGINE_COMPLIANCE_FLOOR_ABSENT` | same | its own code — an absent capability and a dial with no floor are different fixes |
| `VerificationState.publishable` | `apps/api/agents/publishing.py` | what the admin console asks before offering Publish |

The member is a **capability** and not a branch in the publish path for the reason every
other member is one: each value has to be a refusal an operator reads, a metric label, and
something the conformance suite can exercise. A branch is none of those.

**Two values, not three.** A third for *"externally deployed AND we cannot even put a
prompt on the call"* was drafted and rejected: it conflates where an agent COMES FROM with
what one REQUEST can carry, and the second is already expressible — the adapter refuses
the dial, by name, and the suite asserts it.

## What each engine declares, and why

| | `bolna` | `fake` (default) | `fake-restricted` | `fake-deployed` | `cartesia` |
|---|---|---|---|---|---|
| `agent_hosting` | `control_plane` | `control_plane` | `control_plane` | **`external_deployment`** | **`external_deployment`** |
| `stt` / `tts` / `llm` | ours / ours / ours | ours / ours / ours | engine / engine / ours | engine / engine / engine | **engine / engine / engine** |
| `knowledge_base` | true | true | false | true | true |
| `transfer` | false | false | true | false | false |
| `webhook_auth` | `source_ip` | `none` | `hmac` | `none` | `hmac` |
| `number_series` | ∅ | ∅ | ∅ | ∅ | ∅ |

* **`bolna` — `control_plane`, and this is the shape the port was written around.**
  `POST /v2/agent` creates, `PUT /v2/agent/{id}` edits, `GET /v2/agent/{id}` answers, and
  the prompt (with `TRUTHFUL_ANSWER_DIRECTIVE` inside it) is agent-record state. Nothing
  here is assumed: it is the surface the adapter has always called. What the declaration
  BUYS is that the assumption is now refusable.
* **`cartesia` — `external_deployment`, VERIFIED-SDK.** See the table at the top and
  `docs/vendor/cartesia/agents-control-plane.md`.
* **`cartesia.llm` moved `ours` → `engine` (D-281), and it is derived rather than
  weakened.** `SpeechControl`'s own docstring defines `ours` as *"our provider and model
  strings REACH THE VENDOR and run on OUR key"*. On Line `LlmAgent(model=...)` is a
  constructor call inside the DEPLOYED PROGRAM; `AgentSummary` has no `model` and
  `AgentUpdateParams` is four fields none of which is one. It is exactly the argument
  `transfer=False` already makes about a transfer feature the vendor genuinely has. The
  VENDOR fact is unchanged and TRD §10.5's table still states it: Sarvam 105B runs on Line
  through LiteLLM. What is false is that it reaches Line through **this port**. With the
  three agent-write methods refusing, `require_speech_leg` no longer runs on this adapter
  at all, so `llm="ours"` would have become a claim nothing could contradict — the
  unfalsifiable-descriptor defect `test_an_engine_side_campaign_object_is_not_claimable_yet`
  refuses outright. It reverts the day a model reaches a call (gate 19(b)).
* **`fake-deployed` is a SHAPE, not a vendor** — the same argument
  `DICTATED_SPEECH_CAPABILITIES` makes, about a bigger difference. It exists because the
  real adapter of this shape **cannot** dial (below), so without it the branch where an
  externally-deployed engine actually carries our prompt onto a call would be contract
  nothing executes. It needs no account and no imagined vendor JSON.

## How hard rule 5 is held on BOTH shapes

> *"an agent ALWAYS answers truthfully when a caller asks whether it is an AI or whether
> the call is recorded — enforced server-side, appended to every prompt by
> `compose_engine_prompt`, and verified against the engine on every publish and every
> drift sweep."*

### `control_plane` — unchanged, and still the stronger of the two

`compose_engine_prompt` puts `TRUTHFUL_ANSWER_DIRECTIVE` at the END of the prompt; the
adapter writes it to the agent record; `agents/verification.judge` reads
`TRUTHFUL_ANSWER_MARKER` back off the engine and a PROVEN absence **refuses the publish**;
the half-hourly drift sweep asks the same question again. `scripts/check_compliance_
invariants` §6 fails the build if such an adapter builds a prompt without the composer.

### `external_deployment` — the floor rides the call, or the engine is not dialled

There is no agent record to write and no read-back to score, so:

1. `dispatch_call` composes the prompt through `_call_prompt_for` → `_to_config` →
   `compose_engine_prompt` (never a second rendering of our intent) and puts it on
   `CallContext.system_prompt`.
2. Every adapter's `start_outbound_call` calls `require_call_compliance_floor`, passing
   **what it is about to put on the wire** — not the context it was handed. That
   distinction is the whole design: an adapter that receives the prompt and has no request
   field for it would pass a context-shaped check and dial anyway, dropping the floor
   silently, which is verbatim the failure `require_speech_leg` exists to stop one layer
   down.
3. A dial with no floor is refused with `engine_compliance_floor_absent` — a member of
   `DIAL_NOT_PLACED_CODES`, because it is raised before any HTTP request leaves the
   process, so no line was seized and the contact keeps its place on the ladder.

**And an adapter that cannot carry it refuses EVERY dial.** `CartesiaEngine` passes
`prompt_on_the_wire=None`, deliberately and with the finding at the line: `POST
/agents/calls` (REPORTED-DOCS) names `from_number_id`, `agent_id`,
`ringing_timeout_seconds` and `outbound_calls`, and no prompt field. The per-call prompt
that IS read at source — `agent: {system_prompt, introduction}` on a `start` event — belongs
to the WebSocket Calls API, which this adapter does not speak. Guessing a field would be
D-31/D-32's rule broken on the compliance path.

**Inbound is closed by the same act.** An inbound call reaches us only through
`engine_agent_routes`, and that row is written by `publish_agent` — which refuses on this
shape. No publish, no routing row, no inbound. So there is no second path on which a
Cartesia agent could take a call without a floor.

### Why the negative probe is the falsifier

`start_outbound_call` returns a handle and offers no read-back, so "it carried our prompt"
and "it dropped our prompt" are the same observation from the port. That is `transfer`'s
problem exactly, and the suite uses `transfer`'s answer: an adapter that can really carry
the floor is required to REFUSE a dial that has none, and one that cannot must refuse
both. The POSITIVE round trip is observed where it can be — on the fixture that is its own
vendor — and enforced statically everywhere else by the guardrail.

## The publish path, and what the console is told

`publish_agent` asks `require_capability("agent_hosting")` **first**, before the row lock
and before the vendor. Nothing is written, no `engine_agent_ref` can exist, and the client
gets a named refusal with a remediation instead of a 404 arriving mid-transaction —
which is indistinguishable from a vendor outage, so an operator retries a structural fact
for ever.

Three consequences, all of them true rather than convenient:

* `engine_drift_for` reports `not_published`, because the agent genuinely is not on the
  platform. No new state, no migration, no `check` constraint change.
* `verify_publish` re-raises the capability refusal rather than converting it to
  `unreachable`. No caller can reach it today; it is there so a future one that forgets
  gets the named answer rather than a verdict that reads like a blip.
* `PendingState.engine_verification.publishable` is `False`, the admin prompt screen
  renders the server's own sentence and **does not render the Publish button**. A console
  offering a control the route cannot honour is the divergence D-93 exists to remove.

**Adoption was considered and refused.** `GET /agents` is real and `name` is documented
unique, so "adopt the agent whose name matches" is implementable — and it would put an
agent live running a prompt we did not write and cannot read back, i.e. hard rule 5
resting on a repository nobody in this deployment can see. That is a product decision with
a compliance consequence (gate 19(a)), not a rename.

## What the conformance suite now measures

The split is taken from `EngineCapabilities.agent_hosting`, never from a name — the same
by-type derivation `test_every_adapter_that_speaks_http_is_held_to_the_transport_clauses`
uses for the transport ladder (D-240), so a third vendor cannot join unmeasured.

| Clause | What it holds |
|---|---|
| `test_agent_hosting_decides_where_the_truthful_answer_rule_lives` | `control_plane`: the marker comes back off the engine. `external_deployment`: `create_agent` and `get_agent` refuse naming `agent_hosting`; a floor-less dial is refused by name; a floor-carrying dial is placed **or** refused by the same named code — never accepted silently. |
| `test_an_externally_deployed_engine_claims_no_byok_leg` | `ModelConfig` reaches an engine through the agent object, so no agent object means no BYOK leg. Derived from `SpeechControl`'s own definition, not declared per vendor. |
| `test_every_agent_hosting_shape_is_exercised_by_the_roster` | Derived from the `AgentHosting` Literal: a shape no subject declares fails, so the `external_deployment` half cannot be deleted and leave the suite green. |
| the agent-record clauses (create/read-back/delete/KB-reference/BYOK read-back) | gated on `hosts_agents()`, each with the reason at the line |
| the call/KB clauses | take their ref from `_agent_ref()` and their context from `_dial_context()`, which make the same decision `dispatch_call` makes in production |

`tests/engine_capability_test.py` carries what the port cannot: the positive round trip on
`fake-deployed` (the prompt goes in on the `CallContext` and comes back off the call), both
directions on one engine, the control-plane engine needing no per-call prompt, and
Cartesia's five refusals.

`scripts/check_compliance_invariants` §6 learned the second shape. It asks each adapter
what its DECLARED hosting owes — `control_plane` must call `compose_engine_prompt`,
`external_deployment` must call the floor guard **inside `start_outbound_call`** — and it
checks the single dial site builds its `CallContext` with `system_prompt=`. It also refuses
a hosting value that is not a member of `AgentHosting`, so a third shape has to say what it
owes hard rule 5 before it can ship.

## What did NOT change, and why

* **The cost unit** (`_ASSUMED_MINOR_UNITS_PER_MAJOR`), **`family` vs `provider`** for the
  Sarvam LLM leg, **`voicemail`** status-vs-flag, the **transfer** built-in,
  **`webhook_auth="hmac"`** for Cartesia, and **repeat-DELETE semantics**. All are gated
  (OPERATIONS §2 gates 7, 16, 17, 18, 19(e), 2) and none became decidable from anything
  read here.
* **`CARTESIA_CAPABILITIES.knowledge_base` stays `True`.** Agent-scoped retrieval is read
  at source; how a document gets IN is gate 19(f). The KB methods still work against a ref,
  which is why the KB clauses run on this shape.
* **`delete_agent` and `list_executions` still work on Cartesia.** They are verified
  operations that do not depend on an agent record of ours.

## Still open, and what closes each

| | Blocked on |
|---|---|
| Whether `POST /agents` really 404s and a `PATCH` carrying `system_prompt` is ignored | A Cartesia API key — gate 19(a). The refusals are correct either way; the confirmation is what lets them be replaced by adoption. |
| Which outbound field, if any, carries a per-call prompt | One real outbound call — gate 19(b). It is the single thing that turns Cartesia's dial refusal back into behaviour, and `require_call_compliance_floor`'s argument becomes that field. |
| Whether a Cartesia agent could ever be adopted rather than created | The above, plus a decision about whose repository holds the prompt. Gate 19(a). |

Every one of them is the same external blocker the reconciliation named: **a Cartesia
account.** Not a legal entity, not a regulator, not a signed term — an API key.
