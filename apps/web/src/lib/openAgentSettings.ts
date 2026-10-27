/**
 * `?open=call-handling` on the agents list: the address the retired account call-handling
 * page sends people to (founder, 27 Oct 2026). Plain data, so the server redirect and the
 * client list read the one spelling.
 */
export const OPEN_SETTINGS = { param: "open", callHandling: "call-handling" } as const;
