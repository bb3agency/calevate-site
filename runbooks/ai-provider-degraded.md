# A platform AI provider's main leg is failing (`ai_provider_degraded`)

You were mailed because one of our own AI providers has failed 3 times in 10 minutes, or 3
times in a row, on one leg. Nothing is down yet, but the product is degraded:

| `leg` | What the client notices while it lasts |
| --- | --- |
| `copilot` | The assistant answers on the disclosed standby (`ai_assist_unmetered_fallback` in the log), without tools. |
| `standby` | The Sarvam standby itself is failing: when the main model also fails, the assistant has no answer left. |
| `extraction` | Post-call rows land without fields or a summary (`errors._model`), or the dashboard assist falls back. |
| `embeddings` | New knowledge and caller history stay `pending`; dashboard search answers from the keyword arm only. |
| `memory`, `kb_gloss`, `ocr`, `script` | Background distillation, Telugu glosses, document OCR or script drafts stop landing. |

The mail repeats every hour while the episode is open, and one `cleared` mail arrives when
the provider answers again. The full history is on `/admin/ops/alerts`.

## 1. Read `status` on the mail

- `429` — our quota or rate limit on that provider. Check the provider console for the
  account's limits and billing.
- `401` / `403` — the key was revoked, rotated or lost a permission. Reinstall it in the ops
  console.
- `5xx`, or `none` (a timeout or transport failure) — the vendor is failing. Check their
  status page.
- `400` / `404` — usually our configuration: a model id or Azure deployment that does not
  exist. Search the logs for `azure_deployment_not_found`.

**`provider: sarvam` — check the Sarvam credit balance first.** Sarvam credits are
prepaid and the API returns errors once they run out (sarvam.ai/api-pricing, read 10 Oct
2026); the exact status and error body for that case have not been verified here, so this
alarm fires on any repeated failure and the `status` is what to compare. A Sarvam outage
stops the assistant's standby AND post-call extraction at once. Top up in the Sarvam
dashboard; payments are non-refundable.

`error` is the exception class (`HTTPStatusError`, `ReadTimeout`, `ConnectError`, ...).

## 2. Search the logs

The failing call sites log the same `status`, `error` and `provider`:
`copilot_provider_failed`, `extraction_failed`, `query_embedding_failed`,
`document_ocr_provider_error`, `script_assist_azure_failed`. No body is ever logged.

## 3. Nothing to replay

Every leg already recovers its own work: extraction re-drives `_model` rows, embeddings and
glosses re-sweep `pending`, the assistant answered on its standby. Fix the provider; the
`cleared` mail confirms it.

The counting lives in `apps/api/core/provider_health.py` (Redis keys `provider_health:*`).
If Redis is down the alarm cannot open; the failures are still logged.
