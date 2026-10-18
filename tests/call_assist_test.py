"""The seam: a second reading of one call, asked of Pip (`call_summarise_again`, D-821)
— subject, gate, run, meter (D-127). It was `POST /v1/calls/{call_id}/assist`; every
property below is the same, proved through the confirmation that replaced the route.

`billing/ai_quota.py` (D-137/D-140) and `workers/extraction.run_assist` (D-134/D-142)
were built one call apart by two agents who did not know about each other, and both
recorded the same top gap: nothing joined them, so the ledger, the ceiling, the wallet
dialog, the platform brake, the capability ladder and the assistant client were reachable
by no user. `crm/resummarise.second_reading` is the call that joins them and this file is
what makes each half of the join falsifiable.

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
3. **A double-click is paid for once.** The card's token is burnt BEFORE the model call, the
   only place it saves anything (`billing/ai_quota.ASSIST_REF_PREFIX`).
4. **A fallback is disclosed and is not metered.** The sentence reaches the response, and
   the free leg writes no rupees.
5. **`usage is None` on the PAID leg is an alert, not a zero.** The one case where "we
   do not know" and "it was free" would otherwise meter the same.

WHAT D-410 CHANGED IN THIS FILE, and it is smaller than the diff suggests. Every property
above is unchanged; the provider under them moved from Gemini on Vertex to Azure OpenAI,
and one assertion class GENUINELY DISAPPEARED rather than being relaxed — there is no
bearer to mint, so "even the token exchange did not happen" is not a thing a refusal can
be checked against any more. A static key is why (D-410), and the tests that used to make
that check now check the one request that remains.

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
from apps.api.billing import ai_quota, rates
from apps.api.copilot import write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.schemas import CopilotProposalEvent
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.crm import assist, resummarise
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import extraction as extraction_module
from apps.workers.chat import TokenUsage
from apps.workers.extraction import (
    GOOGLE_PROVIDER,
    SARVAM_PROVIDER,
    AssistCapability,
    AssistResult,
    AzureOpenAIExtractor,
    SarvamExtractor,
)
from apps.workers.redaction import redact
from calevate_shared.engine import AZURE_OPENAI_DEFAULT_MODEL, LLM_MODELS
from calevate_shared.extraction import ExtractionOutput, ExtractionSchemaSpec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

# ONE fake Azure in this repo. It records the request objects httpx was actually handed,
# which is the artefact test 1 needs, and a second copy here would drift from the response
# shape the client parses. Same reason `route_shape_test` imports `view_as_headers`.
from tests.azure_extraction_test import API_KEY, DEPLOYMENT, RESOURCE, FakeAzure

#: A Telugu turn with a real-shaped Indian mobile in it — the exact pair hard rule 6
#: names. `redact()` keeps the last two digits, so the redacted copy is recognisably the
#: same sentence and the assertion "the raw number is absent" is not satisfied by the
#: whole turn being absent.
CALLER_NUMBER = "9876500123"
RAW_TURNS: list[tuple[str, str]] = [
    ("agent", "Namaskaram, Sunrise Clinic. Cheppandi."),
    ("caller", f"Naa peru Ravi. Naa number {CALLER_NUMBER}, repu appointment kavali."),
]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


TOOL = "call_summarise_again"


class _Answer:
    """What the person was shown: the reading's three facts, or the refusal's problem body."""

    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body

    @property
    def text(self) -> str:
        return json.dumps(self.body, default=str)

    def json(self) -> dict[str, Any]:
        return self.body


#: The readings `second_reading` returned, in order: the confirmation shows them as one
#: sentence, and these tests assert the three facts it is made from.
_READINGS: list[resummarise.SecondReading] = []


@pytest.fixture(autouse=True)
def _keep_each_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    _READINGS.clear()
    real = resummarise.second_reading

    async def spy(*args: Any, **kwargs: Any) -> resummarise.SecondReading:
        reading = await real(*args, **kwargs)
        _READINGS.append(reading)
        return reading

    monkeypatch.setattr(resummarise, "second_reading", spy)


def _principal(tenant_id: UUID, token: str, role: str = "owner") -> Principal:
    user_id = UUID(token.rsplit(":", 1)[1])
    return Principal(realm="client", user_id=user_id, tenant_id=tenant_id, role=role)


async def _card(principal: Principal, call_id: UUID) -> CopilotProposalEvent:
    return await write_tools.plan_write(
        TOOL, json.dumps({"call_id": str(call_id)}), actor=write_tools.actor_for(principal)
    )


async def _ask(tenant_id: UUID, token: str, call_id: UUID, *, role: str = "owner") -> _Answer:
    """Pip proposes, the person confirms: the whole path the call page's button took."""
    principal = _principal(tenant_id, token, role)
    try:
        proposal = await _card(principal, call_id)
        async with tenant_session(tenant_id) as session:
            out = await write_tools.confirm(session, proposal.token, principal=principal, ip=None)
    except ProblemError as refused:
        return _Answer(refused.status, {**refused.as_problem(), "remediation": refused.remediation})
    except WriteRefusedError as refused:
        return _Answer(403, {"kind": "permission", "detail": refused.reason})
    reading = _READINGS[-1]
    return _Answer(
        200,
        {
            "summary": reading.summary,
            "disclosure": reading.disclosure,
            "metered": reading.metered,
            "detail": out.detail,
        },
    )


@pytest.fixture(autouse=True)
def _the_platform_brake_is_not_this_suites_business(monkeypatch: pytest.MonkeyPatch) -> None:
    """`platform_ai_spend` is shared with every other suite on this database and only
    ever goes up. `ai_quota_test` records what depending on it cost that file; this one
    severs the dependency for the same reason rather than re-learning it."""

    async def not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


@pytest.fixture
def azure_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment holding an Azure OpenAI credential and NO Sarvam key: the top rung of
    the ladder, so anything that falls off it has to say so.

    THE THREE FIELDS ARE SET TOGETHER because `azure_credentials()` requires all three —
    a half-set deployment is a distinct state with its own test in
    `tests/azure_extraction_test.py`, and reaching it here by accident would silently
    move every test in this file onto the fallback rung.

    ⚠ **IT MUST ALSO PIN `platform_llm_model`, AND THAT IS NEW (D-530).** Holding an Azure
    credential no longer puts an account ON the Azure leg: the platform default moved to
    `gemini-2.5-flash-lite`, so an account that has chosen no model of its own resolves to
    the GOOGLE leg, finds no Google credential, and the assistant correctly falls to its
    disclosed substitution. That is the ladder working — but it is not what these tests are
    about, and without this line they assert Azure metering against an answer Azure never
    produced.

    IT NO LONGER RESETS A TOKEN CACHE. The fixture beside this one used to, because the
    Vertex bearer was process-level state shared between tests; an Azure key is static
    and is read per request, so there is nothing to go stale. That is a deleted class of
    test flakiness rather than an omission.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", RESOURCE, raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", API_KEY, raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", DEPLOYMENT, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    monkeypatch.setattr(settings, "platform_llm_model", AZURE_OPENAI_DEFAULT_MODEL, raising=False)


def use_fake_azure(monkeypatch: pytest.MonkeyPatch, azure: FakeAzure) -> None:
    """Drive the REAL Azure client through httpx's own plumbing.

    Patching the class rather than its `run` method is deliberate: the URL, the
    authorization header and the request body are all built inside the constructor and
    `run`, and a hand-written stand-in for them could not get any of them wrong — which
    is exactly what test 1 is trying to catch.
    """

    # `timeout_s` is accepted and forwarded rather than dropped: `azure_extractor()` now
    # passes it (the assist path asks for the tighter user-facing budget), and a stand-in
    # that swallowed the keyword would make every one of these tests pass while the real
    # constructor's signature had moved. It has no effect on the request here — the
    # injected client owns its own timeout, which is the adapter's stated ownership rule.
    def _stand_in(
        resource: str,
        api_key: str,
        deployment: str,
        model: str,
        timeout_s: float = extraction_module.EXTRACTION_TIMEOUT_S,
    ) -> AzureOpenAIExtractor:
        return AzureOpenAIExtractor(
            resource, api_key, deployment, model, client=azure.client(), timeout_s=timeout_s
        )

    monkeypatch.setattr(extraction_module, "AzureOpenAIExtractor", _stand_in)


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
                "'First pass.', 'neutral', 'answered', now(), now(), now())"
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


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


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


# ----------------------------------------- 1. G-2: raw transcript text never reaches Azure


async def test_the_model_is_sent_the_redacted_turns_and_never_the_raw_column(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
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
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    azure = FakeAzure()
    use_fake_azure(monkeypatch, azure)

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 200, response.text
    sent = azure.sent.content.decode()
    assert CALLER_NUMBER not in sent, "the raw transcript column reached Azure"
    assert json.dumps(CALLER_NUMBER)[1:-1] not in sent
    assert "[phone ••23]" in sent, (
        "the redacted turn is missing too — the assertion above proves nothing if the "
        "transcript never travelled at all"
    )
    assert "Namaskaram" in sent, "the agent's turn is part of the conversation the model reads"


async def test_the_model_is_told_the_language_the_agent_speaks(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE agents SET language_primary = 'hi-IN'"))
    azure = FakeAzure()
    use_fake_azure(monkeypatch, azure)

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 200, response.text
    sent = azure.sent.content.decode()
    assert "The call is in Hindi" in sent
    assert "The call is in Telugu" not in sent


async def test_a_turn_whose_redacted_copy_still_holds_a_number_is_refused_before_the_model(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
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
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id, redacted=[RAW_TURNS[0][1], RAW_TURNS[1][1]])
    azure = FakeAzure()
    use_fake_azure(monkeypatch, azure)

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/assist_input_not_redacted")
    assert azure.requests == [], "the provider was reached with unredacted text"
    assert await _usage_rows(tenant_id) == []


async def test_a_turn_with_no_redacted_copy_at_all_fails_closed(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`transcript_turns.text_redacted` is NULLable, and the two wrong answers are
    obvious: send `text` instead (the residency inversion), or skip the turn and hand the
    client a summary of part of a call presented as a summary of the call."""
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id, redacted=[redact(RAW_TURNS[0][1]).text, None])
    azure = FakeAzure()
    use_fake_azure(monkeypatch, azure)

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/assist_transcript_not_redacted")
    assert azure.requests == []


def test_the_transcript_the_model_reads_is_speaker_prefixed_lines() -> None:
    """The shape `workers/pipeline._persist_transcript` builds from the RAW column, built
    here from the redacted one. One prompt builder reads both, so a second dialect would
    mean the assist ran against a format the golden-transcript fixtures never exercise."""
    assert assist.transcript_for_model([("agent", "Cheppandi."), ("caller", "Ravi.")]) == (
        "agent: Cheppandi.\ncaller: Ravi."
    )


# ------------------------------------------------- 2. a refusal costs nothing (G-4, G-5)


async def test_a_tenant_at_the_ceiling_is_refused_before_a_token_is_spent(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-5's block, from the outside, and the three things a refusal must not do.

    `ai_quota_exceeded` is the code the browser switches on to open the wallet dialog, so
    it is asserted by name rather than by status: a 422 with a different code would leave
    the client with a dead button and no dialog.
    """
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    await _at_the_ceiling(tenant_id, monkeypatch)
    azure = FakeAzure()
    use_fake_azure(monkeypatch, azure)
    spend_before = await _platform_spend()

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/ai_quota_exceeded")
    assert response.json()["remediation"], "a refusal a person can act on, not a bare code"
    # In this order: the provider first, because a ledger assertion alone passes on a path
    # that paid Microsoft and then failed to record it.
    #
    # THIS USED TO BE TWO ASSERTIONS and the second one is deleted rather than weakened:
    # under Vertex a refusal also had to prove no BEARER was minted, because minting one
    # was a second network round trip on the same path. A static Azure key is read out of
    # settings, so there is exactly one request a refusal can fail to avoid, and it is
    # this one (D-410).
    assert azure.requests == [], "the model was called for a refused request"
    assert await _usage_rows(tenant_id) == []
    assert await _platform_spend() == spend_before
    assert await _audit_actions(call_id) == []


async def test_a_call_with_no_transcript_is_refused_for_that_reason_and_not_for_money(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SUBJECT before GATE, which is the one ordering choice that is not about money.

    A client at their ceiling pressing this on a call whose transcript has not landed
    would otherwise be told to spend ₹500 on a call the money cannot help with. Both
    conditions hold here, and the answer names the one they can act on.
    """
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _empty_call(tenant_id)
    await _at_the_ceiling(tenant_id, monkeypatch)

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/assist_no_transcript")


async def test_another_tenants_call_is_not_found_rather_than_assisted() -> None:
    """Hard rule 1 from the outside. Under RLS "no such call" and "somebody else's call"
    are one answer, deliberately, and the route must not turn the second into a 200."""
    tenant_id, _slug, token = await _make_tenant()
    other_tenant, _other_slug, _other_token = await _make_tenant()
    stranger_call = await _call_with_transcript(other_tenant)

    response = await _ask(tenant_id, token, stranger_call)

    assert response.status_code == 404, response.text
    assert await _usage_rows(tenant_id) == []
    assert await _usage_rows(other_tenant) == []


async def test_a_staff_member_cannot_spend_the_accounts_ai_allowance() -> None:
    """`org:manage`, with the control that makes the refusal mean something: the same token
    reaches a client-realm route it DOES hold, so the refusal is about this permission
    and not about a broken credential.

    The population is deliberately the same one the rest of the AI surface already has —
    `GET /v1/billing/ai-quota` is `billing:read` and the purchase is `org:manage`, both
    owner-only, on SEC-COMP §5's ground that spend is an owner's business.
    """
    tenant_id, slug, token = await _make_tenant(role="staff")
    call_id = await _call_with_transcript(tenant_id)

    refused = await _ask(tenant_id, token, call_id, role="staff")
    async with _client() as http:
        accepted = await http.get(f"/v1/calls/{call_id}", headers=_headers(token, slug))

    assert accepted.status_code == 200, (
        f"the control failed: this staff token cannot read a call either ({accepted.text}), "
        "so the refusal below proves nothing about the permission"
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["kind"] == "permission"


# ------------------------------------------------------- 3. the happy path, and the meter


async def test_a_successful_assist_is_metered_in_ktok_at_the_published_price(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The join, end to end: Azure's own token count becomes two `usage_events` rows and
    one movement of the platform counter, under a server-minted key.

    The quantities are asserted as exact `Decimal`s in THOUSANDS of tokens, because that
    is the whole of D-137's unit argument — `unit_cost_paid` is NUMERIC(12,4) and a
    per-TOKEN price would have stored as 0.0000 and made every assist free.
    """
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    azure = FakeAzure()  # 1,200 prompt / 800 completion, 500 of them reasoning
    use_fake_azure(monkeypatch, azure)
    spend_before, requests_before = await _platform_spend()

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"], "the assistant's answer reached the client"
    assert body["disclosure"] is None, "nothing was substituted, so nothing to disclose"
    assert body["metered"] is True

    rows = await _usage_rows(tenant_id)
    assert [r[0] for r in rows] == ["ai_assist_ktok_in", "ai_assist_ktok_out"]
    assert rows[0][1] == Decimal("1.2000"), "1,200 prompt tokens are 1.2 ktok"
    # 800 completion tokens, of which 500 are reasoning. `completion_tokens_details` is a
    # BREAKDOWN of `completion_tokens`, never an addition to it — adding them would bill
    # 1.3 ktok for 0.8 ktok of output, which is the regression this number exists to fail.
    assert rows[1][1] == Decimal("0.8000")
    prices = rates.llm_inr_per_ktok(get_settings().azure_openai_model)
    assert rows[0][2] == prices["in"]
    assert rows[1][2] == prices["out"]
    assert rows[0][3] == rows[1][3], "both legs of one assist share one key"
    assert rows[0][3].startswith("assist:"), "the key is the server's, never a browser's"

    exact = Decimal("1.2") * prices["in"] + Decimal("0.8") * prices["out"]
    # `platform_ai_spend.spend_inr` is NUMERIC(12,4), so what the counter can hold is four
    # decimals. QUANTIZED here rather than the assertion loosened to an `approx`: the
    # rounding is a property of the column and is what the brake will actually accumulate,
    # and a tolerance would also pass on an arithmetic error.
    #
    # THE LITERAL THAT USED TO SIT HERE IS NOW A SECOND DERIVATION, and that is a
    # strengthening rather than a retreat (D-410). `₹0.2258` was pinned beside the
    # `LLM_INR_PER_KTOK` arithmetic so the two had to agree; the price is now per MODEL and
    # `azure_openai_model` is a live console switch between two models 2.7x apart, so a
    # single literal would pin one model's price into a test about metering arithmetic and
    # fail on a config change that is supposed to be free. What replaces it is the same
    # cross-check taken one step further back — from the VENDOR'S dollars and the exchange
    # rate, not from the rupee table this row was written out of — so an arithmetic error
    # anywhere in the chain still fails here.
    expected = exact.quantize(Decimal("0.0001"))
    # THE VENDOR'S DOLLARS, now read off the model's own catalogue entry (D-456)
    # instead of a price table beside it. The cross-check is unchanged and so is its
    # point: this derives from further back than the rupee table the metering row was
    # written out of, so an arithmetic error anywhere in the chain still fails here.
    from_vendor_usd = LLM_MODELS[get_settings().azure_openai_model].price
    per_ktok = {
        leg: (usd * rates.PLANNING_USD_INR / 1000).quantize(
            Decimal("0.0001"), rounding=rates.ROUNDING
        )
        for leg, usd in (
            ("in", from_vendor_usd.input_usd_per_mtok),
            ("out", from_vendor_usd.output_usd_per_mtok),
        )
    }
    assert expected == (
        Decimal("1.2") * per_ktok["in"] + Decimal("0.8") * per_ktok["out"]
    ).quantize(Decimal("0.0001"))
    spend_after, requests_after = await _platform_spend()
    assert spend_after - spend_before == expected
    assert requests_after - requests_before == 1
    assert await _audit_actions(call_id) == ["call.ai_assist"]


async def test_the_stored_summary_and_extraction_are_left_exactly_as_they_were(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-summarise is a VIEW, not a rewrite (`crm/assist.py` argues why).

    The stored record is the FIRST pass over the RAW transcript, which is the only pass
    that can capture a callback number; replacing it with a redacted-pass reading would
    silently degrade the lead, the Leads columns and the CSV export — and
    `call_extractions` rows are what pins a lead to its schema version, so it would
    rewrite history a client may already have exported.
    """
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    azure = FakeAzure()
    azure.answer = {**azure.answer, "summary": "A completely different second reading."}
    use_fake_azure(monkeypatch, azure)

    response = await _ask(tenant_id, token, call_id)

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
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Belt to the braces. The model cannot copy a digit it never saw, so this pass should
    never have anything to do — which is exactly why it has to be tested: a guard that is
    normally a no-op is a guard nobody notices the absence of. A model that invents a
    phone-shaped run (or a future prompt that quotes one back) must not print it."""
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    azure = FakeAzure()
    azure.answer = {**azure.answer, "summary": f"Ravi asked us to ring {CALLER_NUMBER}."}
    use_fake_azure(monkeypatch, azure)

    response = await _ask(tenant_id, token, call_id)

    summary = response.json()["summary"]
    assert CALLER_NUMBER not in summary
    assert "[phone ••23]" in summary
    assert "Ravi asked us to ring" in summary, "the sentence survived; only the digits went"


# ---------------------------------------------- 4. the double-click (D-140, then D-821)


async def test_one_confirmation_is_paid_for_once(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deduping AFTER the provider has been paid hides the spend rather than saving it
    (`billing/ai_quota.ASSIST_REF_PREFIX`), so a second press of the same Confirm must not
    reach Azure at all — asserted on the request count, not only on the ledger. Since
    D-821 the card's token is what dedupes (`write_tools.confirm` burns it once)."""
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    azure = FakeAzure()
    use_fake_azure(monkeypatch, azure)
    spend_before, requests_before = await _platform_spend()
    principal = _principal(tenant_id, token)
    proposal = await _card(principal, call_id)

    async with tenant_session(tenant_id) as session:
        await write_tools.confirm(session, proposal.token, principal=principal, ip=None)
    with pytest.raises(ProblemError) as again:
        async with tenant_session(tenant_id) as session:
            await write_tools.confirm(session, proposal.token, principal=principal, ip=None)

    assert again.value.code == "copilot_proposal_already_used"
    assert len(azure.requests) == 1, "the second press was paid for"
    rows = await _usage_rows(tenant_id)
    assert len(rows) == 2, "one assist is two rows (in and out), not four"
    spend_after, requests_after = await _platform_spend()
    assert requests_after - requests_before == 1
    assert spend_after > spend_before


async def test_asking_again_about_the_same_call_is_a_second_reading(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: asking twice about one call is legitimate — the first answer was
    thin, the caller rang back — so dedupe is per CONFIRMATION, never per call."""
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    azure = FakeAzure()
    use_fake_azure(monkeypatch, azure)
    spend_before, requests_before = await _platform_spend()

    first = await _ask(tenant_id, token, call_id)
    second = await _ask(tenant_id, token, call_id)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(azure.requests) == 2, "the second ask was answered from a cache"
    rows = await _usage_rows(tenant_id)
    assert len(rows) == 4, "two assists are four rows under two distinct keys"
    assert len({row[3] for row in rows}) == 2, "both assists metered under one key"
    spend_after, requests_after = await _platform_spend()
    assert requests_after - requests_before == 2
    assert spend_after > spend_before


# -------------------------- 5. G-6: the fallback is disclosed, and it is not metered


async def test_an_azure_outage_answers_with_sarvam_and_the_disclosure_reaches_the_client(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-6 forbids a silent fallback, so the sentence is part of the RESPONSE and not a
    thing the screen is trusted to remember to compose.

    And the free leg writes no rupees: D-36 prices Sarvam at zero, so a `usage_events`
    row here would be a paid quantity claimed for a call the paid leg never served.
    """
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)
    spend_before = await _platform_spend()

    async def _azure_down(
        self: AzureOpenAIExtractor, spec: ExtractionSchemaSpec, transcript: str, **_: Any
    ) -> dict[str, Any]:
        raise httpx.ConnectError("azure is unreachable")

    sarvam_saw: list[str] = []

    async def _sarvam_run(
        self: SarvamExtractor, spec: ExtractionSchemaSpec, transcript: str, **_: Any
    ) -> dict[str, Any]:
        sarvam_saw.append(transcript)
        return {"summary": "Ravi wants a Tuesday slot.", "sentiment": "neutral"}

    monkeypatch.setattr(AzureOpenAIExtractor, "run", _azure_down)
    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == "Ravi wants a Tuesday slot."
    assert body["disclosure"] is not None, "a silent fallback is the one thing G-6 rules out"
    assert "our standby model" in body["disclosure"]
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
    for field in (
        "azure_openai_resource",
        "azure_openai_api_key",
        "azure_openai_deployment",
        "sarvam_api_key",
    ):
        monkeypatch.setattr(settings, field, None, raising=False)
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 503, response.text
    assert response.json()["type"].endswith("/assist_no_credential")
    assert response.json()["remediation"]
    assert await _usage_rows(tenant_id) == []


# -------------------------------- 6. `usage is None` on Azure: an alert, never a zero


async def test_an_azure_answer_azure_did_not_count_alerts_instead_of_metering_zero(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE decision this join had to make, and the one D-140 named in advance.

    `AssistResult.usage is None` has two causes and they are not the same event. A Sarvam
    fallback is free (test above). An AZURE answer with no `usage` block is money we
    spent and cannot account for: the tenant's ceiling and the platform brake are both
    blind to it. Metering it as zero would be a fabricated quantity in an append-only
    ledger, and estimating it from the transcript length is exactly what D-140 refused —
    "a fabricated quantity in a ledger looks exactly like a real one".

    So: the client still gets their answer (we paid for it), nothing is written, and an
    operator is told. The assertion is on the ALERT, because "no rows" is also what a
    quietly broken meter looks like.
    """
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    azure = FakeAzure()
    azure.usage = None  # a 200 whose body carries no `usage` block at all
    use_fake_azure(monkeypatch, azure)
    spend_before = await _platform_spend()

    fired: list[tuple[str, str, dict[str, str]]] = []

    def _capture(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append((stage, code, ids))

    monkeypatch.setattr(assist, "alert", _capture)

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 200, response.text
    assert response.json()["summary"], "we paid for this answer; the client still gets it"
    assert response.json()["metered"] is False
    assert await _usage_rows(tenant_id) == [], "an unknown quantity is not a zero one"
    assert await _platform_spend() == spend_before
    assert [(stage, code) for stage, code, _ in fired] == [("CORE_LOGIC", "ai_assist_unmeterable")]
    assert fired[0][2]["tenant_id"] == str(tenant_id)
    assert fired[0][2]["feature"] == assist.ASSIST_FEATURE_RESUMMARISE


async def test_a_sarvam_fallback_is_unmetered_without_waking_an_operator(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the same `if`, asserted separately because the two outcomes look
    identical in the ledger and must not look identical to a person on call: a free leg is
    correct and an unaccountable paid leg is an incident."""
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    async def _azure_down(
        self: AzureOpenAIExtractor, spec: ExtractionSchemaSpec, transcript: str, **_: Any
    ) -> dict[str, Any]:
        raise httpx.ConnectError("azure is unreachable")

    async def _sarvam_run(
        self: SarvamExtractor, spec: ExtractionSchemaSpec, transcript: str, **_: Any
    ) -> dict[str, Any]:
        return {"summary": "Sarvam answered."}

    monkeypatch.setattr(AzureOpenAIExtractor, "run", _azure_down)
    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)
    fired: list[str] = []
    monkeypatch.setattr(
        assist,
        "alert",
        lambda stage, code, **kw: fired.append(code),
    )

    response = await _ask(tenant_id, token, call_id)

    assert response.status_code == 200, response.text
    assert response.json()["metered"] is False
    assert fired == [], "a free, disclosed fallback is not an incident"


# --------------------------------------------------- 7. the wiring the halves asked for


def test_the_action_declares_a_mutating_permission_that_exists_and_is_granted() -> None:
    """D-119's two halves in one assertion: a declared permission that is not in
    `get_args(Permission)` is a typo two copies of which agree with each other, and one no
    role holds is a lock with no key. And it is a confirm action: it spends money."""
    from typing import get_args

    from apps.api.core.rbac import GRANTED_PERMISSIONS, MUTATING_PERMISSIONS, Permission

    tool = write_tools.tool_named(TOOL)
    assert tool is not None
    assert tool.permission in get_args(Permission)
    assert tool.permission in GRANTED_PERMISSIONS
    assert tool.permission in MUTATING_PERMISSIONS, (
        "an assist spends money, so a D-22 read-only operator must be refused it"
    )
    assert tool.tier == "confirm" and tool.external_spend


async def test_a_failure_after_the_provider_was_paid_does_not_let_the_same_card_pay_again(
    azure_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CORRECTNESS 1 (D-181), on the path that replaced the route (D-821).

    A failure after the executor returned rolls back the confirm's transaction, and the
    confirm ordinarily gives the card's token back so the person can try again. The model
    was already paid and that money does not roll back, so for this action the token must
    stay spent (`ActionTool.external_spend`). Driven with the audit write raising, because
    it sits between the payment and the answer.
    """
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call_with_transcript(tenant_id)
    azure = FakeAzure()
    use_fake_azure(monkeypatch, azure)
    principal = _principal(tenant_id, token)
    proposal = await _card(principal, call_id)

    async def refuse_to_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit chain unavailable")

    real_write_audit = write_tools.write_audit
    monkeypatch.setattr(write_tools, "write_audit", refuse_to_audit)
    with pytest.raises(RuntimeError):
        async with tenant_session(tenant_id) as session:
            await write_tools.confirm(session, proposal.token, principal=principal, ip=None)
    assert len(azure.requests) == 1, "the provider was paid once"
    monkeypatch.setattr(write_tools, "write_audit", real_write_audit)
    with pytest.raises(ProblemError) as again:
        async with tenant_session(tenant_id) as session:
            await write_tools.confirm(session, proposal.token, principal=principal, ip=None)
    assert again.value.code == "copilot_proposal_already_used"
    assert len(azure.requests) == 1, "the same card paid Microsoft a second time"


async def test_a_provider_this_meter_does_not_know_is_not_quietly_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The free branch used to be a bare `else`, which SAID "not Azure" and MEANT "Sarvam".

    That fact is owned by `assist_capability`'s ladder in `apps/workers/extraction.py` and
    was depended on here with nothing comparing the two, so the DEFAULT for an
    unrecognised provider was "free" — on an append-only ledger, where a missing row
    cannot be back-filled by an UPDATE. It is not a live hole today (the ladder returns
    exactly two providers, and `SarvamExtractor` has no `last_usage` so that leg always
    arrives unmetered), and it opens the day somebody adds a third, PAID provider in a
    file that has no reason to look at this one.

    FAILS IF: the Sarvam arm goes back to being a bare `else`, or the unknown arm stops
    alerting. `meter_assist` is called directly because no route can produce this state —
    which is exactly why the arm needs a test of its own.

    The session is never touched: `usage is None` returns before any write, so passing
    `None` for it both proves that and keeps this a unit test.
    """
    fired: list[tuple[str, str, dict[str, str]]] = []

    def _capture(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append((stage, code, ids))

    monkeypatch.setattr(assist, "alert", _capture)
    tenant_id = uuid.uuid4()
    result = AssistResult(
        output=ExtractionOutput(summary="Answered by something new."),
        capability=AssistCapability(available=True, provider="a-third-model"),
        usage=None,
    )

    metering = await assist.meter_assist(
        None,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        ref="assist-unknown-provider",
        result=result,
    )

    assert metering.metered is False
    assert [(stage, code) for stage, code, _ in fired] == [
        ("CORE_LOGIC", "ai_assist_unknown_provider")
    ]
    assert fired[0][2]["provider"] == "a-third-model"
    assert fired[0][2]["tenant_id"] == str(tenant_id)


async def test_a_sarvam_fallback_is_still_the_recognised_free_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other side of the new `elif`, at the same level, so the pair fails apart.

    FAILS IF: the Sarvam arm is deleted or its provider constant is mistyped — either
    would route the ordinary, correct, free fallback into the unknown-provider alert and
    page an operator for a non-event every time Azure blinks.
    """
    fired: list[str] = []
    monkeypatch.setattr(assist, "alert", lambda stage, code, **kw: fired.append(code))

    result = AssistResult(
        output=ExtractionOutput(summary="Sarvam answered."),
        capability=AssistCapability(
            available=True,
            provider=SARVAM_PROVIDER,
            fallback_reason=extraction_module.PROVIDER_UNAVAILABLE_REASON,
        ),
        usage=None,
    )
    metering = await assist.meter_assist(
        None,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        ref="assist-sarvam",
        result=result,
    )

    assert metering.metered is False
    assert fired == [], "a free, disclosed fallback is not an incident"


async def test_a_gemini_answer_the_provider_did_not_count_is_unmeterable_not_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-478's paid third leg. A Gemini answer that carried no usage block is a metering
    OUTAGE — the same severity as Azure's, NOT the unknown-provider case — so it fires
    `ai_assist_unmeterable` with the provider named, never `ai_assist_unknown_provider` and
    never a fabricated zero.

    FAILS IF: `google` drops out of the paid-leg branch and falls into the unknown-provider
    catch-all, which would page an operator with the wrong message on a real outage."""
    fired: list[tuple[str, dict[str, str]]] = []

    def _capture(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append((code, ids))

    monkeypatch.setattr(assist, "alert", _capture)
    result = AssistResult(
        output=ExtractionOutput(summary="Gemini answered but sent no usage."),
        capability=AssistCapability(available=True, provider=GOOGLE_PROVIDER),
        usage=None,
    )

    metering = await assist.meter_assist(
        None,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        ref="assist-gemini-uncounted",
        result=result,
        model="gemini-2.5-flash",
    )

    assert metering.metered is False
    assert [code for code, _ in fired] == ["ai_assist_unmeterable"]
    assert fired[0][1]["provider"] == GOOGLE_PROVIDER


async def test_a_gemini_answer_meters_under_the_gemini_model_not_the_azure_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE PRICE HALF (hard rule 7). A Gemini answer with usage must reach
    `record_ai_assist_usage` under the GEMINI model id the run named — `rates.llm_inr_per_ktok`
    prices it directly — NOT `azure_openai_model`, which would put a wrong `unit_cost_paid`
    and a wrong `meta.model` on an append-only row. Proved by capturing the model that reaches
    the ledger writer, with no database: the writer is the one place the price is derived."""
    captured: dict[str, Any] = {}

    async def _fake_record(session: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)

        class _Recorded:
            recorded = True
            cost_inr = Decimal("0.01")

        return _Recorded()

    monkeypatch.setattr(assist, "record_ai_assist_usage", _fake_record)
    result = AssistResult(
        output=ExtractionOutput(summary="Gemini answered."),
        capability=AssistCapability(available=True, provider=GOOGLE_PROVIDER),
        usage=TokenUsage(prompt_tokens=100, output_tokens=40),
    )

    metering = await assist.meter_assist(
        None,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        ref="assist-gemini-metered",
        result=result,
        model="gemini-2.5-flash",
    )

    assert metering.metered is True
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["model"] != get_settings().azure_openai_model
    assert captured["tokens_in"] == 100 and captured["tokens_out"] == 40
