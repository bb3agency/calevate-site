"""The business profile's own words for each business.

What is under test:

1. **The rule.** A draft is the business's labels, hints and examples; a part that breaks a
   rule of text a client reads falls back to the neutral part, and an empty price label
   means no price applies.
2. **The read.** Before a draft, every business reads the neutral wording: generic labels
   and no example at all. After one, it reads its own.
3. **The writing.** Queued when the description changes and when a read finds no draft for
   the current one; stored only for the description it was written from; a refusal stores
   nothing.
4. **Tenancy (hard rule 1).** One business's wording never reaches another's profile.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import starter_plans
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.main import app
from apps.api.tenancy import profile_wording
from apps.api.tenancy.profile_wording import NEUTRAL, clean_wording
from apps.workers import profile_wording as worker
from apps.workers.extraction import AssistCapability
from apps.workers.script_assist import JsonAnswer
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_starters_test import _tenant


def _raw(**over: Any) -> dict[str, Any]:
    """An answer for a farmers' bookkeeping app."""
    raw: dict[str, Any] = {
        "offer_label": "Plan",
        "price_label": "Monthly fee",
        "offers_hint": "The plans farmers can sign up for.",
        "booking_title": "How do farmers sign up?",
        "booking_hint": "What a farmer needs before signing up.",
        "examples": {
            "branch_label": "",
            "offer_name": "Crop records plan",
            "offer_price": "99",
            "offer_note": "First month free",
            "faq_question": "Does it work without internet?",
            "staff_name": "Ravi Kumar",
            "staff_spoken": "RAA-vi KOO-mar",
            "staff_role": "Support lead",
            "booking_rules": "Sign up with a mobile number. Never promise a loan.",
            "contact_name": "Support desk",
        },
    }
    raw.update(over)
    return raw


# --- 1. the rule ----------------------------------------------------------------------------


def test_a_draft_is_the_businesss_own_words() -> None:
    wording = clean_wording(_raw(), clinic=False)
    assert wording is not None and wording.drafted
    assert (wording.offer_label, wording.price_label) == ("Plan", "Monthly fee")
    assert wording.booking_title == "How do farmers sign up?"
    assert wording.examples.offer_name == "Crop records plan"
    assert wording.examples.offer_price == "99"
    # An empty example is no example.
    assert wording.examples.branch_label is None


def test_no_price_label_means_no_price_and_no_price_example() -> None:
    wording = clean_wording(_raw(price_label=""), clinic=False)
    assert wording is not None
    assert wording.price_label is None and wording.examples.offer_price is None


def test_a_part_that_breaks_a_rule_falls_back_to_the_neutral_part() -> None:
    raw = _raw(offers_hint="Plans priced by Gemini.", booking_title="**Sign up**")
    raw["examples"]["contact_name"] = "Doctor's desk"
    raw["examples"]["offer_price"] = "₹99"
    raw["offer_label"] = "x" * (profile_wording.LABEL_MAX + 1)
    wording = clean_wording(raw, clinic=False)
    assert wording is not None
    assert wording.offers_hint == NEUTRAL.offers_hint
    assert wording.booking_title == NEUTRAL.booking_title
    assert wording.offer_label == NEUTRAL.offer_label
    assert wording.examples.contact_name is None
    assert wording.examples.offer_price is None
    # Medical words are a clinic's own.
    clinic = _raw()
    clinic["examples"]["contact_name"] = "Doctor's desk"
    drafted = clean_wording(clinic, clinic=True)
    assert drafted is not None and drafted.examples.contact_name == "Doctor's desk"


def test_an_answer_of_another_shape_is_no_draft() -> None:
    assert clean_wording([], clinic=False) is None
    assert clean_wording(_raw(examples=None), clinic=False) is None


# --- 2-4. the read, the writing, tenancy -----------------------------------------------------


async def _profile(token: str) -> dict[str, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.get(
            "/v1/business-profile", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _describe(tenant_id: uuid.UUID, services: str) -> str:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_profiles (id, tenant_id, services) VALUES "
                "(:id, :tid, CAST(:services AS jsonb)) "
                "ON CONFLICT (tenant_id) DO UPDATE SET services = EXCLUDED.services"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "services": services},
        )
        known = await starter_plans.business_known(session, tenant_id=tenant_id)
    assert known is not None
    return known


async def _queued(tenant_id: uuid.UUID, known: str) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'tenant_id' = :tid AND payload->>'known' = :known"
                    ),
                    {"job": profile_wording.WRITE_JOB, "tid": str(tenant_id), "known": known},
                )
            ).scalar_one()
        )


def _answer(raw: dict[str, Any]) -> Any:
    async def answered(*_args: Any, parse: Any, **_kwargs: Any) -> JsonAnswer[Any]:
        return JsonAnswer(
            value=parse(raw),
            capability=AssistCapability(available=True, provider="gemini"),
            model="gemini-2.5-flash-lite",
        )

    return answered


@pytest.mark.rls
async def test_a_business_with_no_draft_reads_neutral_words_and_no_example() -> None:
    _tenant_id, token = await _tenant("clinic", "Rytu Khata")
    wording = (await _profile(token))["wording"]
    assert wording["drafted"] is False
    assert wording["offer_label"] == NEUTRAL.offer_label
    assert wording["price_label"] == NEUTRAL.price_label
    assert all(value is None for value in wording["examples"].values())


@pytest.mark.rls
async def test_a_business_reads_its_own_words_once_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    known = await _describe(tenant_id, '[{"name": "Crop records"}]')
    # The read finds no draft for this description and queues one, once.
    await _profile(token)
    await _profile(token)
    assert await _queued(tenant_id, known) == 1

    monkeypatch.setattr(worker, "ask_json", _answer(_raw(price_label="")))
    payload = {"tenant_id": str(tenant_id), "known": known}
    assert await worker.write_profile_wording({}, payload) == "written"
    wording = (await _profile(token))["wording"]
    assert wording["drafted"] is True
    assert wording["offer_label"] == "Plan" and wording["price_label"] is None
    assert wording["examples"]["offer_name"] == "Crop records plan"
    # The draft is current: reading it queues nothing more.
    assert await _queued(tenant_id, known) == 1


@pytest.mark.rls
async def test_an_answer_about_an_older_description_is_not_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, token = await _tenant("custom", "Rytu Khata")
    older = await _describe(tenant_id, '[{"name": "Crop records"}]')
    await _describe(tenant_id, '[{"name": "Crop records"}, {"name": "Soil tests"}]')
    monkeypatch.setattr(worker, "ask_json", _answer(_raw()))
    payload = {"tenant_id": str(tenant_id), "known": older}
    assert await worker.write_profile_wording({}, payload) == "superseded"
    assert (await _profile(token))["wording"]["drafted"] is False


@pytest.mark.rls
async def test_a_refusal_stores_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, token = await _tenant("custom", "Beta Traders")
    known = await _describe(tenant_id, '[{"name": "Rice"}]')

    async def refused(*_args: Any, **_kwargs: Any) -> Any:
        raise ProblemError.business_rule("assist_answer_unusable", "Nothing usable came back.")

    monkeypatch.setattr(worker, "ask_json", refused)
    payload = {"tenant_id": str(tenant_id), "known": known}
    assert await worker.write_profile_wording({}, payload) == "refused"
    assert (await _profile(token))["wording"]["drafted"] is False


@pytest.mark.rls
async def test_one_business_never_reads_anothers_words(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_a, _ = await _tenant("custom", "Rytu Khata")
    _, token_b = await _tenant("custom", "Beta Traders")
    known = await _describe(tenant_a, '[{"name": "Crop records"}]')
    monkeypatch.setattr(worker, "ask_json", _answer(_raw()))
    assert await worker.write_profile_wording({}, {"tenant_id": str(tenant_a), "known": known})
    wording = (await _profile(token_b))["wording"]
    assert wording["drafted"] is False and wording["offer_label"] == NEUTRAL.offer_label
