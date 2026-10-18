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
   (`gemini-3.1-flash-lite` unless changed, D-817), with its **cached input** figure from the
   same invoice (US$0.025 per 1M on Google's list, ai.google.dev/gemini-api/docs/pricing,
   updated 2026-10-16), and of any other Gemini model agents may run
   (ops console, model pricing), from the Google invoice. An unattested model is not offered.
3. Attest the Google data-use position (Models, dashboard data use: `google`): the project is on
   the paid tier and log sharing is off (OPERATIONS §2 gate 41). Raw caller speech goes through
   this key on every turn of every call.
4. Attest the `byok_llm_voice` per-minute rate (ops console, Per-minute rates; VENDOR-PUBLISHED
   ₹1.00/min, `bring-your-own-keys.md:26-29`).

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

**Not before ThinnestAI confirms per-agent scopes are live** (D-769). Their reply of 14 Oct 2026
says each agent's own `llm` / `llm_voice` takes effect "with our next release", and that they
will confirm. Until then an agent's scope may not take effect: our publish read-back refuses an
agent whose `byok` does not come back as sent, so switching on early fails every publish rather
than silently billing a different set-up. Switch on only once ThinnestAI has confirmed and a
test call on each set-up (step 3) passes (OPERATIONS §2 gate T-29).

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
   tokens), the usage rows show `llm_ktok_in` / `llm_ktok_out` with a cost (plus
   `llm_10ktok_cached_in` when the cache was hit and its rung is attested), and the
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
| `own_model_not_offered` | An agent named a Gemini model that is not offerable (no key, no attested price, or one Google limits to earlier users, such as 2.5), or our model is off. | Attest the model's price, or choose another; for a 2.5 default see §1. |
| `engine_own_model_unavailable` | ThinnestAI refused the agent's model (`PUT /agents/{id}/byok-model`). | Choose a model our key reaches. |
