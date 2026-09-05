"""`apps/workers/document_ocr.py` — a photograph becomes text a human must confirm.

THREE THINGS THIS SUITE PINS, and they are the three the lane would be wrong without:

1. **The confirmation is not optional.** Every successful OCR comes back with
   `needs_confirmation=True`. It is the accuracy gate — a vision model returns no
   confidence score, so the only instrument that can tell 260 from 280 on a client's own
   menu is the client.
2. **A failed read is discarded and SAID, never silently kept.** A truncated
   transcription is the dangerous one: it reads perfectly and is missing half the price
   list.
3. **Nothing runs without an offerable model.** `unofferable_reason` is the same
   predicate the model picker uses, so the OCR leg switches on when the Google key is
   installed AND the price is attested — hard rule 7's attestation gates the OCR spend
   exactly as it gates a call minute.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.core.settings import get_settings
from apps.workers import document_ocr
from apps.workers.document_ocr import (
    MAX_SOURCE_OCR_COST_USD,
    NO_TEXT_SENTINEL,
    OcrImage,
    _legibility_reason,
    estimated_page_cost_usd,
    ocr_images,
    ocr_leg,
)
from calevate_shared.document_ingest import (
    MAX_IMAGE_BYTES,
    MAX_OCR_IMAGES,
    DocumentTooLargeError,
    OcrUnavailableError,
    OcrUnusableError,
)
from calevate_shared.engine import DOCUMENT_OCR_MODEL

_JPEG = b"\xff\xd8\xff\xe0 pretend this is a photograph of a menu"


def _image(position: int = 1) -> OcrImage:
    return OcrImage(data=_JPEG, mime_type="image/jpeg", position=position)


def _reply(content: str, *, finish: str = "stop", usage: bool = True) -> dict[str, Any]:
    body: dict[str, Any] = {"choices": [{"message": {"content": content}, "finish_reason": finish}]}
    if usage:
        body["usage"] = {"prompt_tokens": 2580, "completion_tokens": 300}
    return body


def _client(*replies: object) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    """A transport that answers each call with the next reply. Records the requests.

    A reply may be a body dict or an `int` status, which answers with that status — the
    per-image provider-failure path.
    """
    seen: list[httpx.Request] = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        reply = queue.pop(0)
        if isinstance(reply, int):
            return httpx.Response(reply, json={"error": "nope"})
        return httpx.Response(200, json=reply)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


@pytest.fixture(autouse=True)
def _offerable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two live conditions, satisfied. Both are an operator's act in production —
    `unofferable_reason` reads the installed credential and the price attestation — so a
    test that wants the leg to work has to stand in for both, and the tests that want it
    NOT to work turn one back off."""
    monkeypatch.setattr(document_ocr, "unofferable_reason", lambda _model: None)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "gk-test", raising=False)


# --- THE ACCURACY GATE ---------------------------------------------------------------


async def test_ocr_output_always_asks_a_human_to_confirm_it() -> None:
    """THE ACCURACY GATE. The founder's rule is "if the OCR is not accurate we discard
    it", and the honest reading of it is that no machine can decide "accurate" here: the
    failure that matters is a fluent transcription saying 260 where the menu says 280,
    which passes every check anybody could write. The client reads it back instead."""
    client, _ = _client(_reply("Idli 40\nDosa 60\nPaneer butter masala 260"))
    async with client:
        out = await ocr_images([_image()], client=client)
    assert out.needs_confirmation is True
    assert out.provenance == "ocr"
    assert out.model == DOCUMENT_OCR_MODEL


@pytest.mark.parametrize(
    ("content", "finish", "expected"),
    [
        # The dangerous one, and it is first for that reason: a transcription cut off at
        # the token ceiling reads perfectly and is missing half the price list.
        ("Idli 40\nDosa 60\nUttapam", "length", "truncated"),
        ("", "stop", "no_text"),
        (NO_TEXT_SENTINEL, "stop", "no_text"),
        # What a failed read actually returns: one token that looks like an answer.
        ("Menu", "stop", "too_little_text"),
        ("```", "stop", "too_little_text"),
        ("�" * 40 + "Idli", "stop", "garbled"),
        # The keep case, with an apostrophe and Telugu, so the filter is not accidentally
        # refusing the script this product exists for.
        ("ఇడ్లీ 40\nదోస 60\nWe're open", "stop", None),
    ],
)
def test_the_mechanical_filter_catches_reads_that_failed_and_nothing_else(
    content: str, finish: str, expected: str | None
) -> None:
    """These check "did the read FAIL", which is decidable. None of them checks "is this
    what the page says", which is not — that is what the confirmation is for."""
    assert _legibility_reason(content, finish_reason=finish) == expected


# --- DISCARDING, AND SAYING SO -------------------------------------------------------


async def test_a_page_that_could_not_be_read_is_named_rather_than_quietly_dropped() -> None:
    """Keeping four of five pages and saying nothing would leave the client with an agent
    confidently missing a page. The position travels so the screen can say WHICH."""
    client, _ = _client(_reply("Idli 40\nDosa 60"), _reply("", finish="stop"))
    async with client:
        out = await ocr_images([_image(1), _image(2)], client=client)
    assert out.text == "Idli 40\nDosa 60"
    assert out.unit_count == 1
    assert out.discarded == ("page 2: no_text",)


async def test_nothing_readable_at_all_is_a_refusal_and_not_an_empty_success() -> None:
    client, _ = _client(_reply(NO_TEXT_SENTINEL), _reply("x"))
    async with client:
        with pytest.raises(OcrUnusableError) as refusal:
            await ocr_images([_image(1), _image(2)], client=client)
    assert refusal.value.reason == "all_images_discarded"
    assert refusal.value.code == "ingest_ocr_unusable"
    # A client can act on it without knowing what a vision model is.
    assert "light" in refusal.value.remediation


async def test_a_provider_failure_on_one_page_does_not_lose_the_other_five() -> None:
    """Deliberately NOT the retry ladder: the unit of work is one page, and failing the
    whole upload because page 2 got a 503 turns a recoverable partial into a lost one."""
    client, _ = _client(_reply("Idli 40\nDosa 60"), 503)
    async with client:
        out = await ocr_images([_image(1), _image(2)], client=client)
    assert out.discarded == ("page 2: provider_rejected_503",)
    assert out.text == "Idli 40\nDosa 60"


# --- THE WIRE ------------------------------------------------------------------------


async def test_the_image_travels_as_a_data_uri_beside_the_transcription_prompt() -> None:
    client, seen = _client(_reply("Idli 40\nDosa 60"))
    async with client:
        await ocr_images([_image()], client=client)
    body = json.loads(seen[0].content)
    assert body["model"] == DOCUMENT_OCR_MODEL
    # One right answer on the page: this is transcription, not composition.
    assert body["temperature"] == 0
    parts = body["messages"][0]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "do not translate" in parts[0]["text"]
    assert NO_TEXT_SENTINEL in parts[0]["text"]


async def test_one_call_per_image_so_a_discard_can_name_a_page() -> None:
    client, seen = _client(_reply("Idli 40 Dosa 60"), _reply("Uttapam 70 Vada 30"))
    async with client:
        out = await ocr_images([_image(1), _image(2)], client=client)
    assert len(seen) == 2
    # A blank line between pages: `kb.service.chunk_text` splits on it first, so a chunk
    # boundary falls between two pages rather than across the seam of one.
    assert out.text == "Idli 40 Dosa 60\n\nUttapam 70 Vada 30"


async def test_tokens_are_summed_across_pages_for_the_callers_ledger() -> None:
    client, _ = _client(_reply("Idli 40 Dosa 60"), _reply("Uttapam 70 Vada 30"))
    async with client:
        out = await ocr_images([_image(1), _image(2)], client=client)
    assert (out.prompt_tokens, out.output_tokens) == (5160, 600)


async def test_a_provider_that_reports_no_usage_reports_none_and_never_zero() -> None:
    """Throughout this repository a missing usage block means "we do not know what this
    cost" and never "it was free" — metering it as zero would hand one tenant free work
    and move the platform brake by nothing."""
    client, _ = _client(_reply("Idli 40 Dosa 60", usage=False))
    async with client:
        out = await ocr_images([_image()], client=client)
    assert out.prompt_tokens is None and out.output_tokens is None


# --- BOUNDS --------------------------------------------------------------------------


async def test_more_pages_than_the_ceiling_is_refused_before_a_single_call() -> None:
    client, seen = _client()
    async with client:
        with pytest.raises(DocumentTooLargeError) as refusal:
            await ocr_images([_image(n) for n in range(MAX_OCR_IMAGES + 1)], client=client)
    assert refusal.value.limit == MAX_OCR_IMAGES
    assert seen == []


async def test_an_oversized_photograph_is_refused_before_a_single_call() -> None:
    client, seen = _client()
    async with client:
        with pytest.raises(DocumentTooLargeError):
            await ocr_images(
                [OcrImage(data=b"\0" * (MAX_IMAGE_BYTES + 1), mime_type="image/jpeg", position=1)],
                client=client,
            )
    assert seen == []


async def test_an_image_type_the_vendor_does_not_document_is_refused() -> None:
    """The accepted set is the vendor's own discovery document, minus animated GIF —
    "which frame did it read" is a question a client cannot answer about their own file."""
    client, seen = _client()
    async with client:
        with pytest.raises(OcrUnusableError) as refusal:
            await ocr_images(
                [OcrImage(data=_JPEG, mime_type="image/gif", position=1)], client=client
            )
    assert refusal.value.reason == "unsupported_image_type"
    assert seen == []


def test_one_source_of_ocr_stays_inside_its_stated_cost_bound() -> None:
    """THE COST BOUND, ASSERTED RATHER THAN ASSUMED. Raising `MAX_OCR_IMAGES`, or moving
    `DOCUMENT_OCR_MODEL` to something an order of magnitude dearer, fails here instead of turning
    up on an invoice. The prices come from `LLM_MODELS`, so they cannot drift from the
    catalogue this repository already keeps."""
    per_page = estimated_page_cost_usd(DOCUMENT_OCR_MODEL)
    assert Decimal(0) < per_page < Decimal("0.01")
    assert per_page * MAX_OCR_IMAGES <= MAX_SOURCE_OCR_COST_USD


# --- THE THREE CONDITIONS ------------------------------------------------------------


def test_no_ocr_without_an_offerable_model_because_that_is_where_hard_rule_7_lives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`llm_inr_per_ktok` RAISES on a model nobody has attested, so an OCR leg that ran
    without the attestation would deliver work it cannot bill — an UNMETERED cost, not a
    free one. Refusing at the leg is the only place that failure is free."""
    monkeypatch.setattr(
        document_ocr, "unofferable_reason", lambda _model: "no attested price on file"
    )
    with pytest.raises(OcrUnavailableError) as refusal:
        ocr_leg()
    assert refusal.value.reason == "no attested price on file"
    # The operator learns the ground; the client learns the one action they have.
    assert "vendor" not in refusal.value.detail.lower()
    assert "Word document" in refusal.value.remediation


def test_no_ocr_without_the_google_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "gemini_api_key", None, raising=False)
    with pytest.raises(OcrUnavailableError) as refusal:
        ocr_leg()
    assert refusal.value.reason == "google_credential_missing"


def test_the_leg_is_the_one_verified_google_endpoint_and_dialect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No new host literal and no new dialect: `google_openai_compat_base_url()` is the
    single emitter `check_model_residency` grants the Gemini host to, and `google` is the
    dialect `chat.py` already carries a verified credential header for."""
    leg = ocr_leg()
    assert leg.dialect == "google"
    assert leg.wire_model == DOCUMENT_OCR_MODEL
    assert leg.url.endswith("/chat/completions")
    assert "generativelanguage.googleapis.com" in leg.url


# --- HARD RULE 6 ---------------------------------------------------------------------


async def test_an_ocr_refusal_carries_no_transcribed_text() -> None:
    """The transcription is the client's document. A refusal is shown, logged and may be
    stored; it gets counts and codes, never a word of what the model read."""
    client, _ = _client(_reply("Ravi Kumar 9876543210"[:8], finish="length"))
    async with client:
        with pytest.raises(OcrUnusableError) as refusal:
            await ocr_images([_image()], client=client)
    rendered = " ".join(
        [refusal.value.title, refusal.value.detail, refusal.value.remediation, str(refusal.value)]
    )
    assert "Ravi" not in rendered


def test_an_image_carries_no_filename_for_a_log_to_leak() -> None:
    """A filename is client data that routinely carries a person's name
    (`menu-ravi-kumar.jpg`). `OcrImage` has nowhere to put one."""
    assert set(OcrImage.__slots__) == {"data", "mime_type", "position"}
