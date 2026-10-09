"""The campaign list's provenance flag.

The list screen could see `status` and nothing about consent, so it either warned about
every draft or ran the whole launch gate once per row. The tests pin the fix at its
weakest point: the answer must come out of the list query, with `launch_blockers`
sabotaged so a hidden call to it cannot pass.

Moved here from `intake_test.py` when the admin intake step was retired (D-695).

Concurrency: every case creates its own run-unique tenant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service as campaigns_service
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from sqlalchemy import text
from tests.conftest import accept_agreements


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Sunrise Dental",
        slug=f"prov-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    await accept_agreements(uuid.UUID(str(created["id"])))
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _draft(
    session: Any, *, tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, source: str | None
) -> uuid.UUID:
    return await campaigns_service.create_campaign(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        name=name,
        classification="service",
        number_id=None,
        dlt_template_id=None,
        concurrency=1,
        consent_source=source,
        consent_collected_at=(
            datetime.now(UTC) - timedelta(days=10) if source is not None else None
        ),
    )


async def test_the_list_says_which_drafts_need_provenance_without_running_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gap the campaigns screen recorded in its own source: the summary carried
    `status` and nothing about consent, so the list either warned about every draft or
    ran the full launch gate once per row.

    `launch_blockers` is sabotaged for the duration: if the answer needs the gate, this
    test fails rather than quietly costing one round trip per campaign.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        unanswered = await _draft(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Unanswered", source=None
        )
        answered = await _draft(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Answered",
            source="web_form_optin",
        )
        purchased = await _draft(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Purchased",
            source="purchased_list",
        )

        def _no_gate(*args: object, **kwargs: object) -> None:
            raise AssertionError("the list must answer from its own query, not the gate")

        monkeypatch.setattr(campaigns_service, "launch_blockers", _no_gate)
        rows = {r["name"]: r for r in await campaigns_service.list_campaigns(session)}

    assert rows["Unanswered"]["consent_provenance_blocker"] == "consent_provenance_missing"
    assert rows["Answered"]["consent_provenance_blocker"] is None
    assert rows["Purchased"]["consent_provenance_blocker"] == "consent_source_refused"
    assert {unanswered, answered, purchased} == {r["id"] for r in rows.values()}


async def test_the_flag_carries_the_gate_s_own_rule_names() -> None:
    """The value is the blocker's `rule`, not a private vocabulary: the list links to
    the same explanation the launch check renders, and a third name for the same fact
    is how the two screens start disagreeing."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _draft(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Unanswered", source=None
        )
        await _draft(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Purchased",
            source="purchased_list",
        )
        rows = {r["name"]: r for r in await campaigns_service.list_campaigns(session)}
        gate = {
            name: [
                b.rule
                for b in await campaigns_service.launch_blockers(
                    session, tenant_id=tenant_id, campaign_id=row["id"]
                )
            ]
            for name, row in rows.items()
        }

    for name, row in rows.items():
        assert row["consent_provenance_blocker"] in gate[name], name


async def test_a_campaign_past_the_gate_is_not_flagged_for_something_it_cannot_fix() -> None:
    """Provenance is answerable while a campaign is a draft and never afterwards
    (`declare_consent_provenance`). Flagging a running campaign that predates the
    columns would put a to-do on the list with no way to do it."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _draft(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Already out", source=None
        )
        # Straight to `running` on purpose: this is the pre-migration campaign the
        # column was added underneath, not a campaign that passed today's gate.
        await session.execute(
            text("UPDATE campaigns SET status = 'running', launched_at = now() WHERE id = :cid"),
            {"cid": campaign_id},
        )
        rows = await campaigns_service.list_campaigns(session)

    assert rows[0]["status"] == "running"
    assert rows[0]["consent_provenance_blocker"] is None
