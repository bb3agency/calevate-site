"""First-party authentication — the CREDENTIAL layer (D-165, docs/AUTH-MIGRATION.md).

`core/auth.py` is the REQUEST-TIME layer: given a credential, who is this caller, which
realm, which tenant. This package is the layer underneath it: how a credential comes
into existence, how it is proved, and how it is destroyed. Today the credential is a
Clerk JWT and `core/auth.py` verifies it against Clerk's JWKS; D-165 replaces that leg
with a password + an opaque server-side session that we mint ourselves, because Clerk
stores identity data outside India and the hosting move to an Indian VPS exists to make
the residency claim true rather than aspirational.

THIS PACKAGE IS DELIBERATELY NOT MOUNTED ON ANY ROUTER, and that is the one thing to
know before reading further. It is the proof-of-concept vertical slice the design
document is measured against — schema, hashing, session issue/verify/rotate/revoke, and
a negative control per security property — not a second front door. Mounting a
credential-accepting route while Clerk is still the live authenticator would give this
deployment two ways to obtain a session, which is the defect class CLAUDE.md's "one way
per problem" names, and it would do so on the surface where a mistake is a cross-tenant
breach rather than a bug. The cutover sequence that mounts it is AUTH-MIGRATION §5.

`scripts/check_wiring.py` does not report this package, and the reason is structural
rather than lucky: it declares no `APIRouter`, so there is no route table it is missing
from, and every column it declares is read by `hashing.py` / `sessions.py`.

Layout mirrors BACKEND-PATTERNS §1 minus the two files a routed module would have:

    models.py    SQLAlchemy — `auth_credentials`, `auth_sessions`
    hashing.py   Argon2id + a KEK-derived pepper. No database, no session.
    sessions.py  issue / verify / rotate / revoke. All queries, no HTTP.
"""

from __future__ import annotations

__all__: list[str] = []
