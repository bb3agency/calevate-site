"""A signed-in person's own mobile number: `users.phone` (D-976).

Until D-976 only an invitation wrote this column, so an owner who signed up had no number
and nothing could add one: WhatsApp hot-lead alerts (`compliance/whatsapp_optin_routes.
_phone_of`) and automatic top-ups (`billing/auto_recharge._payer_contact`) refused with
"add a mobile number" and no screen offered the field.

**NO CODE IS SENT, BY THE FOUNDER'S DECISION** (9 Nov 2026: "Initially no code but later
once we setup whatsapp then via whatsapp"). The number is stored as typed, normalised to
E.164. What keeps that honest is `users.phone_verified_at`: it is never set here, and every
write that changes the number clears it, so the WhatsApp code step can be added later by
setting it, without any number stored before that step reading as confirmed. Nothing reads
it yet. The screen guards against a typo instead, by showing the number back before saving.

Changing the number does not move a WhatsApp alert opt-in onto the new number: that ledger
is keyed on (person, number) (`whatsapp_optin.read_alert_optin`), so the owner agrees again
for the new one.

Client realm only. The admin realm has no `phone` and an operator acting as a client has
no `users` row, so the route that calls this is mounted on `/v1/auth/client` and reads
only the client session cookie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text

from apps.api.compliance.audit import write_audit
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import untenanted_session
from apps.api.ingest.service import normalize_phone

log = get_logger(__name__)

AUDIT_ACTION: Final = "auth.mobile_number_changed"

#: What happened to the number, the only fact the audit row and the log line carry
#: (hard rule 6: never the number itself).
Change = Literal["added", "changed", "removed", "unchanged"]

# The previous number is read and the new one written in ONE statement, under the row
# lock the UPDATE takes, so two tabs saving at once cannot both report "added".
# `phone_verified_at` survives only an unchanged number.
_SET_OWN: Final = text(
    "WITH before AS (SELECT phone FROM users WHERE id = :uid FOR UPDATE) "
    "UPDATE users SET phone = :phone, "
    "phone_verified_at = CASE WHEN users.phone IS NOT DISTINCT FROM :phone "
    "THEN users.phone_verified_at ELSE NULL END, "
    "updated_at = CASE WHEN users.phone IS NOT DISTINCT FROM :phone "
    "THEN users.updated_at ELSE now() END "
    "FROM before WHERE users.id = :uid RETURNING before.phone"
)


@dataclass(frozen=True, slots=True)
class OwnMobileChange:
    change: Change


def invalid_number() -> ProblemError:
    return ProblemError(
        kind="validation",
        code="mobile_number_invalid",
        title="Check your mobile number",
        detail="Enter a 10-digit mobile number, or the full number starting with +.",
        fields=[{"field": "phone", "rule": "format", "message": "Not a mobile number."}],
    )


def normalised(raw: str | None) -> str | None:
    """E.164 from what the person typed, or None for "remove it".

    `ingest.normalize_phone` is the repo's one door from a typed number to E.164: a bare
    ten-digit Indian mobile (or `0` + ten) gains +91, a number with `+` keeps its country,
    and anything else is refused rather than guessed at.
    """
    if raw is None or not raw.strip():
        return None
    phone = normalize_phone(raw)
    if phone is None:
        raise invalid_number()
    return phone


def _change(before: str | None, after: str | None) -> Change:
    if before == after:
        return "unchanged"
    if after is None:
        return "removed"
    return "added" if before is None else "changed"


async def set_own(*, user_id: UUID, raw: str | None, ip: str | None) -> OwnMobileChange:
    """Set, change or clear the caller's own number. Audits a change, not a repeat."""
    phone = normalised(raw)
    async with untenanted_session() as session:
        row = (await session.execute(_SET_OWN, {"uid": user_id, "phone": phone})).first()
        if row is None:
            # The session was verified a moment ago, so the row exists unless it was
            # removed in between; the session refusal is the honest answer to that.
            raise ProblemError.unauthorized("Your session is not valid. Sign in again.")
        change = _change(row[0], phone)
        if change != "unchanged":
            await write_audit(
                session,
                action=AUDIT_ACTION,
                actor=Principal(realm="client", user_id=user_id, tenant_id=None, role=None),
                object_type="auth_subject",
                object_id=str(user_id),
                ip=ip,
                summary={"change": change, "by": "self"},
            )
    log.info("own_mobile_number_set", extra={"user_id": str(user_id), "change": change})
    return OwnMobileChange(change=change)


__all__ = ["AUDIT_ACTION", "OwnMobileChange", "invalid_number", "normalised", "set_own"]
