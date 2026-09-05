/**
 * The surface a screen gets when it has not declared one — so the assistant is never
 * absent (D-501).
 *
 * ## What changed, and what the old objection was
 *
 * The dock used to render NOTHING without a declaration, on the argument that a launcher
 * over an undeclared screen "would open onto an empty context" and teach a person the
 * feature is broken on the screen where they first tried it. That argument is answered
 * rather than deleted: the context is not empty. A fallback carries the ROUTE the person
 * is on, a title derived from it, and — the part that does the work — the assistant keeps
 * every read tool, so "how many leads do I have?" and "which campaign is blocked?" are
 * answered on a screen that never described itself. The degraded state is "slightly less
 * context", not "the feature disappeared".
 *
 * ## It is composed at the DOCK and never pushed onto the registry stack
 *
 * This is the single most likely way to get this change wrong, and it is why this module
 * exports a surface rather than a hook that registers one. `registry.ts` is a STACK whose
 * top entry wins, and a parent's effect commits AFTER its children's — so a layout that
 * declared a generic surface unconditionally would land on top of the real declaration
 * made by the screen inside it and SHADOW it. That has already cost this console two field
 * lists once. `CopilotDock` therefore reads the stack, and falls back only when the stack
 * is empty: a real declaration wins by construction, in any mount order, because the
 * fallback is never in the running.
 *
 * ## The route is masked before it is sent
 *
 * The route reaches the model, and (for the client realm) `audit_log.object_id`, and it
 * goes through the server's redaction guard (`copilot/sanitize.assert_redacted`) like
 * everything else. A DECLARED route is a string a screen author wrote; this one is
 * whatever is in the address bar, which can hold an email, a phone number or an identity
 * number in a path segment. So segments are allow-listed rather than screened: a segment
 * is kept only if it is a plain name (a letter, then letters/digits/hyphens), and anything
 * else — a numeric id, a uuid, `foo@bar.com`, `+919876543210` — becomes `:hidden`. An
 * allow-list is used instead of a PII pattern because a pattern here would be a second,
 * drifting copy of `apps/workers/redaction.py` written in another language: the guard
 * would refuse the request and the person would see a defect message on a screen they
 * did nothing wrong on. The cost is that a slug starting with a digit is masked too, which
 * loses a word of context and nothing else.
 */

import { noFill, type CopilotSurface } from "./types";

/** What a masked segment becomes. Says "a value that was not sent", not "an id". */
const HIDDEN = ":hidden";

/** A path segment safe to send verbatim: a name, not a value. See the header. */
const PLAIN_SEGMENT = /^[A-Za-z][A-Za-z0-9-]{0,63}$/;

/** `CopilotScreen.route`'s own ceiling (`copilot/schemas.py`, `_MAX_ID`). */
const MAX_ROUTE = 200;

/**
 * The address bar, reduced to the part that is safe to say out loud.
 *
 * Takes a pathname (`usePathname()` already excludes the query string in the App Router)
 * and cuts anything after `?` or `#` anyway — a caller passing a full href is the
 * realistic mistake, and the hazard it carries is exactly the one this function exists
 * for.
 */
export function fallbackRoute(pathname: string): string {
  const path = pathname.split(/[?#]/, 1)[0];
  const segments = path
    .split("/")
    .filter((segment) => segment !== "")
    .map((segment) => (PLAIN_SEGMENT.test(segment) ? segment : HIDDEN));
  return segments.length === 0 ? "/" : `/${segments.join("/")}`.slice(0, MAX_ROUTE);
}

/**
 * What to call the screen: the last NAMED segment of the route, humanised.
 *
 * `/c/:hidden/billing` is "Billing", which is the sentence the founder asked for — "I can
 * see you're on the billing screen". It is derived from the address and nothing else, so
 * it can be a little coarse ("New" for `/c/acme/agents/new`) and it can never be a claim
 * about what is ON the screen, which is the property that matters here.
 */
export function fallbackTitle(route: string, realm: "client" | "admin"): string {
  const named = route
    .split("/")
    .filter((segment) => segment !== "" && segment !== HIDDEN)
    .at(-1);
  if (named === undefined) return realm === "admin" ? "Admin console" : "Your account";
  const words = named.replace(/-/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * THE HONEST SENTENCE, and the reason it is a `fact` rather than a new wire field.
 *
 * "This screen declared nothing" and "this screen shows nothing" are different statements
 * and the second one is a lie — a great many declared screens legitimately carry zero
 * writable fields (`noFill`), so an empty `<fields/>` cannot carry the distinction and the
 * model would read the fallback as a screen with nothing on it. This says which it is.
 *
 * It rides on `facts` — "read-only context the browser volunteers" — which is the seam a
 * recalled memory already uses (`copilot/routes.py`), so no schema, no OpenAPI change and
 * no new prompt section. What tells the model what to DO about it is static and trusted:
 * the paragraph in `copilot/prompt.py::SYSTEM_PROMPT`, because the screen block is fenced
 * as content and a behavioural rule stated inside it would be an instruction from the one
 * place the prompt says to take none.
 */
export const UNDECLARED_FACT_KEY = "screen_details";

const UNDECLARED_FACT_VALUE =
  "Not available. This screen did not describe itself, so its fields, values and " +
  "settings are not visible to you. That is missing information, not an empty screen — " +
  "do not say the screen is blank or that it has nothing on it.";

/**
 * The surface for a screen that declared none: route, a derived title, no fields, and the
 * fact above. `apply` is `noFill` and can never be reached — there are no declared fields,
 * so the panel filters every fill item away and `service.validate_fill` refuses the tool
 * call server-side before that (D-501, requirement 4).
 */
export function fallbackSurface(pathname: string, realm: "client" | "admin"): CopilotSurface {
  const route = fallbackRoute(pathname);
  return {
    route,
    title: fallbackTitle(route, realm),
    realm,
    fields: [],
    facts: [
      {
        key: UNDECLARED_FACT_KEY,
        label: "Details of this screen",
        value: UNDECLARED_FACT_VALUE,
      },
    ],
    apply: noFill,
    undeclared: true,
  };
}
