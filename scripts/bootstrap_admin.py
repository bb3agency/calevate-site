"""Create the first administrator, without whom a deployed platform is unreachable (D-167).

`admin_users` is the allowlist the entire admin realm resolves against, and **nothing else
in this repository ever inserts a row** — not `scripts/seed.py`, not `vps-deploy.sh`, not
`compose.prod.yml`. So after `alembic upgrade head` on a fresh host the table is empty and
every admin-realm request 403s: no organization can be created, no platform setting written,
no vendor credential stored, no first campaign approved. The deploy comes up green and the
product cannot onboard anybody. It fails closed, so this is not a security hole — it is a
deployment with no way in, and this script is the way in.

WHAT CHANGED, AND WHY THE OLD SHAPE IS GONE. This script used to take `--clerk-user-id`: a
row was an allowlist entry pointing at an account that already existed in the admin Clerk
application, and Clerk held the password. D-166 makes authentication first-party, so there
is no vendor dashboard in which to make the first account, and the id it took no longer
identifies anything. It now takes `--email` and mails a single-use setup link, which is what
AUTH-MIGRATION C-16 always said it would do. The `--clerk-user-id` form is deleted rather
than deprecated: it cannot work, and a flag that cannot work is worse than one that is gone.

NO PASSWORD IS PRINTED, GENERATED, OR DEFAULTED, ANYWHERE. The reference implementation's
`seed-admin.mjs` creates an admin with a fixed password and logs
`Admin created: ${admin.email} / ${PASSWORD}`; that is a hard rule 6 violation on its face
and `scripts/check_redaction_exposure.py` would fail the build on it. What this prints is a
LINK — a single-use token that expires in an hour — and locally, with no mail provider
configured, `ConsoleTransport` also logs the mail to the terminal, so a developer needs no
special path.

IDEMPOTENT, AND NOT A BACK DOOR (`apps/api/authn/bootstrap.py` argues it in full):
  * no operator at all       → create the row, mail a link
  * the named operator exists but has no password → mail a FRESH link (a resend)
  * any operator already has a password           → REFUSE, with no `--force` to override

USAGE (from the repo root, with the same environment `alembic upgrade head` needs):

    uv run python -m scripts.bootstrap_admin --email ops@example.com --name "Ops"
    uv run python -m scripts.bootstrap_admin --email ops@example.com --role operator

The link is mailed through the deployment's configured transport
(`apps/workers/transport.py`) and is ALSO printed to stdout, because the operator running a
deploy is standing at the terminal and a mail provider that is not configured yet must not
be the thing that blocks a bootstrap.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

#: Where the emailed link lands. The token travels in the `token` query parameter of a
#: PAGE, which then POSTs it to `/v1/auth/admin/bootstrap/confirm` — never in an API URL,
#: so it stays out of access logs and out of any `Referer`.
ADMIN_CONSOLE_BASE = "https://admin.calevate.tech"

_SUBJECT = "Set up your Calevate administrator account"


def _require_env() -> None:
    """Both URLs, for two different roles, and neither substitutes for the other.

    `ALEMBIC_DATABASE_URL` is the OWNER role, and this script needs it for the same reason
    `alembic` does — `admin_users` is written here and the app role has no business holding
    write access to the operator allowlist. `DATABASE_URL` is the APP role, and the authn
    package needs it because `auth_credentials` and `auth_email_tokens` are FORCE-RLS'd
    against `app.auth`, a GUC `credential_session()` sets on the application connection.
    """
    missing = [k for k in ("DATABASE_URL", "ALEMBIC_DATABASE_URL") if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            f"{' and '.join(missing)} not set. This script writes the operator allowlist "
            "and the credential store — set the environment the way `alembic upgrade head` "
            "needs it set."
        )


def _link(token: str) -> str:
    return f"{ADMIN_CONSOLE_BASE}/bootstrap?token={token}"


async def _run(*, email: str, name: str | None, role: str) -> str:
    # Imported inside the function so `--help` works on a host with no database reachable,
    # and so an import error names this module rather than argparse's frame.
    from apps.api.authn.bootstrap import bootstrap_first_admin
    from apps.workers.transport import get_transport

    result = await bootstrap_first_admin(email=email, name=name, role=role)
    link = _link(result.token)

    body = (
        "You have been made an administrator of a Calevate deployment.\n\n"
        f"Set your password:\n\n{link}\n\n"
        "This link works once and expires in one hour. If it expires, ask whoever "
        "deployed this environment to run the bootstrap again.\n"
    )
    # Delivery is best-effort and its failure is NOT fatal: the link is printed below, and
    # a deployment whose mail provider is not configured yet must still be able to acquire
    # its first operator. A bootstrap that failed because SMTP was not ready would be a
    # chicken-and-egg — the mail credentials are stored by an operator, in the console.
    delivered = False
    try:
        transport = get_transport()
        delivered = await asyncio.to_thread(
            lambda: transport.send(to=result.email, subject=_SUBJECT, body=body)
        )
    except Exception as exc:
        print(f"warning: could not send the email ({type(exc).__name__})", file=sys.stderr)

    what = "created" if result.created else "already present, new link issued for"
    return "\n".join(
        [
            f"{what} admin_users row {result.admin_id} ({role})",
            f"email sent: {'yes' if delivered else 'NO — use the link below'}",
            f"expires:    {result.expires_at.isoformat()}",
            "",
            "Setup link (single use):",
            link,
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bootstrap_admin",
        description=(
            "Create the first administrator on a freshly migrated database and email them "
            "a single-use setup link. Refuses if the deployment already has one."
        ),
    )
    parser.add_argument("--email", required=True, help="The address the setup link is sent to.")
    parser.add_argument("--role", choices=("superadmin", "operator"), default="superadmin")
    parser.add_argument("--name", default=None, help="Display name, for the audit trail.")
    args = parser.parse_args(argv)

    _require_env()

    from apps.api.core.errors import ProblemError

    try:
        print(asyncio.run(_run(email=args.email, name=args.name, role=args.role)))
    except ProblemError as exc:
        # `already_bootstrapped` is the expected non-zero exit, and it is not a crash: it
        # is this script doing its job. Printing the remediation rather than a traceback is
        # what makes it actionable to whoever is standing at the deploy.
        print(f"{exc.title}: {exc.detail}", file=sys.stderr)
        if exc.remediation:
            print(exc.remediation, file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
