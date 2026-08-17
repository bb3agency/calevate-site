"use client";

/**
 * The single-use token an emailed link arrives with — read once, then taken out of the URL.
 *
 * Reset links, invitation links and the first-administrator setup link all deliver their
 * credential in the query string, because a link is the delivery mechanism and there is no
 * other place in a URL to put one. That is the server's contract
 * (`apps/api/authn/service.py`, `bootstrap.py`, and the unchanged `/invite?token=` shape)
 * and this hook does not get to argue with it.
 *
 * ## What it DOES get to fix
 *
 * Hard rule 6 forbids putting a credential in a query string, and while we did not put it
 * there, leaving it there keeps it live in places that outlast the page: the address bar
 * over somebody's shoulder, the browser history, a `Referer` header on any outbound link
 * the page renders, and a screenshot pasted into a support chat. So the token is captured
 * into React state on the first render and then removed from the URL with
 * `history.replaceState` — same document, no navigation, no re-render, no new history
 * entry to press Back into.
 *
 * `replaceState` rather than `router.replace`: this must not re-run the route or remount
 * the form, and a soft navigation would do both — including in the middle of a submit.
 *
 * The token is never logged and never rendered. It goes from the URL into state into one
 * request body, and nowhere else.
 */

import { useEffect, useState } from "react";

export const LINK_TOKEN_PARAM = "token";

export interface LinkToken {
  /** The token, or `""` when the link arrived without one. */
  token: string;
  /** False until the first client render has read the URL — SSR has no `location`. */
  ready: boolean;
}

export function useLinkToken(): LinkToken {
  const [state, setState] = useState<LinkToken>({ token: "", ready: false });

  useEffect(() => {
    const url = new URL(window.location.href);
    const token = (url.searchParams.get(LINK_TOKEN_PARAM) ?? "").trim();
    setState({ token, ready: true });

    if (!url.searchParams.has(LINK_TOKEN_PARAM)) return;
    url.searchParams.delete(LINK_TOKEN_PARAM);
    // `pathname + search + hash`, not `url.href`: keeping it relative means nothing here
    // can rewrite the origin, which is the one part of a URL a page must never move.
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, []);

  return state;
}
