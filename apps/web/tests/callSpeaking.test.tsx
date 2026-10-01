import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { type CallSpeaking, callSpeakingPath, parseSpeakingFrame, useCallSpeaking } from "@/lib/api/callSpeaking";
import type { Session } from "@/lib/api/client";

/**
 * `useCallSpeaking` — the live "who is speaking" stream (D-656).
 *
 * The properties a component relies on: it renders `speaker` as frames arrive, it stops for
 * good when the call ends or the call is refused, it reconnects when a stream merely
 * closes, it makes no request when disabled, and it lets go of the request on unmount.
 */

const SESSION: Session = { orgSlug: "acme" };
const CALL = "0190a7c4-0000-7000-8000-000000000001";

function frame(speaker: string | null, live = true): string {
  return `data: ${JSON.stringify({ speaker, live, since: null })}\n\n`;
}

/** A streamed `Response` whose chunks the test pushes one at a time. */
function controlledStream(): { response: Response; push: (chunk: string) => void; close: () => void } {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
    push: (chunk) => controller.enqueue(encoder.encode(chunk)),
    close: () => controller.close(),
  };
}

function finished(chunks: string[]): Response {
  const stream = controlledStream();
  for (const chunk of chunks) stream.push(chunk);
  stream.close();
  return stream.response;
}

describe("parseSpeakingFrame", () => {
  it("reads the three fields and drops anything that is not a frame", () => {
    expect(parseSpeakingFrame('{"speaker":"agent","live":true,"since":"2026-10-01T10:00:00Z"}')).toEqual({
      speaker: "agent",
      live: true,
      since: "2026-10-01T10:00:00Z",
    });
    expect(parseSpeakingFrame('{"speaker":null,"live":false}')).toEqual({ speaker: null, live: false, since: null });
    expect(parseSpeakingFrame('{"speaker":"robot","live":true}')).toBeNull();
    expect(parseSpeakingFrame('{"speaker":"caller"}')).toBeNull();
    expect(parseSpeakingFrame("[1]")).toBeNull();
    expect(parseSpeakingFrame("null")).toBeNull();
    expect(parseSpeakingFrame("not json")).toBeNull();
  });
});

describe("useCallSpeaking", () => {
  it("follows the frames and stops for good when the call ends", async () => {
    const stream = controlledStream();
    const fetchMock = vi.fn().mockResolvedValue(stream.response);
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useCallSpeaking(SESSION, CALL));
    expect(result.current).toEqual<CallSpeaking>({ speaker: null, live: false });

    act(() => stream.push(frame(null)));
    await waitFor(() => expect(result.current).toEqual({ speaker: null, live: true }));
    // Split mid-frame: the parser must hold the half until the rest arrives.
    const caller = frame("caller");
    act(() => stream.push(caller.slice(0, 9)));
    act(() => stream.push(caller.slice(9)));
    await waitFor(() => expect(result.current.speaker).toBe("caller"));
    act(() => stream.push("event: other\ndata: {}\n\n" + "data: garbage\n\n" + frame("agent")));
    await waitFor(() => expect(result.current.speaker).toBe("agent"));
    act(() => {
      stream.push(frame(null, false));
      stream.close();
    });
    await waitFor(() => expect(result.current).toEqual({ speaker: null, live: false }));

    await new Promise((resolve) => setTimeout(resolve, 1_200));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith(callSpeakingPath(CALL))).toBe(true);
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-Org-Slug"]).toBe("acme");
    expect((init.headers as Record<string, string>)["Accept"]).toBe("text/event-stream");
  });

  it("reconnects when a stream closes while the call is still live", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(finished([frame("agent")]))
      .mockResolvedValueOnce(finished([frame("caller"), frame(null, false)]));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useCallSpeaking(SESSION, CALL));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), { timeout: 4_000 });
    await waitFor(() => expect(result.current).toEqual({ speaker: null, live: false }));
  });

  it("reconnects after a transport failure", async () => {
    const open = controlledStream();
    open.push(frame("caller"));
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(open.response);
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useCallSpeaking(SESSION, CALL));
    await waitFor(() => expect(result.current.speaker).toBe("caller"), { timeout: 4_000 });
  });

  it("gives up on a call it may not see", async () => {
    const problem = { type: "https://calevate.tech/problems/not_found", title: "Call not found", status: 404 };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(problem), { status: 404, headers: { "content-type": "application/problem+json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useCallSpeaking(SESSION, CALL));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 1_200));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current).toEqual({ speaker: null, live: false });
  });

  it("makes no request when disabled", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useCallSpeaking(SESSION, CALL, { enabled: false }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current).toEqual({ speaker: null, live: false });
  });

  it("aborts the request on unmount", async () => {
    const stream = controlledStream();
    const fetchMock = vi.fn().mockResolvedValue(stream.response);
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = renderHook(() => useCallSpeaking(SESSION, CALL));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    unmount();
    expect(init.signal?.aborted).toBe(true);
  });
});
