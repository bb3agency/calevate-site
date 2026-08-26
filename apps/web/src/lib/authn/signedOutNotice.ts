/**
 * Did this browser HAVE a session before it was told it has none?
 *
 * ## Why this cannot come from the server
 *
 * A restore that answers `signed_out` says the same thing for two different people: one
 * whose session just expired, and one who has never signed in. The server genuinely
 * cannot tell them apart — an expired cookie and an absent cookie both arrive as no
 * usable credential — and neither can this browser, because the session cookie is
 * `HttpOnly` and no script may read it.
 *
 * So the only evidence is a mark this tab made WHILE it had a session, and that is all
 * this module is.
 *
 * ## `sessionStorage`, not `localStorage`, and the difference is user-visible
 *
 * The mark must be per-TAB. A session ending is a thing that happened to the tab the
 * person is looking at; `localStorage` would put "you are signed out" in front of every
 * other tab and every future one on the same machine, including a fresh visit hours
 * later by somebody else on a shared computer. That is worse than saying nothing.
 *
 * ## One-shot by construction
 *
 * `takeSignedOut` reads AND clears, so the notice appears once. A flag that survived
 * being read would re-announce a sign-out on every visit to the sign-in page — including
 * the visit after a successful sign-in, which is the one moment it would be actively
 * wrong.
 *
 * Every access is wrapped: `sessionStorage` throws outright in some privacy modes, and a
 * cosmetic notice must never be the thing that breaks a sign-in page.
 */

/** Namespaced per realm: an operator session ending is not a client session ending. */
const KEY = (realm: string) => `calevate.authn.had-session.${realm}`;

function read(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
  } catch {
    /* A browser that refuses storage gets no notice. That is the correct degradation. */
  }
}

/**
 * Record that this tab holds a live session in `realm`.
 *
 * Called when a restore answers `ready`, which covers both ways a session begins — a
 * fresh sign-in and a reload of a tab that already had one.
 */
export function rememberSession(realm: string): void {
  if (typeof window === "undefined") return;
  write(KEY(realm), "1");
}

/**
 * Record that the session in `realm` has ended, so the sign-in page can say so.
 *
 * Returns whether there was anything to end: `false` on a browser that never held a
 * session here, which is the case the notice must stay silent for.
 */
export function markSignedOut(realm: string): boolean {
  if (typeof window === "undefined") return false;
  const had = read(KEY(realm)) === "1";
  write(KEY(realm), had ? "ended" : null);
  return had;
}

/** Read-and-clear. `true` means: tell this person their session ended. */
export function takeSignedOut(realm: string): boolean {
  if (typeof window === "undefined") return false;
  const ended = read(KEY(realm)) === "ended";
  if (ended) write(KEY(realm), null);
  return ended;
}
