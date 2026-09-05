import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { API_BASE, type Session } from "@/lib/api/client";
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
 * The DURABLE conversation (D-540): it is loaded when the panel opens, and "Start again"
 * ends it on the server rather than only on this device.
 *
 * The whole point of the change is that the panel is no longer the only place the chat
 * exists, so both tests here are about the WIRE — what the panel asks for on mount, and
 * what it sends when a person says forget it. A test that only checked the bubbles would
 * pass just as well against the state-only version this replaced.
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

/** Every request the panel makes, as `METHOD path`, plus what the GET answers with. */
function stubConversation(turns: { role: string; content: string }[]) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      calls.push(`${init?.method ?? "GET"} ${path}`);
      if (path.startsWith("/v1/copilot/conversation")) {
        if (init?.method === "DELETE") {
          return new Response(JSON.stringify({ cleared: turns.length }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
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
  return calls;
}

describe("the durable conversation", () => {
  it("IS LOADED WHEN THE PANEL OPENS — the chat survives a refresh, a navigation and a closed browser", async () => {
    const calls = stubConversation([
      { role: "user", content: "how many leads came in today" },
      { role: "assistant", content: "Eleven." },
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
    expect(screen.getByText("Eleven.")).toBeTruthy();
    // BOUNDED. A conversation is a list, and the panel asks for a page rather than all of
    // it — the server caps `limit` too, and this is the half that would rot silently if
    // somebody dropped the parameter.
    expect(calls.some((call) => call.includes("/v1/copilot/conversation?limit="))).toBe(true);
  });

  it("IS ENDED ON THE SERVER BY START AGAIN — not only on the device that clicked it", async () => {
    const calls = stubConversation([
      { role: "user", content: "what did we say about the scan" },
      { role: "assistant", content: "You asked me to note it." },
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
      expect(screen.getByText("what did we say about the scan")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Forget this conversation and start again" }),
      );
    });

    expect(screen.queryByText("what did we say about the scan")).toBeNull();
    expect(calls.some((call) => call === "DELETE /v1/copilot/conversation")).toBe(true);
  });

  it("OFFERS NOTHING TO FORGET WHEN THERE IS NOTHING", async () => {
    stubConversation([]);
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
      expect(
        screen.queryByRole("button", { name: "Forget this conversation and start again" }),
      ).toBeNull();
    });
  });
});
