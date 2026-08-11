"""Client-realm read of this tenant's own DLT Principal Entity registration (SEC-COMP §3).

The view that explains a disabled launch button. `campaigns.service.launch_blockers` emits
`pe_registration_missing`, `pe_registration_not_active` and `tm_link_not_active`; until this
route existed, a client who saw one of them had nowhere to look up what the registrar
actually holds for their business, when it was filed, or when we last checked it. The write
stays admin-only for the reason `campaigns.service.record_dlt_registration` documents — a
client who could mark their own PE `active` would be marking the gate green on a
registration that does not exist — but that argument is about WRITING, and it was quietly
extended to reading.

Three shapes worth explaining before someone "tidies" them:

- **`org:read`, not `org:manage`.** Looking at your own compliance state is not changing
  it. `org:manage` is in `MUTATING_PERMISSIONS`, so D-22 would make this invisible to a
  support person inside a read-only "view as client" session — exactly the person looking
  at the screen when the launch button is disabled, and exactly the recurring bug
  `tests/impersonation_reads_test.py` exists to stop. `org:read` is held by `staff`,
  `owner` and `operator`, and by nothing that mutates.
- **A missing registration is a 200, not a 404.** It is the normal state of every new
  account. The console renders "not filed yet" from `recorded: false`; a 404 arrives at
  the fetch layer indistinguishable from a moved route or a lost permission, and the
  generated TS client would make every caller special-case it before it could show the
  one thing the page exists to show.
- **No audit row.** Unlike the subject-access export, this discloses no personal data —
  a business's own registration state, to that business — and it is the page a blocked
  client will refresh. An audit chain that grows a row per poll stops being readable.

Hard rule 1: the session is `deps.db`, so the row is scoped by RLS rather than by a
predicate anyone could forget. `tests/pe_registration_read_test.py` proves tenant B sees
zero rows both through this route and on the raw session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.registration import PeRegistration, read_pe_registration
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/dlt-registration", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is only waived for
# `**/routes.py`, and this module is `registration_routes.py` — same situation, and same
# resolution, as `dnc_routes.py`, `export_routes.py` and `deletion_routes.py`.
RegistrationReader = Annotated[Principal, Depends(requires("org:read"))]


class PeRegistrationOut(BaseModel):
    """This tenant's Principal Entity registration, as the platform last verified it.

    Every field except `recorded` and `is_active` is nullable, because all of them are
    genuinely absent before ops files anything. `is_active` is computed server-side for
    the same reason `TmRegistrationOut.is_live` is: "is `submitted` good enough" is a
    question the console must not answer for itself, and this response and the launch
    gate must never disagree about it.
    """

    model_config = ConfigDict(extra="forbid")

    recorded: bool
    status: str | None
    # The PE→TM authorisation — the client naming Calevate as permitted to dial for them.
    # Reported separately because it fails separately and sends the client to a different
    # desk than their own entity registration does.
    tm_link_status: str | None
    pe_id: str | None
    entity_name: str | None
    registered_at: datetime | None
    # When WE last checked it against the registrar, not when we last hoped: every write
    # in `record_dlt_registration` stamps `verified_at = now()`.
    verified_at: datetime | None
    is_active: bool


def _out(registration: PeRegistration) -> PeRegistrationOut:
    return PeRegistrationOut(
        recorded=registration.recorded,
        status=registration.status,
        tm_link_status=registration.tm_link_status,
        pe_id=registration.pe_id,
        entity_name=registration.entity_name,
        registered_at=registration.registered_at,
        verified_at=registration.verified_at,
        is_active=registration.is_active,
    )


@router.get(
    "",
    response_model=PeRegistrationOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's DLT Principal Entity registration — absence is data, not a 404",
    description=(
        "What the DLT registrar holds for this business, as the platform last verified "
        "it. Read-only: registrations are recorded by Calevate operations against the "
        "registrar, never by the client. A business with nothing filed yet gets "
        "`recorded: false` and a 200."
    ),
)
async def read_registration(
    session: Session,
    principal: RegistrationReader,
) -> PeRegistrationOut:
    assert principal.tenant_id is not None
    return _out(await read_pe_registration(session, tenant_id=principal.tenant_id))


__all__ = ["router"]
