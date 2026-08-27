/**
 * Where the client console lives, when it is not on the hostname you are reading this on.
 *
 * THIS DEPLOYMENT IS THREE HOSTNAMES AND ONE BUNDLE. `calevate.tech` serves the marketing
 * site and the three auth screens; `app.calevate.tech` serves the client console;
 * `admin.calevate.tech` serves the operator console. Each console hostname REFUSES the
 * other's tree (D-177/P7.3), and the apex refuses both — nginx answers 404 for `/admin`
 * and `/c/` there. So a bare `href="/c/…"` is correct on exactly one of the three and a
 * dead end on the other two, and which one it is depends on where the reader happened to
 * be. That is not a rendering detail; it is the whole defect class, and it has now
 * produced two live bugs:
 *
 *   - "View as" on the operator console opened `admin.calevate.tech/c/<slug>` and 404'd
 *     for every tenant.
 *   - Signing in from the marketing site sent the user to `/c`, which the apex serves,
 *     which forwards to `/c/<slug>`, which the apex does not serve. A successful sign-in
 *     ended on a not-found page.
 *
 * `NEXT_PUBLIC_CLIENT_CONSOLE_ORIGIN` is the answer to both. It is REQUIRED in a deploy
 * build (`next.config.ts` refuses one without it, naming this consequence), and empty is
 * the honest default for a single-origin development box where a bare path is right.
 *
 * ## Why this is its own module
 *
 * It began inside `lib/api/session.tsx`, which is where the first caller was. That file
 * is React and TanStack Query; the auth layer and the marketing header need this too, and
 * neither should have to import a query provider to learn a hostname. A hostname is not
 * an API concern — it is a deployment fact — so it lives on its own with no imports at
 * all.
 */

/**
 * Read once at module scope, because `NEXT_PUBLIC_*` is INLINED at build time — a
 * per-call read would suggest it can change while the page is open, and it cannot.
 */
const CLIENT_CONSOLE_ORIGIN = process.env.NEXT_PUBLIC_CLIENT_CONSOLE_ORIGIN ?? "";

/**
 * A path on the client console, absolute when the realms are on different hostnames.
 *
 * Falls back to the bare path when nothing is configured, which is right for a
 * single-origin dev box and is exactly what a deploy build refuses to ship.
 */
export function clientConsoleUrl(path: string): string {
  const origin = CLIENT_CONSOLE_ORIGIN.replace(/\/+$/, "");
  return origin === "" ? path : `${origin}${path}`;
}

/**
 * Read once at module scope, for `CLIENT_CONSOLE_ORIGIN`'s reason: `NEXT_PUBLIC_*` is
 * inlined at build time and cannot change while the page is open.
 */
const ADMIN_CONSOLE_ORIGIN = process.env.NEXT_PUBLIC_ADMIN_CONSOLE_ORIGIN ?? "";

/**
 * A path on the OPERATOR console, absolute when the realms are on different hostnames.
 *
 * The mirror of `clientConsoleUrl`, added because the defect class is symmetric and the
 * other half reached production too: the impersonation banner's "Exit and return to the
 * admin console" called `window.location.assign("/admin")` from a page served on
 * `app.calevate.tech`, where nginx answers `location ^~ /admin { return 404; }`. An
 * operator finishing a view-as session — the one moment they are guaranteed to be on the
 * client hostname — got the not-found screen instead of their console.
 *
 * The same is true of every `/admin` destination on the AUTH screens, which are served on
 * the apex, and the apex refuses `/admin` as well.
 */
export function adminConsoleUrl(path: string): string {
  const origin = ADMIN_CONSOLE_ORIGIN.replace(/\/+$/, "");
  return origin === "" ? path : `${origin}${path}`;
}
