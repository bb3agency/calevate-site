"""The `tls_certificate_expiring` alarm — OPERATIONS §4's "cert/domain expiry", ours half.

WHAT WAS WRONG. §4 lists cert expiry among the things that trigger an alert and nothing
raised one. Every public surface of this platform — the client dashboard, the admin
console, the API and the webhook receiver the voice engine posts into — is terminated by
ONE certbot lineage on the deployment host (`infra/nginx/calevate.conf.template`: all four
server blocks read `${TLS_LIVE_DIR}/fullchain.pem`). If that lineage stops renewing, all
four go down together, and the only thing that would have told us is gone: **Let's Encrypt
stopped sending expiration notification emails on 4 June 2025**
(https://letsencrypt.org/2025/01/22/ending-expiration-emails/), having previously sent
them at 20 days and 7 days. There is now nothing between a broken renewal and an outage
except a check we write.

WHY IT HANDSHAKES WITH THE ORIGIN AND NOT WITH THE PUBLIC NAME
---------------------------------------------------------------
The obvious implementation — connect to `hooks.calevate.tech:443` and read the peer
certificate — measures the wrong certificate. Traffic is proxied by Cloudflare in Full
(strict) mode, so what answers on the public name is CLOUDFLARE's edge certificate: it
renews itself, it is not ours to lose, and it stays valid for months after our origin
certificate has expired. What actually happens when the origin expires is a 526 from the
edge, with our check reporting green.

So the connection is made to the ORIGIN (`TLS_ORIGIN_ADDRESS`, the host's nginx reached
through the container gateway) with the public hostname supplied in SNI, which is how the
right `server` block and therefore the right certificate is selected. nginx applies its
Cloudflare-only `deny all` at the HTTP layer, after the handshake, so the certificate is
readable from here even though a request from here would be refused.

THIS IS STRICTLY STRONGER THAN READING THE PEM FILE, which was the other candidate. A
file read proves certbot wrote a certificate; a handshake proves nginx is SERVING it.
Those differ in exactly the failure `infra/nginx/README.md` §4.3 warns about — `certonly`
never touches nginx, so a renewal without `--deploy-hook "systemctl reload nginx"` leaves
a fresh file on disk and an expiring certificate on the wire. It also needs no bind mount
and no root-readable `/etc/letsencrypt/archive`.

WHY VERIFICATION IS OFF
------------------------
`ssl` is asked for the peer certificate with `CERT_NONE`, and the certificate is parsed
from its DER bytes rather than from the dict Python builds after validating. A checker
that verifies would raise `SSLCertVerificationError` on precisely the condition it exists
to report — an expired certificate — and could then say only "something is wrong", never
"it expired on the 14th". Nothing here trusts the peer: the only field read is `notAfter`,
and the only thing done with it is arithmetic.

THE THRESHOLD
--------------
21 days. Certbot renews when less than a third of the lifetime remains — 30 days for the
90-day Let's Encrypt certificate this deployment uses (certbot >= 4.0; it was a flat 30
days before that) — and `certbot.timer` tries twice a day. Nine days past the first
attempt is therefore about eighteen failed renewals: comfortably past any transient DNS,
rate-limit or webroot problem, so an alert here is a real breakage rather than a slow
Tuesday. It still leaves three weeks, and it is earlier than the 20-day notice Let's
Encrypt itself used to send, so the operator is told no later than they used to be by a
service that no longer exists.

WHAT IS NOT HERE, AND WHY
--------------------------
* **Domain-registration expiry.** The other half of §4's "cert/domain expiry" phrase. It
  is EXTERNAL and stays external: the authority is the registrar, the notice goes to the
  registrant, and the remedy is a payment nothing in this repo can make. Implementing an
  RDAP poll would produce a number we cannot act on programmatically and a second thing
  to be wrong about. It is named in OPERATIONS §4 as external, beside the Cloudflare zone.
* **The Cloudflare Origin CA certificate** on nginx's `default_server`. It is issued once
  with a 15-year lifetime and is not renewed by anything, so it has no silent-failure
  mode — the class of failure this alarm exists for does not apply to it.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from cryptography import x509

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

#: See the module docstring: nine days and ~18 renewal attempts past certbot's own
#: trigger, and no later than the 20-day notice Let's Encrypt used to send.
EXPIRY_ALERT_DAYS = 21

#: The handshake budget. This is a cron with nothing waiting on it, so the number is
#: about not hanging a worker slot rather than about latency: an origin that needs more
#: than five seconds to complete a local TLS handshake is itself the finding.
HANDSHAKE_TIMEOUT_S = 5.0


def _read_certificate(address: str, *, server_hostname: str) -> x509.Certificate:
    """Handshake, take the peer's DER, parse it. BLOCKING — run in a thread.

    Split out and synchronous because `ssl`/`socket` are, and because a test can drive
    this half against a real socket without an event loop.
    """
    host, _, port = address.partition(":")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Both off deliberately — see the module docstring. `check_hostname` must be cleared
    # BEFORE `verify_mode`: Python refuses the reverse order.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with (
        socket.create_connection((host, int(port)), timeout=HANDSHAKE_TIMEOUT_S) as sock,
        context.wrap_socket(sock, server_hostname=server_hostname) as tls,
    ):
        # `binary_form=True` and not the dict: an unvalidated peer certificate makes
        # `getpeercert()` return an EMPTY dict, which is the documented behaviour and
        # would have made this check silently measure nothing.
        der = tls.getpeercert(binary_form=True)
    if not der:
        raise ssl.SSLError("the origin completed a handshake without presenting a certificate")
    return x509.load_der_x509_certificate(der)


def public_hostname(webhook_base_url: str) -> str | None:
    """The name to put in SNI, or None when there is nothing real to check.

    Derived from `WEBHOOK_BASE_URL` rather than from a setting of its own: that value is
    already the one public hostname this deployment cannot be wrong about — it is baked
    into every published agent — and all four server blocks serve the same lineage, so
    one name proves the certificate for all of them. A second setting naming the same
    host would be a second thing to keep in step.
    """
    parsed = urlparse(webhook_base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return parsed.hostname


async def check_tls_expiry(ctx: dict[str, Any]) -> str:
    """Daily cron. Returns a short outcome string; arq stores it.

    Never raises. A cron that fails is retried by arq and then vanishes; what an operator
    needs from this one is a page, and both failure modes have one.
    """
    settings = get_settings()
    if settings.app_env == "local":
        # A stated no-op rather than a silent pass — the shape `BACKUP_HEARTBEAT_URL`
        # uses. There is no origin and no certificate on a laptop.
        log.info("tls_expiry_skipped", extra={"reason": "local"})
        return "skipped_local"

    hostname = public_hostname(settings.webhook_base_url)
    if hostname is None:
        # A non-local deployment whose webhook base URL is not HTTPS has a bigger problem
        # than certificate expiry, and it is one `check_deploy_env` refuses at deploy
        # time. Here it means only that there is no name to ask about.
        log.warning("tls_expiry_skipped", extra={"reason": "webhook_base_url_not_https"})
        return "skipped_no_https_host"

    address = settings.tls_origin_address
    try:
        certificate = await asyncio.to_thread(_read_certificate, address, server_hostname=hostname)
    except Exception as exc:
        # "We cannot see the certificate that terminates all four public surfaces" is an
        # alarm in its own right, and it is the state a wrong address, a stopped nginx or
        # a firewall change produces — every one of which hides an expiry rather than
        # causing one.
        alert(
            "CORE_LOGIC",
            "tls_certificate_unreadable",
            detail=f"{type(exc).__name__} handshaking with the origin for {hostname}",
            host=hostname,
        )
        return "unreadable"

    # `not_valid_after_utc` rather than the deprecated naive `not_valid_after`: an
    # expiry compared against a naive local clock is the timezone bug CLAUDE.md names.
    remaining = certificate.not_valid_after_utc - datetime.now(UTC)
    days = remaining.days
    if days > EXPIRY_ALERT_DAYS:
        log.info("tls_certificate_checked", extra={"host": hostname, "days_remaining": days})
        return f"ok days={days}"

    # Past the expiry the count goes negative, and "expires in -3 days" is the kind of
    # sentence a reader files as a bug in the checker rather than as an outage.
    # `(-remaining).days` and not `abs(days)`: `timedelta.days` floors, so a certificate
    # that died three days and one second ago reports -4, and "expired 4 days ago" is a
    # number an operator will check against the date and distrust the whole alert over.
    when = f"expired {(-remaining).days} day(s) ago" if days < 0 else f"expires in {days} day(s)"
    alert(
        "CORE_LOGIC",
        "tls_certificate_expiring",
        detail=(
            f"the certificate served for {hostname} {when} "
            f"({certificate.not_valid_after_utc:%Y-%m-%d}); certbot renews at 30 days, "
            f"so renewal has been failing for about {30 - days} day(s)"
        ),
        host=hostname,
    )
    return f"expiring days={days}"


__all__ = ["EXPIRY_ALERT_DAYS", "check_tls_expiry", "public_hostname"]
