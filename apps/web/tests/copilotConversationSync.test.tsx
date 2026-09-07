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
 * MULTI-DEVICE, THE FOUNDER'S ANSWER (D-542): *refresh when you return to the tab*.
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
    vi.fn(async (input: RequestInfo | URL) => {
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

/**
 * THE TRANSCRIPT IS KEYED BY IDENTITY, NOT BY POSITION.
 *
 * `turns` is `[...page, ...pending]` and the page loses turns from the FRONT: the stored
 * conversation is bounded, so a long one is trimmed between two reads. Under `key={index}`
 * that shift re-labels every bubble below it and React rebuilds each one — the DOM node a
 * person is mid-selection in is replaced, and the scroller's measurements are taken against
 * nodes that no longer exist.
 */
describe("the transcript's keys", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  /** Two reads of a conversation whose FIRST turn is trimmed away between them. */
  function stubTrimmedConversation() {
    const pages = [
      [
        { id: "0198f000-0000-7000-8000-0000000000a1", role: "user", content: "how many leads" },
        { id: "0198f000-0000-7000-8000-0000000000a2", role: "assistant", content: "Eleven." },
      ],
      [
        { id: "0198f000-0000-7000-8000-0000000000a2", role: "assistant", content: "Eleven." },
        { id: "0198f000-0000-7000-8000-0000000000a3", role: "user", content: "and refunds" },
      ],
    ];
    let read = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input).replace(API_BASE, "");
        if (path.startsWith("/v1/copilot/conversation") && (init?.method ?? "GET") === "GET") {
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

  it("KEEPS THE SAME DOM NODE for a turn that survived a page trim", async () => {
    stubTrimmedConversation();
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
    await waitFor(() => expect(screen.getByText("how many leads")).toBeTruthy());
    const before = screen.getByText("Eleven.");

    await returnToTheTab();
    await waitFor(() => expect(screen.getByText("and refunds")).toBeTruthy());
    // The first turn is gone, so "Eleven." has moved from position 1 to position 0.
    expect(screen.queryByText("how many leads")).toBeNull();

    // FAILS IF: the map keys on `index`. Position 0 held a `<p>` (the person's turn) and
    // now holds an answer, so React discards the node and builds a new one — this is a
    // DIFFERENT element with the same text, and everything anchored to the old one is lost.
    expect(screen.getByText("Eleven.")).toBe(before);
  });

  it("NEVER SENDS the client-only key, which the server has no row for", async () => {
    // `localKey` exists to give the panel a stable React key WITHOUT inventing a
    // server-facing `id` — the merge reconciles by counting against the server's own ids,
    // and a key we minted appearing on the wire would be this browser asserting a row.
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input).replace(API_BASE, "");
        if (path.startsWith("/v1/copilot/ask")) {
          bodies.push(typeof init?.body === "string" ? init.body : "");
          const encoder = new TextEncoder();
          return new Response(
            new ReadableStream<Uint8Array>({
              start(controller) {
                controller.enqueue(encoder.encode('event: text\ndata: {"delta":"Eleven."}\n\n'));
                controller.enqueue(encoder.encode('event: done\ndata: {"metered":true}\n\n'));
                controller.close();
              },
            }),
            { status: 200, headers: { "content-type": "text/event-stream" } },
          );
        }
        return new Response(JSON.stringify({ turns: [], has_more: false }), {
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
    const box = await screen.findByLabelText("Your question about this screen");
    for (const question of ["how many leads", "and refunds"]) {
      fireEvent.change(box, { target: { value: question } });
      await act(async () => {
        fireEvent.submit(screen.getByRole("button", { name: "Ask" }).closest("form")!);
      });
    }

    expect(bodies.length).toBe(2);
    // The second ask replays the first exchange as `history`, which is where a leaked
    // key would show up.
    expect(bodies[1]).toContain("how many leads");
    for (const body of bodies) {
      expect(body).not.toContain("localKey");
      expect(body).not.toContain("local-");
    }
  });
});
