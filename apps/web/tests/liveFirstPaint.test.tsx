import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, apiRequest, type Session } from "@/lib/api/client";
import { useLiveUpdates } from "@/lib/live/useLiveUpdates";

/**
 * The live stream's `ready` and a page's first reads (D-774, D-787).
 *
 * The stream opens in the same render as the screen's reads, so `ready` arrives just after
 * them. Refetching every live family on it sent each of those reads twice on every page
 * load. These tests hold the rule: what was read after the stream opened is not read again;
 * what was read before it — a reconnect after a drop — is.
 */

const SESSION: Session = { orgSlug: "acme" };
const READY = 'event: ready\ndata: {"heartbeat_s":20,"max_age_s":1800}\n\n';

function fakeApi() {
  const encoder = new TextEncoder();
  const server = {
    reads: 0,
    streams: new Set<ReadableStreamDefaultController<Uint8Array>>(),
    /** Hold the stream's `ready` until the test sends it. */
    sendReady() {
      for (const stream of server.streams) stream.enqueue(encoder.encode(READY));
    },
    dropStreams() {
      for (const stream of server.streams) stream.close();
      server.streams.clear();
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      if (path === "/v1/live") {
        let mine: ReadableStreamDefaultController<Uint8Array> | null = null;
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            mine = controller;
            server.streams.add(controller);
          },
          cancel() {
            if (mine !== null) server.streams.delete(mine);
          },
        });
        init?.signal?.addEventListener("abort", () => {
          if (mine !== null) server.streams.delete(mine);
        });
        return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
      }
      if (path === "/v1/dashboard") {
        server.reads += 1;
        return Response.json({ calls_today: server.reads });
      }
      return new Response(null, { status: 404 });
    }),
  );
  return server;
}

function Screen() {
  useLiveUpdates(SESSION, "/v1/live");
  const dashboard = useQuery({
    queryKey: ["dashboard", SESSION.orgSlug],
    queryFn: () => apiRequest<{ calls_today: number }>(SESSION, "/v1/dashboard"),
  });
  return <p>{dashboard.data ? `read ${dashboard.data.calls_today}` : "loading"}</p>;
}

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <Screen />
      </QueryClientProvider>,
    );
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the live stream on a page load", () => {
  it("does not read the screen a second time when the stream becomes ready", async () => {
    const server = fakeApi();
    await mount();
    await waitFor(() => expect(server.reads).toBe(1));
    await waitFor(() => expect(server.streams.size).toBe(1));

    await act(async () => server.sendReady());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(server.reads).toBe(1);
  });

  it("reads again after a reconnect, because the old read predates the new stream", async () => {
    const server = fakeApi();
    await mount();
    await waitFor(() => expect(server.streams.size).toBe(1));
    await act(async () => server.sendReady());
    await waitFor(() => expect(server.reads).toBe(1));

    // The drop itself refetches (polling takes over); the reopened stream's `ready` then
    // refetches what was read before it opened.
    await act(async () => server.dropStreams());
    await waitFor(() => expect(server.reads).toBe(2));
    await waitFor(() => expect(server.streams.size).toBe(1), { timeout: 3_000 });
    await act(async () => server.sendReady());
    await waitFor(() => expect(server.reads).toBe(3));
  });
});
