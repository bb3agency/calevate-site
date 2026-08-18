# The certificate is about to expire (or we cannot see it)

**Alarms:** `tls_certificate_expiring`, `tls_certificate_unreadable`.
**Blast radius when it lands:** all four public surfaces at once — `app.` (client
dashboard), `admin.` (console), `api.` and `hooks.` (the voice engine's webhook
receiver). They share ONE certbot lineage (`infra/nginx/calevate.conf.template`), so they
do not fail one at a time.

**Nobody else is watching.** Let's Encrypt stopped sending expiration notices on
4 June 2025. The daily `check_tls_expiry` cron (`apps/workers/tls_expiry.py`) is the only
thing between a broken renewal and an outage.

## 0. What the alarm actually measured

The check does **not** connect to `hooks.calevate.tech`. Cloudflare proxies that name in
Full (strict) mode, so a handshake with the public name returns Cloudflare's own edge
certificate — which renews itself and stays valid long after ours has died. The check
handshakes with the **origin** (`TLS_ORIGIN_ADDRESS`, default `host.docker.internal:443`)
and puts the public hostname in SNI, so what it reports is the certificate **nginx is
serving right now**.

That distinction matters for triage: this alarm can fire while the site still looks fine
from a browser. It is telling you what Cloudflare will start rejecting with a 526.

## 1. `tls_certificate_expiring` — how many days are left?

The alert body carries the day count and the expiry date. The threshold is 21 days, and
certbot renews at 30, so **renewal has already been failing for at least a week** —
roughly eighteen attempts, twice a day. This is never a transient failure.

On the host:

```
sudo certbot certificates                 # what certbot thinks it has
sudo certbot renew --dry-run              # does issuance work at all?
sudo systemctl status certbot.timer       # is anything even trying?
journalctl -u certbot --since '10 days ago'
```

The three failures that produce this alarm, in the order they actually happen:

1. **The ACME challenge cannot be served.** `/.well-known/acme-challenge/` must be served
   from `ACME_WEBROOT` before any redirect. Test it by hand:
   `curl -I http://api.<domain>/.well-known/acme-challenge/probe` — a 301 to HTTPS means
   the challenge location is being shadowed and every renewal has been failing on it.
2. **Cloudflare is in the way.** The challenge is HTTP-01 through the proxy; a rule that
   redirects or blocks the path breaks it. Check the zone's rules, not the host.
3. **The renewal worked and nginx never read it.** `certonly` does not touch nginx. If
   `certbot certificates` shows a fresh expiry and this alarm still fires, the running
   server is holding the old file — that is exactly the failure this check exists to
   catch, because a file-based check would have reported green.
   `renew_hook =` must appear in `/etc/letsencrypt/renewal/<lineage>.conf`
   (`infra/nginx/README.md` §4.3). Fix: `sudo systemctl reload nginx`, then add the hook
   so it does not happen again.

**Never run `certbot --nginx`** — it rewrites templated config (DEPLOYMENT §10).

After a fix, confirm with the same measurement the alarm uses rather than with a browser:

```
openssl s_client -connect 127.0.0.1:443 -servername hooks.<domain> </dev/null 2>/dev/null \
  | openssl x509 -noout -enddate
```

## 2. If it has already expired

Cloudflare answers 526 for every proxied hostname: the dashboard, the console, the API and
the webhook receiver are all down. Order of recovery:

1. Reissue and reload nginx (above). This is the only real fix.
2. **Do not** switch the zone to Flexible to "get it back". That serves client traffic over
   an unencrypted origin leg, which is a data-protection incident on a platform holding
   callers' phone numbers.
3. Voice calls already in progress are unaffected — they run inside the rented engine. What
   is lost is the post-call webhook, and D-31's reconciliation poller re-drives those once
   `hooks.` answers again. Expect a burst of repairs; that is the design working.

## 3. `tls_certificate_unreadable` — we could not see it at all

The check could not complete a handshake with the origin. In order of likelihood:

1. **nginx is not running**, in which case everything is already down and this is the
   second alarm you got, not the first.
2. **`TLS_ORIGIN_ADDRESS` is wrong for this host.** It defaults to
   `host.docker.internal:443`, which is correct for the compose stack. A worker running
   outside a container needs `127.0.0.1:443`.
3. **The host firewall changed** and the container gateway can no longer reach 443.

A 403 from that address is **not** a failure of this check — nginx's origin lock refuses
non-Cloudflare addresses at the HTTP layer, after the handshake, and the certificate is
read from the handshake. If you can `openssl s_client` it, the check can too.

Treat an unreadable certificate as urgent: it is not a certificate that is fine, it is a
certificate nobody is watching, and the expiry alarm cannot fire while this one is firing.

## 4. What is NOT ours

- **Domain registration expiry.** The registrar is the authority and the notice goes to
  the registrant. Nothing in this repo can renew it. Keep the registrar's contact address
  one a human reads (OPERATIONS §4, external items).
- **The Cloudflare edge certificate.** Cloudflare's own, renewed by them.
- **The Cloudflare Origin CA certificate** on nginx's `default_server`: issued once with a
  15-year lifetime, so it has no silent-renewal failure mode. It is deliberately not
  checked.
