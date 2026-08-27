# infra/nginx/

The edge config for the Calevate VPS. Rendered by `scripts/vps-deploy.sh` and installed by
`infra/privileged/sbin/calevate-nginx-apply`, the root-owned script that owns everything
touching `/etc/nginx` (D-167, DEPLOYMENT §11) — the deploy stages files into a fixed
directory and names one command with no arguments; it composes no privileged command of its
own. Nothing here is installed by hand in the normal case.

> **Nothing in this directory has been loaded by an nginx process.** It has never been
> through `nginx -t`, because no nginx exists where it was written. Read §4 before
> believing any of it works. The same caveat `infra/backup/README.md` carries, for the
> same reason.

---

## 1. What is here, and where each file lands

| Source | Installed as | Context |
|---|---|---|
| `00-log-format.conf.template` | `/etc/nginx/conf.d/00-calevate-log-format.conf` | `http` — the `map` + `log_format` that keep mailed tokens out of the access log. `00-` because conf.d is included alphabetically and a `log_format` must precede the `access_log` naming it |
| `calevate.conf.template` | `/etc/nginx/conf.d/calevate-site.conf` | the four server blocks |
| `000-default.conf.template` | `/etc/nginx/conf.d/000-default.conf` | certless-default_server fix (525) |
| `rate-zones.conf.template` | `/etc/nginx/conf.d/calevate-rate-zones.conf` | `http` — `limit_req_zone` lives here or nowhere |
| `snippets/calevate-tls.conf` | `/etc/nginx/snippets/` | TLS parameters |
| `snippets/calevate-origin.conf` | `/etc/nginx/snippets/` | Cloudflare real-ip + origin lock |
| `snippets/calevate-headers.conf` | `/etc/nginx/snippets/` | security response headers |
| `snippets/calevate-proxy.conf` | `/etc/nginx/snippets/` | proxy headers and timeouts |

**Two directories, and the split is not cosmetic.** Debian's `nginx.conf` auto-includes
`/etc/nginx/conf.d/*.conf` inside `http {}` and nothing at all from `/etc/nginx/snippets/`.
So anything that must be *inside* `http` (the rate zones) goes in `conf.d`, and anything
that is a fragment of `server`/`location` directives goes in `snippets` and is pulled in
by an explicit `include`. Put a snippet in `conf.d` and `nginx -t` fails; put the zones in
`snippets` and every `limit_req zone=` in the site config fails to resolve.

## 2. Rendering

`envsubst` over an **explicit** variable list — `ROOT_DOMAIN`, `TLS_LIVE_DIR`,
`ACME_WEBROOT`, `ORIGIN_CERT_PATH`, `ORIGIN_KEY_PATH`. Bare `envsubst` would substitute
every `$name` in the file, and an nginx config is made of `$name`: `$host`,
`$remote_addr`, `$binary_remote_addr` would all become empty strings, producing a config
that passes `nginx -t` and puts every request on Earth into one rate-limit bucket. The
deploy script also greps the rendered output for surviving `${...}` and aborts, so a
variable added to a template and forgotten in the list fails on the runner rather than at
reload on the live host.

**No secret is substituted, and none should be.** Everything here is a hostname or a
path. TLS private keys are referenced by path; they are never inlined.

## 3. Deliberately NOT built (say it out loud rather than approximate it)

- **The maintenance gate.** DEPLOYMENT §5 and §10 inherit a specific, hard-won shape for
  it — single-hop `error_page 401 =503`, because `if` in the rewrite phase cannot see
  `auth_request` variables and a two-hop error_page dies on `recursive_error_pages off`.
  A half-remembered version of that is worse than none: it fails in the exact situation
  it exists for. Not built; the lesson stays recorded in DEPLOYMENT §10.
- **`auth_request`.** Nothing here needs it, and it buffers request bodies, which breaks
  large uploads. Its absence is why `hooks.` can safely stream (`proxy_request_buffering off`).
- **Content-Security-Policy.** Belongs where the Next.js nonce is generated, not in a
  shared edge fragment. See the comment in `snippets/calevate-headers.conf`.
- **certbot issuance and renewal.** One-time human steps (DEPLOYMENT §9 step 5). The
  config serves `/.well-known/acme-challenge/` from `ACME_WEBROOT` so `certonly --webroot`
  and its renewals work; the issuance itself is not automated by this repo. **Never
  `certbot --nginx`** — it rewrites templated config (DEPLOYMENT §10). Issuance MUST carry
  `--deploy-hook "systemctl reload nginx"` (DEPLOYMENT §9.5a steps 3 and 5): `certonly`
  never touches nginx, so without it a day-60 renewal writes a certificate the running
  server never reads.
- **Cloudflare zone settings.** Proxy status, Full (strict), WAF, Turnstile and the
  per-token rate limits of DEPLOYMENT §7a are dashboard state, not files. They are not
  represented here and this directory does not pretend to be the source of truth for them.

## 4. What a human must do before any of this is real

1. **`nginx -t` it, once, on a host that has nginx.** Never done. `vps-deploy.sh` runs it
   before every reload, so the first deploy is where this is discovered — that is by
   design, but it means the first deploy should be an attended one.
2. **Refresh the Cloudflare ranges.** `snippets/calevate-origin.conf` carries a
   `CLOUDFLARE_IPS_UPDATED` stamp and the deploy **fails** when it is older than 180 days.
   Refresh from <https://www.cloudflare.com/ips-v4> and `/ips-v6`, update the stamp,
   commit. Do not edit one without the other.
3. **Issue the certificates, with the renewal hook attached in the same command.** A
   single SAN certificate over `admin.` `app.` `api.` `hooks.` via `certbot certonly
   --webroot --deploy-hook "systemctl reload nginx"`, plus a Cloudflare Origin CA
   certificate for the default_server. Set `TLS_LIVE_DIR`, `ORIGIN_CERT_PATH` and
   `ORIGIN_KEY_PATH` to match. *Pass condition*: `renew_hook =` appears in
   `/etc/letsencrypt/renewal/<lineage>.conf`. A plain `certbot renew --dry-run` does NOT
   run deploy hooks and does not prove this.
4. **Verify the origin lock does not lock YOU out.** `deny all` at the bottom of
   `calevate-origin.conf` means a direct-to-IP request gets 403. Loopback is allowed so
   the deploy script's own health poll works; anything else you rely on reaching directly
   (an uptime monitor pointed at the IP, say) must be added or moved behind Cloudflare.
5. **Prove the real-ip chain end to end.** This is pilot gate 1's edge half
   (OPERATIONS §2): POST to `hooks.` from a non-allowlisted host and confirm the app
   rejects it, then from the engine's address and confirm it is accepted. Until that has
   been done, "the source-IP allowlist works" is a claim about config, not a measurement —
   and for an unsigned engine that allowlist is the whole authenticity control.
