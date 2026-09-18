/**
 * The routes an emailed single-use credential arrives on, and the `Referrer-Policy` they
 * are served with.
 *
 * ## The leak this closes
 *
 * `useLinkToken` takes `?token=` out of the address bar — but it does so in a
 * `useEffect`, which runs AFTER the first paint. Every same-origin subresource the
 * document has already asked for by then (`/_next/static/chunks/*`, the `next/font/local`
 * files under `/_next/static/media`) was issued while `location.href` still carried the
 * token, so each one sent
 *
 *     Referer: https://app.calevate.tech/auth/reset-password?token=<43 url-safe chars>
 *
 * `infra/nginx/snippets/calevate-headers.conf` sets `strict-origin-when-cross-origin`,
 * whose SAME-ORIGIN arm is the full URL — that is the documented behaviour of that value,
 * and it is the right default everywhere else in this console. And
 * `infra/nginx/00-log-format.conf.template` logs `"$http_referer"` on the field right
 * after the `$request_uri` it redacts, so the exact secret that format exists to keep out
 * of `/var/log/nginx/access.log` was arriving through the column beside it — and, every
 * zone being CF-proxied (D-27), through the edge request log too. A live
 * `password_reset` (1h), `accept-invitation` (72h) or `admin_bootstrap` (60m) token, in a
 * file readable by `adm`, by the log shipper and by the nightly backup.
 *
 * ## Why `strict-origin` and not something narrower
 *
 * `strict-origin` sends the ORIGIN only, on same-origin and cross-origin alike, and
 * withholds it entirely when HTTPS downgrades to HTTP. The origin is not a secret — it is
 * in the `Host` header of the same request — so nothing operational is lost, while the
 * path and the query string (the part carrying the credential) never leave the browser.
 *
 * `no-referrer` would also work and buys nothing more here, at the cost of being a
 * different value from the one the rest of the console serves for no reason a reader
 * could reconstruct. `same-origin` is the wrong shape entirely: its same-origin arm is
 * the FULL URL, which is precisely the arm that leaks.
 *
 * **A `<meta name="referrer">` is NOT sufficient and must not be used instead.** Next
 * emits the preload/stylesheet links for those chunks and fonts in the document head, and
 * the browser begins fetching them as it parses; a meta element that appears in the same
 * head does not reliably precede the requests it would have governed. The header is set
 * by `src/middleware.ts` on the document response itself, so it is in force before the
 * first byte of the body is parsed.
 *
 * ## Why this is not the whole fix
 *
 * It is the app half. The edge half is in `00-log-format.conf.template`, which now maps
 * `$http_referer` through the same redaction as `$request_uri` — because this header
 * governs only the browsers that honour it and only the routes listed below, and the log
 * must not depend on either. Either half alone leaves the other's failure mode open.
 */

/**
 * ## Why the paths are literals here and not imports
 *
 * This module is imported by `src/middleware.ts`, which Next bundles for the edge runtime
 * and evaluates on EVERY document request. `ADMIN_RESET_PATH` and its three siblings live
 * in `adminAuthn.ts` / `clientAuthn.ts`, whose import graph reaches `realm.ts`,
 * `transport.ts` and `lib/api/client.ts` and constructs a realm session instance at module
 * scope — a browser-tier runtime dragged into the request path of every page to read four
 * string constants.
 *
 * The drift that import would have prevented is instead pinned by a test:
 * `tests/linkTokenReferrer.test.ts` asserts this list EQUALS those constants plus the
 * legacy door, so renaming a route and forgetting this file is a red suite rather than a
 * silently unprotected page.
 */

/** The header name, spelled once. */
export const REFERRER_POLICY_HEADER_NAME = "Referrer-Policy";

/** Origin only, never the path or the query string. */
export const LINK_TOKEN_REFERRER_POLICY = "strict-origin";

/**
 * The legacy Clerk-era invite URL. It is a client redirect (`app/invite/page.tsx`) that
 * forwards the SAME token to `CLIENT_ACCEPT_INVITE_PATH`, so the document it serves holds
 * a live credential in its URL exactly like the pages below and is listed with them.
 *
 * Not imported from `lib/api/members.ts`: `inviteLink()` builds the DESTINATION, and this
 * is the old door. They are different strings and conflating them is how one of the two
 * silently stops being covered.
 */
export const LEGACY_INVITE_PATH = "/invite";

/**
 * Every path a mailed token can land on. `apps/api/core/console_links.py` mints four links (`ADMIN_BOOTSTRAP_PATH`, `ADMIN_RESET_PASSWORD_PATH`,
 * `CLIENT_RESET_PASSWORD_PATH`, `CLIENT_ACCEPT_INVITE_PATH`, at `:36-39`); the fifth entry
 * is the legacy door above. A new token-bearing route goes here in the same change that
 * mints it — the same instruction the nginx map carries for the same reason.
 */
export const LINK_TOKEN_PATHS: readonly string[] = [
  "/auth/reset-password",
  "/auth/accept-invitation",
  "/auth/admin/reset-password",
  "/auth/admin/bootstrap",
  LEGACY_INVITE_PATH,
];

/**
 * Whether a request path is one of them.
 *
 * Trailing slash tolerated because Next serves `/auth/reset-password/` as the same page,
 * and a policy that depends on which of the two the mail client produced is a policy that
 * is sometimes absent. Nothing DEEPER matches: these are leaf routes, and a prefix test
 * would hand the policy to any future `/invite/<something>` without anybody deciding it.
 */
export function carriesLinkToken(pathname: string): boolean {
  const path = pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
  return LINK_TOKEN_PATHS.includes(path);
}
