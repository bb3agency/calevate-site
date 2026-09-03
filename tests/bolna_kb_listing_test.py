"""`GET /knowledgebase/all` is a PAGE, not an account (D-516).

The defect D-430 fixed on `GET /v2/agent/all`, unfixed on the one other bare-array
listing this adapter reads. Both halves of the evidence are the same two pages:

* the route's own OpenAPI block declares NO parameters and answers a bare
  `KnowledgebaseList` array with no `has_more` and no `total`
  (`bolna-findings/mirror/pages/api-reference/knowledgebase/get_knowledgebases.md:29-44,
  47-51`), so truncation is not detectable from the response;
* the vendor's pagination page says *"The endpoints also support pagination using the
  `page_number` and `page_size` query parameters"* and defaults `page_size` to **20**
  (`.../api-reference/pagination.md:9,13-14`).

One Bolna account holds EVERY tenant's knowledge bases; every publish is a fresh CREATE
because the object has no update route (`.../knowledgebase/overview.md:11-16`); and
unreferenced ones linger (OPERATIONS §2 gate 43e). Twenty rows is a handful of clients.

Past that boundary the unpaged read did not truncate a report — it made `detach_kb` tell
a client *"The voice platform does not hold that knowledge base"* about a document the
platform is holding, retrieving from and billing for, with no retry that could succeed.

Evidence class: VERIFIED-VENDOR-DOCS (hash-manifested mirror). Whether the platform
HONOURS the parameter is OPERATIONS §2 gate 30's second half and needs a live account;
the walk is written to be correct under both answers, which is why this file asserts the
outcome rather than the vendor's behaviour.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.bolna import BASE_URL, BolnaEngine
from calevate_shared.engine import AgentConfig, ModelConfig


def _config() -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic receptionist",
        direction="inbound",
        system_prompt="You are the receptionist for Sunrise Clinic.",
        opening_line="Idi AI assistant.",
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v3",
            llm_model="sarvam-105b",
            tts_provider="sarvam",
            tts_voice="bulbul:v3",
        ),
    )


def _row(index: int) -> dict[str, str]:
    return {"rag_id": f"rag_{index}", "vector_id": f"vec_{index}"}


class _Vendor:
    """A vendor that PAGES `/knowledgebase/all` and answers everything else blandly."""

    def __init__(self, pages: dict[int, list[dict[str, str]]]) -> None:
        self.pages = pages
        self.listing_params: list[dict[str, str]] = []
        self.writes: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/knowledgebase/all":
            self.listing_params.append(dict(request.url.params))
            page = int(request.url.params.get("page_number", "1"))
            return httpx.Response(200, json=self.pages.get(page, []))
        if request.method in ("PUT", "DELETE", "POST"):
            self.writes.append((request.method, path))
        if path == "/v2/agent/agent_1" and request.method == "GET":
            return httpx.Response(200, json={"agent_id": "agent_1", "data": {"tasks": []}})
        return httpx.Response(200, json={"message": "success", "state": "deleted"})


def _engine(vendor: _Vendor) -> BolnaEngine:
    return BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(vendor)),
    )


def _full_page() -> list[dict[str, str]]:
    """Exactly the page size we ask for — the only shape that can be hiding rows."""
    from apps.api.engine.bolna import _LISTING_PAGE_SIZE

    return [_row(i) for i in range(_LISTING_PAGE_SIZE)]


async def test_the_knowledge_base_listing_asks_for_a_page() -> None:
    """Unparameterised, the request takes the vendor's DEFAULT page — 20 rows — and the
    adapter read that as the whole account."""
    vendor = _Vendor({1: [_row(1)]})

    await _engine(vendor).detach_kb("agent_1", "vec_1", agent=_config())

    assert vendor.listing_params, "no listing request was made at all"
    assert vendor.listing_params[0] == {"page_number": "1", "page_size": "50"}, (
        "`GET /knowledgebase/all` must carry the documented pagination parameters "
        "(`api-reference/pagination.md:13-14`), not rely on the vendor's default of 20"
    )


async def test_a_knowledge_base_past_the_first_page_is_still_found() -> None:
    """THE DEFECT ITSELF: the row is there, on page two, and the old read never asked."""
    vendor = _Vendor({1: _full_page(), 2: [_row(99)]})

    await _engine(vendor).detach_kb("agent_1", "vec_99", agent=_config())

    assert ("DELETE", "/knowledgebase/rag_99") in vendor.writes, (
        "the document on page two was never deleted, and the client was told the "
        "platform does not hold it"
    )


async def test_a_short_page_ends_the_account_and_absence_is_a_real_answer() -> None:
    """The ONE exit that may claim absence: the vendor returned fewer rows than we asked
    for, so nothing can be hiding behind it. `detach_kb` raises the Protocol's 404."""
    vendor = _Vendor({1: [_row(1)]})

    with pytest.raises(ProblemError) as raised:
        await _engine(vendor).detach_kb("agent_1", "vec_missing", agent=_config())

    assert raised.value.code == "engine_rejected"
    assert vendor.listing_params == [{"page_number": "1", "page_size": "50"}], (
        "a short first page is the end of the account; asking for a second is wasted engine load"
    )


async def test_a_listing_that_cannot_be_walked_to_the_end_does_not_claim_absence() -> None:
    """An unlocatable reference must not look like a cleared one (D-41).

    A vendor that keeps answering the same full page — which is what an IGNORED
    `page_number` looks like, and their OSS server is FastAPI — has told us nothing about
    rows past it. "Not held" would be a claim about rows we never saw.
    """
    vendor = _Vendor(dict.fromkeys(range(1, 40), _full_page()))

    with pytest.raises(ProblemError) as raised:
        await _engine(vendor).detach_kb("agent_1", "vec_missing", agent=_config())

    assert raised.value.code == "engine_kb_listing_incomplete"
    assert not vendor.writes, "nothing may be written on an inconclusive read"


async def test_the_walk_is_bounded() -> None:
    """A vendor answering full pages for ever must not spin this adapter for ever."""
    from apps.api.engine.bolna import _LISTING_MAX_PAGES

    pages = {n: [_row(n * 1000 + i) for i in range(50)] for n in range(1, 200)}
    vendor = _Vendor(pages)

    with pytest.raises(ProblemError) as raised:
        await _engine(vendor).detach_kb("agent_1", "vec_missing", agent=_config())

    assert raised.value.code == "engine_kb_listing_incomplete"
    assert len(vendor.listing_params) == _LISTING_MAX_PAGES


async def test_a_matching_row_with_no_usable_rag_id_is_a_bad_response_not_an_absence() -> None:
    """`rag_id` is declared on that row (`.../get_knowledgebases.md:65-70`).

    A match carrying none is a response we cannot use. Reporting it as absence — which is
    what the old `return rag_id if isinstance(...) else None` did — told the publisher the
    document was already gone and deleted nothing.
    """
    vendor = _Vendor({1: [{"vector_id": "vec_1"}]})

    with pytest.raises(ProblemError) as raised:
        await _engine(vendor).detach_kb("agent_1", "vec_1", agent=_config())

    assert raised.value.code == "engine_bad_response"


def _adapter_source() -> str:
    from pathlib import Path

    import apps.api.engine.bolna as bolna_module

    return Path(bolna_module.__file__).read_text()


def test_no_unpaged_account_listing_survives_in_the_adapter() -> None:
    """The reverse direction: the fix cannot be undone by deleting a parameter.

    Both bare-array account listings this adapter reads — `/v2/agent/all` and
    `/knowledgebase/all` — must be requested WITH a page. `/providers` is deliberately
    excluded and its reasoning is `docs/evidence/bolna-request-contract.md` F-2: its key
    vocabulary is enumerated by the vendor and cannot plausibly overflow one page.
    """
    source = _adapter_source()
    for route in ('"/v2/agent/all"', '"/knowledgebase/all"'):
        index = source.index(route)
        window = source[index : index + 400]
        assert "page_number" in window and "page_size" in window, (
            f"{route} is requested without pagination parameters — the account listing "
            "is a page and reading one page as the account is D-430's defect"
        )
