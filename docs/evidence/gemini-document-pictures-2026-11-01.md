# Pictures inside documents: the facts D-956 rests on (read 1 Nov 2026)

Every line below was read from the primary source on 1 Nov 2026, with the page's own date.
Anything the source does not say is marked UNKNOWN or REPORTED.

| Fact | Value | Source (page date) | Class |
|---|---|---|---|
| Images per request | "Gemini models support a maximum of 3,600 image files per request" | ai.google.dev/gemini-api/docs/image-understanding | VENDOR-PUBLISHED |
| Request size | "Inline image data limits your total request size (text prompts, system instructions, and inline bytes) to 20MB" | same | VENDOR-PUBLISHED |
| Order | "When using a single image with text, place the text prompt before the image" (the files prompt guide says the image may do better first; the two pages disagree, and we keep text first) | same; ai.google.dev/gemini-api/docs/files#prompt-guide (2026-10-26) | VENDOR-PUBLISHED |
| Prompting | Be specific; name the output format; few-shot examples help | ai.google.dev/gemini-api/docs/files#prompt-guide (2026-10-26) | VENDOR-PUBLISHED |
| Tokens per image, Gemini 3 | Default (`unspecified`) 1,120; low 280, medium 560, high 1,120. For documents "quality typically saturates at `medium`" | ai.google.dev/gemini-api/docs/media-resolution | VENDOR-PUBLISHED |
| OpenAI-compatible image part | `image_url` with `data:image/jpeg;base64,…`, one image shown; several images in one message is not shown | ai.google.dev/gemini-api/docs/openai (2026-10-28) | VENDOR-PUBLISHED (one image) / REPORTED (several) |
| Media resolution on the compatible surface | Not documented there | same | UNKNOWN |
| `gemini-3.5-flash-lite` limits | Input 1,048,576 tokens, output 65,536; text, image, video, audio, PDF in | ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite (2026-10-30) | VENDOR-PUBLISHED |
| `gemini-3.5-flash-lite` price | Standard paid: input $0.30 / 1M (text/image/video/audio), output incl. thinking $2.50 / 1M | ai.google.dev/gemini-api/docs/pricing (2026-10-30) | VENDOR-PUBLISHED |
| Thinking | "Reasoning cannot be turned off for Gemini 2.5 Pro or 3 models" (counts as output) | ai.google.dev/gemini-api/docs/openai (2026-10-28) | VENDOR-PUBLISHED |
| pypdf images | `page.images` yields `ImageFile` (`name`, `data`, `image`); iterating it "will raise an exception on the first issue", so read by key | pypdf.readthedocs.io/en/stable/user/extract-images.html; installed pypdf 6.21.2 | VENDOR-PUBLISHED |
| openpyxl images | Loaded only outside `read_only` mode, and only with Pillow; we read `xl/drawings` relationships ourselves instead | installed openpyxl 3.1.5, `openpyxl/reader/excel.py`, `reader/drawings.py` | VERIFIED-SOURCE |

## Cost of one picture

ESTIMATE from the published figures above, not measured on a live call:

- input: 1,120 image tokens plus about 75 tokens of shared prompt (4 pictures to a request)
  at $0.30 / 1M = about $0.00036;
- output: the transcription plus thinking. Thinking tokens are UNKNOWN until measured; at
  200 output tokens a picture, $0.0005.

So about $0.0009 a picture, under one US cent for a document's 20-picture cap. What a client
is billed is `billing/rates.llm_inr_per_ktok` on the operator-attested price, never this.

## Choices made from these facts

- 4 pictures to a request (`document_ocr.PICTURES_PER_REQUEST`), at most 14 MiB of pictures
  (`MAX_REQUEST_PICTURE_BYTES`), 6,000 output tokens a picture: inside the 20 MB and 65,536
  limits. A batch the compatible surface refuses is asked again one picture at a time.
- Pictures under 24 px on the short side or 100 px on the long side are skipped: on Gemini 3
  they cost the same 1,120 tokens as a page and hold no line of words.
- Repeated bytes in one document (a logo on each page) are read once.
