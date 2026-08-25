"""Every URL this platform mails to a human, composed in ONE place.

**THE DEFECT THIS MODULE EXISTS FOR.** Two composers — `apps/workers/auth_email._body`
and `scripts/bootstrap_admin._link` — each wrote the operator setup link as
`{base}/bootstrap?token=…`. The page that redeems that token is served at
`/auth/admin/bootstrap`. There is no `/bootstrap` route and no redirect to one, so the
link 404'd as printed, on the one screen a fresh deployment cannot be reached without.
The password-reset link was wrong the same way and worse: `{base}/reset-password?token=…`
against real routes of `/auth/reset-password` (client) and `/auth/admin/reset-password`
(admin) — one string for two realms, neither of which it named.

It survived a guard that looked right. `tests/auth_email_delivery_test` compared the two
BOOTSTRAP composers **to each other**, so they agreed, and agreed on a page nobody serves.
Two writers of one URL can only be kept honest against the thing that answers it.

So: one writer, and a test that resolves every path here against the Next.js route tree on
disk. A link that names no page fails in CI rather than in somebody's inbox.

**Why the token is in a PAGE's query string and never an API route's.** The page POSTs it
to `/v1/auth/...`; the secret therefore stays out of the API's access logs, and out of any
`Referer` an outbound link on that page would send. Changing any of these to point at an
API endpoint would undo that quietly.
"""

from __future__ import annotations

#: The two browser realms. Separate hostnames, separate session modules (D-177) — and
#: separate reset pages, which is why `password_reset_link` takes a realm rather than
#: assuming one.
CONSOLE_BASE = "https://app.calevate.tech"
ADMIN_CONSOLE_BASE = "https://admin.calevate.tech"

#: Paths, exactly as `apps/web/src/app` serves them. `(auth)` is a Next.js ROUTE GROUP and
#: contributes no URL segment — which is precisely why these are easy to get wrong from
#: the directory listing, and why the guard resolves them rather than eyeballing them.
ADMIN_BOOTSTRAP_PATH = "/auth/admin/bootstrap"
ADMIN_RESET_PASSWORD_PATH = "/auth/admin/reset-password"
CLIENT_RESET_PASSWORD_PATH = "/auth/reset-password"
CLIENT_ACCEPT_INVITE_PATH = "/auth/accept-invitation"

#: The query parameter every single-use link travels in. One name, because
#: `apps/web/src/lib/authn/useLinkToken` strips exactly this one out of the URL on arrival
#: so the secret is not left in browser history or in a screenshot.
TOKEN_PARAM = "token"


def console_base(realm: str) -> str:
    """The hostname for `realm`. Anything that is not `admin` is the client console —
    the same defaulting `authn/service` uses, stated once."""
    return ADMIN_CONSOLE_BASE if realm == "admin" else CONSOLE_BASE


def _link(base: str, path: str, token: str) -> str:
    return f"{base}{path}?{TOKEN_PARAM}={token}"


def admin_bootstrap_link(token: str) -> str:
    """The first-administrator (and every-later-operator) setup link.

    Single-use and one hour long, which is what makes a wrong path expensive: the person
    clicks, gets a 404, and by the time anyone works out why, the token is gone.
    """
    return _link(ADMIN_CONSOLE_BASE, ADMIN_BOOTSTRAP_PATH, token)


def password_reset_link(realm: str, token: str) -> str:
    """The password-reset link for `realm`. Two realms, two pages, two hostnames."""
    path = ADMIN_RESET_PASSWORD_PATH if realm == "admin" else CLIENT_RESET_PASSWORD_PATH
    return _link(console_base(realm), path, token)


def accept_invitation_link(token: str) -> str:
    """The client-console invitation link.

    Client realm only: an operator is not invited, they are bootstrapped
    (`admin_bootstrap_link`), which is why this one takes no realm.
    """
    return _link(CONSOLE_BASE, CLIENT_ACCEPT_INVITE_PATH, token)


__all__ = [
    "ADMIN_BOOTSTRAP_PATH",
    "ADMIN_CONSOLE_BASE",
    "ADMIN_RESET_PASSWORD_PATH",
    "CLIENT_ACCEPT_INVITE_PATH",
    "CLIENT_RESET_PASSWORD_PATH",
    "CONSOLE_BASE",
    "TOKEN_PARAM",
    "accept_invitation_link",
    "admin_bootstrap_link",
    "console_base",
    "password_reset_link",
]
