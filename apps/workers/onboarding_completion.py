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

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.core.logging import get_logger
from apps.api.db.session import admin_session, tenant_session
from apps.api.tenancy.onboarding import complete_onboarding_if_finished

log = get_logger(__name__)

#: Accounts asked per tick, newest first: a recently created account is the one most likely
#: to have just been finished. Far more than the accounts ever in onboarding at once.
SWEEP_BUDGET: Final = 200

#: The hourly tick's minute and second.
SWEEP_MINUTE: Final = 41
SWEEP_SECOND: Final = 20

_ONBOARDING: Final = (
    "SELECT id FROM organizations WHERE deleted_at IS NULL AND status = 'onboarding' "
    "ORDER BY created_at DESC, id LIMIT :limit"
)


async def complete_finished_onboardings(ctx: dict[str, Any]) -> str:
    """Hourly. Move every finished account still marked `onboarding` to `active`."""
    del ctx
    async with admin_session() as directory:
        rows = (await directory.execute(text(_ONBOARDING), {"limit": SWEEP_BUDGET})).all()
    moved = failed = 0
    for row in rows:
        tenant_id = UUID(str(row[0]))
        try:
            async with tenant_session(tenant_id) as scoped:
                if await complete_onboarding_if_finished(scoped, tenant_id=tenant_id):
                    moved += 1
        except Exception as exc:
            # One account's failure must not stop the others; it is asked again next hour.
            failed += 1
            log.warning(
                "onboarding_completion_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )
    return f"onboarding={len(rows)} moved={moved} failed={failed}"


__all__ = ["SWEEP_MINUTE", "SWEEP_SECOND", "complete_finished_onboardings"]
