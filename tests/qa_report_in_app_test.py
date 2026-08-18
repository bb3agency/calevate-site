"""The monthly QA report, in-app — and the ONE test that matters (SURFACES §2, D-15).

    GET /v1/quality/reports   (apps/api/quality/routes.py)

`make qa-report` has rendered this document since M3. SURFACES §2 asks for it "rendered
in-app, not just PDF", and the way that goes wrong is not a bug in a screen — it is a
second implementation. A QA report that disagrees with itself is the sales asset
contradicting the console in front of the client, and neither of us can say which is
right.

1. **THE ANTI-FORK TEST.** The numbers the route returns are compared, field by field,
   with the numbers PARSED BACK OUT of the Markdown the CLI prints. It is written this
   way on purpose: comparing the API against `summarize()` would only prove the API can
   call a function, while parsing the Markdown compares the two DOCUMENTS a client can
   actually hold — the emailed one and the screen. Any number re-derived inside the API
   turns this red.
2. **The screen cannot invent a clean run.** A tenant with no stored report gets an
   empty list, never a zeroed report. "No defects across 0 scenarios" is the one
   sentence this surface must never be able to say by accident.
3. **Hard rules 5 and 6.** The served payload is scanned against every fixture
   transcript, the same scan `tests/eval_qa_report_test.py` runs over the Markdown — the
   in-app path must not become the way transcript-derived text reaches a browser.
4. **Hard rule 1.** Tenant B cannot see tenant A's report, asserted through the route
   AND on the raw RLS-scoped session, so an endpoint that filtered in Python would still
   fail.
5. **The store is the harness's own path.** The row is written by
   `quality.service.store_report` — the function `--store` calls — never by test SQL, so
   a test cannot pass against a write path production does not use.

Run: uv run pytest -q tests/qa_report_in_app_test.py
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from typing import Any

import pytest
import scripts.eval as ev
import scripts.qa_report as qa
from apps.api.admin import service as admin_service
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.quality.service import latest_report, store_report
from calevate_shared.extraction import ExtractionSchemaSpec
from calevate_shared.qa_report import QaReport
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

REPORTS_PATH = "/v1/quality/reports"
AS_OF = date(2026, 8, 31)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant() -> tuple[uuid.UUID, str]:
    created = await admin_service.create_organization(
        name="Sunrise Clinic",
        slug=f"quality-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), str(created["slug"])


async def _member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


def _spec() -> ExtractionSchemaSpec:
    payload = json.loads(ev.FIXTURES.read_text())
    return ExtractionSchemaSpec(version=1, fields=payload["schema"])


async def _computed(slug: str, vertical: str = "clinic") -> QaReport:
    """The harness's own output — exactly what `make qa-report` computes."""
    results, meta = await ev.run_suite(slug, vertical)
    return qa.summarize(
        results,
        _spec(),
        client=slug,
        vertical=vertical,
        model=str(meta["model"]),
        as_of=AS_OF,
    )


# --- 1. THE ANTI-FORK TEST --------------------------------------------------------


def _markdown_numbers(markdown: str) -> dict[str, Any]:
    """Every number a client can read off the CLI document, parsed back out of it.

    Deliberately parsed rather than read from the object: the point is to compare the two
    DOCUMENTS, so this side must not touch the model the API also uses. If the Markdown's
    shape changes, this parser fails loudly — which is correct, because a report whose
    numbers moved is a report whose in-app twin has to be re-checked.
    """
    headline = re.search(
        r"\*\*(?:No defects found across (\d+)|(\d+) of (\d+)) scenarios", markdown
    )
    assert headline, "the report always opens with the defect headline"
    if headline.group(1):
        defects, total = 0, int(headline.group(1))
    else:
        defects, total = int(headline.group(2)), int(headline.group(3))

    captured = re.search(r"\| Scenarios where everything was captured \| ([^|]+)\|", markdown)
    blank = re.search(r"\| Scenarios where a field came back blank \| ([^|]+)\|", markdown)
    red_team = re.search(r"^(\d+) of those scenarios are adversarial", markdown, re.MULTILINE)
    assert captured and blank and red_team

    classes = re.findall(r"^\| ([^|]+?) \| (\d+) \| ([^|]+?) \|$", markdown, re.MULTILINE)
    limits = re.findall(r"^\| ([^|]+?) \| (\d+) \|$", markdown, re.MULTILINE)
    return {
        "defects": defects,
        "scenarios_total": total,
        "everything_captured": captured.group(1).strip(),
        "field_left_blank": blank.group(1).strip(),
        "red_team": int(red_team.group(1)),
        "scenario_counts": {label.strip(): int(count) for label, count, _meaning in classes},
        "limits": {label.strip(): int(count) for label, count in limits},
    }


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_the_in_app_report_and_the_cli_report_agree(vertical: str) -> None:
    """THE anti-fork assertion: two documents, one set of numbers.

    The Markdown is produced by the CLI's own renderer; the JSON is fetched through the
    live route off a stored row. Every number a client can read is compared. There is no
    tolerance and no "close enough" — a defect count that differs by one between the
    email and the screen is a support call we cannot answer.
    """
    tenant_id, slug = await _tenant()
    token = await _member(tenant_id)
    computed = await _computed(slug, vertical)
    await store_report(computed, slug=slug)

    markdown = qa.render_report(computed)
    printed = _markdown_numbers(markdown)

    async with _client() as http:
        response = await http.get(
            REPORTS_PATH,
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200, response.text
    served = response.json()[0]

    assert served["defects"] == printed["defects"]
    assert served["scenarios_total"] == printed["scenarios_total"]
    assert served["red_team"] == printed["red_team"]
    # The rendered STRING, not just the integers: the percentage and the honesty basis
    # are what a client quotes back at us, and a screen that rounded independently would
    # differ by a point without any count being wrong.
    assert (
        QaReport.model_validate(served).everything_captured.rendered
        == printed["everything_captured"]
    )
    assert QaReport.model_validate(served).field_left_blank.rendered == printed["field_left_blank"]
    assert {row["label"]: row["count"] for row in served["scenario_classes"]} == printed[
        "scenario_counts"
    ]
    # The limits table's rows are a subset of the two-column matches (the results table
    # has two-column rows too), so it is compared by containment in that direction.
    for limit in served["known_limits"]:
        assert printed["limits"].get(limit["label"]) == limit["scenarios"], limit["label"]


async def test_the_route_recomputes_nothing_it_serves_what_was_stored() -> None:
    """A stored report is served VERBATIM — the API is a reader, not a second harness.

    Proved by storing a document whose numbers the fixtures could never produce and
    checking they come back unchanged. If any field were re-derived server-side, this
    doctored row would be "corrected" and the test would fail — which is exactly the
    failure mode the anti-fork test above exists to prevent, caught here without needing
    the harness to disagree by accident.
    """
    tenant_id, slug = await _tenant()
    token = await _member(tenant_id)
    computed = await _computed(slug)
    doctored = computed.model_copy(update={"defects": 7, "red_team": 3})
    await store_report(doctored, slug=slug)

    async with _client() as http:
        response = await http.get(
            REPORTS_PATH, headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )
    assert response.json()[0]["defects"] == 7
    assert response.json()[0]["red_team"] == 3


# --- 2. It cannot invent a clean run ----------------------------------------------


async def test_a_tenant_with_no_run_gets_no_report_not_a_zeroed_one() -> None:
    """The worst sentence this surface could produce is "no defects across 0 scenarios"
    for an account nobody ever ran the harness against. The API answers with nothing at
    all and the screen renders that as "not run yet"."""
    tenant_id, slug = await _tenant()
    token = await _member(tenant_id)
    async with _client() as http:
        response = await http.get(
            REPORTS_PATH, headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )
    assert response.status_code == 200
    assert response.json() == []
    async with tenant_session(tenant_id) as session:
        assert await latest_report(session) is None


async def test_a_regeneration_replaces_the_month_rather_than_duplicating_it() -> None:
    """The document is a pure function of its inputs, so a second run of one month is the
    same month — not a second row the client has to choose between."""
    tenant_id, slug = await _tenant()
    computed = await _computed(slug)
    first = await store_report(computed, slug=slug)
    second = await store_report(computed, slug=slug)
    assert first == second
    async with tenant_session(tenant_id) as session:
        rows = (await session.execute(text("SELECT count(*) FROM qa_reports"))).scalar_one()
    assert rows == 1


async def test_storing_against_an_unknown_slug_is_refused() -> None:
    """`make qa-report CLIENT=typo --store` must not report success having filed the
    report against nobody — the operator would see a green line and the client an empty
    screen a month later."""
    from apps.api.core.errors import ProblemError

    computed = await _computed("nobody")
    with pytest.raises(ProblemError):
        await store_report(computed, slug=f"missing-{uuid.uuid4().hex[:8]}")


# --- 3. Hard rules 5 and 6 --------------------------------------------------------


async def test_no_line_any_caller_or_agent_said_reaches_the_served_report() -> None:
    """The same scan `eval_qa_report_test` runs over the Markdown, run over the JSON.

    The in-app path is a NEW way for this document to reach a browser, so it gets the
    same proof rather than inheriting the Markdown's. Every spoken line in every fixture
    transcript is checked against the served payload.
    """
    tenant_id, slug = await _tenant()
    token = await _member(tenant_id)
    await store_report(await _computed(slug), slug=slug)
    async with _client() as http:
        body = (
            await http.get(
                REPORTS_PATH, headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
            )
        ).text

    cases = json.loads(ev.FIXTURES.read_text())["cases"]
    for case in cases:
        assert case["title"] not in body, case["id"]
        for line in case.get("transcript", []):
            spoken = str(line).split(":", 1)[-1].strip()
            if len(spoken) > 12:
                assert spoken not in body, case["id"]
    # No long digit run at all — stricter than masking, and there is no legitimate one
    # in a document built from counts and labels. Two fields legitimately hold digits and
    # are dropped rather than exempted by a looser pattern, because a rule of "no such
    # digits exist here" is only worth having if it is tight:
    #
    #   `as_of`  — the ISO month-end.
    #   `client` — the TENANT'S OWN SLUG, which is a name they chose and may contain any
    #              number of digits (`clinic24x7`). It reached this scan by accident and
    #              the accident is instructive: the test mints slugs like
    #              `quality-dc48252b`, and it went red the run one of them happened to
    #              carry five consecutive digits. So this assertion was both FLAKY (it
    #              depended on a random hex draw) and WRONG (it would have fired in
    #              production on a real client whose slug has digits in it) — and it is
    #              wrong in the direction that matters, because a redaction test nobody
    #              trusts is a redaction test somebody switches off.
    #
    # A tenant slug is not call content; it is already in the URL of every request that
    # fetched this document. What the scan is for is a caller's number or a spoken line
    # reaching a client-readable page, and neither can hide in either dropped field.
    scannable = json.loads(body)
    for report in scannable:
        report.pop("as_of", None)
        report.pop("client", None)
    assert not re.search(r"\d{5,}", json.dumps(scannable))


# --- 4. Hard rule 1 ---------------------------------------------------------------


async def test_tenant_b_cannot_see_tenant_as_report() -> None:
    """Cross-tenant zero rows, through the route AND on the raw RLS-scoped session."""
    tenant_a, slug_a = await _tenant()
    tenant_b, slug_b = await _tenant()
    token_b = await _member(tenant_b)
    await store_report(await _computed(slug_a), slug=slug_a)

    async with _client() as http:
        response = await http.get(
            REPORTS_PATH, headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": slug_b}
        )
    assert response.json() == []

    async with tenant_session(tenant_b) as session:
        rows = (await session.execute(text("SELECT count(*) FROM qa_reports"))).scalar_one()
    assert rows == 0
    async with tenant_session(tenant_a) as session:
        rows = (await session.execute(text("SELECT count(*) FROM qa_reports"))).scalar_one()
    assert rows == 1


async def test_an_unauthenticated_request_is_refused() -> None:
    async with _client() as http:
        response = await http.get(REPORTS_PATH, headers={"X-Org-Slug": "whoever"})
    assert response.status_code in (401, 403)


async def test_staff_may_read_the_report() -> None:
    """`agents:read`, held by both client roles. A trust document nobody in the office
    may open is not a trust document — and it contains nothing from any call."""
    tenant_id, slug = await _tenant()
    token = await _member(tenant_id, role="staff")
    await store_report(await _computed(slug), slug=slug)
    async with _client() as http:
        response = await http.get(
            REPORTS_PATH, headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )
    assert response.status_code == 200
    assert len(response.json()) == 1
