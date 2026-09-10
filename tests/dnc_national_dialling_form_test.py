"""A number written the way Indians write it — `0` + ten digits — is suppressible (D-562).

THE DEFECT. `ingest.normalize_phone` accepted a bare ten-digit mobile, `91` + ten, and an
explicit `+`. It did not accept `09876543210`: eleven digits behind India's `0` trunk
prefix, the standard national-dialling form, printed on business cards and typed into web
forms every day. It returned None, and None is not harmless on this path —
`compliance/dnc.add_numbers` counts an unreadable number as `malformed` and does NOT
suppress it. So a client pasted their customer's number into the do-not-call page to stop
us ringing them, read "1 malformed", and the number stayed dialable. Hard rule 5 says a
DNC addition takes effect before the next dispatch tick; for this spelling nothing took
effect at all.

WHAT IS DELIBERATELY NOT WIDENED. Everything else. `normalize_phone` returning None rather
than guessing a country is the correct default and the tests below pin it: a foreign
national number, a short number, a number with a `0` in front of a non-mobile shape. The
one country-specific arm rests on the premise the ten-digit arm already rested on, and
that premise is explicit product scope rather than an assumption — `compliance/service.py`
refuses every non-`+91` destination at the dial gate (`INDIA_E164_PREFIX`,
LEGAL-OPS-PLAYBOOK §14/§18).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import dnc
from apps.api.compliance.service import check_dispatch
from apps.api.db.session import tenant_session
from apps.api.ingest.service import normalize_phone
from sqlalchemy import text
from tests.conftest import accept_agreements, arm_agent_for_outbound, fund_wallet


def _national_form() -> str:
    """A fresh Indian mobile as a person writes it: the `0` trunk prefix and ten digits
    starting 6-9. Fresh per call because `dnc_list` outlives a test (a global row has no
    tenant), so a constant would couple these tests to each other."""
    return "09" + f"{uuid.uuid4().int % 10**9:09d}"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the gate's clock to 11:00 IST — `dnc_test._daytime`'s reason: a suppression
    test that passes at 22:00 because of `calling_hours` proves nothing."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _dialable_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant that lawfully CAN dial, so a refusal below is the suppression and not the
    paperwork. Exactly `dnc_test._tenant`'s arming and for its stated reasons."""
    created = await admin_service.create_organization(
        name="Trunk Prefix Motors",
        slug=f"tp-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    await accept_agreements(uuid.UUID(str(tenant_id)))
    await fund_wallet(uuid.UUID(str(tenant_id)))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
    await arm_agent_for_outbound(tenant_id, agent_id)
    return tenant_id, agent_id


# --- 1. the normaliser --------------------------------------------------------


def test_the_national_dialling_form_is_the_same_number_as_the_bare_ten_digits() -> None:
    """The trunk prefix is how you reach the number from inside India; it is not part of
    the number, and E.164 has no room for it. Three spellings of one person."""
    assert normalize_phone("09876543210") == "+919876543210"
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("+91 98765 43210") == "+919876543210"
    assert normalize_phone("919876543210") == "+919876543210"
    # As people actually type it.
    assert normalize_phone("0 98765 43210") == "+919876543210"


def test_nothing_else_loosened_and_a_country_is_still_never_guessed() -> None:
    """The widening is ONE arm. Refusing rather than guessing is the promise that makes
    the return type dialable, and it is unchanged in every other direction."""
    # A `0` in front of a shape that is not an Indian mobile is still unreadable: the
    # second digit carries the whole claim, and 6-9 is what an Indian mobile starts with.
    assert normalize_phone("05876543210") is None
    assert normalize_phone("00876543210") is None
    # Wrong length behind the prefix — nine digits, or eleven.
    assert normalize_phone("0987654321") is None
    assert normalize_phone("098765432101") is None
    # And the refusals that were already there.
    assert normalize_phone("12345") is None, "too short to dial, too risky to guess"
    assert normalize_phone("5551234567") is None, "not an Indian mobile shape; no guessing"
    assert normalize_phone("++919876543210") is None
    assert normalize_phone("+91+9876543210") is None


# --- 2. the consequence that made it worth fixing -----------------------------


async def test_a_number_pasted_in_national_form_is_suppressed_and_not_counted_malformed() -> None:
    """THE FINDING. `malformed` meant "we did nothing with this", and the screen said so
    while the number stayed dialable."""
    tenant_id, agent_id = await _dialable_tenant()
    national = _national_form()
    e164 = "+91" + national[1:]

    async with tenant_session(tenant_id) as session:
        before = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=e164
        )
    assert before.allowed is True, f"the fixture cannot dial for another reason: {before.rule}"

    async with tenant_session(tenant_id) as session:
        result = await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[national], source="manual"
        )
    assert result.malformed == 0, "the client's own spelling of their customer's number"
    assert result.added == 1

    async with tenant_session(tenant_id) as session:
        after = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=e164
        )
    assert after.allowed is False
    assert after.rule == "dnc"


async def test_the_two_spellings_are_one_entry_and_not_two() -> None:
    """A suppression keyed on a spelling is a suppression that misses. The second paste is
    `already_suppressed`, which is also what the client is told."""
    tenant_id, _ = await _dialable_tenant()
    national = _national_form()
    bare = national[1:]

    async with tenant_session(tenant_id) as session:
        first = await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[national], source="manual"
        )
        second = await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[bare], source="manual"
        )
    assert (first.added, first.malformed) == (1, 0)
    assert (second.added, second.already_suppressed, second.malformed) == (0, 1, 0)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = :p"),
                {"p": "+91" + bare},
            )
        ).scalar_one()
    assert rows == 1
