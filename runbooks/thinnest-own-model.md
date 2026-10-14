# Our own language model on ThinnestAI: switching it on, and keeping it on

D-764 (founder's target set-ups, 13 Oct 2026). With the ops console switch `thinnest_own_model`
on, a paying client's agents answer on **our** Gemini model through our Google key:

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

Free-trial agents (our developer workspace) stay on ThinnestAI's model: a key there would be
inherited by every client workspace without keys of its own (:180-184). Our Google key goes
only into each paying client's own workspace, at its first publish on our model.

## 1. Before it can be switched on (founder)

Voices, "Our own model" card lists what is still missing. All four are required; saving the
switch is refused (`own_model_not_ready`) until they are done.

1. Save the Google (Gemini) API key in the ops console Secrets panel (`gemini_api_key`). Test it
   there first.
2. Attest the Gemini price of the default model, `thinnest_own_model_default`
   (`gemini-2.5-flash-lite` unless changed), and of any other Gemini model agents may run
   (ops console, model pricing), from the Google invoice. An unattested model is not offered.
3. Attest the Google data-use position (Models, dashboard data use: `google`): the project is on
   the paid tier and log sharing is off (OPERATIONS §2 gate 41). Raw caller speech goes through
   this key on every turn of every call.
4. Attest the `byok_llm_voice` per-minute rate (ops console, Per-minute rates; VENDOR-PUBLISHED
   ₹1.00/min, `bring-your-own-keys.md:26-29`).

## 2. Switch it on

1. Optional, recommended for a client with many live agents: prepare its workspace first with
   `POST /v1/ops/voices/own-model/enable {tenant_id}` (step-up `enable_own_model_workspace`).
   It installs our Google key there, switches the workspace's own keys on with scope `llm` when
   they are off (agents that would follow the workspace confirmed `off` first), and reads it
   back. A Studio workspace keeps its default scope `voice`.
2. Set `thinnest_own_model` on in the ops console (typed confirmation). Saving it republishes
   every live agent: each paying client's agents move to `llm` (Clear) or `llm_voice` (Studio),
   with `PUT /agents/{id}/byok-model` naming the model, and their routes are stamped with the
   model and rate key the meter reads. The live-apply run lists any agent not applied.
3. Place one test call on a Clear agent and one on a Studio agent of a paying client
   (OPERATIONS §2 gate T-29). On each: the reply comes from Gemini (the call's usage shows
   tokens), the usage rows show `llm_ktok_in` / `llm_ktok_out` with a cost, and the
   `platform_min` row's `meta.engine_rate_key` is the band's (Clear) or `byok_llm_voice`
   (Studio).

## 3. Keeping it on

- **Rotation.** Saving a new `gemini_api_key` enqueues `push_own_model_key`, which replaces the
  key in every client workspace on our model, keeping each workspace's model.
  `own_model_key_push_failed` (page) names a client whose push failed: test the key and save it
  again.
- **Hourly check** (`sweep_own_model_workspaces`, minute 41). Each workspace must answer `GET
  /byok` with our checked Google key in use; one that does not is switched back on and alarmed
  `own_model_workspace_repaired` (attention), or `own_model_workspace_drift` (page) when it
  could not be. The card lists each client's last error code.
- **Per agent.** The drift sweep reads each agent's `byok` and its model of our key back and
  puts them back when they moved (`engine_agent_voice_key_repaired`).
- **A key failure on a call** arrives as `call.problem` `byok_failed` and alarms
  `engine_call_own_key_failed`; the caller heard ThinnestAI's apology for that turn. The docs
  give nothing more specific about which key failed.

## 4. Switching it off

Set `thinnest_own_model` off. Every live agent is republished back to `off` (Clear) or
`workspace` (Studio, our voice key), its route's model cleared. The Google key stays installed
in each client workspace and costs nothing while no agent names a model scope.

## Error codes

| Code | Meaning | Fix |
| --- | --- | --- |
| `own_model_not_ready` | The switch was refused: something in §1 is missing. | Do what the refusal lists. |
| `own_model_key_missing` | No `gemini_api_key` is set. | §1 step 1. |
| `engine_model_key_rejected` | Google refused the key, or the model on it. | Test the key; check the model id. |
| `engine_model_key_not_ready` | ThinnestAI would not switch the keys on: the key is not checked or has no model. | Retry the enable; check the workspace's keys on ThinnestAI. |
| `own_model_agents_not_kept_off` | An agent that would follow the workspace could not be confirmed `off`. | Republish that agent, then retry. |
| `own_model_workspace_not_ready` | The read-back did not show our checked Google key in use. | Retry; read the workspace's keys on ThinnestAI. |
| `own_model_account_not_ready` | A client's publish was refused for one of the above (the client saw no vendor name). | Retry with the enable route. |
| `own_model_minute_unpriced` | A Studio publish on our model with `byok_llm_voice` unattested. | §1 step 4. |
| `own_model_not_offered` | An agent named a Gemini model that is not offerable, or our model is off. | Attest the model's price, or choose another. |
| `engine_own_model_unavailable` | ThinnestAI refused the agent's model (`PUT /agents/{id}/byok-model`). | Choose a model our key reaches. |
