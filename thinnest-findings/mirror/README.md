# ThinnestAI documentation mirror (read-only)

This is a byte-exact snapshot of the ThinnestAI developer documentation. ThinnestAI is our voice engine (D-678; the only one since D-763).

This mirror is the **VERIFIED-VENDOR-DOCS** evidence class for every ThinnestAI claim in this repository. Cite it as `thinnest-findings/mirror/pages/<path>.md:<line>`.

## Source

- **Vendor:** ThinnestAI, at `https://docs.thinnest.ai/`.
- **Page list:** every `.md` link in `https://docs.thinnest.ai/llms.txt`, the docs site's own index, saved here as `llms.txt`.
- **Fetching:** each page was fetched as raw Markdown at its listed `.md` URL on 6 Oct 2026. The per-run UTC timestamp is in `MANIFEST.json`.
- **Result:** 90 of 90 pages fetched, with no failures.

## Layout

| Path | What it is |
| --- | --- |
| `pages/<path>.md` | One page per docs URL, with its path preserved (`/api-reference/agents.md` becomes `pages/api-reference/agents.md`) |
| `llms.txt` | The docs site's index, as fetched |
| `MANIFEST.json` | The URL, path, sha256 and byte count of every page |

## Rules

- **Never edit, reformat or move a file here.**
  - Ruff excludes this tree (`pyproject.toml`).
  - Git stores it with `-text` (`.gitattributes`), so line endings are never rewritten.
  - The large-file hook skips it (`.pre-commit-config.yaml`).
- **Refreshing the mirror is a new fetch and a new MANIFEST, committed as one change.** Pages cited by line number must then be re-checked.
- **What the docs do not say is not evidence.** Several commercial terms are founder-relayed and recorded in `docs/evidence/thinnest-ai-evaluation.md` with their own evidence class, never as documentation:
  - BYOK at ₹1/min including telephony;
  - concurrency raised on request;
  - the per-minute prices quoted on the call.

## Snapshot of 7 Oct 2026 (`snapshots/2026-10-07/`)

The docs site was restructured after the first fetch. `llms.txt` now lists 252 pages, and the API reference is split into one page per endpoint. For example, `api-reference/get-call.md` moved to `api-reference/calls/get-call.md`; most old paths now return an empty page.

`snapshots/2026-10-07/` is a complete new fetch with its own `llms.txt` and `MANIFEST.json` (252 of 252 pages, 0 failures). The pages under `pages/` are unchanged, so existing line citations into them stay valid as a record of what the docs said on 6 Oct 2026. **Cite the snapshot for anything current**: `thinnest-findings/mirror/snapshots/2026-10-07/pages/<path>.md:<line>`.

Facts that are new in the snapshot, or that it changes:
- **BYOK** has a full API (`api-reference/bring-your-own-keys/*`) and per-agent BYOK model and voice (`agents/set-agent-byok-*`). Every BYOK endpoint takes `Thinnest-Workspace`. It is still all three keys or none (`agents/set-agent-byok-voice.md:155-157`).
- **Customers** (`api-reference/customers*`, `guides/build-a-platform.md`) are isolated workspaces per end customer, addressed with the `Thinnest-Workspace` header. One `includeCustomers` webhook covers all of them, with `data.workspaceId` in the signed body.
- **Webhooks:** deliveries are `{event, sentAt, data}`, so a signed send time is in the body (`webhooks/create-webhook.md:162`).
- **Call log:** `GET` usage call log carries `costMicro`, the amount actually charged per call (`usage/list-call-log.md:533-540`).
- **Phone numbers:** they can be rented, imported and released through the API, and carrier accounts can be saved for `plivo`, `vobiz`, `twilio` and `telnyx` (`phone-numbers/*`).

**One deliberate edit in the snapshot.** In `snapshots/2026-10-07/pages/api-reference/phone-numbers/save-carrier-account.md`, the vendor's example Twilio account id (an `example:` value, lines 278 and 380) is replaced with `ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`, at the same byte length. GitHub push protection reads any value of that shape as a credential and refuses the push. `MANIFEST.json` carries the hash of the edited file. Every other byte is as fetched.

## Snapshot of 7 Oct 2026, evening (`snapshots/2026-10-07b/`)

This is a full re-fetch after ThinnestAI's founder answered our questions: 268 of 268 pages, 0 failures, with its own `llms.txt` and `MANIFEST.json`. New pages since `2026-10-07/`:
- `agent/after-the-call`;
- `api-reference/do-not-call/*`;
- `api-reference/sms/*`;
- `api-reference/webhooks/redeliver-webhook-events`;
- `channels/sms`;
- `guides/text-the-caller`.

Example account ids of the form `AC` + 32 hex were masked at fetch time (one file), for the push-protection reason above, and the manifest hashes are of the masked files. Cite this snapshot for anything current. What it confirms and contradicts in the founder's email is in `docs/evidence/thinnest-ai-evaluation.md` §10.

## Snapshot of 8 Oct 2026 (`snapshots/2026-10-08/`)

A full re-fetch on 8 Oct 2026 (UTC run 09:57–10:02, `generated_at` in its `MANIFEST.json`): 271 of 271 pages, 0 failures, every page served as `text/markdown`, with its own `llms.txt` and `MANIFEST.json`. As before, example account ids of the form `AC` + 32 hex were masked at fetch time (one file, `api-reference/phone-numbers/save-carrier-account.md`, lines 359 and 463, same byte length), and the manifest hashes are of the masked files. Cite this snapshot for anything current.

Against `2026-10-07b/`: 3 pages added, 0 removed, 196 changed.
- **Added:** `api-reference/phone-numbers/get-business-details`, `api-reference/phone-numbers/send-business-details` (`GET`/`PUT /phone-numbers/business-details`, multipart: legal name, GST yes/no, one document), `workspace/data-and-erasure`.
- **Changed only in the OpenAPI preamble every API page embeds (170 pages):** the spec title (`API` → `ThinnestAI API`), the BYOK tag text (per-agent `byok: "off"`), and the shared error responses, which now carry `code` (and a `limit` object on `429`). No endpoint on those pages changed. This includes every `webhooks/*` page, `tools/update-built-in-tools`, `do-not-call/*`, `recordings/*` and `calls/get-call*`.
- **Changed in substance (26 pages):** `agent/behaviour`, `channels/voice`, `channels/phone-numbers`, `guides/multilingual`, `api-reference/errors`, `api-reference/bring-your-own-keys`, `api-reference/bring-your-own-keys/list-byok-voices`, `api-reference/agents/{create,update,get,list}-agent(s)`, `api-reference/agents/get-agent-byok-{model,voice}`, `api-reference/calls/place-call`, `api-reference/calls/place-batch-calls`, `api-reference/contacts/delete-contact`, `api-reference/messages/send-message`, `api-reference/one-time-codes/send-one-time-code`, `api-reference/phone-numbers/rent-phone-number`, and a `validation_failed` code added to the `400` example of eight list endpoints (`actions`, `do-not-call`, `invitations`, `code-templates`, `projects`, `saved-replies`, `sequences`, `teams`).

What moved, by topic (paths are under `snapshots/2026-10-08/pages/`):
- **Webhook headers and signature: unchanged since `2026-10-07b`.** `api-reference/webhooks.md` is byte-identical. `x-thinnest-signature-v2` is "`sha256=` + hex HMAC-SHA256 of `<x-thinnest-delivered-at>.<raw body>`" (`api-reference/webhooks.md:105`).
- **`secondLanguage` retired.** On requests it is "Retired. Accepted so an older integration keeps working, but ignored", `deprecated: true` (`api-reference/agents/update-agent.md:566-573`); on responses "Retired — always `null`" (`:688-695`). `voice.language` is unchanged.
- **Per-agent BYOK.** A new agent field `byok: workspace | off`, default `workspace` (`api-reference/agents/update-agent.md:596`, `:720`; prose in `api-reference/bring-your-own-keys.md`). While an agent is `off`, its `byok-model`/`byok-voice` reads answer `409`.
- **`null` is the reset.** `model: null` returns to the default model "(Prana [Voice])" and `voice.voice: null` to the default voice "(currently Kavya, a Premium voice …)"; an empty string is a `400` (`api-reference/agents/update-agent.md:535`, `:952`; `channels/voice.md:124-127`).
- **New `voice.unavailableMessage` / `unavailableMessageNote`.** This is what a caller hears when the line is switched off, up to 300 characters. It is spoken on Plivo and Twilio only, and "a Vobiz number gets no message (the call is declined as before)" (`api-reference/agents/create-agent.md`, `AgentVoiceInput`; `channels/voice.md`, "When Answer calls is off"). Creating a voice channel through these fields now leaves it switched OFF.
- **Live call transfer.** `channels/voice.md:483-492` replaces "The agent cannot put a caller through to a person" with a note that it can on phone calls "over a number we rent you, or a Plivo or Telnyx number you brought", via `PATCH /agents/{id}/tools` with `handOver` and `tools.escalate_to_human`. That endpoint's page itself is unchanged since `2026-10-07b`.
- **Errors.** Every error body is now `{error, code}` with an optional `limit` on `429` (`api-reference/errors.md:9-15`, `:39-54`). The full code list is in the `Error` schema (55 codes) and in tables at `api-reference/errors.md:75-177`. `place-call` names `CallConflict.code` and `CallNoBalance.reason`, and `place-batch-calls` names `CallBatchRefused.code`.
- **Business details.** India number rental now has an API (the new pages above; `channels/phone-numbers.md`, "Doing it from the API"). It needs a full key and a paid plan.
- **Contacts delete.** It now says recordings are erased too: stored audio, the carrier's copy on a rented number, and any training copy. A failed deletion is retried nightly, and a `200 {recordingsPending}` is returned when some remain. A `503` means nothing was deleted. Do-not-call entries are deliberately kept (`api-reference/contacts/delete-contact.md:9-11`, `:345-414`; `workspace/data-and-erasure.md`). The new page also says that on pay-as-you-go a copy of recordings and transcripts "may be kept to improve our speech and language models" unless the workspace asks to be excluded (`workspace/data-and-erasure.md:67-77`).
- **Unchanged in substance:** `do-not-call/*`, `recordings/*`, `calls/get-call*`, `calls/cancel-call` (`DELETE /calls/{id}` still only cancels; an ended call answers `409`), and `pastConversations` (`fresh | quiet | recap`). No endpoint deletes a single call, recording or conversation.

## Snapshot of 13 Oct 2026 (`snapshots/2026-10-13/`)

A full re-fetch on 13 Oct 2026 (UTC run 15:17–15:22, `generated_at` in its `MANIFEST.json`): 282 of 282 pages, 0 failures, every page served as `text/markdown`, with its own `llms.txt` and `MANIFEST.json`. The example account id of the form `AC` + 32 hex was masked at fetch time (one file, `api-reference/phone-numbers/save-carrier-account.md`, lines 430 and 534, same byte length), and the manifest hashes are of the masked file. Against `2026-10-08/`: 11 pages added, 0 removed, 212 changed. Cite this snapshot for anything current.

What it settles, claim by claim against Ashutosh's 13 Oct email, is in `docs/evidence/thinnest-docs-snapshot-2026-10-13.md`. The facts Calevate builds on: the own-key scopes `all | voice | llm_voice | llm` with their prices (`api-reference/bring-your-own-keys.md:16-28`), the LLM key on `PUT /byok/credentials` with `kind: "llm"`, the per-agent `byok` scope and `byok-model`, `usage` token counts on Get Call and `call.analysed`, own-key failures as `call.problem` kind `byok_failed` (there is no `byok.failed` webhook), `voice.turnDetection`, `voice.recordDoNotCall`, the `contact.opted_out` `data.reason`, and the own-voice tuning fields. Open questions against it are in `docs/vendor/thinnest-replies-2026-10-12.md` §11.8.

## Snapshot of 15 Oct 2026 (`snapshots/2026-10-15/`)

A full re-fetch on 15 Oct 2026 (UTC run 16:48–16:56, `generated_at` in its `MANIFEST.json`): 284 of 284 pages, 0 failures, every page served as `text/markdown` with HTTP 200, with its own `llms.txt` and `MANIFEST.json`. The example account id of the form `AC` + 32 hex was masked at fetch time (one file, `api-reference/phone-numbers/save-carrier-account.md`, lines 473 and 577, same byte length), and the manifest hashes are of the masked file. Against `2026-10-13/`: 2 pages added, 0 removed, 212 changed. Cite this snapshot for anything current.

- **Added:** `api-reference/post-call/delete-call-content` (`DELETE /calls/{id}/content`) and `agent/find-leads` (a lead-search product we do not use).
- **Changed only in the OpenAPI preamble every API page embeds (about 190 pages):** the Webhooks tag text now lists `contact.erased` and `byok.changed`, describes `data.billing` on `call.analysed`, and adds "Workspace events". No endpoint on those pages changed.
- **Changed in substance:** `calls/get-call`, `calls/list-calls`, `calls/cancel-call` (`billing`, `usage.inputTokensEstimated`, `usage.ttsCharacters`, `contentDeleted`, `contentDeletedAt`), `webhooks` and `webhooks/create-webhook` (two new events), `workspace/{get,update}-workspace` (`callRetentionDays`, `planRetentionDays`), `voices/list-voices` (`sharedFromDeveloper`), `bring-your-own-keys` and `bring-your-own-keys/list-byok-voices` (`own`), `contacts/delete-contact`, `customers`, `channels/voice-clone`, `workspace/data-and-erasure`, `agents/{create,update,get,list}-agent(s)` (`voice.speakingSpeed`, Ear backchannel fields), `channels/voice`, `agent/behaviour`, `agent/leads`, `guides/how-your-agent-sounds`, `guides/multilingual`, `mcp/tools` and `whats-new/index` (entries for 14 and 15 Oct).

What matters to us (paths under `snapshots/2026-10-15/pages/`; the item-by-item check of ThinnestAI's 15 Oct email is `docs/evidence/thinnest-reply-2026-10-15.md`):
- **Per-call billing.** Get Call and `call.analysed` carry `billing {keys, voicePlan, ratePerMinuteMicro, billedSeconds, currency}`; `voicePlan` is lower-case `standard | premium | studio | null` (`api-reference/calls/get-call.md:1228-1294`). `keys` is the stack the call ran on as set up at its start, which is after any fallback (`:1240-1252`, `:200-203`).
- **Usage.** `usage.inputTokensEstimated` and `usage.ttsCharacters` (`api-reference/calls/get-call.md:1171-1227`), both null on calls before 15 Oct.
- **Deleting one call's content.** `DELETE /calls/{id}/content` returns `{contentDeleted, contentDeletedAt, recordingsPending, call}` and keeps the billing record (`api-reference/post-call/delete-call-content.md:443-533`, `:565-589`). `DELETE /calls/{id}` still only cancels.
- **Retention.** `PATCH /workspace {callRetentionDays}`: 1 up to `planRetentionDays` (30 PAYG, 49 Pro, 75 Scale, 365 Enterprise); `null` keeps recordings for the plan and transcripts with no end (`api-reference/workspace/update-workspace.md:541-553`, `:582-599`).
- **Workspace webhooks.** `contact.erased {contactId, erasedAt}` and `byok.changed {change, kind, provider, byokEnabled, scope}`, delivered once per address to every subscribed endpoint in the workspace, signed like every other delivery (`api-reference/webhooks.md:536-597`, `:210-226`).
- **Clones shared with customers.** A developer's clones are listed in each customer workspace's `GET /voices` with `sharedFromDeveloper: true`, count against the developer's limit only, and cannot be renamed or deleted there (`api-reference/voices/list-voices.md:579-589`; `channels/voice-clone.md:114-126`).
- **Own voices marked.** `GET /byok/voices` rows carry `own` (`api-reference/bring-your-own-keys/list-byok-voices.md:731-739`).
- **Not used yet:** `voice.speakingSpeed` 0.7–1.3 (Studio, cloned and own-key voices ignore it, `channels/voice.md:153-167`); the Ear backchannel fields (`api-reference/agents/update-agent.md:1480-1525`); `voice.reaskAfterSeconds`, which `channels/voice.md:659` documents but no API schema in this snapshot defines; and up to four reply languages in the console (`agent/behaviour.md:66-95`), with no matching API field found.
