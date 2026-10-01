import { describe, expect, it, vi } from "vitest";

import { ApiProblem, TimeoutProblem, TransportProblem, openEventStream, type Session } from "@/lib/api/client";

/**
 * `openEventStream` — the console's one SSE transport (D-656). The copilot's POST and the
 * call screen's GET both depend on these properties; their own suites cover the frames.
 */

const SESSION: Session = { orgSlug: "acme" };

function sse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

describe("openEventStream", () => {
  it("POSTs a JSON body with the identity headers and a correlation id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sse(["data: {}\n\n"]));
    vi.stubGlobal("fetch", fetchMock);
    const events: string[] = [];
    await openEventStream(SESSION, "/v1/copilot/ask", {
      method: "POST",
      body: { question: "hi" },
      onEvent: (event) => events.push(event.data),
    });
    expect(events).toEqual(["{}"]);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"question":"hi"}');
    expect(init.credentials).toBe("include");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["Accept"]).toBe("text/event-stream");
    expect(headers["X-Org-Slug"]).toBe("acme");
    expect(headers["X-Correlation-Id"]).toMatch(/^[0-9a-f]{32}$/);
  });

  it("a GET carries no body and no correlation id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sse([]));
    vi.stubGlobal("fetch", fetchMock);
    await openEventStream(SESSION, "/v1/calls/x/speaking", { onEvent: () => {} });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
    expect((init.headers as Record<string, string>)["X-Correlation-Id"]).toBeUndefined();
  });

  it("answers a missed header deadline with TimeoutProblem", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          }),
      ),
    );
    await expect(
      openEventStream(SESSION, "/v1/copilot/ask", { method: "POST", body: {}, headersTimeoutMs: 10, onEvent: () => {} }),
    ).rejects.toBeInstanceOf(TimeoutProblem);
  });

  it("hands back the caller's own abort reason, not a transport failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          }),
      ),
    );
    const controller = new AbortController();
    const pending = openEventStream(SESSION, "/x", { signal: controller.signal, onEvent: () => {} });
    const reason = new Error("stopped by the person");
    controller.abort(reason);
    await expect(pending).rejects.toBe(reason);
  });

  it("turns a browser failure into TransportProblem and a refusal into ApiProblem", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(openEventStream(SESSION, "/x", { onEvent: () => {} })).rejects.toBeInstanceOf(TransportProblem);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ title: "Not found", status: 404 }), {
          status: 404,
          headers: { "content-type": "application/problem+json" },
        }),
      ),
    );
    const refusal = await openEventStream(SESSION, "/x", { onEvent: () => {} }).catch((e: unknown) => e);
    expect(refusal).toBeInstanceOf(ApiProblem);
    expect((refusal as ApiProblem).status).toBe(404);
  });

  it("lets a handler's own throw through unchanged and cancels the body", async () => {
    const cancelled = vi.fn();
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode("data: 1\n\n"));
      },
      cancel: cancelled,
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    const thrown = new ApiProblem(200, { title: "inside the stream" });
    await expect(
      openEventStream(SESSION, "/x", {
        onEvent: () => {
          throw thrown;
        },
      }),
    ).rejects.toBe(thrown);
    await vi.waitFor(() => expect(cancelled).toHaveBeenCalled());
  });

  it("a 2xx with no body is a stream with no events", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 200 })));
    const onEvent = vi.fn();
    await openEventStream(SESSION, "/x", { onEvent });
    expect(onEvent).not.toHaveBeenCalled();
  });
});
