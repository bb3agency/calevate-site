"use client";

import { ApiProblem, openEventStream, type Session } from "@/lib/api/client";

import type {
  CopilotAction,
  CopilotFillItem,
  CopilotJobFrame,
  CopilotNavigation,
  CopilotProposal,
  CopilotStep,
} from "./types";
import type { WireFact, WireField } from "./redaction";

/**
 * The one call this feature makes: `POST /v1/copilot/ask`, answered as `text/event-stream`.
 *
 * ## The transport is `lib/api/client.ts`
 *
 * This module owns the copilot's FRAMES, not the connection. `openEventStream` sends the
 * request with the same identity headers, cookie and correlation id as every other write,
 * turns a non-2xx into `problemFrom`'s `ApiProblem`, a browser failure into
 * `TransportProblem`, and a missed header deadline into `TimeoutProblem`, so every refusal
 * here renders through `ProblemNotice` like every other refusal in the console.
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
  /** Admin realm only: the client account the page is about (`adminTenantOf`). */
  tenant_id?: string;
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
  /**
   * The request was handed to a BACKGROUND JOB (D-694). Optional, so a consumer that does
   * not follow jobs loses nothing but the card: the answer still says it started one.
   */
  onJob?: (job: CopilotJobFrame) => void;
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
  let finished = false;
  await openEventStream(session, copilotAskPath(body.screen.realm), {
    method: "POST",
    body,
    signal: options.signal,
    headersTimeoutMs: COPILOT_HEADERS_TIMEOUT_MS,
    onEvent: (event) => {
      if (event.event === "text") {
        const payload = safeJson(event.data) as { delta?: string } | null;
        if (typeof payload?.delta === "string") handlers.onText(payload.delta);
      } else if (event.event === "fill") {
        const payload = safeJson(event.data) as { items?: CopilotFillItem[] } | null;
        if (Array.isArray(payload?.items) && payload.items.length > 0) {
          handlers.onFill(payload.items);
        }
      } else if (event.event === "proposal") {
        // Guarded on the field that MATTERS. A frame with no usable `token` cannot be
        // confirmed, so a card rendered from it would offer a button that can only refuse.
        // The arguments a Confirm would run are inside the token's signature, not in
        // anything this browser could validate.
        const payload = safeJson(event.data) as CopilotProposal | null;
        if (typeof payload?.token === "string" && payload.token !== "") {
          handlers.onProposal(payload);
        }
      } else if (event.event === "action") {
        // Guarded on `tool`, which a renderer cannot do without. Every other field is the
        // server's own prose about something it has ALREADY done.
        const payload = safeJson(event.data) as CopilotAction | null;
        if (typeof payload?.tool === "string" && payload.tool !== "") {
          handlers.onAction(payload);
        }
      } else if (event.event === "navigate") {
        // Guarded on `route`. The route is a template and is NOT validated here: turning it
        // into a path this console has is `navigate.ts`'s job, at the moment of the move.
        const payload = safeJson(event.data) as CopilotNavigation | null;
        if (typeof payload?.route === "string" && payload.route !== "") {
          handlers.onNavigate(payload);
        }
      } else if (event.event === "job") {
        // Guarded on `job_id`, without which there is nothing to follow.
        const payload = safeJson(event.data) as CopilotJobFrame | null;
        if (typeof payload?.job_id === "string" && payload.job_id !== "") {
          handlers.onJob?.(payload);
        }
      } else if (event.event === "step") {
        // Guarded on `id`, which pairs the terminal frame with its own `running` one.
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
        // fact; losing a disclosure sentence and a meter flag is a far smaller harm than
        // telling a person that a finished answer was cut off.
        finished = true;
        handlers.onDone({
          disclosure: payload?.disclosure ?? null,
          metered: payload?.metered === true,
        });
      } else if (event.event === "error") {
        // A problem+json body delivered INSIDE a 200 stream, because the status line was
        // already sent. Thrown from here, it propagates unchanged out of
        // `openEventStream`, which releases the reader. An `error` frame that does not
        // parse is dropped; the stream then ends without `done` and is reported below.
        const problem = safeJson(event.data);
        if (problem !== null) throw new ApiProblem(200, problem);
      }
    },
  });
  // A stream that ended without `done` — including a 200 with no body — was cut.
  if (!finished) throw new StreamDroppedProblem();
}
