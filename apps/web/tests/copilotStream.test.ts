import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "@/lib/api/client";
import { createSseParser } from "@/lib/copilot/sse";
import { StreamDroppedProblem, askCopilot, type CopilotAskBody } from "@/lib/copilot/stream";
import type { CopilotFillItem } from "@/lib/copilot/types";

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
  screen: { route: "/c/acme/agents/new", title: "Build an agent", realm: "client" },
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
  return {
    text,
    fills,
    done,
    onText: (delta: string) => text.push(delta),
    onFill: (items: CopilotFillItem[]) => fills.push(items),
    onDone: (payload: { disclosure: string | null; metered: boolean }) => done.push(payload),
  };
}

describe("the SSE parser", () => {
  it("emits nothing until a record is terminated by a blank line", () => {
    const parser = createSseParser();
    expect(parser.push('event: text\ndata: {"delta":"hi"}\n')).toEqual([]);
    expect(parser.push("\n")).toEqual([{ event: "text", data: '{"delta":"hi"}' }]);
  });

  it("REASSEMBLES AN EVENT SPLIT ACROSS CHUNK BOUNDARIES", () => {
    // The split is inside a JSON string value — the byte position a network chunk is
    // most likely to land on and the one a naive per-chunk parser mangles silently.
    const parser = createSseParser();
    expect(parser.push('event: fill\ndata: {"items":[{"field_id":"new-ag')).toEqual([]);
    expect(parser.push('ent-name","value":"Front desk"}]}\n\n')).toEqual([
      { event: "fill", data: '{"items":[{"field_id":"new-agent-name","value":"Front desk"}]}' },
    ]);
  });

  it("strips one space after the colon, joins multi-line data, and drops comments", () => {
    const parser = createSseParser();
    expect(parser.push(": keep-alive\n\nevent:text\ndata:one\ndata: two\n\n")).toEqual([
      { event: "text", data: "one\ntwo" },
    ]);
  });

  it("handles CRLF framing", () => {
    const parser = createSseParser();
    expect(parser.push("event: done\r\ndata: {}\r\n\r\n")).toEqual([
      { event: "done", data: "{}" },
    ]);
  });
});

describe("askCopilot", () => {
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
    expect(sink.done).toEqual([{ disclosure: "Answered by AI.", metered: true }]);
  });

  it("REJECTS WITH A RENDERABLE PROBLEM WHEN THE STREAM DROPS BEFORE `done`", async () => {
    // No reconnect, by design: the request is metered and can fill fields, so replaying
    // it could charge twice and re-apply a batch over an edit made in between.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => streamOf(['event: text\ndata: {"delta":"half an ans'])),
    );
    const sink = handlers();
    const failure = await askCopilot(SESSION, BODY, sink).catch((cause: unknown) => cause);
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
          new Response(JSON.stringify({ type: "urn:x/ai_quota_exceeded", detail: "no." }), {
            status: 402,
            headers: { "content-type": "application/problem+json" },
          }),
      ),
    );
    const failure = await askCopilot(SESSION, BODY, handlers()).catch((cause: unknown) => cause);
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
    const failure = await askCopilot(SESSION, BODY, handlers()).catch((cause: unknown) => cause);
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
    await askCopilot({ orgSlug: "acme", token: () => "dev:client:u1" }, BODY, handlers());
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Org-Slug"]).toBe("acme");
    expect(headers["Authorization"]).toBe("Bearer dev:client:u1");
    expect(headers["Accept"]).toBe("text/event-stream");
    // The deployed credential is the HttpOnly cookie; the API is a different origin.
    expect(init.credentials).toBe("include");
  });
});
