"""An operator's correction of the AI's capability profile for one client (audit A7-08).

The copy run judges what a business does with its callers (`tenancy/business_copy.
Capabilities`) and every screen and plan that adapts to the business reads that verdict.
When the AI judges wrongly ("Main crops grown" suggested to a free support app), an operator
sets the capability here.

WHERE THE DECISION LIVES. `business_copies.capability_overrides` holds
`{"set": {capability: bool}, "ai": {capability: verdict}}`. The decided value is ALSO
written into `generated.capabilities`, so every reader (`capabilities_for`, `parse_stored`,
the business-fit check) keeps reading one place rather than learning a second. The AI
verdict it replaced is kept under `ai`, so clearing the override restores it. The copy run
re-applies `set` after each regeneration (`apply_overrides`), so a refresh never reverts an
operator's correction.
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.base import uuid7
from apps.api.tenancy.business_copy import CAPABILITY_KEYS

#: The reason stored with an operator's verdict. Plain: an owner may read it.
OVERRIDE_REASON: Final = "Set by Calevate."


def overrides_of(raw: Any) -> dict[str, bool]:
    """The operator's decisions, from the stored column (anything malformed reads as none)."""
    if not isinstance(raw, dict):
        return {}
    decided = raw.get("set")
    if not isinstance(decided, dict):
        return {}
    return {k: v for k, v in decided.items() if k in CAPABILITY_KEYS and isinstance(v, bool)}


def apply_overrides(generated: dict[str, Any], raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """`generated` with the operator's decisions written over the AI's verdicts, and the
    column with the AI's fresh verdicts recorded under `ai`. Used by the copy run after each
    regeneration and by `set_override`."""
    decided = overrides_of(raw)
    stored: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    ai: dict[str, Any] = dict(stored.get("ai") or {})
    capabilities = generated.get("capabilities")
    if decided and isinstance(capabilities, dict):
        capabilities = dict(capabilities)
        for key, applies in decided.items():
            current = capabilities.get(key)
            if isinstance(current, dict) and current.get("reason") != OVERRIDE_REASON:
                ai[key] = current
            capabilities[key] = {"reason": OVERRIDE_REASON, "applies": applies}
        generated = {**generated, "capabilities": capabilities}
    return generated, {"set": decided, "ai": ai}


async def set_override(
    session: AsyncSession, *, tenant_id: UUID, capability: str, applies: bool | None
) -> dict[str, bool]:
    """Set (True/False) or clear (None) one capability for this tenant, in its own RLS
    session. Answers the decisions now in force. The caller audits."""
    if capability not in CAPABILITY_KEYS:
        raise ValueError(capability)
    await session.execute(
        text(
            "INSERT INTO business_copies (id, tenant_id) VALUES (:id, :tid) "
            "ON CONFLICT (tenant_id) DO NOTHING"
        ),
        {"id": uuid7(), "tid": tenant_id},
    )
    row = (
        await session.execute(
            text(
                "SELECT generated, capability_overrides FROM business_copies "
                "WHERE tenant_id = :tid FOR UPDATE"
            ),
            {"tid": tenant_id},
        )
    ).one()
    generated: dict[str, Any] | None = row[0]
    stored: dict[str, Any] = dict(row[1] or {})
    decided = overrides_of(stored)
    ai: dict[str, Any] = dict(stored.get("ai") or {})
    if applies is None:
        decided.pop(capability, None)
        restored = ai.pop(capability, None)
        if generated is not None and isinstance(generated.get("capabilities"), dict):
            capabilities = dict(generated["capabilities"])
            if restored is not None:
                capabilities[capability] = restored
            generated = {**generated, "capabilities": capabilities}
        stored = {"set": decided, "ai": ai}
    else:
        decided[capability] = applies
        stored = {"set": decided, "ai": ai}
        if generated is not None:
            generated, stored = apply_overrides(generated, stored)
    await session.execute(
        text(
            "UPDATE business_copies SET capability_overrides = CAST(:stored AS jsonb), "
            "generated = CAST(:generated AS jsonb), updated_at = now() WHERE tenant_id = :tid"
        ),
        {
            "stored": json.dumps(stored),
            "generated": None if generated is None else json.dumps(generated),
            "tid": tenant_id,
        },
    )
    return decided


__all__ = ["OVERRIDE_REASON", "apply_overrides", "overrides_of", "set_override"]
