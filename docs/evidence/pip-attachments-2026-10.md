# Pip attachments (D-781) — sources read, 15 Oct 2026

What was read to build files-and-pictures for Pip, and what each source supports. Evidence
class per CLAUDE.md hard rule 11. "Search summary" means the page was not fetched and the
claim rests on a search engine's summary of it — REPORTED, not confirmed.

## Model providers

| Claim | Source | Class |
|---|---|---|
| Gemini takes PNG, JPEG, WebP, HEIC, HEIF; inline data limits the whole request to 20 MB; larger or reused files go through the Files API | ai.google.dev/gemini-api/docs/image-understanding (updated 2026-09-23) | VERIFIED-VENDOR-DOCS |
| Gemini bills an image ≤384 px on both sides at 258 tokens; larger images in 768×768 tiles of 258 tokens each; `media_resolution` is a Gemini 3 control | same page | VERIFIED-VENDOR-DOCS |
| "When using a single image with text, place the text prompt before the image" | same page, Tips and best practices | VERIFIED-VENDOR-DOCS |
| Gemini's OpenAI-compatible endpoint takes an image as an `image_url` part with a base64 `data:` URL after a text part; it documents `input_audio`; it documents no PDF input and no `detail` key | ai.google.dev/gemini-api/docs/openai (updated 2026-10-13) | VERIFIED-VENDOR-DOCS |
| Gemini 2.5 Flash input $0.30/M and 2.5 Flash-Lite $0.10/M for text, image and video alike; audio priced higher ($1.00 / $0.30); paid tier not used to improve products | ai.google.dev/gemini-api/docs/pricing (updated 2026-10-14) | VERIFIED-VENDOR-DOCS |
| PDF through the OpenAI-compatible endpoint: forum moderators say unsupported; a workaround via `image_url` is a user suggestion | discuss.ai.google.dev threads "OpenAI compatibility for pdf file" and "Document/Files understanding … with OpenAI SDK" | Search summary — REPORTED |
| Azure vision deployments take JPEG, PNG, GIF (first frame), WEBP; 10 images a chat request; 20 MB an image; `detail` low/high/auto, `auto` the default | learn.microsoft.com/en-us/azure/foundry/openai/how-to/gpt-with-vision (updated 2026-07-31) | VERIFIED-VENDOR-DOCS |
| gpt-4o-mini image cost: 2833 base tokens and 5667 per 512-px tile; `detail: low` costs the base only | developers.openai.com/api/docs/guides/images-vision | VERIFIED-VENDOR-DOCS (OpenAI's own page; Azure bills the same model by token) |

What follows for Pip: pictures are sent inline as `image_url` parts after the text, with no
`detail` key, on both legs; image tokens arrive inside `prompt_tokens` and are metered at the
model's attested input rate, which on Gemini 2.5 is the same rate as text (above). Audio is NOT offered: it is priced above text on Gemini while gpt-4o-mini
(the backup) does not take it, so metering it at the text rate would under-record cost (hard
rule 7). PDFs ARE offered, on Gemini only (next section).

## PDFs

| Claim | Source | Class |
|---|---|---|
| Gemini takes PDFs "up to 50MB or 1000 pages"; "Each document page is equivalent to 258 tokens"; read with "native vision"; inline is "best suited for smaller documents" | ai.google.dev/gemini-api/docs/document-processing (updated 2026-10-08; its example now uses the Interactions API) | VERIFIED-VENDOR-DOCS |
| `generateContent` / `streamGenerateContent?alt=sse`; `Part.inlineData` (`mimeType`, `data`), `functionCall` (`id`, `name`, `args`), `functionResponse` (`id`, `name`, `response`), `thoughtSignature`; `FunctionDeclaration.parametersJsonSchema` (exclusive with `parameters`); `usageMetadata` incl. `toolUsePromptTokenCount`, `thoughtsTokenCount`, `cachedContentTokenCount` | ai.google.dev/api/generate-content | VERIFIED-VENDOR-DOCS |
| REST key in header `x-goog-api-key` | ai.google.dev/gemini-api/docs/api-key (updated 2026-10-06) | VERIFIED-VENDOR-DOCS |
| Stateless callers must resend the model's turns "exactly as they were received" (signatures) | ai.google.dev/gemini-api/docs/thinking (updated 2026-10-14) | VERIFIED-VENDOR-DOCS |
| Which 2.5 models REQUIRE signatures on function calls | not stated on the pages read | UNKNOWN — they are replayed regardless |
| pdf.js advisories: GHSA-wgrm-67xf-hhpq (CVE-2024-4367, 2024) and GHSA-hq66-cqwq-w95j (CVE-2026-16633, affects >= 5.6.83, patched 6.2.108, needs scripting enabled) | github.com/mozilla/pdf.js/security/advisories | VERIFIED |
| pdfjs-dist 6.3.289: published 2026-08-29, integrity `sha512-ZHjSVpDa…`, no dependencies, `scripts: {}`, optional `@napi-rs/canvas` | npm registry (`npm view`, 15 Oct 2026) | VERIFIED |

## Storage

| Claim | Source | Class |
|---|---|---|
| R2 presigned URLs support GET, HEAD, PUT, DELETE; "POST (multipart form uploads via HTML forms) is not currently supported"; a signed `ContentType` fails `SignatureDoesNotMatch` on a mismatch; presigned URLs do not work with custom domains; expiry 1 s to 7 days | developers.cloudflare.com/r2/api/s3/presigned-urls/ (updated 2026-08-22) | VERIFIED-VENDOR-DOCS |
| "All objects stored in R2, including their metadata, are encrypted at rest" (AES-256, GCM, Cloudflare-managed keys) | developers.cloudflare.com/r2/reference/data-security/ (updated 2026-04-21) | VERIFIED-VENDOR-DOCS |
| Whether R2 enforces a signed `Content-Length` on a presigned PUT | not documented on the page above | UNKNOWN — moot after the founder routed uploads through the API |

## Upload security

| Claim | Source | Class |
|---|---|---|
| Allow-list extensions; "don't trust the Content-Type header as it can be spoofed"; signature validation "should not be used on its own"; random server-generated names; store outside the webroot / on another server; set a size limit; antivirus or sandbox "if available"; CDR for documents | cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html | VERIFIED (OWASP) |
| Prompt injection can ride images ("hiding instructions in images that accompany benign text"); mitigations: segregate untrusted content, constrain behaviour, human approval for privileged actions | genai.owasp.org/llmrisk/llm01-prompt-injection/ | VERIFIED (OWASP) |
| Pillow 12.3: `MAX_IMAGE_PIXELS` / `DecompressionBombError`; `Image.open` is lazy | pillow.readthedocs.io/en/stable/reference/Image.html | VERIFIED — not used in the final design (no server-side image decode) |
| iOS used to transcode HEIC to JPEG on every file input; since WebKit bug 267277 (fixed 2024-03-05) only when the input's image types are restricted and exclude HEIC | bugs.webkit.org/show_bug.cgi?id=267277 | VERIFIED-VENDOR (bug tracker) |
| clamd needs 3 GiB minimum, 4 GiB preferred; ~1.2 GiB to load signatures and ~2.4 GiB briefly at each daily reload; "2GB may be insufficient" | docs.clamav.net/manual/Installing/Docker.html (RAM figures dated 2020-09-20) | VERIFIED-VENDOR-DOCS (dated) — recorded for the scanner decision; no scanner was built |

## Chat-file retention elsewhere

| Claim | Source | Class |
|---|---|---|
| ChatGPT: deleting a chat removes it at once and permanently within 30 days; uploaded files saved to the Library are kept separately until deleted; some transient files expire after 48 hours on Enterprise | help.openai.com/en/articles/8983778 | Search summary — REPORTED |
| Claude and Gemini consumer apps | not read | UNKNOWN |

## Law (India)

| Claim | Source | Class |
|---|---|---|
| DPDP Act 2023 s.8(1): a Data Fiduciary is responsible "irrespective of any agreement to the contrary" for processing by it or on its behalf by a Data Processor | dpdpa.com/dpdpa2023/chapter-2/section8.html (a reproduction; the MeitY PDF refused this environment with 403) | REPORTED-REPRODUCTION — check against the Gazette |
| s.8(2): a processor only "under a valid contract"; s.8(5): the fiduciary takes reasonable security safeguards, including for processing by its processor | same | REPORTED-REPRODUCTION |
| DPDP Rules 2025 rule 6 (security safeguards) and its commencement | search summaries of dpdp.myndsolution.com and practitioner notes; Gazette G.S.R. 846(E) not read | REPORTED |

## Upload clauses of large AI providers

| Claim | Source | Class |
|---|---|---|
| Anthropic Commercial Terms: customer "represents and warrants that it has all rights and permissions required to submit Inputs"; customer defends Anthropic against claims related to customer's Inputs | anthropic.com/legal/commercial-terms (effective 17 Jun 2025) | VERIFIED |
| Gemini API terms: "Do not submit sensitive, confidential, or personal information to the Unpaid Services"; paid prompts not used to improve products and logged for a limited period | ai.google.dev/gemini-api/terms (updated 2026-04-28) | VERIFIED |
| OpenAI terms | openai.com refused this environment (403) | UNKNOWN |

What follows for the legal text (D-781): under s.8(1) the client, as Data Fiduciary, already
carries the statutory responsibility for what its people attach, whatever a contract says, and
we as processor cannot contract out of the security and deletion duties our DPA gives it. So
the documents do not say "Calevate is not responsible". They say: the client warrants the right
to share, the notice and the consent; the client should keep personal data out of questions
that do not need it; files are sent as they are to the assistant's model provider; Calevate does
not review, redact or scan them; the content and its lawful basis are the client's
responsibility, under the existing indemnity; and our own security and deletion duties stand.
This is drafting by engineers from primary and reproduced sources, not legal advice; counsel
should review it.
