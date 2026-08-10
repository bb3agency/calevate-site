"""Request-scoped context, carried by contextvars so nothing has to thread it.

Only two things live here and both are non-PII: the correlation id (echoed on the
response, stamped into audit rows and Langfuse traces — BACKEND-PATTERNS §3) and the
resolved principal set by the auth dependency. Never put a phone number, transcript
or extraction payload in here — this object gets logged.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Realm = Literal["client", "admin", "system"]

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Header names live here, in a leaf module, because BOTH the auth dependency (which
# reads them) and the CORS config (which must allow them) need the same strings — and
# a mismatch between those two is invisible to curl and fatal in a browser.
ORG_HEADER = "X-Org-Slug"
IMPERSONATE_HEADER = "X-Impersonate-Org"


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is making this request. Ids only (hard rule 6)."""

    realm: Realm
    user_id: UUID | None
    clerk_user_id: str | None
    tenant_id: UUID | None
    role: str | None
    # D-22: an admin viewing a client dashboard gets a READ-ONLY scoped session.
    # Mutating dependencies refuse when this is True; every page view is audited.
    impersonating: bool = False

    @property
    def is_admin(self) -> bool:
        return self.realm == "admin"

    @property
    def can_mutate(self) -> bool:
        return not self.impersonating


principal_var: ContextVar[Principal | None] = ContextVar("principal", default=None)


__all__ = [
    "IMPERSONATE_HEADER",
    "ORG_HEADER",
    "Principal",
    "Realm",
    "correlation_id_var",
    "principal_var",
]
