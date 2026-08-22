"""Admin realm surfaces (admin.calevate.tech).

Separate realm, separate session, separate route group (TRD §11) — the two
realms never share session logic, so nothing in here may be reachable with a client
token. That is enforced by `requires(..., realm="admin")` on every route, not by the
URL prefix.

**AND IT IS NOW CHECKED AT BOOT RATHER THAN BY REVIEW.** `core/rbac.ADMIN_REALM_PREFIXES`
makes "every route under `/v1/admin/**` and `/v1/ops/**` resolves the admin realm" a clause
of `assert_policy_registry_complete`, because the permission alone never carried that
weight: `ROLE_PERMISSIONS` is one flat dict over both realms, so a client `owner` holds
`org:manage`, `agents:write` and `kb:write` — the strings a dozen routes in this package
declare — and a route that omitted `realm="admin"` would read as guarded everywhere a
human looks.

The package has two TIERS inside that realm. `operator_routes.py` is the surface that
decides who is in which, and it is the one thing `superadmin` can reach and `operator`
cannot touch at all.
"""
