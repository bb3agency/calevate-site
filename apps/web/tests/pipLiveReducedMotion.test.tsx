/**
 * Pip's live view under "reduce motion": no row slides in, no light sweeps across a label,
 * no mascot animation, no fading tail on the thinking. What it says is unchanged.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunHeader } from "@/components/copilot/RunHeader";
import { RunTimeline } from "@/components/copilot/RunTimeline";
import { ScriptDraftLive } from "@/components/scriptDraft/ScriptDraftLive";
import { API_BASE } from "@/lib/api/client";
import type { ThoughtEntry } from "@/lib/copilot/liveEvents";

const motion = vi.hoisted(() => ({ reduce: true }));
vi.mock("motion/react", async (original) => ({
  ...(await original<typeof import("motion/react")>()),
  useReducedMotion: () => motion.reduce,
}));

afterEach(() => vi.unstubAllGlobals());

const T0 = Date.parse("2026-11-24T10:00:00Z");
const thought: ThoughtEntry = { kind: "thought", id: "t", text: "List the campaigns first, then compare.", startedAt: T0, endedAt: null };
const running = { id: "s1", tool: "leads_search", status: "running" as const, args: "{}", label: "Searching your leads…" };

function timeline(reduced: boolean) {
  return render(
    <RunTimeline entries={[{ kind: "step", id: "s1", startedAt: T0 }, thought]} steps={[running]} now={T0} live reduced={reduced} />,
  );
}

describe("reduced motion", () => {
  it("draws the live thread without entrances, sweep or fading tail", () => {
    const { container } = timeline(true);
    expect(container.querySelector(".live-enter")).toBeNull();
    expect(container.querySelector(".text-shimmer")).toBeNull();
    expect(container.querySelector(".opacity-50")).toBeNull();
    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.getByTestId("thought-live").textContent).toBe(thought.text);
  });

  it("and with motion welcome, the same thread moves", () => {
    const { container } = timeline(false);
    expect(container.querySelector(".live-enter")).not.toBeNull();
    expect(container.querySelector(".text-shimmer")).not.toBeNull();
  });

  it("keeps the mascot still in the header", () => {
    const { container } = render(<RunHeader state="working" since={T0} now={T0} reduced onStop={() => {}} />);
    expect(container.querySelector(".pip-dot")).toBeNull();
  });

  it("writes a script draft's lines without entrances when the reader asked for less motion", async () => {
    const encoder = new TextEncoder();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input).replace(API_BASE, "");
        if (!path.endsWith("/script-draft/stream")) throw new Error(`unexpected request: ${path}`);
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(encoder.encode('event: phase\ndata: {"phase":"writing","detail":null}\n\n'));
              controller.enqueue(
                encoder.encode('event: line\ndata: {"path":"opening_line","label":"Opening line","text":"Namaste"}\n\n'),
              );
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }),
    );
    const client = new QueryClient();
    const { container } = render(
      <QueryClientProvider client={client}>
        <ScriptDraftLive session={{ orgSlug: "acme" }} holder={{ kind: "campaign", id: "c1" }} proposalId="p1" />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Namaste")).toBeTruthy();
    expect(container.querySelector(".live-enter")).toBeNull();
    expect(container.querySelector(".text-shimmer")).toBeNull();
  });
});
