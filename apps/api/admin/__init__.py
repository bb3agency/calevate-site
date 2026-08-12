"""Admin realm surfaces (admin.calevate.tech).

Separate Clerk application, separate session, separate route group (TRD §11) — the two
realms never share session logic, so nothing in here may be reachable with a client
token. That is enforced by `requires(..., realm="admin")` on every route, not by the
URL prefix.
"""
