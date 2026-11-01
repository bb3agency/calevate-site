# Gemini embeddings: the facts D-952 rests on (read 1 Nov 2026)

Every line below was read from Google's own pages on 1 Nov 2026 with the page date stated.
Anything Google's page does not say is marked UNKNOWN.

| Fact | Value | Source (page date) | Class |
|---|---|---|---|
| Model | `gemini-embedding-2`, listed Stable, latest update April 2026 | ai.google.dev/gemini-api/docs/models/gemini-embedding-2 (2026-10-29) | VENDOR-PUBLISHED |
| Retirement | "No shutdown date announced"; `gemini-embedding-001` shuts down 14 May 2028 with `gemini-embedding-2` as its replacement | ai.google.dev/gemini-api/docs/deprecations (2026-10-22) | VENDOR-PUBLISHED |
| Input limit | 8,192 tokens per input (`gemini-embedding-001`: 2,048) | ai.google.dev/gemini-api/docs/embeddings (2026-10-29) | VENDOR-PUBLISHED |
| Output width | 128 to 3,072; 768, 1,536, 3,072 recommended; default 3,072 | same | VENDOR-PUBLISHED |
| Normalisation | "Gemini Embedding 2 also auto-normalizes truncated dimensions (e.g., 768, 1536)" — the caller does not normalise (`gemini-embedding-001` requires manual normalisation) | same | VENDOR-PUBLISHED |
| Task types | `task_type` is not supported on `gemini-embedding-2`; the task is a text prefix: query `task: search result \| query: {content}`, document `title: {title} \| text: {content}` (`title: none` without a title) | same | VENDOR-PUBLISHED |
| Endpoint | Native `POST /v1beta/models/{model}:batchEmbedContents`, `requests[]` each with `model`, `content`, `embedContentConfig.outputDimensionality`; response `embeddings[]` "in the same order as the input" and `usageMetadata.promptTokenCount`; key in `x-goog-api-key` | ai.google.dev/api/embeddings (2026-10-26); ai.google.dev/gemini-api/docs/embeddings (2026-10-29) | VENDOR-PUBLISHED |
| Body accepted | `embedContentConfig.outputDimensionality` passes Google's request parser (an unknown field is refused with 400 before authentication; this body reaches the 403 "unregistered callers" check) | `curl` without a key, 1 Nov 2026 | VERIFIED-LIVE (parse only, no live embedding) |
| OpenAI-compatible `/v1beta/openai/embeddings` | Documented with a single string; documents neither `dimensions` nor `usage`. Not used: the width and the token count must be documented | ai.google.dev/gemini-api/docs/openai (2026-10-28) | VENDOR-PUBLISHED |
| Batch size limit | UNKNOWN: the reference states no maximum. We send 32 (`EMBED_BATCH`) | ai.google.dev/api/embeddings (2026-10-26) | UNKNOWN |
| Languages | "over 100 languages"; Telugu and Hindi are not named. Telugu quality: UNKNOWN until measured (`docs/evidence/telugu-embedding-quality.md`) | ai.google.dev/gemini-api/docs/embeddings (2026-10-29) | VENDOR-PUBLISHED / UNKNOWN |
| Price | Paid tier, standard: $0.20 per 1M text input tokens (batch API $0.10). `gemini-embedding-001`: $0.15 | ai.google.dev/gemini-api/docs/pricing (2026-10-30) | VENDOR-PUBLISHED |
| Training | Pricing page: "Used to improve our products" free tier Yes, paid tier No. Terms, Paid Services: Google does not use prompts or responses to improve its products and logs them for a limited period only to detect Prohibited Use Policy violations; no sentence names embeddings specifically | ai.google.dev/gemini-api/docs/pricing (2026-10-30); ai.google.dev/gemini-api/terms (2026-04-28) | VENDOR-PUBLISHED |
| Flex tier | Not listed for any embedding model | ai.google.dev/gemini-api/docs/flex-inference (2026-10-13) | VENDOR-PUBLISHED |

## How the repo uses it

- `retrieval/embedding.EMBEDDING_MODEL = "gemini-embedding-2"`, `EMBEDDING_DIMS = 1536`
  (the existing `vector(1536)` columns; no migration).
- The catalogue price (`calevate_shared.engine.EMBEDDING_MODELS`) is filed `verified=False`
  like every Gemini price, so nothing is billed until an operator attests it in the ops
  console (hard rule 7).
- The leg runs only with `GEMINI_API_KEY` and the Google data-use attestation
  (`llm_models.client_content_data_use_reason`).
- Embeddings run only for accounts whose owner turned Pip on (`copilot/consent`, read by
  `retrieval/embedding.tenant_allows_embedding` in both sweeps and on the query path), so the
  sub-processor page's promise that nothing reaches the language-model providers before then
  stays true. Other accounts search by keyword; their rows stay `pending` until consent.
- Rows embedded under any other model are re-claimed by both sweeps (`embed_model IS DISTINCT
  FROM :model`), and the dense search arm reads only vectors whose `embed_model` and
  `embed_dim` match the question's.
