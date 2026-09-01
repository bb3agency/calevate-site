import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "@/lib/api/client";
import { createSseParser } from "@/lib/copilot/sse";
import {
  ADMIN_COPILOT_ASK_PATH,
  COPILOT_ASK_PATH,
  StreamDroppedProblem,
  askCopilot,
  type CopilotAskBody,
} from "@/lib/copilot/stream";
import type {
  CopilotAction,
  CopilotFillItem,
  CopilotProposal,
  CopilotStep,
} from "@/lib/copilot/types";

/**
 * The transport half of the screen assistant.
 *
 * The framing is OURS — `EventSource` cannot POST a body, so `fetch` + a `ReadableStream`
 * is the only shape available and the record splitting is hand-written (see `sse.ts`).
 * Hand-written framing is exactly the code that passes on a stream the test author
 * happened to chunk conveniently, so the split-mid-event case below is the point of this
 * file rather than an extra.
 */

const BODY: CopilotAskBody = {
  screen: {
    route: "/c/acme/agents/new",
    title: "Build an agent",
    realm: "client",
  },
  question: "what should I call it?",
  fields: [],
  facts: [],
  history: [],
};

const SESSION = { orgSlug: "acme" };

/** A `Response` whose body arrives in exactly these chunks, in this order. */
function streamOf(chunks: string[], { status = 200 } = {}): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, {
    status,
    headers: { "content-type": "text/event-stream" },
  });
}

function handlers() {
  const text: string[] = [];
  const fills: CopilotFillItem[][] = [];
  const done: { disclosure: string | null; metered: boolean }[] = [];
  const proposals: CopilotProposal[] = [];
  const actions: CopilotAction[] = [];
  const steps: CopilotStep[] = [];
  return {
    text,
    fills,
    done,
    proposals,
    actions,
    steps,
    onText: (delta: string) => text.push(delta),
    onFill: (items: CopilotFillItem[]) => fills.push(items),
    onProposal: (proposal: CopilotProposal) => proposals.push(proposal),
    onAction: (action: CopilotAction) => actions.push(action),
    onStep: (step: CopilotStep) => steps.push(step),
    onDone: (payload: { disclosure: string | null; metered: boolean }) =>
      done.push(payload),
  };
}

describe("the SSE parser", () => {
  it("emits nothing until a record is terminated by a blank line", () => {
    const parser = createSseParser();
    expect(parser.push('event: text\ndata: {"delta":"hi"}\n')).toEqual([]);
    expect(parser.push("\n")).toEqual([
      { event: "text", data: '{"delta":"hi"}' },
    ]);
  });

  it("REASSEMBLES AN EVENT SPLIT ACROSS CHUNK BOUNDARIES", () => {
    // The split is inside a JSON string value — the byte position a network chunk is
    // most likely to land on and the one a naive per-chunk parser mangles silently.
    const parser = createSseParser();
    expect(
      parser.push('event: fill\ndata: {"items":[{"field_id":"new-ag'),
    ).toEqual([]);
    expect(parser.push('ent-name","value":"Front desk"}]}\n\n')).toEqual([
      {
        event: "fill",
        data: '{"items":[{"field_id":"new-agent-name","value":"Front desk"}]}',
      },
    ]);
  });

  it("strips one space after the colon, joins multi-line data, and drops comments", () => {
    const parser = createSseParser();
    expect(
      parser.push(": keep-alive\n\nevent:text\ndata:one\ndata: two\n\n"),
    ).toEqual([{ event: "text", data: "one\ntwo" }]);
  });

  it("handles CRLF framing", () => {
    const parser = createSseParser();
    expect(parser.push("event: done\r\ndata: {}\r\n\r\n")).toEqual([
      { event: "done", data: "{}" },
    ]);
  });
});

describe("askCopilot", () => {
  it("asks the realm's own endpoint, because the two have different payers", async () => {
    /**
     * D-499. The client assistant spends the ACCOUNT'S AI allowance; the admin one spends
     * the platform's own ledger, and an operator never spends a client's. They are two
     * endpoints for that reason and not for tidiness — `/v1/copilot/ask` resolves an admin
     * identity only when an impersonation header is present, so an operator on a console
     * screen would be answered with a 401 rather than anything they could act on.
     *
     * FAILS IF: somebody collapses the two paths, or derives the path from the pathname
     * rather than from the realm the dock was mounted with.
     */
    const fetchMock = vi.fn(async () =>
      streamOf(['event: done\ndata: {"disclosure":null,"metered":false}\n\n']),
    );
    vi.stubGlobal("fetch", fetchMock);
    await askCopilot(SESSION, BODY, handlers());
    await askCopilot(
      SESSION,
      { ...BODY, screen: { ...BODY.screen, realm: "admin" } },
      handlers(),
    );
    const asked = fetchMock.mock.calls.map(([url]) => String(url));
    expect(asked[0].endsWith(COPILOT_ASK_PATH)).toBe(true);
    expect(asked[1].endsWith(ADMIN_COPILOT_ASK_PATH)).toBe(true);
    expect(COPILOT_ASK_PATH).not.toBe(ADMIN_COPILOT_ASK_PATH);
  });

  it("drives text, fill and done off one stream", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamOf([
          'event: text\ndata: {"delta":"Sure"}\n\n',
          'event: text\ndata: {"delta":", done."}\n\n',
          'event: fill\ndata: {"items":[{"field_id":"a","value":"1"}]}\n\n',
          'event: done\ndata: {"disclosure":"Answered by AI.","metered":true}\n\n',
        ]),
      ),
    );
    const sink = handlers();
    await askCopilot(SESSION, BODY, sink);
    expect(sink.text.join("")).toBe("Sure, done.");
    expect(sink.fills).toEqual([[{ field_id: "a", value: "1" }]]);
    expect(sink.done).toEqual([
      { disclosure: "Answered by AI.", metered: true },
    ]);
  });

  it("REJECTS WITH A RENDERABLE PROBLEM WHEN THE STREAM DROPS BEFORE `done`", async () => {
    // No reconnect, by design: the request is metered and can fill fields, so replaying
    // it could charge twice and re-apply a batch over an edit made in between.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => streamOf(['event: text\ndata: {"delta":"half an ans'])),
    );
    const sink = handlers();
    const failure = await askCopilot(SESSION, BODY, sink).catch(
      (cause: unknown) => cause,
    );
    expect(failure).toBeInstanceOf(StreamDroppedProblem);
    expect((failure as ApiProblem).retryable).toBe(true);
    // Everything that DID arrive was delivered before the failure — the panel keeps it.
    expect(sink.done).toEqual([]);
  });

  it("turns a non-2xx into the same ApiProblem every screen renders", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ type: "urn:x/ai_quota_exceeded", detail: "no." }),
            {
              status: 402,
              headers: { "content-type": "application/problem+json" },
            },
          ),
      ),
    );
    const failure = await askCopilot(SESSION, BODY, handlers()).catch(
      (cause: unknown) => cause,
    );
    expect(failure).toBeInstanceOf(ApiProblem);
    expect((failure as ApiProblem).code).toBe("ai_quota_exceeded");
  });

  it("turns an `error` event inside a 200 stream into the same problem class", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamOf([
          'event: text\ndata: {"delta":"…"}\n\n',
          'event: error\ndata: {"type":"urn:x/ai_quota_exceeded","detail":"ceiling"}\n\n',
        ]),
      ),
    );
    const failure = await askCopilot(SESSION, BODY, handlers()).catch(
      (cause: unknown) => cause,
    );
    expect((failure as ApiProblem).code).toBe("ai_quota_exceeded");
  });

  it("sends the org header and the credential, and asks for an event stream", async () => {
    let init: RequestInit = {};
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, request?: RequestInit) => {
        init = request ?? {};
        return streamOf(['event: done\ndata: {"metered":false}\n\n']);
      }),
    );
    await askCopilot(
      { orgSlug: "acme", token: () => "dev:client:u1" },
      BODY,
      handlers(),
    );
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Org-Slug"]).toBe("acme");
    expect(headers["Authorization"]).toBe("Bearer dev:client:u1");
    expect(headers["Accept"]).toBe("text/event-stream");
    // The deployed credential is the HttpOnly cookie; the API is a different origin.
    expect(init.credentials).toBe("include");
  });
});

describe("the proposal frame", () => {
  const FRAME = {
    token: "eyJ.signed.zzz",
    tool: "dnc_add",
    title: "Stop calling this lead",
    summary:
      "Add this lead's number to your do-not-call list. Not suppressed right now. " +
      "Calls already queued to it are pulled back as well. Nothing changes until you confirm.",
    object_type: "lead",
    object_id: "0192f0aa-0000-7000-8000-00000000l001",
    current: "Not suppressed",
    proposed: "On your do-not-call list",
    cost: null,
    reversal:
      "You can take the number off your do-not-call list from the Do not call screen. " +
      "Calls it pulled out of the queue are not put back.",
    expires_at: "2099-01-01T00:00:05Z",
  };

  it("arrives whole, unedited, even when the chunk boundary falls inside it", async () => {
    // Split mid-JSON, which is the ordinary case on a real `ReadableStream` and the
    // reason the parser buffers across pushes.
    const frame = `event: proposal\ndata: ${JSON.stringify(FRAME)}\n\n`;
    const cut = frame.indexOf('"summary"') + 12;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamOf([
          frame.slice(0, cut),
          frame.slice(cut),
          'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
        ]),
      ),
    );
    const sink = handlers();
    await askCopilot(SESSION, BODY, sink);
    // Every field, verbatim: the browser edits none of them, because the token's
    // signature binds what the sentences describe.
    expect(sink.proposals).toEqual([FRAME]);
  });

  it("IGNORES a frame with no usable token rather than offering a dead button", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamOf([
          `event: proposal\ndata: ${JSON.stringify({ ...FRAME, token: "" })}\n\n`,
          'event: done\ndata: {"metered":false}\n\n',
        ]),
      ),
    );
    const sink = handlers();
    await askCopilot(SESSION, BODY, sink);
    expect(sink.proposals).toEqual([]);
  });
});

describe("the action frame — a receipt, not an offer", () => {
  const ACTION = {
    tool: "agent_create",
    title: "Create a draft agent",
    detail:
      "“Raghava outbound” exists as a draft. It has an AI disclosure and a recording " +
      "notice already written for it.",
    object_type: "agent",
    object_id: "0192f0aa-0000-7000-8000-00000000a001",
    applied: true,
    reversal:
      "A draft reaches no caller. You can rename it, or archive it, from the Agents screen.",
    where: "under Agents in your dashboard",
  };

  it("REACHES A DIFFERENT HANDLER FROM A PROPOSAL, because it is a different promise", async () => {
    // The distinction this test exists for: a proposal has a Confirm button and nothing
    // behind it; an action has already written to the database. One handler taking both
    // is the seam where a receipt gets rendered as an offer.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamOf([
          `event: action\ndata: ${JSON.stringify(ACTION)}\n\n`,
          'event: done\ndata: {"metered":true}\n\n',
        ]),
      ),
    );
    const sink = handlers();
    await askCopilot(SESSION, BODY, sink);
    expect(sink.actions).toEqual([ACTION]);
    expect(sink.proposals).toEqual([]);
  });

  it("ignores a frame with no tool rather than rendering a receipt for nothing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamOf([
          `event: action\ndata: ${JSON.stringify({ ...ACTION, tool: "" })}\n\n`,
          'event: done\ndata: {"metered":false}\n\n',
        ]),
      ),
    );
    const sink = handlers();
    await askCopilot(SESSION, BODY, sink);
    expect(sink.actions).toEqual([]);
  });
});

describe("the step frame", () => {
  it("delivers both frames of one call, in order, sharing an id", async () => {
    // TWO FRAMES, ONE CALL. The consumer upserts on `id`; this level just has to hand
    // both over in the order they arrived, with `elapsed_ms` only on the terminal one.
    const running = {
      id: "r1",
      tool: "leads_search",
      status: "running",
      args: '{"status":"hot"}',
      detail: null,
      elapsed_ms: null,
    };
    const finished = {
      ...running,
      status: "done",
      detail: "12 leads, 3 hot.",
      elapsed_ms: 84,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamOf([
          `event: step\ndata: ${JSON.stringify(running)}\n\n`,
          `event: step\ndata: ${JSON.stringify(finished)}\n\n`,
          'event: done\ndata: {"metered":true}\n\n',
        ]),
      ),
    );
    const sink = handlers();
    await askCopilot(SESSION, BODY, sink);
    expect(sink.steps).toEqual([running, finished]);
  });

  it("IGNORES a frame with no id, which could only ever draw a second row for one call", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamOf([
          'event: step\ndata: {"id":"","tool":"leads_search","status":"running","args":"","detail":null,"elapsed_ms":null}\n\n',
          'event: done\ndata: {"metered":false}\n\n',
        ]),
      ),
    );
    const sink = handlers();
    await askCopilot(SESSION, BODY, sink);
    expect(sink.steps).toEqual([]);
  });
});
