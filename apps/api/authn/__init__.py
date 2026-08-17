"""First-party authentication — the CREDENTIAL layer (D-165, docs/AUTH-MIGRATION.md).

`core/auth.py` is the REQUEST-TIME layer: given a credential, who is this caller, which
realm, which tenant. This package is the layer underneath it: how a credential comes
into existence, how it is proved, and how it is destroyed. Today the credential is a
Clerk JWT and `core/auth.py` verifies it against Clerk's JWKS; D-165 replaces that leg
with a password + an opaque server-side session that we mint ourselves, because Clerk
stores identity data outside India and the hosting move to an Indian VPS exists to make
the residency claim true rather than aspirational.

THIS PACKAGE IS MOUNTED AND IS THE ONLY AUTHENTICATION THIS PRODUCT HAS (D-170). An
earlier version of this docstring said the opposite — "deliberately not mounted on any
router", written when it was the proof-of-concept slice — and that sentence outlived its
truth by two slices. `routes.py` declares three routers, `core/bootstrap.py` mounts all
three, and `Settings.first_party_auth_enabled` is a kill switch rather than a cutover
gate. The Clerk paths still exist and still pass their tests; they are dead weight
awaiting AUTH-MIGRATION §5 step 6, not a live peer.

Layout mirrors BACKEND-PATTERNS §1:

    models.py       SQLAlchemy — the four tables this package owns
    hashing.py      Argon2id + a KEK-derived pepper. No database, no session.
    sessions.py     issue / verify / rotate / revoke. All queries, no HTTP.
    subjects.py     id or address → a person who may sign in, or `None`.
    credentials.py  the password store. tokens.py / otp.py / codes.py the secrets.
    throttle.py     the two failure budgets. cookies.py the transport and the CSRF rule.
    service.py      the flows. routes.py the surface. stepup.py the C-09 freshness gate.
    bootstrap.py    the first administrator (D-171). invitations.py redemption.
"""

from __future__ import annotations

__all__: list[str] = []
