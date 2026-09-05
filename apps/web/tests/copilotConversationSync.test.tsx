import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { API_BASE, type Session } from "@/lib/api/client";
import { useConversation } from "@/lib/copilot/conversation";
import { useCopilotSurface, useCopilotSurfaceHolder } from "@/lib/copilot/registry";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

/**
 * MULTI-DEVICE, THE FOUNDER'S ANSWER (D-541): *refresh when you return to the tab*.
 *
 * Not live push. What has to be true is three things, and each is one test here: coming
 * back to the tab shows what the other device said; a refetch NEVER lands while an answer
 * is streaming, because it would replace the list with a page taken before the question
 * was asked and the person would watch their own message vanish; and a history that fails
 * to load says so rather than showing an empty panel, which reads as "it forgot".
 *
 * The sync is `refetchOnWindowFocus`, which is this console's default (`app/providers.tsx`
 * sets no other) rather than a listener of our own — the point of using the idiom is that
 * the guard is one option on one query and cannot be half-applied by a second caller.
 */

const SESSION: Session = { orgSlug: "acme" };

function Screen() {
  useCopilotSurface({
    route: "/c/[slug]/leads",
    title: "Leads",
    realm: "client",
    fields: [],
    apply: () => undefined,
  });
  return <div id="main-content" tabIndex={-1} />;
}

function PanelMount() {
  const holder = useCopilotSurfaceHolder();
  if (holder === null) return null;
  return (
    <CopilotPanel
      session={SESSION}
      holder={holder}
      realm="client"
      labelledBy="copilot-title"
      onClose={() => undefined}
    />
  );
}

function withQuery(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

function wrapper({ children }: { children: ReactNode }) {
  return withQuery(children);
}

/** A conversation whose contents can change between reads — a second device talking. */
function stubGrowingConversation(pages: { role: string; content: string }[][]) {
  let read = 0;
  const gets: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      if (path.startsWith("/v1/copilot/conversation") && (init?.method ?? "GET") === "GET") {
        gets.push(path);
        const turns = pages[Math.min(read, pages.length - 1)];
        read += 1;
        return new Response(
          JSON.stringify({
            turns: turns.map((turn, index) => ({
              id: `0198f000-0000-7000-8000-00000000000${index}`,
              role: turn.role,
              content: turn.content,
              screen_route: "/c/[slug]/leads",
              said_at: "2026-09-05T08:00:00+00:00",
            })),
            has_more: false,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  return gets;
}

/** What the browser does when a tab is looked at again. */
async function returnToTheTab() {
  await act(async () => {
    window.dispatchEvent(new Event("visibilitychange"));
    await Promise.resolve();
  });
}

describe("coming back to the tab", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("SHOWS WHAT THE OTHER DEVICE SAID — the whole of the multi-device answer", async () => {
    stubGrowingConversation([
      [{ role: "user", content: "how many leads came in today" }],
      [
        { role: "user", content: "how many leads came in today" },
        { role: "assistant", content: "Eleven." },
        { role: "user", content: "and on the phone I asked about refunds" },
      ],
    ]);

    await act(async () => {
      render(
        withQuery(
          <>
            <Screen />
            <PanelMount />
          </>,
        ),
      );
    });
    await waitFor(() => {
      expect(screen.getByText("how many leads came in today")).toBeTruthy();
    });
    expect(screen.queryByText("and on the phone I asked about refunds")).toBeNull();

    await returnToTheTab();

    await waitFor(() => {
      expect(screen.getByText("and on the phone I asked about refunds")).toBeTruthy();
    });
  });

  it("DOES NOT REFETCH WHILE AN ANSWER IS STREAMING — the one rule the sync has", async () => {
    const gets = stubGrowingConversation([[{ role: "user", content: "anything" }]]);
    let streaming = true;

    const { result } = renderHook(
      () => useConversation(SESSION, "client", () => streaming),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(gets.length).toBe(1);

    // Focus, mid-stream: nothing may be fetched, or the turns the panel has appended to
    // this cache are replaced by a page taken before the question was asked.
    await returnToTheTab();
    await returnToTheTab();
    expect(gets.length).toBe(1);

    // …and the moment the stream ends, focus works again. The guard is a PREDICATE read at
    // focus time, not a flag captured at render, so nothing has to re-render to release it.
    streaming = false;
    await returnToTheTab();
    await waitFor(() => expect(gets.length).toBe(2));
  });

  it("SAYS THE HISTORY DID NOT LOAD rather than showing an empty panel", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input).replace(API_BASE, "");
        if (path.startsWith("/v1/copilot/conversation")) {
          return new Response(JSON.stringify({ title: "no" }), {
            status: 503,
            headers: { "content-type": "application/problem+json" },
          });
        }
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    await act(async () => {
      render(
        withQuery(
          <>
            <Screen />
            <PanelMount />
          </>,
        ),
      );
    });

    await waitFor(() => {
      expect(screen.getByText(/earlier messages could not be loaded/i)).toBeTruthy();
    });
  });
});


/** A `text/event-stream` response with these frames — `copilot.test.tsx`'s own shape. */
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

/**
 * An assistant that answers one question, and a conversation the server reads back from
 * `pages` — one entry per GET, so a test decides whether the exchange it just had was
 * STORED (the next page contains it) or not (the next page does not).
 */
function stubAskAndConversation(
  answer: string,
  pages: { id: string; role: string; content: string }[][],
) {
  let read = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      if (path.startsWith("/v1/copilot/ask")) {
        return sse([
          `event: text\ndata: ${JSON.stringify({ delta: answer })}\n\n`,
          'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
        ]);
      }
      if (path.startsWith("/v1/copilot/conversation")) {
        const turns = pages[Math.min(read, pages.length - 1)];
        read += 1;
        return new Response(
          JSON.stringify({
            turns: turns.map((turn) => ({
              ...turn,
              screen_route: "/c/[slug]/leads",
              said_at: "2026-09-05T08:00:00+00:00",
            })),
            has_more: false,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

async function askOnScreen(question: string) {
  fireEvent.change(screen.getByLabelText("Your question about this screen"), {
    target: { value: question },
  });
  await act(async () => {
    fireEvent.submit(screen.getByRole("button", { name: "Ask" }).closest("form")!);
  });
}

describe("the refresh after an exchange", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("KEEPS AN ANSWER THE SERVER DID NOT STORE — a refusal is not wiped by its own refresh", async () => {
    // `copilot/routes.py::_record` returns before writing a turn when the run SPENT
    // nothing, so a selector refusal is answered and deliberately never stored. The
    // refresh fired after the exchange therefore comes back without it, and the panel must
    // still be showing it: an answer that vanishes a second after it arrives is worse than
    // one that was never persisted.
    stubAskAndConversation("I cannot see this screen.", [[], []]);

    await act(async () => {
      render(
        withQuery(
          <>
            <Screen />
            <PanelMount />
          </>,
        ),
      );
    });
    await askOnScreen("set the plan to growth");
    await waitFor(() => {
      expect(screen.getByText("I cannot see this screen.")).toBeTruthy();
    });
    // …and it survives the sync, and a focus refresh after it.
    await returnToTheTab();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getByText("set the plan to growth")).toBeTruthy();
    expect(screen.getByText("I cannot see this screen.")).toBeTruthy();
  });

  it("SHOWS A STORED EXCHANGE ONCE — the server's copy replaces the local one, never doubles it", async () => {
    // The other direction, and the one a naive merge gets wrong: the same exchange is now
    // in the local list AND in the page the refresh brings back. Two bubbles saying the
    // same thing is the failure that never heals, which is why the reconciliation counts
    // what the server has LEARNED since the last page rather than matching text.
    stubAskAndConversation("Eleven.", [
      [],
      [
        { id: "0198f000-0000-7000-8000-000000000001", role: "user", content: "how many leads" },
        { id: "0198f000-0000-7000-8000-000000000002", role: "assistant", content: "Eleven." },
      ],
    ]);

    await act(async () => {
      render(
        withQuery(
          <>
            <Screen />
            <PanelMount />
          </>,
        ),
      );
    });
    await askOnScreen("how many leads");
    await waitFor(() => {
      expect(screen.getAllByText("Eleven.").length).toBeGreaterThan(0);
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getAllByText("Eleven.").length).toBe(1);
    expect(screen.getAllByText("how many leads").length).toBe(1);
  });
});
