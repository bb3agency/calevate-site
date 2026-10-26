"""A click-to-dial reads the big red switch fresh (hard rule 5).

The halt is written in the API process that served the operator, which refreshes ITS
memo and the Redis copy and leaves every other process's `loadshed._memo` saying
"running" for up to five seconds. A dial placed in that gap is never recalled:
`dial_recall` scans once, on the halt's edge. So every manual and instant dial path, all
of which go through `check_dispatch`, reads the switch past the memo; only the dispatch
ticks, which read it fresh themselves just before, keep the memo
(`halt_read_by_caller=True`).
"""

from __future__ import annotations

import time
import uuid

from apps.api.compliance.service import BIG_RED_SWITCH_RULE, check_dispatch
from apps.api.core import loadshed
from apps.api.core.loadshed import set_platform_status
from apps.api.db.session import tenant_session
from tests.conftest import create_org_with_receptionist


def _this_process_has_not_noticed() -> None:
    loadshed._memo = (
        time.monotonic(),
        loadshed.PlatformStatus(mode="normal", outbound_halted=False),
    )


async def test_a_halt_from_another_process_stops_the_very_next_click_dial() -> None:
    created = await create_org_with_receptionist(
        name="Halt Click Traders",
        slug=f"halt-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    await set_platform_status(outbound_halted=True, halt_reason="click test", actor_id=None)
    try:
        _this_process_has_not_noticed()
        async with tenant_session(tenant_id) as session:
            clicked = await check_dispatch(
                session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876543210"
            )
        assert clicked.rule == BIG_RED_SWITCH_RULE, "a click-dial answered from the stale memo"

        # A tick that read the switch itself keeps the memo, by its own choice.
        _this_process_has_not_noticed()
        async with tenant_session(tenant_id) as session:
            ticked = await check_dispatch(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                phone_e164="+919876543210",
                halt_read_by_caller=True,
            )
        assert ticked.rule != BIG_RED_SWITCH_RULE
    finally:
        await set_platform_status(outbound_halted=False, actor_id=None)
