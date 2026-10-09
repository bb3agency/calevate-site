/**
 * Handing a sign-in connection's result back from the provider's redirect to the screen
 * that started it (D-700).
 *
 * The provider returns to ONE fixed page per provider (`/oauth/callback/<provider>`, the
 * redirect address registered with it), which holds no account session of its own. So the
 * screen notes which account and which provider it is connecting before it opens the
 * consent page, and the callback page writes what came back next to that note. The screen
 * — in the opener tab, told by a `storage` event, or after the callback page sends this tab
 * back to it — finishes the connection with its own session. The `state` inside is checked
 * by the server, bound to this account and this person; nothing here is trusted beyond
 * routing it.
 *
 * Storage can be unavailable (a private window, blocked site data); every access is guarded
 * and a missing note just means the connection is started again.
 */

import type { OAuthKind } from "@/lib/api/actions";
import { lookup } from "@/lib/lookup";

export const OAUTH_START_KEY = "calevate.oauth.start";
export const OAUTH_RETURN_KEY = "calevate.oauth.return";
/** As long as the server's own state lasts. */
const MAX_AGE_MS = 10 * 60 * 1000;

/** The connections each provider's callback page can finish. Google's two share one
 * callback address, so the connection started in this browser decides which it was. */
export const PROVIDER_KINDS: Record<string, readonly OAuthKind[]> = {
  google: ["google_calendar", "google_sheets"],
  zoho: ["zoho_crm"],
  hubspot: ["hubspot"],
};

interface Start {
  slug: string;
  kind: OAuthKind;
  at: number;
  /** The consent page was opened in a popup. Recorded here because the callback page
   * cannot ask `window.opener`: Google's pages send Cross-Origin-Opener-Policy, which cuts
   * the popup off from its opener for good once it has visited them. */
  popup: boolean;
}

/** Where the callback page sends the person, and whether it is the popup to close. */
export interface OAuthReturnRoute {
  back: string;
  popup: boolean;
}

export interface OAuthResult {
  kind: OAuthKind;
  code: string;
  state: string;
  accountsServer: string | null;
}

function read<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage blocked: the connection cannot be handed back and is started again.
  }
}

function drop(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Nothing to drop.
  }
}

/** Called by the screen as it opens the consent page, saying whether that is a popup. */
export function beginOAuthReturn(slug: string, kind: OAuthKind, popup: boolean): void {
  write(OAUTH_START_KEY, { slug, kind, at: Date.now(), popup } satisfies Start);
}

/**
 * Called by the callback page: where to send the person back to, after noting the result.
 * Null when no connection was started here (or it is too old), and nothing is noted.
 */
export function noteOAuthReturn(
  provider: string,
  result: Omit<OAuthResult, "kind">,
): OAuthReturnRoute | null {
  const start = read<Start>(OAUTH_START_KEY);
  const kinds = lookup(PROVIDER_KINDS, provider);
  if (!start || !kinds?.includes(start.kind) || Date.now() - start.at > MAX_AGE_MS) return null;
  const kind = start.kind;
  write(OAUTH_RETURN_KEY, { ...result, kind, slug: start.slug, at: Date.now() });
  return { back: `/c/${encodeURIComponent(start.slug)}/integrations`, popup: start.popup === true };
}

/** Called by the screen: the result waiting for this account, taken once. */
export function takeOAuthReturn(slug: string): OAuthResult | null {
  const back = read<OAuthResult & { slug: string; at: number }>(OAUTH_RETURN_KEY);
  if (!back || back.slug !== slug || Date.now() - back.at > MAX_AGE_MS) return null;
  drop(OAUTH_RETURN_KEY);
  drop(OAUTH_START_KEY);
  return { kind: back.kind, code: back.code, state: back.state, accountsServer: back.accountsServer };
}
