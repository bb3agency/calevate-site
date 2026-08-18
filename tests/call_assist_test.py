"""The seam: `POST /v1/calls/{call_id}/assist` — subject, gate, run, meter (D-127).

`billing/ai_quota.py` (D-137/D-140) and `workers/extraction.run_assist` (D-134/D-142)
were built one call apart by two agents who did not know about each other, and both
recorded the same top gap: nothing joined them, so the ledger, the ceiling, the wallet
dialog, the platform brake, the capability ladder and the Vertex client were reachable by
no user. `crm/routes.assist_call` is the call that joins them and this file is what makes
each half of the join falsifiable.

WHAT IS PROVED HERE, and each one is a property somebody could break silently:

1. **Raw transcript text cannot reach the model (G-2/G-7).** Asserted against the BYTES
   httpx was handed, not against the column the query names — a query is a claim and a
   request body is evidence. The same test also proves the second guard is now LIVE:
   `run_assist` re-runs `redact()` and refuses text that still matches, and that branch
   had no caller in the tree until this route existed.
2. **A refusal costs nothing.** No `usage_events` row, no movement of
   `platform_ai_spend`, and no request reaching the provider at all — checked in that
   order, because a ledger assertion alone would pass on a path that paid Google and
   failed to record it.
3. **A double-click is paid for once.** The dedupe is BEFORE the model call, which is the
   only place it saves anything (`billing/ai_quota.ASSIST_REF_PREFIX`).
4. **A fallback is disclosed and is not metered.** The sentence reaches the response, and
   the free leg writes no rupees.
5. **`usage is None` on GEMINI is an alert, not a zero.** The one case where "we do not
   know" and "it was free" would otherwise meter the same.

CONCURRENCY AND SHARED STATE: every test mints its own tenant. `platform_ai_spend` is the
one row that is not per-tenant, and the autouse fixture severs this file's dependency on
it for the reason `ai_quota_test` records at length — a suite whose result depends on how
many times it has been run is not measuring the code. The ceiling tests reach the ceiling
by moving the TIER CONSTANT to zero rather than by writing hundreds of rupees of usage,
so this file adds essentially nothing to that counter.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.billing import ai_quota
from apps.api.core.settings import get_settings
from apps.api.crm import assist
from apps.api.crm import routes as crm_routes
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import extraction as extraction_module
from apps.workers.extraction import (
    GEMINI_PROVIDER,
    SARVAM_PROVIDER,
    SarvamExtractor,
    VertexGeminiExtractor,
)
from apps.workers.redaction import redact
from calevate_shared.extraction import ExtractionSchemaSpec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

# ONE fake Vertex in this repo. It records the request objects httpx was actually handed,
# which is the artefact test 1 needs, and a second copy here would drift from the response
# shape the client parses. Same reason `route_shape_test` imports `view_as_headers`.
from tests.vertex_extraction_test import FakeVertex, _credential_json

#: A Telugu turn with a real-shaped Indian mobile in it — the exact pair hard rule 6
#: names. `redact()` keeps the last two digits, so the redacted copy is recognisably the
#: same sentence and the assertion "the raw number is absent" is not satisfied by the
#: whole turn being absent.
CALLER_NUMBER = "9876500123"
RAW_TURNS: list[tuple[str, str]] = [
    ("agent", "Namaskaram, Sunrise Clinic. Cheppandi."),
    ("caller", f"Naa peru Ravi. Naa number {CALLER_NUMBER}, repu appointment kavali."),
]

PROJECT = "calevate-assist-test"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


@pytest.fixture(autouse=True)
def _the_platform_brake_is_not_this_suites_business(monkeypatch: pytest.MonkeyPatch) -> None:
    """`platform_ai_spend` is shared with every other suite on this database and only
    ever goes up. `ai_quota_test` records what depending on it cost that file; this one
    severs the dependency for the same reason rather than re-learning it."""

    async def not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


@pytest.fixture(autouse=True)
def _clean_token_cache() -> Any:
    """The Vertex bearer cache is process-level (one token an hour, not one an assist),
    so it is shared state between tests. Cold on both sides, or the second test here
    silently skips the token exchange the fake is counting."""
    from apps.workers import google_oauth

    google_oauth.reset_token_cache()
    yield
    google_oauth.reset_token_cache()


@pytest.fixture
def vertex_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment holding a Vertex credential and NO Sarvam key: the top rung of the
    ladder, so anything that falls off it has to say so."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gcp_project_id", PROJECT, raising=False)
    monkeypatch.setattr(settings, "gcp_service_account_json", _credential_json(), raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", None, raising=False)


def use_fake_vertex(monkeypatch: pytest.MonkeyPatch, google: FakeVertex) -> None:
    """Drive the REAL Vertex client through httpx's own plumbing.

    Patching the class rather than its `run` method is deliberate: the URL, the bearer and
    the request body are all built inside `run`, and a hand-written stand-in for it could
    not get any of them wrong — which is exactly what test 1 is trying to catch.
    """
    monkeypatch.setattr(
        extraction_module,
        "VertexGeminiExtractor",
        lambda account, project: VertexGeminiExtractor(account, project, client=google.client()),
    )


# --------------------------------------------------------------------- fixtures: a call


async def _call_with_transcript(
    tenant_id: UUID,
    turns: list[tuple[str, str]] | None = None,
    *,
    redacted: list[str | None] | None = None,
) -> UUID:
    """One completed call with a raw transcript and its redacted twin.

    `redacted` overrides the redacted column per turn — `None` in a slot writes SQL NULL,
    which is the state `load_assist_source` fails closed on, and a string writes it
    verbatim, which is how the "the redacted copy is not actually redacted" case is built.
    """
    rows = turns if turns is not None else RAW_TURNS
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, summary, sentiment, outcome_tag, started_at, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :ecid, 'inbound', 'completed', :from_e, "
                "'First pass.', 'neutral', 'resolved', now(), now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"as_{call_id.hex[:10]}",
                "from_e": f"+91{CALLER_NUMBER}",
            },
        )
        for idx, (speaker, line) in enumerate(rows):
            override = redacted[idx] if redacted is not None else redact(line).text
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:id, :tid, :cid, :idx, "
                    ":speaker, :raw, :red, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "idx": idx,
                    "speaker": speaker,
                    "raw": line,
                    "red": override,
                },
            )
    return call_id


async def _empty_call(tenant_id: UUID) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', "
                "'completed', now(), now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"as_{call_id.hex[:10]}",
            },
        )
    return call_id


async def _usage_rows(tenant_id: UUID) -> list[tuple[str, Decimal, Decimal, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, ref FROM usage_events "
                    "WHERE tenant_id = :tid AND unit_type LIKE 'ai_assist%' ORDER BY unit_type"
                ),
                {"tid": tenant_id},
            )
        ).all()
    return [(str(r[0]), Decimal(str(r[1])), Decimal(str(r[2])), str(r[3])) for r in rows]


async def _platform_spend() -> tuple[Decimal, int]:
    """The whole `platform_ai_spend` table as one pair. Summed across months so a run
    that straddles an IST boundary still measures a MOVEMENT rather than a month."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(spend_inr), 0), COALESCE(SUM(requests), 0) "
                    "FROM platform_ai_spend"
                )
            )
        ).one()
    return Decimal(str(row[0])), int(row[1])


async def _audit_actions(call_id: UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT action FROM audit_log WHERE object_id = :oid ORDER BY at"),
                {"oid": str(call_id)},
            )
        ).all()
    return [str(r[0]) for r in rows]


def _headers(token: str, slug: str, key: str | None = "idem-1") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    if key is not None:
        headers["Idempotency-Key"] = f"{key}-{uuid.uuid4().hex[:8]}" if key == "fresh" else key
    return headers


async def _at_the_ceiling(tenant_id: UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put this tenant past its included allowance with NO usage rows.

    The tier constant goes to zero rather than the tenant being charged into the ceiling,
    and that is not only a speed trick: writing hundreds of rupees of usage would move
    `platform_ai_spend`, the one counter this file shares with every other suite and with
    its own history. `used_inr (0) >= allowance_inr (0)` is `at_ceiling` by
    `AiQuota`'s own definition, so the gate under test is the real one.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :i"),
            {"i": tenant_id},
        )
    monkeypatch.setitem(ai_quota.AI_QUOTA_INR, "self_serve", Decimal("0.00"))


# ---------------------------------------- 1. G-2: raw transcript text never reaches Gemini


async def test_the_model_is_sent_the_redacted_turns_and_never_the_raw_column(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE test this whole route exists under (D-127 G-2/G-7).

    `workers/pipeline.py:750` hands the EXTRACTOR `turn.text` on purpose — a CRM
    callback-number field needs the digits — and the two column names sit one line apart.
    This route must read the other one, and the proof is the BYTES httpx was handed
    rather than the SQL the service wrote: a query is a claim, a request body is evidence.

    The number is asserted absent in both spellings it could travel in, because the JSON
    encoder is between us and the wire, and the redacted marker is asserted PRESENT so
    that "the number is missing" cannot be satisfied by the transcript being missing too.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    google = FakeVertex()
    use_fake_vertex(monkeypatch, google)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 200, response.text
    sent = google.sent.content.decode()
    assert CALLER_NUMBER not in sent, "the raw transcript column reached Vertex"
    assert json.dumps(CALLER_NUMBER)[1:-1] not in sent
    assert "[phone ••23]" in sent, (
        "the redacted turn is missing too — the assertion above proves nothing if the "
        "transcript never travelled at all"
    )
    assert "Namaskaram" in sent, "the agent's turn is part of the conversation the model reads"


async def test_a_turn_whose_redacted_copy_still_holds_a_number_is_refused_before_the_model(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SECOND guard, which had no caller in the tree until this route existed.

    `run_assist` re-runs `redact()` over its input and refuses text that still matches.
    Its own docstring says the refusal was unreachable and that the guard was written
    before the caller on `check_model_residency`'s reasoning. This is that caller, and
    this test is what stops it from being written in a way that defeats the guard — a
    route that read `text` would sail straight past every other assertion in this file
    and fail here.

    A `text_redacted` column holding an unredacted number is not hypothetical: it is what
    a re-run of an older redaction pass, or a hand-repaired row, leaves behind.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id, redacted=[RAW_TURNS[0][1], RAW_TURNS[1][1]])
    google = FakeVertex()
    use_fake_vertex(monkeypatch, google)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/assist_input_not_redacted")
    assert google.generate_requests == [], "the provider was reached with unredacted text"
    assert await _usage_rows(tenant_id) == []


async def test_a_turn_with_no_redacted_copy_at_all_fails_closed(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`transcript_turns.text_redacted` is NULLable, and the two wrong answers are
    obvious: send `text` instead (the residency inversion), or skip the turn and hand the
    client a summary of part of a call presented as a summary of the call."""
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id, redacted=[redact(RAW_TURNS[0][1]).text, None])
    google = FakeVertex()
    use_fake_vertex(monkeypatch, google)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/assist_transcript_not_redacted")
    assert google.generate_requests == []


def test_the_transcript_the_model_reads_is_speaker_prefixed_lines() -> None:
    """The shape `workers/pipeline._persist_transcript` builds from the RAW column, built
    here from the redacted one. One prompt builder reads both, so a second dialect would
    mean the assist ran against a format the golden-transcript fixtures never exercise."""
    assert assist.transcript_for_model([("agent", "Cheppandi."), ("caller", "Ravi.")]) == (
        "agent: Cheppandi.\ncaller: Ravi."
    )


# ------------------------------------------------- 2. a refusal costs nothing (G-4, G-5)


async def test_a_tenant_at_the_ceiling_is_refused_before_a_token_is_spent(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-5's block, from the outside, and the three things a refusal must not do.

    `ai_quota_exceeded` is the code the browser switches on to open the wallet dialog, so
    it is asserted by name rather than by status: a 422 with a different code would leave
    the client with a dead button and no dialog.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    await _at_the_ceiling(tenant_id, monkeypatch)
    google = FakeVertex()
    use_fake_vertex(monkeypatch, google)
    spend_before = await _platform_spend()

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/ai_quota_exceeded")
    assert response.json()["remediation"], "a refusal a person can act on, not a bare code"
    # In this order: the provider first, because a ledger assertion alone passes on a path
    # that paid Google and then failed to record it.
    assert google.generate_requests == [], "the model was called for a refused request"
    assert google.token_requests == [], "even the bearer was not worth minting"
    assert await _usage_rows(tenant_id) == []
    assert await _platform_spend() == spend_before
    assert await _audit_actions(call_id) == []


async def test_a_call_with_no_transcript_is_refused_for_that_reason_and_not_for_money(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SUBJECT before GATE, which is the one ordering choice that is not about money.

    A client at their ceiling pressing this on a call whose transcript has not landed
    would otherwise be told to spend ₹500 on a call the money cannot help with. Both
    conditions hold here, and the answer names the one they can act on.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _empty_call(tenant_id)
    await _at_the_ceiling(tenant_id, monkeypatch)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/assist_no_transcript")


async def test_another_tenants_call_is_not_found_rather_than_assisted() -> None:
    """Hard rule 1 from the outside. Under RLS "no such call" and "somebody else's call"
    are one answer, deliberately, and the route must not turn the second into a 200."""
    tenant_id, slug, token = await _make_tenant()
    other_tenant, _other_slug, _other_token = await _make_tenant()
    stranger_call = await _call_with_transcript(other_tenant)

    async with _client() as http:
        response = await http.post(
            f"/v1/calls/{stranger_call}/assist", headers=_headers(token, slug)
        )

    assert response.status_code == 404, response.text
    assert await _usage_rows(tenant_id) == []
    assert await _usage_rows(other_tenant) == []


async def test_the_request_is_refused_without_an_idempotency_key() -> None:
    """REQUIRED, not optional (draft-ietf-httpapi-idempotency-key-header-07 §2.4 asks for
    a 400 with a problem body). An optional key protects only the callers that remember
    to send one — this console, on the day it was written — and what a repeat costs here
    is a second silent payment to Google."""
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)

    async with _client() as http:
        response = await http.post(
            f"/v1/calls/{call_id}/assist", headers=_headers(token, slug, key=None)
        )

    assert response.status_code == 400, response.text
    assert response.json()["type"].endswith("/idempotency_key_required")
    assert "Idempotency-Key" in (response.json()["remediation"] or "")


async def test_a_staff_member_cannot_spend_the_accounts_ai_allowance() -> None:
    """`org:manage`, with the control that makes the 403 mean something: the same token
    reaches a client-realm route it DOES hold, so the refusal is about this permission
    and not about a broken credential.

    The population is deliberately the same one the rest of the AI surface already has —
    `GET /v1/billing/ai-quota` is `billing:read` and the purchase is `org:manage`, both
    owner-only, on SEC-COMP §5's ground that spend is an owner's business.
    """
    tenant_id, slug, token = await _make_tenant(role="staff")
    call_id = await _call_with_transcript(tenant_id)
    headers = _headers(token, slug)

    async with _client() as http:
        refused = await http.post(f"/v1/calls/{call_id}/assist", headers=headers)
        accepted = await http.get(f"/v1/calls/{call_id}", headers=headers)

    assert accepted.status_code == 200, (
        f"the control failed: this staff token cannot read a call either ({accepted.text}), "
        "so the refusal below proves nothing about the permission"
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["kind"] == "permission"


# ------------------------------------------------------- 3. the happy path, and the meter


async def test_a_successful_assist_is_metered_in_ktok_at_the_published_price(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The join, end to end: Vertex's own token count becomes two `usage_events` rows and
    one movement of the platform counter, under a server-minted key.

    The quantities are asserted as exact `Decimal`s in THOUSANDS of tokens, because that
    is the whole of D-137's unit argument — `unit_cost_paid` is NUMERIC(12,4) and a
    per-TOKEN price would have stored as 0.0000 and made every assist free.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    google = FakeVertex()  # 1,200 prompt / 300 candidates + 500 thoughts
    use_fake_vertex(monkeypatch, google)
    spend_before, requests_before = await _platform_spend()

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"], "the assistant's answer reached the client"
    assert body["disclosure"] is None, "nothing was substituted, so nothing to disclose"
    assert body["metered"] is True

    rows = await _usage_rows(tenant_id)
    assert [r[0] for r in rows] == ["ai_assist_ktok_in", "ai_assist_ktok_out"]
    assert rows[0][1] == Decimal("1.2000"), "1,200 prompt tokens are 1.2 ktok"
    # 300 candidates + 500 thinking tokens: Gemini 3 bills thoughts at the OUTPUT rate and
    # `candidatesTokenCount` does not include them.
    assert rows[1][1] == Decimal("0.8000")
    assert rows[0][2] == ai_quota.LLM_INR_PER_KTOK["in"]
    assert rows[1][2] == ai_quota.LLM_INR_PER_KTOK["out"]
    assert rows[0][3] == rows[1][3], "both legs of one assist share one key"
    assert rows[0][3].startswith("assist:"), "the key is the server's, never a browser's"

    exact = (
        Decimal("1.2") * ai_quota.LLM_INR_PER_KTOK["in"]
        + Decimal("0.8") * ai_quota.LLM_INR_PER_KTOK["out"]
    )
    # ₹0.225800 exactly at `gemini-2.5-flash` prices, and `platform_ai_spend.spend_inr` is
    # NUMERIC(12,4), so what the counter can hold is ₹0.2258. QUANTIZED here rather than
    # the assertion loosened to an `approx`: the rounding is a property of the column and
    # is what the brake will actually accumulate, and a tolerance would also pass on an
    # arithmetic error. Pinned as a LITERAL beside the derivation on purpose — the two
    # agree only while the price table and this file's arithmetic agree, which is the
    # thing a price change (and there has already been one) is most likely to break.
    expected = exact.quantize(Decimal("0.0001"))
    assert expected == Decimal("0.2258")
    spend_after, requests_after = await _platform_spend()
    assert spend_after - spend_before == expected
    assert requests_after - requests_before == 1
    assert await _audit_actions(call_id) == ["call.ai_assist"]


async def test_the_stored_summary_and_extraction_are_left_exactly_as_they_were(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-summarise is a VIEW, not a rewrite (`crm/assist.py` argues why).

    The stored record is the FIRST pass over the RAW transcript, which is the only pass
    that can capture a callback number; replacing it with a redacted-pass reading would
    silently degrade the lead, the Leads columns and the CSV export — and
    `call_extractions` rows are what pins a lead to its schema version, so it would
    rewrite history a client may already have exported.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    google = FakeVertex()
    google.answer = {**google.answer, "summary": "A completely different second reading."}
    use_fake_vertex(monkeypatch, google)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.json()["summary"] == "A completely different second reading."
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(text("SELECT summary FROM calls WHERE id = :i"), {"i": call_id})
        ).scalar()
        extractions = (
            await session.execute(
                text("SELECT count(*) FROM call_extractions WHERE call_id = :i"), {"i": call_id}
            )
        ).scalar()
    assert stored == "First pass.", "the assist overwrote the raw pass's summary"
    assert extractions == 0, "the assist wrote an extraction row"


async def test_the_answer_goes_out_through_the_same_redaction_pass_as_every_summary(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Belt to the braces. The model cannot copy a digit it never saw, so this pass should
    never have anything to do — which is exactly why it has to be tested: a guard that is
    normally a no-op is a guard nobody notices the absence of. A model that invents a
    phone-shaped run (or a future prompt that quotes one back) must not print it."""
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    google = FakeVertex()
    google.answer = {**google.answer, "summary": f"Ravi asked us to ring {CALLER_NUMBER}."}
    use_fake_vertex(monkeypatch, google)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    summary = response.json()["summary"]
    assert CALLER_NUMBER not in summary
    assert "[phone ••23]" in summary
    assert "Ravi asked us to ring" in summary, "the sentence survived; only the digits went"


# --------------------------------------------------------- 4. the double-click (D-140)


async def test_the_same_idempotency_key_answers_twice_and_is_paid_for_once(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deduping AFTER the provider has been paid hides the spend rather than saving it
    (`billing/ai_quota.ASSIST_REF_PREFIX`), so the second click must not reach Vertex at
    all — asserted on the request count, not only on the ledger."""
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    google = FakeVertex()
    use_fake_vertex(monkeypatch, google)
    spend_before, requests_before = await _platform_spend()
    headers = _headers(token, slug, key=f"double-{uuid.uuid4().hex[:8]}")

    async with _client() as http:
        first = await http.post(f"/v1/calls/{call_id}/assist", headers=headers)
        second = await http.post(f"/v1/calls/{call_id}/assist", headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json(), "the second click got a different answer"
    assert len(google.generate_requests) == 1, "the second click was paid for"
    rows = await _usage_rows(tenant_id)
    assert len(rows) == 2, "one assist is two rows (in and out), not four"
    spend_after, requests_after = await _platform_spend()
    assert requests_after - requests_before == 1
    assert spend_after > spend_before


async def test_a_different_key_on_the_same_call_is_a_second_assist(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half, and the reason the key is per-ATTEMPT rather than per-call.

    Asking the assistant twice about one call is a legitimate thing to do — the first
    answer was thin, the caller rang back, the lead is being written up — and an
    idempotency scheme keyed on the CALL would answer the second ask with the first
    answer forever, at no charge and with no way to tell.

    THIS TEST WAS WRITTEN THE LAZY WAY FIRST and is recorded here because it passed:
    `assert body_hash({"call_id": "a"}) != body_hash({"call_id": "b"})` is green whatever
    this route does, because it exercises `reliability.service` and never issues a
    request. Its NAME made a claim about the endpoint that its body could not fail on.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    google = FakeVertex()
    use_fake_vertex(monkeypatch, google)
    spend_before, requests_before = await _platform_spend()

    async with _client() as http:
        first = await http.post(
            f"/v1/calls/{call_id}/assist",
            headers=_headers(token, slug, key=f"ask-1-{uuid.uuid4().hex[:8]}"),
        )
        second = await http.post(
            f"/v1/calls/{call_id}/assist",
            headers=_headers(token, slug, key=f"ask-2-{uuid.uuid4().hex[:8]}"),
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(google.generate_requests) == 2, "the second ask was answered from a cache"
    rows = await _usage_rows(tenant_id)
    assert len(rows) == 4, "two assists are four rows under two distinct keys"
    assert len({row[3] for row in rows}) == 2, "both assists metered under one key"
    spend_after, requests_after = await _platform_spend()
    assert requests_after - requests_before == 2
    assert spend_after > spend_before


# -------------------------- 5. G-6: the fallback is disclosed, and it is not metered


async def test_a_gemini_outage_answers_with_sarvam_and_the_disclosure_reaches_the_client(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-6 forbids a silent fallback, so the sentence is part of the RESPONSE and not a
    thing the screen is trusted to remember to compose.

    And the free leg writes no rupees: D-36 prices Sarvam at zero, so a `usage_events`
    row here would be a Gemini quantity claimed for a call Gemini never served.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)
    spend_before = await _platform_spend()

    async def _vertex_down(
        self: VertexGeminiExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        raise httpx.ConnectError("vertex is unreachable")

    sarvam_saw: list[str] = []

    async def _sarvam_run(
        self: SarvamExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        sarvam_saw.append(transcript)
        return {"summary": "Ravi wants a Tuesday slot.", "sentiment": "neutral"}

    monkeypatch.setattr(VertexGeminiExtractor, "run", _vertex_down)
    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == "Ravi wants a Tuesday slot."
    assert body["disclosure"] is not None, "a silent fallback is the one thing G-6 rules out"
    assert "Sarvam" in body["disclosure"]
    assert "did not answer" in body["disclosure"]
    assert body["metered"] is False
    # The fallback saw the SAME redacted text — a second provider is not a second rule.
    assert CALLER_NUMBER not in sarvam_saw[0]
    assert await _usage_rows(tenant_id) == []
    assert await _platform_spend() == spend_before


async def test_no_provider_at_all_is_a_refusal_with_something_to_do_about_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bottom rung. A deployment with neither credential must not answer a spinner or
    an empty summary — `assist_unavailable` carries the remediation `ProblemNotice`
    renders verbatim, and the client's copy of it names an action a CLIENT can take."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gcp_project_id", None, raising=False)
    monkeypatch.setattr(settings, "gcp_service_account_json", None, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", None, raising=False)
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 502, response.text
    assert response.json()["type"].endswith("/assist_no_credential")
    assert response.json()["remediation"]
    assert await _usage_rows(tenant_id) == []


# ------------------------------- 6. `usage is None` on Gemini: an alert, never a zero


async def test_a_gemini_answer_vertex_did_not_count_alerts_instead_of_metering_zero(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE decision this join had to make, and the one D-140 named in advance.

    `AssistResult.usage is None` has two causes and they are not the same event. A Sarvam
    fallback is free (test above). A GEMINI answer with no `usageMetadata` is money we
    spent and cannot account for: the tenant's ceiling and the platform brake are both
    blind to it. Metering it as zero would be a fabricated quantity in an append-only
    ledger, and estimating it from the transcript length is exactly what D-140 refused —
    "a fabricated quantity in a ledger looks exactly like a real one".

    So: the client still gets their answer (we paid for it), nothing is written, and an
    operator is told. The assertion is on the ALERT, because "no rows" is also what a
    quietly broken meter looks like.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    google = FakeVertex()
    google.usage = None  # a body with no `usageMetadata` block at all
    use_fake_vertex(monkeypatch, google)
    spend_before = await _platform_spend()

    fired: list[tuple[str, str, dict[str, str]]] = []

    def _capture(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append((stage, code, ids))

    monkeypatch.setattr(assist, "alert", _capture)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 200, response.text
    assert response.json()["summary"], "we paid for this answer; the client still gets it"
    assert response.json()["metered"] is False
    assert await _usage_rows(tenant_id) == [], "an unknown quantity is not a zero one"
    assert await _platform_spend() == spend_before
    assert [(stage, code) for stage, code, _ in fired] == [("CORE_LOGIC", "ai_assist_unmeterable")]
    assert fired[0][2]["tenant_id"] == str(tenant_id)
    assert fired[0][2]["feature"] == assist.ASSIST_FEATURE_RESUMMARISE


async def test_a_sarvam_fallback_is_unmetered_without_waking_an_operator(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the same `if`, asserted separately because the two outcomes look
    identical in the ledger and must not look identical to a person on call: a free leg is
    correct and an unaccountable paid leg is an incident."""
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    async def _vertex_down(
        self: VertexGeminiExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        raise httpx.ConnectError("vertex is unreachable")

    async def _sarvam_run(
        self: SarvamExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        return {"summary": "Sarvam answered."}

    monkeypatch.setattr(VertexGeminiExtractor, "run", _vertex_down)
    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)
    fired: list[str] = []
    monkeypatch.setattr(
        assist,
        "alert",
        lambda stage, code, **kw: fired.append(code),
    )

    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/assist", headers=_headers(token, slug))

    assert response.status_code == 200, response.text
    assert response.json()["metered"] is False
    assert fired == [], "a free, disclosed fallback is not an incident"


# --------------------------------------------------- 7. the wiring the halves asked for


def test_the_provider_names_the_response_can_carry_are_the_ladders_own() -> None:
    """`meter_assist` branches on `capability.provider == GEMINI_PROVIDER`, so the two
    constants have to be the ones `assist_capability` actually sets. A typo here would
    meter a Sarvam fallback at Gemini prices and alert on nothing."""
    assert GEMINI_PROVIDER == "gemini"
    assert SARVAM_PROVIDER == "sarvam"


def test_the_route_declares_a_mutating_permission_that_exists_and_is_granted() -> None:
    """D-119's two halves in one assertion: a declared permission that is not in
    `get_args(Permission)` is a typo two copies of which agree with each other, and one no
    role holds is a lock with no key — a route that reads as guarded and is dead."""
    from typing import get_args

    from apps.api.core.rbac import (
        GRANTED_PERMISSIONS,
        MUTATING_PERMISSIONS,
        Permission,
        iter_api_routes,
    )

    route = next(r for r in iter_api_routes(app) if r.path == "/v1/calls/{call_id}/assist")
    declared = (route.openapi_extra or {})["x-calevate-permission"]
    assert declared in get_args(Permission)
    assert declared in GRANTED_PERMISSIONS
    assert declared in MUTATING_PERMISSIONS, (
        "an assist spends money, so a D-22 read-only operator must be refused it"
    )
    assert route.methods == {"POST"}


async def test_a_failure_after_the_provider_was_paid_does_not_let_the_same_key_pay_again(
    vertex_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CORRECTNESS 1 (D-181): the claim used to roll back with the side effect it guards.

    `claim_idempotency` INSERTed the `processing` record into the REQUEST's transaction.
    `core/deps.db` rolls that transaction back on any exception — so a raise anywhere
    after `run_assist` (the audit chain refusing to write, a statement timeout, a severed
    connection) erased the claim, the usage rows and the audit row while **Google had
    already been paid**, and the retry with the same key — which is what the key is for —
    paid a second time.

    Driven with the audit write raising, because that is the failure the audit report
    names and it sits between the payment and the response. What must be true afterwards
    is one thing: the second request with the same key does not reach Vertex.
    """
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    google = FakeVertex()
    use_fake_vertex(monkeypatch, google)
    headers = _headers(token, slug, key=f"crash-{uuid.uuid4().hex[:8]}")

    async def refuse_to_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit chain unavailable")

    # Patched and restored BY HAND rather than through `monkeypatch.undo()`: undo() is
    # per-test, not per-call, so it would also revert `vertex_configured`'s environment
    # and the retry below would be refused as `assist_no_credential` — a green test that
    # never reached the model. (That is not hypothetical; it is what this test did first.)
    original_write_audit = crm_routes.write_audit
    crm_routes.write_audit = refuse_to_audit  # type: ignore[assignment]
    # The 500 is not the subject; what the crashed request left behind is. `_client()`
    # re-raises an unhandled server exception into the test, which would end it before
    # the retry.
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://api"
    ) as http:
        first = await http.post(f"/v1/calls/{call_id}/assist", headers=headers)
    assert first.status_code >= 500, first.text
    assert len(google.generate_requests) == 1, "the provider was paid once"

    crm_routes.write_audit = original_write_audit  # type: ignore[assignment]
    async with _client() as http:
        second = await http.post(f"/v1/calls/{call_id}/assist", headers=headers)

    assert len(google.generate_requests) == 1, (
        f"the retry paid Google a second time (status {second.status_code}): the claim "
        "did not survive the failure it exists to survive"
    )
