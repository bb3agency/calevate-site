"""Accounts whose setup is finished leave `onboarding` even when nothing else moves them (D-710).

`tenancy/onboarding.complete_onboarding_if_finished` runs when a business profile save or an
accepted invitation finishes setup. An account that was ALREADY finished when D-710 shipped,
or one finished by a path that does neither, would otherwise read "Onboarding" until its
next profile save. This sweep asks the same question of every account still in
`onboarding`, so "by itself" holds for those too, without a backfill migration or an
operator's click.

The move is the same CAS the save path uses, so it never touches an account an operator
set, a suspended one or a closed one, and is audited the same way.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.core.logging import get_logger
from apps.api.db.session import admin_session, tenant_session
from apps.api.tenancy.onboarding import complete_onboarding_if_finished
from apps.workers.set_aside import set_aside, set_aside_ids

log = get_logger(__name__)

#: Accounts asked per tick, newest first: a recently created account is the one most likely
#: to have just been finished.
SWEEP_BUDGET: Final = 200

#: How long an account asked and not moved (unfinished, or the ask failed) is left out of
#: the read (`workers/set_aside.py`). Nothing moves an abandoned signup out of `onboarding`,
#: so without it the newest `SWEEP_BUDGET` of those would fill every read and an older
#: account finished by another path would never be asked. A day covers
#: 24 x `SWEEP_BUDGET` accounts per pass.
SET_ASIDE_FOR: Final = timedelta(hours=24)
_SET_ASIDE_SWEEP: Final = "onboarding_completion"

#: The hourly tick's minute and second.
SWEEP_MINUTE: Final = 41
SWEEP_SECOND: Final = 20

_ONBOARDING: Final = (
    "SELECT id FROM organizations WHERE deleted_at IS NULL AND status = 'onboarding' "
    "AND NOT (id = ANY(CAST(:set_aside AS uuid[]))) "
    "ORDER BY created_at DESC, id LIMIT :limit"
)


async def complete_finished_onboardings(ctx: dict[str, Any]) -> str:
    """Hourly. Move every finished account still marked `onboarding` to `active`."""
    del ctx
    excluded = await set_aside_ids(_SET_ASIDE_SWEEP)
    async with admin_session() as directory:
        rows = (
            await directory.execute(
                text(_ONBOARDING), {"limit": SWEEP_BUDGET, "set_aside": excluded}
            )
        ).all()
    moved = failed = 0
    unmoved: list[str] = []
    for row in rows:
        tenant_id = UUID(str(row[0]))
        try:
            async with tenant_session(tenant_id) as scoped:
                if await complete_onboarding_if_finished(scoped, tenant_id=tenant_id):
                    moved += 1
                    continue
        except Exception as exc:
            # One account's failure must not stop the others.
            failed += 1
            log.warning(
                "onboarding_completion_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
        unmoved.append(str(tenant_id))
    await set_aside(_SET_ASIDE_SWEEP, unmoved, for_=SET_ASIDE_FOR)
    return f"onboarding={len(rows)} moved={moved} failed={failed}"


__all__ = ["SWEEP_MINUTE", "SWEEP_SECOND", "complete_finished_onboardings"]
