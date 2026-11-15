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
 * "Start again" whose delete is refused shows the refusal with a Try again. That button
 * must send the delete again: Start again forgets the last question, so a Try again that
 * re-asks it has nothing to send and does nothing.
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
    <CopilotPanel session={SESSION} holder={holder} realm="client" labelledBy="t" onClose={() => undefined} />
  );
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("Try again after Start again was refused", () => {
  it("SENDS THE DELETE AGAIN rather than doing nothing", async () => {
    let deletes = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input).replace(API_BASE, "");
        if (path.startsWith("/v1/copilot/conversation")) {
          if (init?.method === "DELETE") {
            deletes += 1;
            if (deletes === 1) {
              return json(
                {
                  type: "https://calevate.tech/problems/unavailable",
                  title: "Unavailable",
                  detail: "Not now.",
                  kind: "transient",
                  retryable: true,
                },
                503,
              );
            }
            return json({ cleared: 2 });
          }
          return json({
            turns: [
              {
                id: "0198f000-0000-7000-8000-000000000001",
                role: "user",
                content: "what about the scan",
                screen_route: "/c/[slug]/leads",
                said_at: "2026-09-05T08:00:00+00:00",
              },
              {
                id: "0198f000-0000-7000-8000-000000000002",
                role: "assistant",
                content: "Noted.",
                screen_route: "/c/[slug]/leads",
                said_at: "2026-09-05T08:00:01+00:00",
              },
            ],
            has_more: false,
          });
        }
        return json({});
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrap = (node: ReactNode) => <QueryClientProvider client={client}>{node}</QueryClientProvider>;
    await act(async () => {
      render(
        wrap(
          <>
            <Screen />
            <PanelMount />
          </>,
        ),
      );
    });
    await waitFor(() => expect(screen.getByText("what about the scan")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Forget this conversation and start again" }));
    });
    await waitFor(() => expect(screen.getByText("Not now.")).toBeTruthy());
    expect(deletes).toBe(1);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    });
    await waitFor(() => expect(deletes).toBe(2));
    await waitFor(() => expect(screen.queryByText("Not now.")).toBeNull());
  });
});
