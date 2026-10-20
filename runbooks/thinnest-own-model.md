# Our own language model on ThinnestAI: switching it on, and keeping it on

D-764 (founder's target set-ups, 13 Oct 2026) and D-834 (every agent, 19 Oct 2026). With the ops
console switch `thinnest_own_model` on, every agent, free-trial agents included, answers on
**our** Gemini model through our Google key:

- **Clear** agents keep ThinnestAI's speech-to-text and voice; their `byok` is `llm` and the
  minute is billed at the voice band's own rate, so the rate card and the Clear cost are
  unchanged except for our Google bill.
- **Studio** agents keep our Cartesia voice; their `byok` is `llm_voice` and the minute is the
  flat own-voice-and-model rate, metered at the attested `byok_llm_voice` price.

Vendor basis (`thinnest-findings/mirror/snapshots/2026-10-13/pages/api-reference/
bring-your-own-keys.md`): the four scopes and their prices (:13-29), a scope chosen per agent
whatever the workspace default (:80-103, `agents/update-agent.md:746-768`), the LLM key added
with `PUT /byok/credentials` kind `llm` (:224-245), the agent's model with `PUT
/agents/{id}/byok-model` (:311-330), and no backup model when our key fails (:171-178).

Where the key lives (D-834). Free-trial agents live in our developer workspace (D-697), so our
Google key goes there too, by **Set up developer workspace** (§1 step 5), and into each paying
client's own workspace automatically at its first publish on our model. A per-agent scope
(`llm`, `llm_voice`) needs only that the workspace holds checked keys for it; the workspace
default applies only to agents that follow it (`snapshots/2026-10-18/pages/api-reference/
bring-your-own-keys.md:82-97`). A customer workspace without a complete set of its own inherits
the developer's keys under the developer's default scope (:186-190), and our code never moves
a default already set: the developer workspace stays on `voice` (Studio ready, D-727), so our
Google key there changes nothing for an agent that follows a workspace. Every agent we publish
names its scope. A trial publish never installs a key or flips a switch; it only verifies the
developer workspace and is refused (`own_model_account_not_ready`) when it is not ready. The
Gemini tokens of a free-trial call are absorbed by us; trial limits cap them and the client is
never charged (founder, 19 Oct 2026).

## 1. Before it can be switched on (founder)

Voices, "Our own model" card lists what is still missing. All five are required; saving the
switch is refused (`own_model_not_ready`) until they are done.

1. Save the Google (Gemini) API key in the ops console Secrets panel (`gemini_api_key`). Test it
   there first.
2. Attest the Gemini price of the default model, `thinnest_own_model_default`
   (`gemini-3.1-flash-lite` unless changed, D-817), with its **cached input** figure from the
   same invoice (US$0.025 per 1M on Google's list, ai.google.dev/gemini-api/docs/pricing,
   updated 2026-10-16), and of any other Gemini model agents may run
   (ops console, model pricing), from the Google invoice. An unattested model is not offered.
3. Attest the Google data-use position for callers' speech (Language models, In-call data use:
   `google`, step-up `attest_in_call_data_use:google`, D-839): the project is on
   the paid tier and log sharing is off (OPERATIONS §2 gate 41). Raw caller speech goes through
   this key on every turn of every call. The dashboard assistant's attestation does not count here.
4. Attest the `byok_llm_voice` per-minute rate (ops console, Per-minute rates; VENDOR-PUBLISHED
   ₹1.00/min, `bring-your-own-keys.md:26-29`).
5. Press **Set up developer workspace** on the card (`POST /v1/ops/voices/own-model/developer`,
   step-up `enable_own_model_developer`). It installs our Google key in our developer workspace
   unless a checked one of its own is there; if that workspace's own keys are off, every agent
   that would follow them (there and in customer workspaces that inherit them) is confirmed
   `off` first and the keys go on with scope `llm`; a default already set (`voice` after Studio
   ready) is kept. It reads the state back and records it on `platform_state`; the card then
   shows "developer workspace on our key". Idempotent: press it again after any failure.

### The card says the default model is "no longer available to new users"

The stored console value is a Gemini 2.5 model. Google limits 2.5 to projects that used it
before, and our project gets 404 on both 2.5 models (live test, 18 Oct 2026), so the default
is refused on this leg (D-817): the card is not ready, the switch cannot go on, and every
publish on our model is refused with `own_model_not_offered` rather than placing calls that
would fail. Fix: attest `gemini-3.1-flash-lite` (step 2), then Platform configuration
(`/admin/ops/config?section=voice-engine`) → Voice
engine → "Our language model for agents with none chosen" → **Change** to
`gemini-3.1-flash-lite` and save (or **Reset to default**, which is the same model). Saving
the same 2.5 value again is refused. Agents an operator put on a 2.5 model of their own
(`byok:gemini-2.5-…` on the admin agent page) fall back to the default at their next publish.

## 2. Switch it on

ThinnestAI wrote that per-agent `byok` is live in every workspace (email 18 Oct 2026, item 7)
and that a Clear agent on `llm` can now have its own model through `PUT
/agents/{id}/byok-model` (email 19 Oct 2026); both are VENDOR-STATED and untested live by us. Our
publish read-back still refuses an agent whose `byok` does not come back as sent, so a scope the
platform does not keep fails the publish rather than silently billing a different set-up. The
test calls in step 3 close OPERATIONS §2 gate T-29.

1. Optional, recommended for a client with many live agents: prepare its workspace first with
   `POST /v1/ops/voices/own-model/enable {tenant_id}` (step-up `enable_own_model_workspace`).
   It installs our Google key there, switches the workspace's own keys on with scope `llm` when
   they are off (agents that would follow the workspace confirmed `off` first), and reads it
   back. A Studio workspace keeps its default scope `voice`.
2. Set `thinnest_own_model` on in the ops console (typed confirmation). Saving it republishes
   every live agent IN PLACE, free-trial agents in the developer workspace included: each agent
   is updated (`PATCH /agents/{id}` with `byok` `llm` for Clear or `llm_voice` for Studio, then
   `PUT /agents/{id}/byok-model` naming the model) under the same vendor id, and its route is
   stamped with the model and rate key the meter reads. Nothing is deleted or recreated
   (founder, 19 Oct 2026). The live-apply run lists any agent not applied; an agent that is not
   live (a draft) moves at its next publish, so press **Publish** on it.
3. Place one test call on a Clear agent and one on a Studio agent, a free-trial one and a paying
   client's (OPERATIONS §2 gate T-29). On each: the reply comes from Gemini (the call's usage shows
   tokens), the usage rows show `llm_ktok_in` / `llm_ktok_out` with a cost (plus
   `llm_10ktok_cached_in` when the cache was hit and its rung is attested), and the
   `platform_min` row's `meta.engine_rate_key` is the band's (Clear) or `byok_llm_voice`
   (Studio).

## 3. Keeping it on

- **Rotation.** Saving a new `gemini_api_key` enqueues `push_own_model_key`, which replaces the
  key in our developer workspace (when a Google key is held there) and in every client
  workspace on our model, keeping each workspace's model. `own_model_key_push_failed` (page)
  names a client whose push failed, or none for the developer workspace: test the key and save
  it again.
- **Hourly check** (`sweep_own_model_workspaces`, minute 41). The developer workspace (once set
  up) and each client workspace must answer `GET /byok` with our checked Google key in use; one
  that does not is switched back on and alarmed `own_model_developer_repaired` /
  `own_model_workspace_repaired` (attention), or `own_model_developer_drift` (attention) /
  `own_model_workspace_drift` (page) when it could not be. A `byok.changed` event runs the same
  check at once. The card shows the developer workspace's state and each client's last error
  code.
- **Per agent.** The drift sweep reads each agent's `byok` and its model of our key back and
  puts them back when they moved (`engine_agent_voice_key_repaired`).
- **A key failure on a call** arrives as `call.problem` `byok_failed` and alarms
  `engine_call_own_key_failed`; the caller heard ThinnestAI's apology for that turn. The alarm
  ends with ThinnestAI's own sentence about the failure (`detail`, one line, long numbers
  masked, D-769), which is the best indication of which key failed and why.
- **Is Google's prompt cache being hit on calls?** (D-817) Every metered own-model call logs
  `own_model_call_metered` with `model`, `input_count`, `cached_input_count` and
  `output_count` (counts only). `cached_input_count` null means ThinnestAI reported no cached
  figure, which is not zero hits. From the ledger, per client (run in that client's tenant
  session; RLS scopes it):

  ```sql
  SELECT meta->>'own_model' AS model,
         sum((meta->>'llm_cached_input_tokens')::numeric)
           / NULLIF(sum((meta->>'llm_input_tokens')::numeric), 0) AS hit_rate,
         count(*) AS calls
  FROM usage_events
  WHERE unit_type = 'llm_ktok_in' AND meta->>'own_model' IS NOT NULL
    AND meta->>'llm_cached_input_tokens' IS NOT NULL
    AND occurred_at >= now() - interval '1 day'
  GROUP BY 1;
  ```

  One row per call (`llm_ktok_in` is written on every metered call). Cached tokens are billed
  at the cached rung only once its figure is attested (§1 step 2); the call then carries an
  `llm_10ktok_cached_in` row and `llm_ktok_in` holds the rest.
- **A key gone at call start** does not fail the call: it runs on the workspace's default scope
  and is billed for what ran (ThinnestAI, 14 Oct 2026). On a Studio agent the charge
  reconciliation then raises `engine_call_cost_variance` against the `byok_llm_voice` minute,
  saying the call may have fallen back; check the workspace's keys on the "Our own model" card.

## 4. Switching it off

Set `thinnest_own_model` off. Every live agent is republished back to `off` (Clear) or
`workspace` (Studio, our voice key), its route's model cleared, free-trial agents included. The
Google key stays installed in the developer workspace and each client workspace and costs
nothing while no agent names a model scope.

## Error codes

| Code | Meaning | Fix |
| --- | --- | --- |
| `own_model_not_ready` | The switch was refused: something in §1 is missing. | Do what the refusal lists. |
| `own_model_key_missing` | No `gemini_api_key` is set. | §1 step 1. |
| `engine_model_key_rejected` | Google refused the key, or the model on it. | Test the key; check the model id. |
| `engine_model_key_not_ready` | ThinnestAI would not switch the keys on: the key is not checked or has no model. | Retry the enable; check the workspace's keys on ThinnestAI. |
| `own_model_agents_not_kept_off` | An agent that would follow the workspace could not be confirmed `off`. | Republish that agent, then retry. |
| `own_model_workspace_not_ready` | The read-back did not show our checked Google key in use. | Retry; read the workspace's keys on ThinnestAI. |
| `own_model_account_not_ready` | A client's publish was refused for one of the above (the client saw no vendor name); for a free-trial agent, our developer workspace was not on our Google key. | Paying client: retry with the enable route. Free trial: §1 step 5. |
| `own_model_developer_not_ready` | Set up developer workspace finished, but the read-back did not show our checked Google key in use there. | Retry; read the developer workspace's keys on ThinnestAI. |
| `own_model_minute_unpriced` | A Studio publish on our model with `byok_llm_voice` unattested. | §1 step 4. |
| `own_model_not_offered` | An agent named a Gemini model that is not offerable (no key, no attested price, or one Google limits to earlier users, such as 2.5), or our model is off. | Attest the model's price, or choose another; for a 2.5 default see §1. |
| `engine_own_model_unavailable` | ThinnestAI refused the agent's model (`PUT /agents/{id}/byok-model`). | Choose a model our key reaches. |
