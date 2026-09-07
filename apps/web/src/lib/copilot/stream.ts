"use client";

import { API_BASE, ApiProblem, TimeoutProblem, problemFrom, type Session } from "@/lib/api/client";

import { createSseParser } from "./sse";
import type {
  CopilotAction,
  CopilotFillItem,
  CopilotNavigation,
  CopilotProposal,
  CopilotStep,
} from "./types";
import type { WireFact, WireField } from "./redaction";

/**
 * The one call this feature makes: `POST /v1/copilot/ask`, answered as `text/event-stream`.
 *
 * ## Why this is not `apiRequest`
 *
 * `lib/api/client.ts` is the app's one door to the API and this does not open a second
 * one so much as walk through the same door differently: `apiRequest` reads the WHOLE
 * body (`readBody`) and resolves once, which is precisely what a stream must not do. Its
 * `ApiProblem`, `problemFrom`, `TimeoutProblem` and `API_BASE` are imported rather than
 * re-implemented, so a refusal here renders through `ProblemNotice` exactly like every
 * other refusal in the console.
 *
 * The header block below IS a second spelling of `sendRequest`'s, and that is the cost of
 * the above. It sends the same four names — `Authorization`, `X-Org-Slug`,
 * `X-Impersonate-Org`, `X-Impersonation-Grant` — because `tests/cors_contract_test.py`
 * reads `client.ts` for the header names the API's CORS allowlist must admit, and a name
 * invented here would be one the browser sends and the preflight rejects. It adds none.
 *
 * ## Why there is no reconnect, said out loud
 *
 * `EventSource` reconnects by itself; `fetch` does not, and this deliberately does not
 * either. A reconnect would re-run the request, and the request is METERED (`done` carries
 * `metered`) and can FILL FIELDS — replaying it could charge a client twice for one
 * question and apply one batch of values twice, with the second batch overwriting an edit
 * the person made in between. So a dropped stream ends as `StreamDropped` below: whatever
 * arrived stays on screen and stays undoable, and the person decides whether to ask again.
 */

/** The request body — snake_case because it IS the wire, per the agreed contract. */
export interface CopilotAskBody {
  screen: { route: string; title: string; realm: "client" | "admin" };
  question: string;
  fields: WireField[];
  facts: WireFact[];
  history: { role: "user" | "assistant"; content: string }[];
}

export interface CopilotStreamHandlers {
  /** One streamed chunk of the answer. Already restored (see `redaction.ts`). */
  onText: (delta: string) => void;
  /** A batch the model wants written into the screen. May arrive more than once. */
  onFill: (items: CopilotFillItem[]) => void;
  /**
   * A described change the assistant is OFFERING to make. NOTHING HAS HAPPENED.
   *
   * At most one per response, and it is applied to nothing: the panel shows it beside a
   * Confirm button, and only that button's own request to `POST /v1/copilot/confirm`
   * changes anything. Deliberately a SEPARATE handler from `onFill` — a fill is form
   * state in this browser that the person still has to save, a proposal is an offer to
   * touch the database, and one callback taking both is the seam where that distinction
   * would be lost.
   */
  onProposal: (proposal: CopilotProposal) => void;
  /**
   * A TIER 1 action that HAS ALREADY HAPPENED — reversible, reaching no caller, spending
   * nothing (D-500). A SEPARATE handler from `onProposal` for the same reason `onProposal`
   * is separate from `onFill`: these are three different promises, and one callback taking
   * two of them is the seam where a receipt gets rendered as an offer.
   */
  onAction: (action: CopilotAction) => void;
  /**
   * A SCREEN TO OPEN (D-524). The only handler here that is asked to DO something rather
   * than to render something, which is why it is its own callback and not a variety of
   * `onAction`: a consumer that routed them through one would either navigate on a receipt
   * or ignore a navigation.
   *
   * At most one per response. The frame carries a route TEMPLATE and this layer passes it
   * through unresolved — substituting the slug and checking the result against the console's
   * own nav list is `navigate.ts`'s job, and doing it here would put a route decision in the
   * transport.
   */
  onNavigate: (navigation: CopilotNavigation) => void;
  /**
   * One tool call as it happens. Called TWICE per call — `running`, then a terminal frame
   * sharing the same `id`.
   *
   * OBSERVATIONAL ONLY: a consumer may ignore every one of these and lose no outcome. That
   * is what makes it safe for the panel to render them live while the answer is still
   * arriving, and it is why nothing downstream keys off them.
   */
  onStep: (step: CopilotStep) => void;
  /** The stream finished properly. `disclosure` is rendered VERBATIM when present. */
  onDone: (done: { disclosure: string | null; metered: boolean }) => void;
}

/**
 * The stream ended without a `done` event.
 *
 * An `ApiProblem` rather than a bare `Error` because that is the only failure shape the
 * console renders (`ProblemNotice`), and `retryable: true` because it is honest: nothing
 * about a severed connection says the next attempt fails. What it deliberately does NOT
 * say is that nothing happened — the request may well have completed and been metered on
 * the server after we stopped listening, which is why the remediation asks rather than
 * reassures.
 */
export class StreamDroppedProblem extends ApiProblem {
  constructor() {
    super(0, {
      kind: "transient",
      type: "urn:calevate:browser/copilot_stream_dropped",
      title: "The answer stopped part-way",
      detail: "The connection closed before the assistant finished answering.",
      remediation:
        "Anything it already filled in is still on the form and can still be undone. Ask again if the answer looks incomplete.",
      retryable: true,
    });
    this.name = "StreamDroppedProblem";
  }
}

/**
 * How long we wait for the RESPONSE HEADERS, and nothing else.
 *
 * Below `REQUEST_TIMEOUT_MS` (70s) on purpose, and it governs a different thing: the
 * whole point of a stream is that the BODY takes as long as the answer takes, so a
 * deadline over the body would cut off a long answer for being long. Time-to-first-byte
 * is what a hung request looks like, and 30s is far above any measured value for a route
 * that starts emitting as soon as the model does.
 */
export const COPILOT_HEADERS_TIMEOUT_MS = 30_000;

export const COPILOT_ASK_PATH = "/v1/copilot/ask";

/**
 * The ADMIN realm's own assistant (D-499). A SECOND PATH, not a flag on the first.
 *
 * The two are different endpoints because they are different assistants with different
 * payers: `/v1/copilot/ask` spends the account's own AI allowance and is `realm: "any"` —
 * which resolves an admin identity ONLY when an impersonation header is present, so an
 * operator on `/admin/ops` is invisible to it and would be answered with a 401 rather than
 * a refusal anyone could act on. `/v1/admin/copilot/ask` is `realm: "admin"` and its spend
 * lands on the platform's own ledger: an operator never spends a client's allowance, on
 * any path, including inside a view-as session.
 */
export const ADMIN_COPILOT_ASK_PATH = "/v1/admin/copilot/ask";

/**
 * WHICH ENDPOINT THIS REALM ASKS. Derived from the realm the dock was mounted with
 * (`CopilotDock`'s `realm` prop), never from the pathname and never from the screen
 * declaration in the body — the two normally agree, and the one that decides is the one
 * that also decided which session module minted the credential.
 */
export function copilotAskPath(realm: "client" | "admin"): string {
  return realm === "admin" ? ADMIN_COPILOT_ASK_PATH : COPILOT_ASK_PATH;
}

async function authHeaders(session: Session): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "text/event-stream" };
  const requested = session.token?.();
  const token = typeof requested === "string" ? requested : await requested;
  if (session.orgSlug) headers["X-Org-Slug"] = session.orgSlug;
  if (token !== undefined) headers["Authorization"] = `Bearer ${token}`;
  if (session.impersonateOrg && session.impersonationGrant) {
    headers["X-Impersonate-Org"] = session.impersonateOrg;
    const grant = session.impersonationGrant();
    headers["X-Impersonation-Grant"] = typeof grant === "string" ? grant : await grant;
  }
  return headers;
}

/**
 * Parse one `data:` payload, or `null` if it is not JSON we can read.
 *
 * A FRAME IS NOT THE ANSWER, and that is the whole reason for this function. `JSON.parse`
 * throws a `SyntaxError`, which is not an `ApiProblem`, so ONE malformed frame — a proxy
 * that flushed a half-written line, a vendor error interleaved mid-stream — used to reject
 * `askCopilot` and take the entire answer down with it: the text that had already arrived,
 * and the explanation of the fields it had already filled. Dropping the frame is strictly
 * better, and it is the same outcome every handler below already has for a frame missing
 * the field it needs. It cannot hide a truncated stream either: a stream that then ends
 * without `done` still raises `StreamDroppedProblem`.
 */
function safeJson(data: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(data);
    // An array or a bare scalar is valid JSON and is not a frame body. Returning it would
    // hand every branch below an object it cannot read fields from.
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/**
 * Ask, and drive the handlers until the stream ends.
 *
 * Resolves when `done` arrived. REJECTS with an `ApiProblem` for every other ending — a
 * non-2xx, an `error` event, or a severed stream — so the panel has exactly one failure
 * path to render and cannot end up "finished" on a stream that was cut.
 */
export async function askCopilot(
  session: Session,
  body: CopilotAskBody,
  handlers: CopilotStreamHandlers,
  options: { signal?: AbortSignal } = {},
): Promise<void> {
  const headers = await authHeaders(session);
  const controller = new AbortController();
  const forwardAbort = () => controller.abort(options.signal?.reason);
  if (options.signal) {
    if (options.signal.aborted) forwardAbort();
    else options.signal.addEventListener("abort", forwardAbort);
  }
  let headersTimedOut = false;
  const headersTimer = setTimeout(() => {
    headersTimedOut = true;
    controller.abort();
  }, COPILOT_HEADERS_TIMEOUT_MS);

  try {
    let response: Response;
    try {
      response = await fetch(`${API_BASE}${copilotAskPath(body.screen.realm)}`, {
        method: "POST",
        headers,
        // The credential, in the deployed case (D-177): the realm's HttpOnly `__Host-`
        // cookie, which the browser only sends cross-origin when asked to.
        credentials: "include",
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (cause) {
      if (headersTimedOut) throw new TimeoutProblem(COPILOT_HEADERS_TIMEOUT_MS);
      throw cause;
    } finally {
      // The body is allowed to take as long as the answer takes — see the constant.
      clearTimeout(headersTimer);
    }

    if (!response.ok) throw await problemFrom(response);
    // A 200 with no body is not a stream. `getReader` on `null` would throw a
    // TypeError the console can only render as "Something went wrong".
    if (response.body === null) throw new StreamDroppedProblem();

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = createSseParser();
    let finished = false;

    /*
     * THE READER IS RELEASED ON EVERY EXIT, NOT ONLY THE HAPPY ONE.
     *
     * Three endings leave this loop without the reader having read to `done`: an `error`
     * frame (which throws an `ApiProblem`), a stream that stops without a terminal `done`
     * (`StreamDroppedProblem`), and any throw out of a handler. Each of those left
     * `response.body` LOCKED and undrained, which holds the connection and its buffered
     * bytes until GC gets round to it — on a console people leave open all day, once per
     * failed answer. `cancel()` is the stream API's own way to say "I am done reading and
     * I do not want the rest"; it is a no-op after a clean end, and its rejection is
     * swallowed because the ending already being reported is the one that matters.
     */
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        // `stream: true` so a multi-byte character split across two chunks is held rather
        // than decoded into a replacement character — Telugu is three bytes per glyph, so
        // this is the ordinary case here, not an edge one.
        for (const event of parser.push(decoder.decode(value, { stream: true }))) {
          if (event.event === "text") {
            const payload = safeJson(event.data) as { delta?: string } | null;
            if (typeof payload?.delta === "string") handlers.onText(payload.delta);
          } else if (event.event === "fill") {
            const payload = safeJson(event.data) as { items?: CopilotFillItem[] } | null;
            if (Array.isArray(payload?.items) && payload.items.length > 0) {
              handlers.onFill(payload.items);
            }
          } else if (event.event === "proposal") {
            // Guarded like `fill`, and on the field that MATTERS. A frame with no usable
            // `token` cannot be confirmed, so a card rendered from it would offer a person
            // a button that can only ever refuse. Nothing else is checked here: the rest is
            // the server's own prose, and the arguments a Confirm would actually run are
            // inside the token's signature rather than in anything this browser could
            // validate — re-deriving them would be a second, editable account of the change.
            const payload = safeJson(event.data) as CopilotProposal | null;
            if (typeof payload?.token === "string" && payload.token !== "") {
              handlers.onProposal(payload);
            }
          } else if (event.event === "action") {
            // Guarded on `tool`, which is what a renderer cannot do without. Nothing else is
            // checked: every other field is the server's own prose about something it has
            // ALREADY done, so there is no decision here for the browser to second-guess and
            // no token to validate — unlike a proposal, this one is not an offer.
            const payload = safeJson(event.data) as CopilotAction | null;
            if (typeof payload?.tool === "string" && payload.tool !== "") {
              handlers.onAction(payload);
            }
          } else if (event.event === "navigate") {
            // Guarded on `route`, which is the field this frame exists to carry — a frame
            // without one names no destination and could only ever be dropped later. Nothing
            // else is checked HERE, and in particular the route is not validated here: it is
            // a template, and turning it into a path this console actually has is
            // `navigate.ts`'s job, run at the moment of the move rather than at parse time.
            const payload = safeJson(event.data) as CopilotNavigation | null;
            if (typeof payload?.route === "string" && payload.route !== "") {
              handlers.onNavigate(payload);
            }
          } else if (event.event === "step") {
            // Guarded on `id`, because the id is what pairs the terminal frame with its own
            // `running` one. A frame without it could only ever append a second row for one
            // call, which is worse than dropping it.
            const payload = safeJson(event.data) as CopilotStep | null;
            if (typeof payload?.id === "string" && payload.id !== "") {
              handlers.onStep(payload);
            }
          } else if (event.event === "done") {
            const payload = safeJson(event.data) as {
              disclosure?: string | null;
              metered?: boolean;
            } | null;
            // A `done` THAT DID NOT PARSE STILL ENDS THE STREAM. Its arrival is the terminal
            // fact; its contents are a disclosure sentence and a meter flag, and losing those
            // is a far smaller harm than telling a person that a finished answer was cut off.
            // `disclosure` then stays null, which the panel renders as nothing rather than as
            // a claim of its own.
            finished = true;
            handlers.onDone({
              disclosure: payload?.disclosure ?? null,
              metered: payload?.metered === true,
            });
          } else if (event.event === "error") {
            // A problem+json body delivered INSIDE a 200 stream, because the status line
            // was already sent by the time the failure happened. Same class, same
            // rendering, same `code` — which is what lets the ceiling be recognised.
            // An `error` frame that does not parse carries no problem document to render,
            // so it is dropped like any other malformed frame. The stream then ends without
            // `done` and `StreamDroppedProblem` below reports the failure anyway.
            const problem = safeJson(event.data);
            if (problem !== null) throw new ApiProblem(200, problem);
          }
        }
      }

      if (!finished) throw new StreamDroppedProblem();
    } finally {
      void reader.cancel().catch(() => {});
    }
  } finally {
    options.signal?.removeEventListener("abort", forwardAbort);
  }
}
