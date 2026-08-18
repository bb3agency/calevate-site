"""Request-scoped context, carried by contextvars so nothing has to thread it.

Only two things live here and both are non-PII: the correlation id (echoed on the
response, stamped into audit rows and Langfuse traces — BACKEND-PATTERNS §3) and the
resolved principal set by the auth dependency. Never put a phone number, transcript
or extraction payload in here — this object gets logged.
"""

from __future__ import annotations

import re
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
# The two impersonation headers are ADDRESSING and AUTHORISATION, which is why there are
# two rather than one. `X-Impersonate-Org` names WHICH tenant this request is for (a
# slug, because D-10 addresses clients by slug and ~15 console call sites already hold
# one); `X-Impersonation-Grant` is the signed proof that this operator may enter it
# (`core/impersonation.py`). Collapsing them into one self-describing token would remove
# the very mismatch the grant exists to catch — a grant for tenant A presented against
# tenant B — and would leave `current_any` with nothing cheap to switch realms on.
IMPERSONATION_GRANT_HEADER = "X-Impersonation-Grant"

# Header values arrive latin-1-decoded, so a raw control byte survives as a character.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def bearer_token(header_value: str | None) -> str | None:
    """THE credential an `Authorization` header carries, or None when it carries none.

    HERE, in the leaf module, for the reason the header names above are here — one more
    thing two layers must agree about, where disagreeing is invisible to curl. The two
    readers are `core.auth._credential`, which authenticates with it, and
    `core.middleware.RateLimitMiddleware._caller`, which keys the per-caller rate-limit
    bucket on it; the limiter used to key on `fingerprint(<the whole raw header>)`, so
    `Bearer x`, `bearer x`, `BEARER x`, `Bearer  x` and `Bearer x ` — five spellings the
    verifier calls ONE credential, and every route accepts as one session — were five
    buckets. Padding the value with spaces made that unbounded: a single client could
    spend the whole `bulk_read` allowance (six exports a minute per caller, the profile
    that exists because "this is the shape data exfiltration takes") as many times as it
    liked. A limiter whose ceiling the caller chooses is the same defect class as the
    per-process `hash()` seed D-131 replaced, one layer up, so the fix is the same shape:
    make the identity a property of the credential rather than of how it was typed.

    It cannot live in `core.auth` — `apps.api.core.middleware` is on voice-runtime's
    pinned import surface (`tests/voice_runtime_import_surface_test.py`) and `core.auth`
    pulls `apps.api.compliance`, which that surface FORBIDS under hard rule 3.

    Returns the token with the scheme and surrounding whitespace removed. None means
    "not a bearer credential" — a missing header, another scheme, an empty token, or one
    carrying a control byte:

      a credential is ASCII-printable — a JWT is base64url, a dev token is
      `dev:<realm>:<subject-uuid>` — so a control byte is not a token that failed to
      verify. It mattered because the token's subject used to travel into a SQL
      parameter: `Bearer dev:client:a\\x00b` reached the `users` lookup and psycopg
      refused it ("PostgreSQL text fields cannot contain NUL"), which is a 500 and an
      alert, on every authenticated endpoint, for any unauthenticated caller. The
      subject is a UUID since D-177 and would not parse either, but this stays: two
      independent reasons for one refusal, and this one is at the boundary, where
      every path downstream is spared the case rather than each handling it.
    """
    scheme, _, token = (header_value or "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    if not token or _CONTROL_CHARS.search(token):
        return None
    return token


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is making this request. Ids only (hard rule 6)."""

    realm: Realm
    #: `users.id` on the client realm, `admin_users.id` on the admin realm. There is no
    #: second identifier: D-177 removed `clerk_user_id` from this dataclass because the
    #: credential's subject IS one of our ids, so a vendor id had nothing left to carry
    #: and nothing read it.
    user_id: UUID | None
    tenant_id: UUID | None
    role: str | None
    # D-22: an admin viewing a client dashboard gets a READ-ONLY scoped session.
    # Mutating dependencies refuse when this is True; the read itself is audited by
    # `core/auth.py::_record_impersonated_read`, which is the only place that can set
    # this flag — coalesced to one row per (admin, tenant) per minute, for the volume
    # reason argued there.
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
    "IMPERSONATION_GRANT_HEADER",
    "ORG_HEADER",
    "Principal",
    "Realm",
    "bearer_token",
    "correlation_id_var",
    "principal_var",
]
