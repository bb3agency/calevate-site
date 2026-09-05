"""Photographs of documents → the text in them, through a model leg we already hold.

The founder's instruction, verbatim: *"we will use api calls for OCR of text in images
and if the OCR is not accurate we will discard that image file"*. This module is the
first half. The second half — what "not accurate" MEANS — is the interesting half, and
the answer this module implements is that **a person confirms the text before it can
become knowledge**; everything mechanical here is a filter in front of that, never a
substitute for it. See `_legibility_reason` and `ExtractedText.needs_confirmation`.

═══ WHICH LEG, AND WHY ═══

**No new vendor** (CLAUDE.md's "Do NOT"), so the question is which of the credentials
this product already holds can read a document photograph. Three legs are declared —
`azure_openai`, `openai`, `google` — plus Sarvam on the speech leg.

**CHOSEN: `gemini-2.5-flash` on the existing Google leg**, over
`google_openai_compat_base_url()`, through `apps/workers/chat.py` — the same transport,
the same dialect and the same `gemini_api_key` the dashboard copilot already uses (D-478).
No new client, no new host literal, no new credential.

What is VERIFIED about it, with the evidence class each fact carries:

* **The leg takes images at all.** VERIFIED-VENDOR-API: Google's own Gemini Developer API
  discovery document (`https://generativelanguage.googleapis.com/$discovery/rest?version=
  v1beta`, revision `20260904`) documents `Blob.mimeType` accepting `image/png`,
  `image/jpeg`, `image/webp`, `image/heic`, `image/heif`, `image/avif` (and
  `application/pdf`). Fetched from THIS container on 4 Sep 2026 — the host is reachable
  here, unlike `ai.google.dev`. `calevate_shared.document_ingest.OCR_IMAGE_MIME_TYPES`
  carries the set.
* **The price.** VENDOR-PUBLISHED: Google's own pricing page
  (`https://cloud.google.com/vertex-ai/generative-ai/pricing`, which serves
  `cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing`, read
  4 Sep 2026) lists Gemini 2.5 Flash input (text, image, video) at **$0.30 / 1M tokens**
  and text output at **$2.50 / 1M**, and Gemini 2.5 Flash Lite at $0.10 / $0.40 — the
  same figures already in `calevate_shared.engine.LLM_MODELS`. The same page states the
  image tokenization: *"For an 1024x1024 image, it consumes 1290 tokens"*, and *"PDFs are
  billed as image input, with one PDF page equivalent to one image."* See
  `estimated_page_cost_usd` below for what that makes a page cost.
* ⚠ **UNVERIFIED, and it is the wire shape:** whether the OpenAI-COMPATIBILITY surface
  accepts an image as an OpenAI `image_url` content part with a `data:` URI. Google's own
  page saying so (`ai.google.dev/gemini-api/docs/openai`) is EGRESS-BLOCKED from this
  container; a web search returned a summary of it, which is a summary and not a reading.
  It is therefore REPORTED, not confirmed, and it is settled by one call with a real key —
  which is why `_transcribe` treats a provider error as a per-image discard with a named
  reason rather than as a crash, and why `OcrUnavailableError` exists for the operator.
* ⚠ **UNKNOWN, and it is the one that matters most for this market: how well any of these
  legs reads TELUGU SCRIPT out of a photograph.** Google publishes that Gemini supports
  Telugu as a LANGUAGE; that is a different claim from "it transcribes Telugu script off a
  photo of a menu accurately", and no primary source read this session makes the second
  one. **This is precisely why the accuracy gate is a human and not a threshold.** Nobody
  has to be right about OCR quality: the client reads the extracted text back and says
  whether it is their menu. An operator can close the gap for good with one measurement —
  photograph a real Telugu menu, run it, diff — and until somebody does, this module
  claims nothing about it.

REJECTED, each with its reason:

* **Sarvam Doc AI.** It exists and it is aimed exactly at this problem — VERIFIED-VENDOR-SDK,
  `sarvamai` 0.1.32 (PyPI wheel `sarvamai-0.1.32-py3-none-any.whl`, sha256
  `00a3672d141b8f43dc4ee3d40627cf97981ccd81892fb53b63f7478ed06d8ffc`, read 4 Sep 2026):
  `doc_ai.digitise(file=…, language=<BCP-47>, content_type="printed"|"handwritten"|
  "mixed", output_format="html"|"md"|"json")`, an Indian vendor with an Indic-first
  product. It is not chosen TODAY on three grounds, none of them "it is worse": (a) its
  PRICE is UNKNOWN — `sarvam.ai` and `docs.sarvam.ai` are egress-blocked from this
  container, so nothing can price it and hard rule 7 has nothing to bill from; (b) it is
  an ASYNCHRONOUS JOB API (`POST` a job, poll `GET /doc-ai/v1/job/{id}/status`, then fetch
  results) — a second polling machine beside `engine_reconciliation`, against one
  synchronous call for Gemini; (c) Sarvam's ToS v2.0 s.17.5 permits training on Inputs and
  Outputs absent a signed order form, which we do not have (CLAUDE.md records the reading),
  and a client's whole price list is a bigger input than a call transcript. If (a) and (c)
  are answered it is the better product for this job and should be revisited — it is a
  decision-log entry away, not a rewrite, because the seam is `ExtractedText`.
* **Azure OpenAI / OpenAI direct.** Both hold vision-capable models and would work. Neither
  is chosen because neither is cheaper or better-evidenced for INDIAN SCRIPT than the
  Google leg, and the Azure leg's deployment is a single deployed model (`AZURE_OPENAI_
  DEFAULT_MODEL`) that the whole in-call path depends on — putting a bulk image workload
  through the same deployment's quota is a way to make a phone call slow.
* **Google Cloud Vision / Document AI.** A genuinely excellent OCR, and it is a NEW VENDOR
  SURFACE despite the shared word "Google": a GCP project, billing account, service-account
  credential and API this tree has never spoken. "No new vendor" is about the credential
  and the contract, not the brand.
* **A self-hosted OCR (tesseract, PaddleOCR, docTR).** A new deployable, a model download
  and a CPU budget in a worker — refused by the same rule that refuses LibreOffice.

═══ WHAT THIS MODULE NEVER DOES ═══

Log the text, log a filename, or put either in an exception (hard rule 6). What it logs is
counts and outcome codes. The images themselves are a client's business document; they go
to the same provider the dashboard copilot already speaks to, and the sub-processor
disclosure for that leg is the legal lane's to keep current — this module names the leg so
that it can be.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

import httpx
from calevate_shared.document_ingest import (
    MAX_IMAGE_BYTES,
    MAX_OCR_IMAGES,
    OCR_IMAGE_MIME_TYPES,
    DocumentTooLargeError,
    ExtractedText,
    OcrUnavailableError,
    OcrUnusableError,
)
from calevate_shared.engine import (
    DOCUMENT_OCR_MODEL,
    LLM_MODELS,
    google_openai_compat_base_url,
)

from apps.api.agents.llm_models import client_content_data_use_reason, unofferable_reason
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.workers import chat

log = get_logger(__name__)

#: The model that reads the photographs, read back from the catalogue that declares it.
#:
#: NOT SPELLED HERE. `calevate_shared.engine.DOCUMENT_OCR_MODEL` carries both the id and the
#: argument for choosing the dearer of the two 2.5 flash models, for the reason
#: `tests/sarvam_model_identifier_test.py` states over every model identifier in this tree:
#: a literal at the call site is a second source of truth that drifts the day the catalogue
#: id changes, on a leg where a stale id is a silent 404. Re-exported under the module's own
#: vocabulary is deliberately NOT done — one name, one home.

#: One image, one call. The alternative — all of a document's pages in one request — is
#: cheaper by one round trip and is refused, because the founder's rule is per-IMAGE
#: ("discard that image file") and a single blended answer cannot say WHICH page came back
#: garbled. Per-image calls make the discard decision the same shape as the instruction.
#:
#: Sequential rather than concurrent, deliberately: a burst of twenty parallel image
#: requests is the shape a provider rate-limits, and the deadline below already bounds the
#: total. If measurement ever shows the deadline biting, bounded concurrency is the change
#: to make — not a longer deadline.
OCR_TIMEOUT_S: Final = 45.0

#: Every image of one source inside ONE budget. Read against `WorkerSettings.job_timeout`
#: (300s): a job that runs past its timeout is killed mid-flight, and the whole point of
#: `discarded` is that a partial result is REPORTED rather than inferred from a corpse.
OCR_DEADLINE_S: Final = 240.0

#: A ceiling on ONE transcription, in tokens. Sized against the page: the pricing page's
#: own worked figure is 1,290 tokens for a 1024x1024 image, and a dense A4 page of text is
#: on the order of 3,000-4,000 tokens of output. 6,000 leaves headroom and still turns a
#: model that has started repeating itself into a bounded bill plus a `length` finish
#: reason, which `_legibility_reason` treats as a discard rather than as a short answer.
OCR_MAX_OUTPUT_TOKENS: Final = 6_000

#: What the model is told to say when it can see no writing. A SENTINEL rather than "reply
#: with nothing", because an empty completion is also what a refusal, a safety block and a
#: dropped frame look like, and those are different events from "this photo has no words
#: in it". Uppercase and underscored so it cannot collide with transcribed text.
NO_TEXT_SENTINEL: Final = "NO_TEXT"

#: Below this many non-space characters the transcription is not knowledge, whatever it
#: says. A photo of a signboard legitimately holds four words — so this is deliberately
#: low: it is here to catch "```", "I'm sorry", "Menu" and the other one-token answers a
#: failed read produces, not to judge how much a client's document should contain.
MIN_TRANSCRIPT_CHARS: Final = 12

#: Above this share of replacement/undecodable characters the answer is garbage that
#: happens to be long. U+FFFD is what a mis-decoded byte becomes; a real transcription
#: contains none.
MAX_GARBLE_RATIO: Final = 0.02

_PROMPT: Final = (
    "Transcribe every word visible in this image, exactly as it is written. "
    "Keep the original language and script — do not translate, do not transliterate, "
    "and do not correct spelling or grammar. "
    "Keep the reading order and the line breaks. "
    "Return only the transcribed text: no description of the image, no headings you "
    "have added, no commentary, no code fences. "
    f"If there is no legible writing in the image, reply with exactly {NO_TEXT_SENTINEL}."
)


@dataclass(frozen=True, slots=True)
class OcrImage:
    """One photograph, already fetched from object storage by the caller.

    NO FILENAME AND NO OBJECT KEY. A filename is client data that routinely carries a
    person's name (`menu-ravi-kumar.jpg`), and this module's whole discipline is that
    nothing it holds can reach a log. `position` is 1-based because it is what the
    confirmation screen shows a human ("page 3 could not be read").
    """

    data: bytes
    mime_type: str
    position: int


def ocr_leg() -> chat.ChatLeg:
    """Where a transcription goes, or `OcrUnavailableError` naming what an operator must fix.

    THE THREE CONDITIONS ARE NOT RE-IMPLEMENTED HERE. `unofferable_reason` is the one
    predicate behind the model picker, the validator, the publish path and the rate card;
    asking it means OCR becomes available at the same instant a client's model choice does
    — when the Google key is installed AND the price is attested — rather than at a second
    place that could disagree with it. Hard rule 7 is the reason the price half is in
    there: `billing/rates.llm_inr_per_ktok` RAISES on an unattested model, so an OCR leg
    that ran without the attestation would deliver work it cannot bill, which is an
    UNMETERED cost and not a free one.

    ═══ AND A FOURTH CONDITION, WHICH THOSE THREE DO NOT CONTAIN ═══

    **`unofferable_reason` IS A QUESTION ABOUT A MODEL. THIS IS A QUESTION ABOUT A
    VENDOR'S TERMS, AND THIS MODULE SENDS A CLIENT'S CONTENT TO ONE.** Selectable,
    credentialled and priced says nothing about whether the account we hold with that
    vendor is on a tier where they train on what we submit — and that is the exact
    question this platform built `platform_dashboard_data_use`, an ops screen and an
    operator attestation ladder to answer before a client's SCREEN reaches a model.

    What travels here is stronger than a screen: a photograph of a printed page a client
    uploaded, which in this market is a clinic's own list and can carry a patient's name.
    So the gate is the same one, asked through the half of it that is about the vendor
    rather than about a chat surface — `client_content_data_use_reason`, which
    `dashboard_leg_reason` now also calls. Asking `dashboard_leg_reason` itself would
    refuse OCR on `NO_DASHBOARD_LEG_REASON`, an engineering fact about a surface this
    module does not use.

    It is asked FIRST, for `credit_routes.grant_credits`' reason in a different register:
    when several grounds are true at once, report the one whose remedy is not "install a
    key" — an operator who fixes the credential and comes back to a compliance refusal has
    been sent to do the wrong job.

    THE IN-CALL LEG IS UNAFFECTED. That leg sends raw caller speech under a disclosed
    notice and its own consent regime, and `client_content_data_use_reason` states in as
    many words that it does not govern it.
    """
    terms = client_content_data_use_reason(LLM_MODELS[DOCUMENT_OCR_MODEL].provider)
    if terms is not None:
        raise OcrUnavailableError(reason=terms)
    reason = unofferable_reason(DOCUMENT_OCR_MODEL)
    if reason is not None:
        raise OcrUnavailableError(reason=reason)
    api_key = get_settings().gemini_api_key
    if not api_key:
        # Belt and braces: `unofferable_reason` already asks about the credential, and a
        # None here would be a mypy narrowing hole rather than a state we expect.
        raise OcrUnavailableError(reason="google_credential_missing")
    return chat.ChatLeg(
        url=f"{google_openai_compat_base_url()}/chat/completions",
        api_key=api_key,
        wire_model=DOCUMENT_OCR_MODEL,
        dialect="google",
    )


async def ocr_images(
    images: Sequence[OcrImage],
    *,
    client: httpx.AsyncClient | None = None,
) -> ExtractedText:
    """Photographs → one block of text a human must confirm before it becomes knowledge.

    Raises `OcrUnavailableError` when no leg is configured, `DocumentTooLargeError` when
    the caller hands us more or bigger images than the bounds allow, and
    `OcrUnusableError` when NOTHING came back that a client should be shown as their own
    document. A partial read is not an error: the pages that failed are named in
    `ExtractedText.discarded`, so the confirmation screen can say "we could not read page
    3" instead of a client discovering the gap on a call.
    """
    if not images:
        raise OcrUnusableError(reason="no_images", images=0)
    if len(images) > MAX_OCR_IMAGES:
        raise DocumentTooLargeError(size=len(images), limit=MAX_OCR_IMAGES, unit="images")
    for image in images:
        if len(image.data) > MAX_IMAGE_BYTES:
            raise DocumentTooLargeError(size=len(image.data), limit=MAX_IMAGE_BYTES)
        if image.mime_type not in OCR_IMAGE_MIME_TYPES:
            raise OcrUnusableError(reason="unsupported_image_type", images=len(images))

    leg = ocr_leg()
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=OCR_TIMEOUT_S, follow_redirects=False)
    deadline = time.monotonic() + OCR_DEADLINE_S

    pages: list[str] = []
    discarded: list[str] = []
    prompt_tokens = 0
    output_tokens = 0
    usage_seen = False
    try:
        for image in images:
            if time.monotonic() >= deadline:
                discarded.append(f"page {image.position}: not_attempted")
                continue
            text, reason, usage = await _transcribe(leg, image, http)
            if usage is not None:
                usage_seen = True
                prompt_tokens += usage.prompt_tokens
                output_tokens += usage.output_tokens
            if reason is not None:
                discarded.append(f"page {image.position}: {reason}")
                continue
            pages.append(text)
    finally:
        if owns_client:
            await http.aclose()

    log.info(
        "document_ocr_finished",
        extra={
            "images": len(images),
            "kept": len(pages),
            "discarded": len(discarded),
            "model": DOCUMENT_OCR_MODEL,
        },
    )

    if not pages:
        raise OcrUnusableError(reason="all_images_discarded", images=len(images))

    return ExtractedText(
        # A blank line between pages: `kb.service.chunk_text` splits on it first, so a
        # chunk boundary falls between two pages rather than across the seam of one.
        text="\n\n".join(pages),
        kind="image",
        provenance="ocr",
        unit_count=len(pages),
        unit_name="images",
        # ⚠ NOT A FLAG A CALLER MAY TURN OFF, and the reason is the whole design. A vision
        # model returns no confidence score, so there is no number to threshold; the
        # checks in `_legibility_reason` catch a read that FAILED, and cannot catch the
        # dangerous one — a fluent, confident transcription that says 260 where the menu
        # says 280. The only instrument that can is the person who owns the menu. Showing
        # them the text and requiring a confirmation costs one screen and means a garbled
        # OCR can never reach a phone call silently. (This is separate from, and additional
        # to, the submission review policy: an owner's own submissions are auto-approved
        # and staff's are reviewed, and neither of those asks "did the machine read this
        # right".)
        needs_confirmation=True,
        model=DOCUMENT_OCR_MODEL,
        # `None` where the provider told us nothing, which throughout this repository
        # means "we do not know what this cost" and never "it was free". The caller owns
        # the ledger: `usage_events` with our `unit_cost_paid`, priced through
        # `billing/rates.llm_inr_per_ktok(DOCUMENT_OCR_MODEL)` (NUMERIC INR, hard rule 7), which
        # raises unless an operator has attested the Google price.
        prompt_tokens=prompt_tokens if usage_seen else None,
        output_tokens=output_tokens if usage_seen else None,
        discarded=tuple(discarded),
    )


async def _transcribe(
    leg: chat.ChatLeg,
    image: OcrImage,
    http: httpx.AsyncClient,
) -> tuple[str, str | None, chat.TokenUsage | None]:
    """One image → `(text, discard_reason_or_None, usage)`.

    A PROVIDER ERROR IS A DISCARD, NOT AN EXCEPTION, and that is a deliberate asymmetry
    with the rest of this tree. Everywhere else a 5xx should reach the retry ladder; here
    the unit of work is one page of a client's document, and failing the whole upload
    because page 4 of 6 got a 503 turns a recoverable partial into a lost one. The reason
    is recorded, the human sees it, and they can re-upload that page.
    """
    data_uri = f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode('ascii')}"
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": _PROMPT},
            # ⚠ The OpenAI `image_url` content part on Google's compat surface is the one
            # REPORTED wire fact in this module — see the module docstring. A provider
            # that rejects it answers 400 here, which lands in the `HTTPError` arm below
            # with `provider_rejected`, visible to an operator rather than silent.
            {"type": "image_url", "image_url": {"url": data_uri}},
        ],
    }
    try:
        outcome = await chat.complete(
            leg,
            [message],
            timeout_s=OCR_TIMEOUT_S,
            # Transcription, not composition: there is one right answer on the page.
            temperature=0,
            max_tokens=OCR_MAX_OUTPUT_TOKENS,
            client=http,
        )
    except httpx.HTTPStatusError as failure:
        log.warning(
            "document_ocr_provider_error",
            extra={"status": failure.response.status_code, "model": DOCUMENT_OCR_MODEL},
        )
        return "", f"provider_rejected_{failure.response.status_code}", None
    except httpx.HTTPError as failure:
        log.warning("document_ocr_transport_error", extra={"error": type(failure).__name__})
        return "", "provider_unreachable", None

    text = outcome.content.strip()
    reason = _legibility_reason(text, finish_reason=outcome.finish_reason)
    return ("" if reason else text), reason, outcome.usage


def _legibility_reason(text: str, *, finish_reason: str | None) -> str | None:
    """Why this transcription must be discarded, or `None` to keep it.

    ⚠ **THIS IS A FILTER IN FRONT OF THE HUMAN CONFIRMATION AND IT IS NOT AN ACCURACY
    MEASURE.** Every check here answers "did the read FAIL", which is decidable. None of
    them answers "is this what the page says", which is not — no vision model returns a
    confidence score, and a heuristic that pretended to would be worse than none, because
    it would license skipping the confirmation. Passing all four checks earns a
    transcription the right to be SHOWN TO ITS OWNER, and nothing more.

    THE FOUR, and the failure each is the only defence against:

    1. **Truncated** (`finish_reason == "length"`). The dangerous one, and the reason it is
       first: a transcription cut off at the token ceiling is a document silently missing
       its second half, and it looks completely normal — fluent text, no error, no gap.
       Half a price list is worse than none, because the agent answers confidently about
       the half it has.
    2. **Nothing, or the sentinel.** A photograph with no writing in it, or a refusal, or
       a safety block, or a dropped response — all arrive as an empty completion.
    3. **Too little to be knowledge.** The one-token answers a failed read produces
       ("Menu", "```", an apology). See `MIN_TRANSCRIPT_CHARS` for why the floor is low.
    4. **Garbled.** Replacement characters and C0 controls are what a mis-decoded or
       hallucinated byte stream looks like. They are also refused outright by the
       knowledge gate three steps later (`kb/service._FORBIDDEN_CODEPOINTS`), so catching
       them here turns an unexplainable late refusal into "we could not read that photo".
    """
    if finish_reason == "length":
        return "truncated"
    if not text or text.strip().upper() == NO_TEXT_SENTINEL:
        return "no_text"
    body = "".join(text.split())
    if len(body) < MIN_TRANSCRIPT_CHARS:
        return "too_little_text"
    garble = sum(1 for ch in body if ch == "�" or (ord(ch) < 0x20 and ch not in "\t\n\r"))
    if garble and garble / len(body) > MAX_GARBLE_RATIO:
        return "garbled"
    return None


#: Input tokens for one photographed page. Twice the vendor's 1024x1024 worked figure,
#: because a phone photograph of an A4 menu is bigger than 1024x1024 and the tiling grows
#: with area. An ASSUMPTION, named so it can be replaced by a measurement.
_IMAGE_TOKENS: Final = Decimal(2_580)
#: Output tokens for a dense page of transcription. Also an assumption; a menu is shorter.
_TRANSCRIPT_TOKENS: Final = Decimal(1_500)

#: What ONE knowledge source's OCR may cost us, in USD, at catalogue list prices.
#:
#: **THE BOUND IS ASSERTED, NOT ASSUMED.** `tests/document_ocr_test.py` multiplies
#: `estimated_page_cost_usd(DOCUMENT_OCR_MODEL)` by `MAX_OCR_IMAGES` and fails against this
#: number — so raising the page cap, or swapping `DOCUMENT_OCR_MODEL` for something an order of
#: magnitude dearer, turns CI red instead of turning up on an invoice. 12 cents is
#: roughly ten rupees, which is the size of thing a client uploads without anyone
#: needing to think about it; a source that would cost more than that is a product
#: decision, not a constant to raise quietly.
MAX_SOURCE_OCR_COST_USD: Final = Decimal("0.12")


def estimated_page_cost_usd(model: str) -> Decimal:
    """USD for ONE page on `model`, from its published per-million rates. NEVER a float.

    THE COST OF THIS LANE, WRITTEN AS ARITHMETIC SO IT CAN BE ARGUED WITH rather than as
    a sentence in a commit message. Two inputs, both VENDOR-PUBLISHED from Google's own
    pricing page (read 4 Sep 2026, cited in the module docstring):

    * a 1024x1024 image is **1,290 input tokens** — the page's own worked example. An A4
      page photographed by a phone is bigger than that and the tiling grows with area, so
      `_IMAGE_TOKENS` doubles it rather than taking the vendor's smallest case.
    * output is the transcription itself: `_TRANSCRIPT_TOKENS`, a dense page of text.

    At `gemini-2.5-flash`'s published $0.30 / $2.50 that is about half a US cent a page —
    well under a rupee — so `MAX_OCR_IMAGES` caps a source an order of magnitude below
    anything worth rationing. Which is the point of computing it: it says that a PAGE
    COUNT is the right lever (it bounds abuse and worker time) and a rupee budget is not.

    ⚠ **THIS IS A CATALOGUE ESTIMATE AND IT MAY NEVER REACH `unit_cost_paid`.** It sizes a
    bound and answers "what will this cost us". What a client is BILLED comes from
    `billing/rates.llm_inr_per_ktok`, off an operator's attestation of a real invoice, and
    that function RAISES rather than falling back to a catalogue figure (hard rule 7).
    Reads `LLM_MODELS` rather than re-typing the prices, so the two cannot drift.
    """
    price = LLM_MODELS[model].price
    return (
        _IMAGE_TOKENS * price.input_usd_per_mtok + _TRANSCRIPT_TOKENS * price.output_usd_per_mtok
    ) / Decimal(1_000_000)
