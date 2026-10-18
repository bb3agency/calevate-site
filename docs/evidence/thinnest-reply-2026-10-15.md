# ThinnestAI's 15 Oct 2026 reply (requests A–H), checked against the docs snapshot of 15 Oct 2026

**Source of the claims.** Ashutosh K (founder, ThinnestAI) wrote on 15 Oct 2026 that the eight
requests of `docs/vendor/thinnest-replies-2026-10-12.md` §13.1 are built and live. The founder
relayed the email. Its text is in that file, §14. On its own it is **VENDOR-STATED**.

**Source of the verdicts.** `thinnest-findings/mirror/snapshots/2026-10-15/` is a full re-fetch of
every `.md` link in `https://docs.thinnest.ai/llms.txt`. The UTC run was 16:48–16:56, and
`generated_at` is in its `MANIFEST.json`. 284 of 284 pages were fetched with 0 failures. Against
`2026-10-13/`, 2 pages were added (`api-reference/post-call/delete-call-content`, `agent/find-leads`)
and 212 changed. Every path below is under
`thinnest-findings/mirror/snapshots/2026-10-15/pages/`. Everything cited is
**VERIFIED-VENDOR-DOCS** as of 15 Oct 2026. Where the docs are silent, the item says
**UNKNOWN**, and the claim stays VENDOR-STATED.

## Summary

| Item | Verdict |
|---|---|
| A. `billing` on Get Call and `call.analysed` | **VERIFIED.** One difference: `voicePlan` values are lower case. The forwarded-call rule is VENDOR-STATED only |
| B. `usage.ttsCharacters` | **VERIFIED.** "Matches what our Cartesia account bills" is VENDOR-STATED |
| C. `usage.inputTokensEstimated` | **VERIFIED** (nullable) |
| D. Developer clones usable in customer workspaces | **VERIFIED.** The id a customer agent uses is **UNKNOWN** |
| E. `DELETE /calls/{id}/content`; `callRetentionDays` | **VERIFIED** |
| F. `contact.erased` | **VERIFIED** |
| G. `byok.changed` | **VERIFIED** |
| H. `own` on `GET /byok/voices` | **VERIFIED** |

None of the eight is contradicted on substance. The one literal contradiction is the casing of
the `voicePlan` values (A).

## A. What each call was billed as

**Claim.** Get Call and `call.analysed` carry `billing`, with five fields:

- `keys` (`off|all|voice|llm|llm_voice`): what the call actually ran on, after any fallback.
- `voicePlan` (`Standard|Premium|Studio`): null for flat own-key prices and for older calls.
- `ratePerMinuteMicro`.
- `billedSeconds`: empty until settled.
- `currency`.

For a forwarded call with no agent, trust `costMicro`.

**Docs.**

- **Where it is carried.** Get Call's `CallReport` requires `billing` (`api-reference/calls/get-call.md:608`, `:673-674`). The webhook preamble says `call.analysed` carries `data.billing`, "the same objects as Get Call's" (`api-reference/webhooks/create-webhook.md:330-340`). `call.analysed` is "exactly the object Get Call returns" (`api-reference/webhooks.md:389-391`). Cancel Call's `CallReport` carries `billing` too (`api-reference/calls/cancel-call.md`, the `billing` schema). **List Calls does not:** its rows gained `contentDeleted` and `contentDeletedAt` only (`api-reference/calls/list-calls.md:964`), so per-call billing needs Get Call or the webhook.
- **The object.** `CallBilling` has type `object | null` and is "Null for a booked call that has not rung" (`api-reference/calls/get-call.md:1228-1239`). All five fields are required.
- **`keys`.** A string, enum `off | all | voice | llm | llm_voice`, never null: "Whose keys the call ran on, as it was set up when the call started" (`:1240-1252`). The fallback happens at that moment: "If a key is gone when a call starts, the agent falls back to the workspace's scope … the agent's setting is read once when the call or reply starts" (`:200-203`). So `keys` is the stack after any fallback. This **agrees** with the email.
- **`voicePlan`.** Enum `standard | premium | studio | null`, in **lower case** (`:1253-1265`). "The voice plan the call was priced on (`off` and `llm` calls). Null for the flat own-key prices (`all`, `voice`, `llm_voice`), for a free trial call, and for calls before 15 October 2026."
  - **CONTRADICTS the email's capitalisation.** The docs win, so parse lower case.
  - The free-trial null is in the docs and not in the email.
- **`ratePerMinuteMicro`.** An integer or null, in millionths of `currency` (1820000 is 1.82) (`:1266-1275`).
  - It is the per-minute price "fixed when it started", at a white-label reseller's price for its clients.
  - A call is charged in 30-second steps at half of this rate each (a WhatsApp call by the minute).
  - It is null for a free trial call.
- **`billedSeconds`.** An integer or null (`:1276-1285`). It is the call's length rounded up to its step, or to the carrier's block for a call that ended before the agent spoke (carrier fee only). It is "Null until a charge was taken — a call still live, a free trial call, and calls settled before 15 October 2026."
- **`currency`.** `INR | USD | null` (`:1286-1294`), "as `currency` on the call".
- **Example.** `keys: 'off'`, `voicePlan: standard`, `ratePerMinuteMicro: 1820000`, `billedSeconds: 210`, `currency: INR` (`:538-543`).
- **`costMicro` is unchanged.** It is null until settled. Settlement runs before `call.analysed`, which then normally carries it (`:646-657`).
- **Forwarded calls.** The agent is null on a call forwarded to a phone with no agent (`CallAgentRef`, `:1295-1300`), and `forwardedTo` is set (`:1005-1013`).
  - The docs say nothing about `billing` on such a call.
  - "Trust `costMicro`" for forwarded calls is **VENDOR-STATED only**.
- **The figure is not attested.** `ratePerMinuteMicro: 1820000` in the example is not a price we can rely on. It is a sample value, and no page in this snapshot attests it.

**What this changes in our code.**

- **Adapter.** In `apps/api/engine/thinnest.py`, `ThinnestEngine._snapshot` (around `:3422`) should parse `billing` into a new normalized field on `ExecutionSnapshot` (`packages/shared/src/calevate_shared/engine.py:4515`). Suggested fields:
  - `engine_keys`: the scope;
  - `engine_voice_plan`: lower case;
  - `engine_rate_inr_per_min`: `Decimal`, through `_is_rupees`, as `_charged_inr` (`:1393`) does;
  - `engine_billed_seconds`.

  Hard rule 2: no vendor field names leave the adapter.
- **Charge reconciliation.** In `apps/workers/engine_charges.py`, the module docstring says "neither Get Call nor `call.analysed` documents which scope a call ran on", and that is no longer true.
  - `engine_call_cost_variance` can name the actual scope (`keys`) and voice plan instead of guessing at a fallback.
  - `ratePerMinuteMicro` lets the sweep compare the vendor's per-call rate with the attested rate for the route's rate key directly, and not only the totals.
- **Meter.** In `apps/api/billing/engine_minutes.py`, `engine_minute_cost` costs a call at the rate key stamped on the route (`engine_agent_routes.engine_rate_key`) and computes billed minutes from our own 30-second pulse.
  - `billedSeconds` is the vendor's own figure for the second half of that.
  - `keys`/`voicePlan` say whether the route's key was what ran.
  - Hard rule 7 still holds: `unit_cost_paid` comes only from an attested rate. Treat `ratePerMinuteMicro` as a cross-check (alarm on disagreement), not as a price source, unless the founder decides otherwise.
- **Forwarded calls.** `FORWARDED_RATE_KEY = "standard"` (`engine_minutes.py`) rests on the forwarding page. `billing.voicePlan` on a forwarded call would confirm or refute it per call. Until a forwarded call has been observed, the email's "trust `costMicro`" is the only statement. **Superseded 18 Oct 2026 (D-813):** a forward is charged the carrier's fee only, ₹0.38/min in 30-second blocks, its `voicePlan` showing the set-up plan (`snapshots/2026-10-18/pages/api-reference/calls/get-call.md:1236-1243`; ThinnestAI email of 18 Oct 2026, VENDOR-STATED); `FORWARDED_RATE_KEY` is replaced by the attested `carrier` price key.
- **Tests.** The conformance suite and `FakeEngine` need the new snapshot fields, plus fixtures for `billing: null` (booked call), `voicePlan: null` (own-key flat price) and `billedSeconds: null` (not settled).

## B. Characters sent to the voice

**Claim.** `usage.ttsCharacters` counts all text sent to the voice, including cut-off sentences,
and matches what our Cartesia account bills.

**Docs.** `CallUsage.ttsCharacters` is an integer or null and is required (`api-reference/calls/get-call.md:1218-1227`). It counts "Characters of text sent to the voice to be spoken: every reply, the greeting, fillers and other fixed lines". It includes text sent before the caller interrupted, "even if they never heard it, which is what a voice provider charges for", and it is counted on our own voice key (BYOK) too. It is null when nothing was sent. `call.analysed` carries the same `usage` (`api-reference/webhooks/create-webhook.md:330-336`). The example value is `1840` (`get-call.md:537`).

- That it **matches our Cartesia invoice** is VENDOR-STATED. The docs say only that it is what "a voice provider charges for".
- The docs do not say whether `ttsCharacters` is non-null on calls before 15 Oct. Treat a null as unknown, not as zero.

**What this changes in our code.**

- **Adapter.** `apps/api/engine/thinnest.py` `parse_llm_usage` (`:574-585`) and `CallLlmUsage` (`packages/shared/src/calevate_shared/events.py:163`) gain `tts_characters`. Alternatively, a separate voice-usage field is cleaner, because `CallLlmUsage` is named for the model.
- **Studio cost row.** `apps/workers/pipeline.py` `_tts_cost_rows` (`:4189`) costs a Studio (own Cartesia key) call from `agent_chars`, the characters of the agent's transcript turns (`_agent_transcript`, `:4168`). That count misses cut-off text, greetings and fillers that are not in the transcript. Use `ttsCharacters` when present, fall back to the transcript count when it is null, and stamp which source was used in `meta`.
- **Fleet counter.** The fleet counter (`platform_tts_volume`, migration `f7c2a94e18b3`, and `billing/tts_speaking_rate.py`) shares `agent_chars` with the cost row by design (D-557). Moving one without the other breaks the "one call counted once" invariant, so move both together.
- **Clear calls.** On Clear calls, `ttsCharacters` is informational: the engine buys that synthesis.

## C. Estimated input tokens are marked

**Claim.** `usage.inputTokensEstimated` is true when the input tokens are ThinnestAI's estimate.

**Docs.** `CallUsage.inputTokensEstimated` is a boolean or null and is required (`api-reference/calls/get-call.md:1208-1217`).

- It is true when any reply's input count was estimated from the prompt's length because the provider reported none, so `inputTokens` is "partly an estimate".
- It is false when every count came from the provider.
- It is null when no tokens were recorded, and for calls before 15 October 2026.

The summary and field extraction after the call are still not counted (`:1171-1186`).

**What this changes in our code.**

- **Adapter.** `parse_llm_usage` and `CallLlmUsage` gain `input_tokens_estimated: bool | None`.
- **Meter.** `apps/workers/pipeline.py` `_own_model_rows` (`:3226`) should stamp the flag on the `llm_ktok_in` row's `meta`.
- **Prompt-size floor.** `apps/api/billing/own_model_prompt.py`, in its "Measured" source, should exclude calls whose count was estimated, or at least report them, so that the p95 prompt size used for the own-model floor is built from provider-reported counts.
- **Unanswered.** This closes §12.2 question 2. §13 question 2 (whether the post-call summary and extraction run on our key) is **not** answered by the reply or the docs.

## D. Developer clones usable by customer workspaces

**Claim.**

- Developer-workspace clones are usable by customer workspaces' agents automatically.
- No copies are made, and the clones count only against our limit.
- Customers can pick a clone but cannot edit or delete it.
- Deleting a clone moves its agents to a standard voice.

**Docs.**

- **Prose.** "every voice you clone can be used by all your customer workspaces, automatically". It shows on their Studio tab and in `GET /voices` with `"sharedFromDeveloper": true`. A customer cannot rename or delete it, and it counts against **your** clone limit. A customer's own clones stay theirs alone. Deleting one moves every agent speaking with it, the developer's and the customers', to a standard voice (`channels/voice-clone.md:114-126`). The same rule is on `api-reference/customers.md:236-241`.
- **Schema.** `GET /voices` has `sharedFromDeveloper: boolean, const true` (`api-reference/voices/list-voices.md:579-589`). It is "Present, and true, only on a voice your DEVELOPER cloned, in a workspace that is one of its customers". Update and Delete Voice Clone answer `404` for it there.
- **Listing.** A developer clone is listed in the customer workspace's own `GET /voices` (`:442-453`; example `:495-500`). Studio voices, including shared clones, are listed only on Pro and above (`:450-453`), and "A customer is always on your plan" (`api-reference/customers.md:216`).
- **Id format.** In the example the id is a bare UUID (`7e2b5c90-…`), the same shape as a clone's `voiceId` (`api-reference/voice-clones/create-voice-clone.md:480`).
- **UNKNOWN: same id in both workspaces?** The docs do not say that a shared clone's id in a customer workspace **equals** its `voiceId` in the developer workspace. One `GET /voices` with `Thinnest-Workspace: <client org>`, compared with the developer listing, settles it, and it decides whether our catalogue id can be sent as is.

**What this changes in our code.**

- **`apps/api/agents/clone_copies.py`.** The whole module exists because "A ThinnestAI clone belongs to the workspace that made it". That is superseded.
  - `workspace_voice_id` should stop cloning into the client workspace and answer the developer clone's id, or the id the customer listing shows, if they differ.
  - `keep_clone_sample` and the sealed sample exist only to make copies. Whether to keep them as a re-clone safety net is a decision.
  - `forget_clone` and the `engine_voice_clone_copies` table (`apps/api/agents/models.py:1471`, `EngineVoiceCloneCopy`) become legacy. Existing copies in client workspaces count against nothing of ours, but they are live voices agents may speak. Republish those agents on the shared id, then delete the copies (the client workspace's clone limit is freed).
  - Removing a table is a two-step deprecation (hard rule 8).
- **`voice_clone_workspace_limit`.** The refusal in `clone_copies.py` no longer applies to our clones.
- **Voice listing.** `apps/api/engine/thinnest.py` `list_hosted_voices` (`:2952`) sets `is_custom` from `mine`. In a customer workspace, our clones arrive as `sharedFromDeveloper` instead. Read both if the listing is ever taken in a client workspace.
- **Docs.** `docs/THINNEST-INTEGRATION.md` "Clones" and gate T-18 need updating.

## E. Delete one call's content; shorter retention

**Claim.** `DELETE /api/v1/calls/{id}/content` deletes one call's recording, transcript, summary
and collected fields, and the billing record stays. `callRetentionDays` on Update Workspace sets a
shorter retention, never longer than the plan's.

**Docs: `DELETE /calls/{id}/content`.** `operationId: deleteCallContent`, tag Post-call (`api-reference/post-call/delete-call-content.md:443-533`).

- **Deleted.** The recording: ours, the phone provider's copy on a rented number, and any training copy. Also this call's own turns in its conversation (other calls and chats stay), its summary, its collected fields, and the warm-hand-off summary.
- **Kept.** When the call happened, who it was with, its length, its cost and `billing`.
- **Retried calls.** For a call we placed that was retried, every attempt's content goes. It cannot be undone.
- **Not Cancel Call.** "This is not Cancel Call". The request is idempotent: a repeat answers `200` with the first deletion's time.
- **Requirements.** It needs a **full** key. A developer reaches a customer's call with `Thinnest-Workspace`.
- **Parameters.** `id` is `out_…` or `sch_…` for a placed call, or the call reference for any other (`:536-545`), plus the `Thinnest-Workspace` header.
- **`200` body.** `CallContentDeleted` (`:565-589`):
  - `contentDeleted: true` (const);
  - `contentDeletedAt`: date-time, the same on every repeat;
  - `recordingsPending`: integer, files retried nightly;
  - `call`: the `CallReport` or null.

  The example returns `call: null` with `recordingsPending: 0`.
- **Errors.**
  - `400`: header from a non-developer workspace.
  - `401`.
  - `403`: not a full key.
  - `404`: no such call in this workspace.
  - **`409`: the call is still going on, or it was booked and has not rung.**
  - `410`: workspace deleted.
  - `429`.
  - **`503`: "Something could not be deleted just now. Nothing is lost by trying again."**
- **Afterwards.** Get Call shows `recording: null`, an empty `transcript`, `contentDeleted: true` and `contentDeletedAt`. These fields are also on List Calls (`api-reference/calls/get-call.md:1014-1027`; `workspace/data-and-erasure.md:70-92`).
- **No webhook** is documented for a call-content deletion.

**Docs: `callRetentionDays`.**

- **Request.** `PATCH /api/v1/workspace` (Update Workspace). The body is `WorkspaceUpdate`: any of `name`, `timezone`, `callRetentionDays`, with `minProperties: 1` (`api-reference/workspace/update-workspace.md:442-453`, `:528-553`).
- **Field.** `callRetentionDays` is an integer or null, minimum 1. Its units are **days**, "from 1 to your plan's `planRetentionDays` (a longer number is refused with a 400 naming your plan's maximum)".
- **Effect.** From the next night, older calls lose their recording **and** transcript, exactly as Delete Call Content removes them, and the billing record stays. It applies to calls already held (`workspace/data-and-erasure.md:94-108`).
- **`null`.** Goes back to the plan's window for recordings and keeps transcripts with no end.
- **Response.** The `Workspace` object, with `callRetentionDays` (integer or null) and `planRetentionDays` (integer): 30 on pay-as-you-go, 49 on Pro, 75 on Scale, 365 on Enterprise (`:582-599`). The same fields are on Get Workspace.
- **Customer workspaces.** Set it per customer with `PATCH /workspace` and `Thinnest-Workspace` (`api-reference/customers.md:243-247`).
- **Doc gap.** The `400` description in the response table names only the name and time zone. The `callRetentionDays` refusal is stated in the field description only.

**What this changes in our code.**

- **Proof register.** `apps/api/compliance/deletion.py:315-325` states that "ThinnestAI has no per-call delete", which grounds `ENGINE_OUTCOME = "not_reached_retention_unestablished"` and `VOICE_PLATFORM_RETAINED` (`apps/api/compliance/processor_erasure.py`). Both are now wrong.
  - A DPDP erasure can delete the subject's calls per call. That includes calls in our **developer** workspace (legacy calls from before D-693), where `DELETE /contacts/{id}` was refused because the contact is shared across tenants (D-691).
  - New adapter call: a `delete_call_content` in `apps/api/engine/thinnest_customer_data.py`, or the adapter proper. It needs a full key, workspace-scoped, and must treat `409` (live or booked), `503` (retry) and `404` explicitly.
  - New worker arm: beside `erase_engine_contact` in `apps/workers/engine_customer_data.py`.
  - Per hard rule 4, issued proofs are not rewritten. New proofs get a new outcome token.
- **Vendor-side retention.** `callRetentionDays` makes vendor-side retention settable per client workspace. Our recording copy runs first in the pipeline (`apps/workers/pipeline.py` `_copy_recording_once`), and our 90-day TRAI floor applies to **our** copy (`apps/workers/retention.py`). So the vendor window may be shorter than ours.
  - Set it from the tenant's own retention policy at workspace provisioning (`apps/api/tenancy/engine_workspace.py` `queue_workspace_provisioning`) and on a policy change.
  - Cap it at `planRetentionDays`.
  - Do not set it so short that a call can lose its content before our pipeline has copied it and read `call.analysed`, or before the charge sweep reads it.
  - What value to set is a founder decision.
- **Transcripts.** With `callRetentionDays` null, the vendor keeps transcripts **forever**. That is the default today on every client workspace and is worth stating in the subprocessor register.
- **Snapshot.** Parse `contentDeleted` into the snapshot so a re-drive does not read an emptied call as a call with no transcript.
- **Legal pages.** Wherever they say the voice platform's retention is unestablished or that no per-call deletion exists (`/legal/subprocessors`, `/legal/dpa`), the text is now stale. That needs a founder decision on wording, and it changes `limitations_version`.

## F. `contact.erased`

**Claim.** It is sent once, when the last recording is gone.

**Docs.**

- **Event.** `contact.erased` is in the subscribable event enum (`api-reference/webhooks/create-webhook.md:742`, `:801`) and in the events table (`api-reference/webhooks.md:87`).
- **Payload.** `{ "id": "evt_…", "event": "contact.erased", "sentAt", "data": { "contactId": "cust_…", "erasedAt": "<ISO 8601>" } }` (`api-reference/webhooks.md:545-563`; `api-reference/webhooks/create-webhook.md:352-357`).
- **When.** Sent **once**: straight after Delete Contact answered `204`, or from the nightly retry once the last `recordingsPending` recording is gone. A recording still being written can take up to three nights. Also stated at `api-reference/contacts/delete-contact.md:11` and `workspace/data-and-erasure.md:51-55`.
- **Delivery ("Workspace events", `api-reference/webhooks.md:536-543`).**
  - It goes to **every endpoint in the workspace that subscribed to it**, whichever agent it was added on.
  - It goes **once per address**.
  - It also goes to the developer's `includeCustomers` endpoints, with `workspaceId`.
  - It goes to `["*"]` subscribers.
  - It carries no personal data.
- **Signing.** The same as every other delivery: "Every delivery carries `x-thinnest-signature` … and `x-thinnest-signature-v2`". The headers table applies "on every attempt" (`api-reference/webhooks.md:36-41`, `:210-226`). Nothing exempts workspace events.

**What this changes in our code.**

- **Subscription.** `apps/api/engine/thinnest_webhooks.py:50` `SUBSCRIBED_EVENTS` must add `contact.erased`. `reliability/engine_webhooks.py` then resubscribes, because a changed set reads as drift (`:277`).
- **Intake.** `apps/voice-runtime/signed_intake.py` `SIGNED_INTAKES["thinnest"].events` needs a route with `call_fields=()`, keyed on the event id like `lead.captured`, and a new job.
- **Adapter.** A `parse_contact_erased` in `engine/thinnest.py`, next to `parse_opt_out` (`:3680`).
- **Worker.** In `apps/workers/engine_customer_data.py`, `erase_engine_contact` leaves the `voice_engine` task `requested` when `recordingsPending > 0`, and says an operator must close it because the vendor "publishes no way to ask when the last one went". That is no longer true.
  - On `contact.erased`, find the task by `contactId`. `processor_erasure.record_engine_contact_progress` already keys progress by contact id.
  - Set that contact's pending count to 0, and `record_answer(... "confirmed")` when every contact is 0.
  - The 30-day overdue alarm text changes.
- **Delivery caveat.** The event goes only to endpoints in the client workspace that subscribed. Our endpoints are per agent (secret chosen by the `agent` query parameter). A client workspace with no published agent endpoint gets no delivery. Our URLs differ per agent, so "once per address" means one delivery **per agent endpoint**, and the inbox dedupe on `x-thinnest-event-id` absorbs the duplicates.
- **Developer workspace.** The developer workspace never sends erasures (D-691), so only client workspaces matter here.

## G. `byok.changed`

**Claim.** It is sent when a key is added, replaced, removed or fails verification, or when BYOK or
its default choice changes. It carries no key material.

**Docs.**

- **Event.** `byok.changed` is in the enum (`api-reference/webhooks/create-webhook.md:743`, `:802`).
- **Payload.** `{ "id", "event": "byok.changed", "sentAt", "data": { "change", "kind", "provider", "byokEnabled", "scope" } }` (`api-reference/webhooks.md:565-597`; `api-reference/webhooks/create-webhook.md:359-368`).
- **`change`.** One of:
  - `key_added`;
  - `key_replaced`;
  - `key_removed`;
  - `key_failed_verification` (the provider refused a key we tried to save; nothing was saved);
  - `byok_enabled`;
  - `byok_disabled`;
  - `scope_changed`.
- **`kind` and `provider`.** `kind` (`stt | llm | tts`) and `provider` name the key for the four key changes and are `null` for the other three.
- **`byokEnabled` and `scope`.** They say where the workspace stands **after** the change.
- **Not sent.**
  - A change of a key's model.
  - Saved keys are not re-checked on a schedule. A model key that stops working on a call still shows up only as `call.problem` `byok_failed`.
- **Delivery and signing.** Workspace delivery and signing as in F. "Neither event carries personal details or any part of a key" (`api-reference/webhooks.md:536-543`). Pointer from the BYOK page: `api-reference/bring-your-own-keys.md:180-185`.
- **What the email calls "fails verification".** It is `key_failed_verification`, a refusal **at save time**. It is not a key that later stops working. The docs are explicit that there is no scheduled re-check. So the email's wording is narrower than it reads, and the docs win.

**What this changes in our code.**

- **Subscription.** Add `byok.changed` to `SUBSCRIBED_EVENTS` (`apps/api/engine/thinnest_webhooks.py:50`).
- **Intake.** Add a route in `apps/voice-runtime/signed_intake.py` with `call_fields=()`.
- **Adapter.** Add a parser in `engine/thinnest.py`.
- **Worker.** The worker should trigger an immediate check of that workspace, then alarm on any change it did not make. The checks are:
  - `apps/workers/studio_voice_key.py` `sweep_studio_workspaces` (`:158`);
  - `apps/workers/own_model_key.py` `sweep_own_model_workspaces` (`:141`);
  - `apps/api/agents/studio_voices.py` `ensure_developer_studio` / `ensure_studio_workspace`.

  Examples of changes we did not make: `key_removed` or `byok_disabled` on a Studio workspace, or `scope_changed` away from `voice` / `llm_voice`.
- **Keep the hourly sweeps.** The event is not sent for a model change, and keys are not re-checked by the vendor.
- **Our own writes echo back.** The event fires on our own writes too: rotation, `ensure_*`, own-model install. Correlate it with our own recent writes before alarming.

## H. `own` on `GET /byok/voices`

**Claim.** `GET /byok/voices` marks our own account's voices `own: true`.

**Docs.** `own` is a required boolean on each voice (`api-reference/bring-your-own-keys/list-byok-voices.md:731-739`; examples `:484`, `:490`). Per provider (`api-reference/bring-your-own-keys.md:293`, `:301-310`):

- **Cartesia:** the voices our account owns, listed first.
- **ElevenLabs:** our cloned and designed voices.
- **Soniox:** always `true`.
- **Every other provider:** always `false`.

**What this changes in our code.**

- **Adapter.** `apps/api/engine/thinnest.py` `list_own_key_voices` (`:2989-3023`) says "No field marks which voices are our clones, so none is marked (`HostedVoice.is_custom` stays False here)". Set `is_custom=row.get("own") is True`.
- **Catalogue.** `apps/api/agents/hosted_voices.py` `sync_hosted_voices` then carries it into `platform_voice_catalog.is_custom` for `byok` rows.

## Other changes in this snapshot (not asked for)

These are not part of the reply. They are recorded so that the build lanes do not miss them.

- **`voice.speakingSpeed`.** 0.7–1.3, `null` for normal (`api-reference/agents/update-agent.md:1480-1492`; `channels/voice.md:153-167`). Studio voices, cloned voices and own-key voices keep their own pace. That is every Clear voice we sell on the Studio band, and every Studio voice.
- **Ear backchannel fields.** `backchannelDetection`, `backchannelWords`, `acknowledgements` and `acknowledgementWords` (`api-reference/agents/update-agent.md:1493-1525`). A filler spoken while the caller explains "is not part of the conversation record".
- **`voice.reaskAfterSeconds`.** Documented in `channels/voice.md:659` (null = 2.5 s, 0 = never, or 1.5–10 s). **No API schema in this snapshot defines it**, so whether the API accepts it is UNKNOWN.
- **Up to four reply languages.** The console offers this (`agent/behaviour.md:66-95`). No corresponding API field was found in `update-agent.md`.

## Still open after this reply

These are from `docs/vendor/thinnest-replies-2026-10-12.md`. The docs do not settle them either.

- **§13 question 1.** The live date of per-agent `byok` scopes.
- **§13 question 2, and §12.2 question 3.** Whether the summary and extraction run on our own LLM key. **Answered 18 Oct 2026:** no; they run on ThinnestAI's own light model on its account, and `usage` excludes them (`snapshots/2026-10-18/pages/api-reference/calls/get-call.md:1180-1181`; email, VENDOR-STATED).
- **§13 question 3, and §11.8 item 1.** The `byok-model` `409` wording. `set-agent-byok-model.md` changed only in its preamble.
- **§13 question 4.** The Standard plan's per-minute price. `standard` is now a documented `voicePlan` value, but no price is stated. **Answered 18 Oct 2026 (VENDOR-STATED, ThinnestAI email):** Standard ₹2.00/min, Premium ₹2.50, Studio ₹3.00 on pay-as-you-go and Pro; Scale 5% off for that workspace only; no further volume rate. Standard is not offered (founder, D-813).- **§13 questions 5–13.**
- **§13 questions 14–15.** Place Call `calling_not_set_up` and `callingAgent` surfaces. `place-call.md` changed only in its preamble.
- **New: the shared-clone id (D).** The same id in both workspaces, or a different one?
- **New: forwarded calls (A).** Is `billing` null, or does it show `voicePlan: standard`? **Answered 18 Oct 2026:** carrier fee only; `voicePlan` and `ratePerMinuteMicro` show the set-up plan, not what was charged; reconcile by `costMicro` (get-call.md:1236-1243 in the 18 Oct snapshot; email, VENDOR-STATED).
- **New: "free trial call" (A).** Whether it covers calls in our developer workspace that our own free-trial agents place. **Answered 18 Oct 2026:** no. Only a call paid from a free-plan workspace's trial minutes; our developer workspace is on a paid plan, so its test calls carry plan and rate (get-call.md:1246-1249; email, VENDOR-STATED).
