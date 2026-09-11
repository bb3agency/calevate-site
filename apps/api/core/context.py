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
    # An admin is inside a client account ("view as client"). The read itself is audited by
    # `core/auth.py::_record_impersonated_read`, which is the only place that can set this
    # flag — coalesced to one row per (admin, tenant) per minute, for the volume reason
    # argued there.
    #
    # ⚠ **THIS NO LONGER MEANS "READ-ONLY" (D-587 supersedes D-22).** A view-as session may
    # now write what `rbac.VIEW_AS_MUTATIONS` classifies as writable, and every such write
    # is attributed to the OPERATOR — `user_id` above is already the `admin_users.id`, and
    # `impersonation_grant_id` below is what says the act came through a view-as session and
    # which one. Code that still reads this flag as "refuse" is asking the wrong question;
    # the question is `rbac.withheld_from_view_as(permission)`.
    impersonating: bool = False
    #: The `jti` of the view-as grant this request presented, when there is one.
    #:
    #: WHY IT IS ON THE PRINCIPAL AND NOT LEFT IN THE REQUEST. It is the attribution half of
    #: D-587: `compliance/audit.py::write_audit` reads it off the actor, so EVERY audited
    #: write performed inside a view-as session names the session that authorised it without
    #: the route's author doing anything — and joins to the one
    #: `admin.impersonation_started` row that says who entered this tenant, when, and from
    #: what address. A per-route parameter would have been correct on the routes whose
    #: authors remembered it.
    #:
    #: Set in `core/auth.py::_load_admin_principal` and nowhere else, from a grant
    #: `verify_grant` has already matched to this operator and this tenant. `None` here with
    #: `impersonating=True` is therefore not a reachable state through authentication — and
    #: `requires()` refuses the write anyway if it ever is, because an unattributable write
    #: is the one thing D-587 may not produce.
    impersonation_grant_id: UUID | None = None

    @property
    def is_admin(self) -> bool:
        return self.realm == "admin"

    @property
    def client_user_id(self) -> UUID | None:
        """The `users.id` of the PERSON acting, or `None` when an operator is acting.

        THE ONE WAY A ROUTE OBTAINS A CLIENT USER ID, and the reason it exists is D-587.
        `user_id` is a `users.id` on the client realm and an `admin_users.id` on the admin
        realm, and while impersonation was read-only no client-realm write could ever see
        the second kind. Now that it can, every column that stores "which person did this"
        as a `users.id` — `lead_saved_views.user_id`, `legal_acceptances.accepted_by`,
        `organizations.caller_memory_attested_by`, `whatsapp_alert_optin_ledger.user_id`,
        `knowledge_gaps.resolved_by` — is one FK violation (or, worse, one silent id-space
        mixture) away from an operator's id. Asking this instead of `user_id` makes that
        structural: the answer for an operator is `None`, which those sites either refuse on
        or store as "no person", and the operator is named in the audit row either way.
        """
        return self.user_id if self.realm == "client" else None


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
