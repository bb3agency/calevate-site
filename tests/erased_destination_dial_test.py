"""The placeholder an erasure writes over a number never reaches a dial.

Every store of a dialable number is anonymised in place rather than deleted, to
`retention.ANONYMIZED_PHONE[:9]` plus a slice of the row id. That value starts `+91`, so
the India-only freeze admits it, and nothing else in the dial gate knew what it was. The
retention sweep blanked the number of a contact whose call was still ringing and left it
`dialing`; the ladder returned it to `pending` when the call went unanswered, and the next
tick handed the placeholder to the engine as a phone number.
"""

from __future__ import annotations

import pytest
from apps.api.compliance.caller_ref import ANONYMIZED_PREFIX
from apps.api.compliance.service import DESTINATION_ERASED_RULE, PERSON_LEVEL_REFUSALS
from apps.api.db.session import tenant_session
from apps.workers import campaign_dispatch
from apps.workers.retention import ANONYMIZED_PHONE, sweep_tenant
from sqlalchemy import text
from tests.campaign_dispatch_audit_test import (  # noqa: F401 - autouse fixtures
    _daytime,
    _launched,
    _roomy_platform_pool,
    _settle_what_this_module_started,
    _tick_one_campaign,
)
from tests.outbound_consent_policy_test import _fresh_phone, _gate
from tests.outbound_consent_policy_test import _tenant as _consent_tenant

pytestmark = pytest.mark.asyncio


async def test_a_contact_whose_retention_ran_out_mid_call_is_never_dialled_again() -> None:
    """The retention sweep's side of the same gap. `_CAMPAIGN_CONTACT_EXPIRE_SQL` blanks
    the number of every contact past the lead period but settles only a `pending` one, so
    a contact whose call was ringing at that moment kept `dialing` with a placeholder for
    a number. When the call ended unanswered the ladder put it back to `pending`, and the
    next tick handed `+91000000<hex>` to the dial gate and the engine as a phone number."""
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876670001",))
    await _tick_one_campaign(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text(
                    "UPDATE campaign_contacts SET created_at = now() - interval '1100 days' "
                    "WHERE campaign_id = :c RETURNING last_call_id"
                ),
                {"c": campaign_id},
            )
        ).scalar_one()

    await sweep_tenant(tenant_id)
    async with tenant_session(tenant_id) as session:
        await campaign_dispatch.resolve_campaign_contact(
            session, tenant_id=tenant_id, call_id=call_id, call_status="no_answer"
        )
        await session.execute(
            text("UPDATE campaign_contacts SET next_attempt_at = now() WHERE campaign_id = :c"),
            {"c": campaign_id},
        )
    await sweep_tenant(tenant_id)
    await _tick_one_campaign(tenant_id, campaign_id)

    async with tenant_session(tenant_id) as session:
        dialled = (
            (
                await session.execute(
                    text(
                        "SELECT to_e164 FROM calls WHERE direction = 'outbound' ORDER BY created_at"
                    )
                )
            )
            .scalars()
            .all()
        )
        phone, status = (
            await session.execute(
                text("SELECT phone_e164, status FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).one()
    assert all(not str(to).startswith(ANONYMIZED_PHONE[:9]) for to in dialled), dialled
    assert len(dialled) == 1
    assert str(phone).startswith(ANONYMIZED_PHONE[:9]), "and the period is still honoured"
    assert status == "dnc_blocked"


async def test_the_gate_refuses_the_erasure_placeholder_as_a_destination() -> None:
    """Whatever path reads a destination off an anonymised row, the gate is the one place
    every dial passes, and the placeholder starts `+91`, so the India freeze admits it."""
    tenant_id, agent_id = await _consent_tenant("erased-dest")
    decision = await _gate(tenant_id, agent_id, f"{ANONYMIZED_PREFIX}754bf537bcc7")
    assert decision.allowed is False
    assert decision.rule == DESTINATION_ERASED_RULE
    assert DESTINATION_ERASED_RULE in PERSON_LEVEL_REFUSALS, (
        "a placeholder never becomes a number again, so waiting must not be offered"
    )
    assert (await _gate(tenant_id, agent_id, _fresh_phone())).allowed is True


def test_the_gate_matches_the_placeholder_retention_writes() -> None:
    assert ANONYMIZED_PHONE.startswith(ANONYMIZED_PREFIX)
    assert ANONYMIZED_PHONE[:9] == ANONYMIZED_PREFIX, "the slice every erase statement writes"
