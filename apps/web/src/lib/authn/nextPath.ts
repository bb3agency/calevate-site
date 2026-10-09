/**
 * `?next=` — where a sign-in returns a person to, and the open-redirect guard on it.
 *
 * A signed-out console page sends its visitor to the realm's sign-in screen with the page
 * they were on in `next`; signing in takes them back there instead of to the console's
 * front door. The value arrives in a URL anybody can craft, so it is accepted only as a
 * same-origin PATH inside the realm's own console. Anything else (an absolute URL, a
 * protocol-relative `//host`, a backslash that some browsers read as a slash, a control
 * character, a path in the other realm's console) is ignored and the default destination
 * is used. Pure functions with no realm of their own: each realm passes its own literal
 * prefix, so nothing here can carry one realm's destination into the other.
 */

export const NEXT_PARAM = "next";

/** Longer than any console URL; a cap so a crafted value is not parsed at any size. */
const MAX_NEXT_CHARS = 2048;

// A base that can never be a real origin, so `new URL` resolves a relative path against
// something and an absolute URL is caught by comparing origins.
const PROBE_ORIGIN = "https://next-path.invalid";

const UNSAFE = /[\\\u0000-\u001f\u007f]/;

/**
 * The path to return to, or `null` when `raw` is absent or not a path inside `prefix`.
 *
 * @param prefix - the realm's console root, e.g. `/c` or `/admin`.
 */
export function safeNextPath(raw: string | null | undefined, prefix: string): string | null {
  if (!raw || raw.length > MAX_NEXT_CHARS) return null;
  if (!raw.startsWith("/") || raw.startsWith("//") || UNSAFE.test(raw)) return null;
  let url: URL;
  try {
    url = new URL(raw, PROBE_ORIGIN);
  } catch {
    return null;
  }
  if (url.origin !== PROBE_ORIGIN) return null;
  if (url.pathname !== prefix && !url.pathname.startsWith(`${prefix}/`)) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** `next` from the current address bar, validated against `prefix`. Browser only. */
export function nextFromLocation(prefix: string): string | null {
  if (typeof window === "undefined") return null;
  return safeNextPath(new URLSearchParams(window.location.search).get(NEXT_PARAM), prefix);
}

/** The sign-in path with `here` carried as `next`, for a gate that is sending someone out. */
export function withNext(signInPath: string, here: string): string {
  if (!here || here === "/" || here.startsWith(signInPath)) return signInPath;
  return `${signInPath}?${NEXT_PARAM}=${encodeURIComponent(here)}`;
}
