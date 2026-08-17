"""First-party authentication — the CREDENTIAL layer (D-165, docs/AUTH-MIGRATION.md).

`core/auth.py` is the REQUEST-TIME layer: given a credential, who is this caller, which
realm, which tenant. This package is the layer underneath it: how a credential comes
into existence, how it is proved, and how it is destroyed.

**THIS IS THE ONLY AUTHENTICATION THIS PRODUCT HAS** (D-170 mounted it, D-177 deleted the
vendor beside it). The credential is a password proved with Argon2id under a KEK-derived
pepper, exchanged for an opaque server-side session in a `__Host-` cookie; `core/auth.py`
verifies that cookie through `sessions.verify_session` and nothing else. Clerk held
identity data outside India, and the hosting move to an Indian VPS existed to make the
residency claim true rather than aspirational — that claim is now true of identity too.

Layout mirrors BACKEND-PATTERNS §1:

    models.py       SQLAlchemy — the four `auth_*` tables
    hashing.py      Argon2id + a KEK-derived pepper. No database, no session.
    codes.py        keyed hashing and code minting for one-time secrets
    otp.py          the emailed six-digit second factor and email verification
    tokens.py       single-use emailed links (reset, invite, admin bootstrap)
    credentials.py  set and prove a password
    sessions.py     issue / verify / rotate / revoke. All queries, no HTTP.
    subjects.py     who a `(realm, subject_id)` is, and whether they may sign in
    throttle.py     per-account and per-address failure budgets
    cookies.py      how the session reaches the browser and comes back
    service.py      the flows themselves
    invitations.py  first-party invitation redemption
    bootstrap.py    the first administrator (D-171)
    routes.py       two realm routers from one factory
"""

from __future__ import annotations

__all__: list[str] = []
