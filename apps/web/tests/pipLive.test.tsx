/**
 * Pip's live working view (founder, 24 Nov 2026): the "Working 9s" header with a Stop that
 * waits for the server, the Thinking row that folds to "Thought for Ns", the step thread
 * with durations and results, and the script draft that streams, shows its changes and
 * waits for Keep or Discard, the same in the panel and on the campaign page.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CampaignWorkspace } from "@/app/c/[slug]/campaigns/CampaignWorkspace";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { RunHeader } from "@/components/copilot/RunHeader";
import { RunTimeline } from "@/components/copilot/RunTimeline";
import { StepList } from "@/components/copilot/StepList";
import { StepRow } from "@/components/copilot/StepRow";
import { ScriptDiff, diffBlocks } from "@/components/scriptDraft/ScriptDiff";
import { ScriptDraftLive } from "@/components/scriptDraft/ScriptDraftLive";
import { ScriptDraftView } from "@/components/scriptDraft/ScriptDraftView";
import type { CampaignProposal } from "@/lib/api/campaignWorkspace";
import { API_BASE, type Session } from "@/lib/api/client";
import {
  CLOCK_SKEW_LIMIT_MS,
  IDLE_RUN,
  consoleHref,
  formatWorkTime,
  liveRunReducer,
  runClockStart,
  stepDuration,
  type LiveAction,
  type LiveRun,
  type ThoughtEntry,
} from "@/lib/copilot/liveEvents";
import { useCopilotSurface, useCopilotSurfaceHolder } from "@/lib/copilot/registry";
import type { CopilotStep } from "@/lib/copilot/types";
import { useNow } from "@/lib/copilot/useNow";
import {
  EMPTY_DRAFT_STREAM,
  draftStreamReducer,
  type DraftChange,
  type DraftStreamState,
} from "@/lib/scriptDraft/stream";

import { expectNoA11yViolations } from "./a11y";
import { FIXTURE_CAMPAIGN_ID, settingsFixture, workspaceFixture } from "./campaignFixtures";
import { noReply, renderClientPage } from "./harness";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
}));

const SESSION: Session = { orgSlug: "acme" };
const T0 = Date.parse("2026-11-24T10:00:00Z");

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function run(actions: LiveAction[], from: LiveRun = IDLE_RUN): LiveRun {
  return actions.reduce(liveRunReducer, from);
}

function step(over: Partial<CopilotStep> = {}): CopilotStep {
  return {
    id: "s1",
    tool: "campaigns_list",
    status: "done",
    args: "{}",
    detail: null,
    elapsed_ms: 2400,
    label: "Checked your campaigns",
    ...over,
  };
}

const RESULTS = {
  kind: "list" as const,
  items: [
    { title: "Diwali offer", subtitle: "Running · 240 contacts", href: "/c/acme/campaigns/c-1" },
    { title: "Plot visit reminder", subtitle: null, href: "javascript:alert(1)" },
  ],
  total: 6,
};

// ── The run's order ──────────────────────────────────────────────────────────────────

describe("the run's events, in order", () => {
  it("extends the open thought, opens a step after it, and starts a NEW thought after the step", () => {
    const state = run([
      { type: "ask" },
      { type: "run", frame: { run_id: "r1", started_at: new Date(T0).toISOString() }, now: T0 },
      { type: "thought", delta: "Looking at ", now: T0 + 100 },
      { type: "thought", delta: "the campaigns.", now: T0 + 400 },
      { type: "step", id: "s1", now: T0 + 1_500 },
      // The step's terminal frame: same id, no new row, no reorder.
      { type: "step", id: "s1", now: T0 + 2_000 },
      { type: "thought", delta: "Two are running.", now: T0 + 2_100 },
    ]);
    expect(state.runId).toBe("r1");
    expect(state.entries.map((entry) => entry.kind)).toEqual(["thought", "step", "thought"]);
    const [first, , second] = state.entries as [ThoughtEntry, unknown, ThoughtEntry];
    expect(first.text).toBe("Looking at the campaigns.");
    // The step closed the first thought at the moment it arrived.
    expect(first.endedAt).toBe(T0 + 1_500);
    expect(second.text).toBe("Two are running.");
    expect(second.endedAt).toBeNull();
  });

  it("closes the thinking when the answer starts, and when the run ends", () => {
    const thinking = run([{ type: "ask" }, { type: "thought", delta: "Plan.", now: T0 }]);
    const answered = liveRunReducer(thinking, { type: "text", now: T0 + 3_000 });
    expect((answered.entries[0] as ThoughtEntry).endedAt).toBe(T0 + 3_000);
    const stopped = liveRunReducer(thinking, { type: "end", stopped: true, now: T0 + 5_000 });
    expect(stopped.phase).toBe("stopped");
    expect((stopped.entries[0] as ThoughtEntry).endedAt).toBe(T0 + 5_000);
  });

  it("keeps a draft once, and carries it past the next question until it is settled", () => {
    const frame = { holder_kind: "campaign" as const, holder_id: "c1", proposal_id: "p1" };
    const started = run([{ type: "ask" }, { type: "draft", frame }, { type: "draft", frame }]);
    expect(started.drafts).toHaveLength(1);
    const nextQuestion = liveRunReducer(started, { type: "ask" });
    expect(nextQuestion.drafts.map((d) => d.proposal_id)).toEqual(["p1"]);
    const settled = liveRunReducer(nextQuestion, { type: "draftPhase", proposalId: "p1", phase: "ready", settled: true });
    expect(liveRunReducer(settled, { type: "ask" }).drafts).toEqual([]);
  });

  it("changes nothing when a draft reports the phase it already had", () => {
    const frame = { holder_kind: "campaign" as const, holder_id: "c1", proposal_id: "p1" };
    const once = run([{ type: "draft", frame }, { type: "draftPhase", proposalId: "p1", phase: "writing", settled: false }]);
    expect(liveRunReducer(once, { type: "draftPhase", proposalId: "p1", phase: "writing", settled: false })).toBe(once);
  });

  it("only moves to stopping from working", () => {
    expect(liveRunReducer(IDLE_RUN, { type: "stopping" })).toBe(IDLE_RUN);
    expect(run([{ type: "ask" }, { type: "stopping" }]).phase).toBe("stopping");
  });
});

// ── The timer ───────────────────────────────────────────────────────────────────────

describe("the timer", () => {
  it("says how long in the words a person uses", () => {
    expect(formatWorkTime(9_400)).toBe("9s");
    expect(formatWorkTime(64_000)).toBe("1m 4s");
    expect(formatWorkTime(120_000)).toBe("2m");
    expect(formatWorkTime(-5)).toBe("0s");
    expect(stepDuration(120)).toBe("<1s");
    expect(stepDuration(2_400)).toBe("2s");
    expect(stepDuration(null)).toBeNull();
  });

  it("counts from the run's started_at, unless the two clocks disagree too far", () => {
    expect(runClockStart(new Date(T0 - 2_000).toISOString(), T0)).toBe(T0 - 2_000);
    expect(runClockStart(new Date(T0 + 5_000).toISOString(), T0)).toBe(T0);
    expect(runClockStart(new Date(T0 - CLOCK_SKEW_LIMIT_MS - 1).toISOString(), T0)).toBe(T0);
    expect(runClockStart("not a time", T0)).toBe(T0);
  });

  it("ticks the header once a second while the run works", () => {
    vi.useFakeTimers();
    vi.setSystemTime(T0 + 9_000);
    function Ticking() {
      const now = useNow(true);
      return <RunHeader state="working" since={T0} now={now} reduced onStop={() => {}} />;
    }
    render(<Ticking />);
    expect(screen.getByRole("heading").textContent).toBe("Working 9s");
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(screen.getByRole("heading").textContent).toBe("Working 10s");
  });

  it("says Waiting for you, with no Stop, when the run waits on a decision", () => {
    render(<RunHeader state="waiting" since={T0} now={T0 + 12_000} reduced onStop={() => {}} />);
    expect(screen.getByRole("heading").textContent).toBe("Waiting for you 12s");
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
  });
});

// ── The panel: Stop, thinking, steps ───────────────────────────────────────────────────

function Screen() {
  const [name] = useState("");
  useCopilotSurface({
    route: "/t",
    title: "A test screen",
    realm: "client",
    fields: [{ id: "t-name", label: "Business name", type: "text", value: name }],
    apply: () => {},
  });
  return null;
}

function PanelMount() {
  const holder = useCopilotSurfaceHolder();
  if (holder === null) return null;
  return <CopilotPanel session={SESSION} holder={holder} realm="client" labelledBy="t-panel" onClose={() => {}} />;
}

function withQuery(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function heldStream() {
  let push!: (chunk: string) => void;
  let release!: () => void;
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      push = (chunk) => controller.enqueue(encoder.encode(chunk));
      release = () => controller.close();
    },
  });
  return {
    response: new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
    push: (chunk: string) => push(chunk),
    release: () => release(),
  };
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": status < 300 ? "application/json" : "application/problem+json" },
  });

/** The panel over an ask stream this test drives, and a stop route answered by `stop`. */
function renderPanel(stop: () => Response = () => json({}, 202), draftEvents: string[] = []) {
  const held = heldStream();
  const stops: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      if (path.startsWith("/v1/copilot/ask")) return held.response;
      if (path.startsWith("/v1/copilot/conversation")) return json({ turns: [], has_more: false });
      if (path.startsWith("/v1/copilot/runs/")) {
        stops.push(`${init?.method ?? "GET"} ${path}`);
        return stop();
      }
      if (path.endsWith("/script-draft/stream")) {
        const encoder = new TextEncoder();
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              for (const event of draftEvents) controller.enqueue(encoder.encode(event));
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }
      throw new Error(`unexpected request: ${path}`);
    }),
  );
  render(
    withQuery(
      <>
        <Screen />
        <PanelMount />
      </>,
    ),
  );
  return { held, stops };
}

async function ask(question: string) {
  fireEvent.change(screen.getByLabelText("Your question about this screen"), { target: { value: question } });
  await act(async () => {
    fireEvent.submit(screen.getByRole("button", { name: "Ask" }).closest("form")!);
  });
}

const RUN = { run_id: "0192f0aa-7777-7000-8000-000000000001", started_at: new Date().toISOString() };

describe("Stop, through the server", () => {
  it("posts the stop route, stays pressed until `stopped` arrives, then keeps what was said", async () => {
    const { held, stops } = renderPanel();
    await ask("rewrite my campaign");
    await act(async () => {
      held.push(frame("run", RUN));
      held.push(frame("text", { delta: "I am rewriting it" }));
    });
    expect(await screen.findByTestId("run-header")).toBeTruthy();
    // One Stop on screen: the header's. The ask box offers Ask, held.
    const stopButton = screen.getByRole("button", { name: "Stop" });
    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(true);

    await act(async () => {
      fireEvent.click(stopButton);
    });
    expect(stops).toEqual([`POST /v1/copilot/runs/${RUN.run_id}/stop`]);
    // Pressed and waiting: the run is not over until the server says so.
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("heading", { name: /Stopping/ })).toBeTruthy();
    // A second press sends nothing more.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    });
    expect(stops).toHaveLength(1);

    await act(async () => {
      held.push(frame("stopped", { reason: "person" }));
      held.release();
    });
    await waitFor(() => expect(screen.queryByTestId("run-header")).toBeNull());
    expect(screen.getAllByText(/I am rewriting it/)).toHaveLength(1);
    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText(/stopped part-way|went wrong/i)).toBeNull();
  });

  it("closes the connection itself when the stop route refuses", async () => {
    const { held } = renderPanel(() => json({ title: "Unavailable", status: 503 }, 503));
    await ask("rewrite my campaign");
    await act(async () => {
      held.push(frame("run", RUN));
      held.push(frame("text", { delta: "Half" }));
    });
    const pressed = await screen.findByRole("button", { name: "Stop" });
    await act(async () => {
      fireEvent.click(pressed);
    });
    await waitFor(() => expect(screen.queryByTestId("run-header")).toBeNull());
    expect(screen.getByText("Half")).toBeTruthy();
    held.release();
  });

  it("puts focus back in the ask box when Stop goes away under it", async () => {
    const { held } = renderPanel();
    await ask("rewrite my campaign");
    await act(async () => {
      held.push(frame("run", RUN));
    });
    const stopButton = await screen.findByRole("button", { name: "Stop" });
    stopButton.focus();
    await act(async () => {
      fireEvent.click(stopButton);
    });
    await act(async () => {
      held.push(frame("stopped", { reason: "person" }));
      held.release();
    });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Your question about this screen")));
  });
});

describe("a script draft in Pip's thread", () => {
  it("opens the draft inline on `event: draft`, and the header waits for the person once it is written", async () => {
    const { held } = renderPanel(undefined, READY_EVENTS);
    await ask("rewrite the campaign script");
    await act(async () => {
      held.push(frame("run", RUN));
      held.push(frame("draft", { holder_kind: "campaign", holder_id: "c1", proposal_id: "p1" }));
      held.push(frame("text", { delta: "I rewrote it. Have a look." }));
    });
    expect(await screen.findByText("1 added, 1 removed, 1 changed.")).toBeTruthy();
    await act(async () => {
      held.push(frame("done", { disclosure: null, metered: true }));
      held.release();
    });
    await waitFor(() => expect(screen.getAllByRole("heading", { name: /^Waiting for you/ }).length).toBeGreaterThan(1));
    expect(screen.getByRole("button", { name: "Keep" })).toBeTruthy();
  });
});

describe("the Thinking row", () => {
  it("streams while Pip thinks, then folds to Thought for Ns when it moves on", async () => {
    const { held } = renderPanel();
    await ask("what campaigns do i have");
    await act(async () => {
      held.push(frame("run", RUN));
      held.push(frame("thought", { delta: "I should list the " }));
      held.push(frame("thought", { delta: "campaigns first." }));
    });
    expect(await screen.findByText("Thinking")).toBeTruthy();
    expect(screen.getByTestId("thought-live").textContent).toBe("I should list the campaigns first.");

    await act(async () => {
      held.push(frame("step", { id: "s1", tool: "campaigns_list", status: "running", args: "{}", label: "Checking your campaigns…" }));
    });
    expect(screen.queryByText("Thinking")).toBeNull();
    const folded = screen.getByRole("button", { name: /^Thought for \d+s$/ });
    expect(folded.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(folded);
    expect(screen.getByText("I should list the campaigns first.")).toBeTruthy();
    // The live step is on the thread in its present tense.
    expect(screen.getByText("Checking your campaigns…")).toBeTruthy();
    held.release();
  });

  it("is never announced: the thinking sits outside every live region", () => {
    const thought: ThoughtEntry = { kind: "thought", id: "t", text: "Plan", startedAt: T0, endedAt: null };
    const { container } = render(<RunTimeline entries={[thought]} steps={[]} now={T0} live reduced={false} />);
    expect(container.querySelector("[aria-live]")).toBeNull();
  });
});

describe("steps on the thread", () => {
  it("open their results as they arrive while the run is live, links only inside the console", () => {
    render(
      <ol>
        <StepRow step={step({ results: RESULTS })} label="Checked your campaigns" live />
      </ol>,
    );
    expect(screen.getByRole("button", { name: /Checked your campaigns/ }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("link", { name: "Diwali offer" }).getAttribute("href")).toBe("/c/acme/campaigns/c-1");
    // An href that leaves the console is drawn as text, never as a link.
    expect(screen.queryByRole("link", { name: "Plot visit reminder" })).toBeNull();
    expect(screen.getByText("Plot visit reminder")).toBeTruthy();
    expect(screen.getByText("and 4 more")).toBeTruthy();
    // Past tense and its time.
    expect(screen.getByText("2s")).toBeTruthy();
  });

  it("keep results folded once settled, behind the row's own chevron", () => {
    render(<StepList steps={[step({ results: RESULTS })]} />);
    fireEvent.click(screen.getByRole("button", { name: /Checked 1 thing/ }));
    const row = screen.getByRole("button", { name: /Checked your campaigns/ });
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Diwali offer")).toBeNull();
    fireEvent.click(row);
    expect(screen.getByText("Diwali offer")).toBeTruthy();
  });

  it("counts a running step from when it started", () => {
    render(
      <ol>
        <StepRow
          step={step({ status: "running", elapsed_ms: null, label: "Searching your leads…" })}
          label="Searching your leads…"
          startedAt={T0}
          now={T0 + 3_200}
          live
        />
      </ol>,
    );
    expect(screen.getByText("3s")).toBeTruthy();
  });

  it("checks result links", () => {
    expect(consoleHref("/c/acme/leads")).toBe("/c/acme/leads");
    expect(consoleHref("//evil.example/x")).toBeNull();
    expect(consoleHref("https://evil.example")).toBeNull();
    expect(consoleHref("/c\\evil")).toBeNull();
    expect(consoleHref(null)).toBeNull();
  });
});

// ── The script draft ───────────────────────────────────────────────────────────────────

const CHANGES: DraftChange[] = [
  { path: "opening_line", label: "Opening line", op: "changed", before: "Hello, this is Sunrise.", after: "Namaste, Sunrise Homes here." },
  { path: "goal", label: "The goal", op: "same", before: "Book a visit.", after: "Book a visit." },
  { path: "stages.0.name", label: "Step 1", op: "same", before: "Greet", after: "Greet" },
  { path: "stages.1.sounds_like", label: "Step 2 · what the agent says", op: "added", before: null, after: "Shall I book Saturday?" },
  { path: "faqs.0", label: "Quick fact", op: "removed", before: "We open at 9.", after: null },
];

describe("the draft's changes", () => {
  it("draws removed in red with a minus, added in green with a plus, a change as the pair", () => {
    render(<ScriptDiff changes={CHANGES} />);
    const diff = screen.getByTestId("script-diff");
    const removed = diff.querySelectorAll('[data-op="removed"]');
    const added = diff.querySelectorAll('[data-op="added"]');
    expect([...removed].map((line) => line.textContent)).toEqual([
      "−Removed: Hello, this is Sunrise.",
      "−Removed: We open at 9.",
    ]);
    expect([...added].map((line) => line.textContent)).toEqual([
      "+Added: Namaste, Sunrise Homes here.",
      "+Added: Shall I book Saturday?",
    ]);
    expect(removed[0].className).toContain("bg-danger-soft");
    expect(added[0].className).toContain("bg-success-soft");
    expect(screen.getByText("1 added, 1 removed, 1 changed.")).toBeTruthy();
    expect(screen.getByText("Opening line")).toBeTruthy();
  });

  it("folds unchanged lines into one closed row that opens", () => {
    render(<ScriptDiff changes={CHANGES} />);
    expect(diffBlocks(CHANGES).map((block) => block.kind)).toEqual(["change", "same", "change", "change"]);
    const fold = screen.getByRole("button", { name: "2 unchanged lines" });
    expect(fold.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Book a visit.")).toBeNull();
    fireEvent.click(fold);
    expect(screen.getByText("Book a visit.")).toBeTruthy();
  });
});

function readyState(over: Partial<DraftStreamState> = {}): DraftStreamState {
  return {
    ...EMPTY_DRAFT_STREAM,
    phase: "ready",
    history: [
      { phase: "reading", at: T0 },
      { phase: "writing", at: T0 + 4_000 },
      { phase: "ready", at: T0 + 30_000 },
    ],
    diff: { changes: CHANGES, proposal_id: "p1" },
    ...over,
  };
}

const idle = { status: "idle" as const, run: () => {} };

describe("the draft view", () => {
  it("streams phases and lines while Pip writes, with the finished phase in the past tense", () => {
    const writing: DraftStreamState = {
      ...EMPTY_DRAFT_STREAM,
      phase: "writing",
      history: [
        { phase: "reading", at: T0 },
        { phase: "writing", at: T0 + 4_000 },
      ],
      lines: [{ path: "opening_line", label: "Opening line", text: "Namaste, Sunrise Homes here." }],
    };
    render(
      <ScriptDraftView state={writing} now={T0 + 9_000} reduced keep={idle} discard={idle} cancel={idle} outcome={null} />,
    );
    expect(screen.getByText("Read your main task and sources")).toBeTruthy();
    expect(screen.getByText("4s")).toBeTruthy();
    expect(screen.getByText("Writing the script")).toBeTruthy();
    expect(screen.getByText("5s")).toBeTruthy();
    expect(within(screen.getByTestId("draft-lines")).getByText("Namaste, Sunrise Homes here.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stop writing" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Keep" })).toBeNull();
  });

  it("replaces a line the writer sends again, in place", () => {
    const once = draftStreamReducer(EMPTY_DRAFT_STREAM, { type: "line", line: { path: "a", label: "A", text: "Hel" } });
    const twice = draftStreamReducer(once, { type: "line", line: { path: "b", label: "B", text: "Bye" } });
    const grown = draftStreamReducer(twice, { type: "line", line: { path: "a", label: "A", text: "Hello" } });
    expect(grown.lines.map((line) => `${line.path}:${line.text}`)).toEqual(["a:Hello", "b:Bye"]);
    const phased = draftStreamReducer(
      draftStreamReducer(grown, { type: "phase", phase: "writing", detail: null, at: 1 }),
      { type: "phase", phase: "writing", detail: null, at: 2 },
    );
    expect(phased.history).toEqual([{ phase: "writing", at: 1 }]);
  });

  it("waits for the person with Keep and Discard, and moves focus there only into a vacuum", () => {
    const { rerender } = render(
      <ScriptDraftView state={{ ...readyState(), phase: "writing", diff: null }} now={T0} reduced keep={idle} discard={idle} outcome={null} />,
    );
    (document.activeElement as HTMLElement | null)?.blur();
    rerender(<ScriptDraftView state={readyState()} now={T0} reduced keep={idle} discard={idle} outcome={null} />);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Waiting for you" }));
    expect(screen.getByRole("button", { name: "Keep" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Discard" })).toBeTruthy();
  });

  it("does not take focus from a box the person is typing in", () => {
    const { rerender } = render(
      <>
        <textarea aria-label="Typing" />
        <ScriptDraftView state={{ ...readyState(), phase: "writing", diff: null }} now={T0} reduced keep={idle} discard={idle} outcome={null} />
      </>,
    );
    const box = screen.getByLabelText("Typing");
    box.focus();
    rerender(
      <>
        <textarea aria-label="Typing" />
        <ScriptDraftView state={readyState()} now={T0} reduced keep={idle} discard={idle} outcome={null} />
      </>,
    );
    expect(document.activeElement).toBe(box);
  });

  it("holds Keep and Discard behind the reason when the person cannot change the script", () => {
    render(
      <ScriptDraftView state={readyState()} now={T0} reduced keep={idle} discard={idle} outcome={null} waitingFor="You can't change this campaign's script." />,
    );
    expect(screen.getByRole("button", { name: "Keep" }).getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByText("You can't change this campaign's script.")).toBeTruthy();
  });

  it("says what was saved when it was cancelled or failed", () => {
    const { rerender } = render(
      <ScriptDraftView state={{ ...EMPTY_DRAFT_STREAM, phase: "cancelled" }} now={T0} reduced keep={idle} discard={idle} outcome={null} />,
    );
    expect(screen.getAllByText("Stopped. Nothing was saved.").length).toBeGreaterThan(0);
    rerender(
      <ScriptDraftView
        state={{ ...EMPTY_DRAFT_STREAM, phase: "failed", detail: "The writer did not answer." }}
        now={T0}
        reduced
        keep={idle}
        discard={idle}
        outcome={null}
      />,
    );
    expect(screen.getByText("The writer did not answer.")).toBeTruthy();
  });
});

/** The draft routes for one campaign, the keep and discard ones held open until released. */
function stubDraftRoutes(events: string[]) {
  const calls: string[] = [];
  const pending: Record<string, () => void> = {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      const method = init?.method ?? "GET";
      calls.push(`${method} ${path}`);
      if (path.endsWith("/script-draft/stream")) {
        const encoder = new TextEncoder();
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              for (const event of events) controller.enqueue(encoder.encode(event));
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }
      if (method !== "GET") {
        return new Promise<Response>((resolve) => {
          pending[path] = () => resolve(new Response(null, { status: 204 }));
        });
      }
      return json({});
    }),
  );
  return { calls, release: (path: string) => pending[path]?.() };
}

const READY_EVENTS = [
  frame("phase", { phase: "writing", detail: null }),
  frame("line", { path: "opening_line", label: "Opening line", text: "Namaste, Sunrise Homes here." }),
  frame("phase", { phase: "ready", detail: null }),
  frame("diff", { changes: CHANGES, proposal_id: "p1" }),
];

describe("Keep and Discard", () => {
  it("Keep calls keep-live, shows it is working, then says the script is live", async () => {
    const { calls, release } = stubDraftRoutes(READY_EVENTS);
    render(withQuery(<ScriptDraftLive session={SESSION} holder={{ kind: "campaign", id: "c1" }} proposalId="p1" />));
    const keep = await screen.findByRole("button", { name: "Keep" });
    await act(async () => {
      fireEvent.click(keep);
    });
    expect(calls).toContain("POST /v1/campaigns/c1/script-draft/p1/keep-live");
    await waitFor(() => expect(screen.getByRole("button", { name: "Keep" }).getAttribute("aria-busy")).toBe("true"));
    // Discard waits while Keep works.
    expect((screen.getByRole("button", { name: "Discard" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => {
      release("/v1/campaigns/c1/script-draft/p1/keep-live");
    });
    expect(await screen.findByText("Kept. This script is live now.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Keep" })).toBeNull();
  });

  it("Discard calls the existing discard route and shows it is working", async () => {
    const { calls, release } = stubDraftRoutes(READY_EVENTS);
    render(withQuery(<ScriptDraftLive session={SESSION} holder={{ kind: "campaign", id: "c1" }} proposalId="p1" />));
    const pressed = await screen.findByRole("button", { name: "Discard" });
    await act(async () => {
      fireEvent.click(pressed);
    });
    expect(calls).toContain("DELETE /v1/campaigns/c1/script/proposal/p1");
    await waitFor(() => expect(screen.getByRole("button", { name: "Discard" }).getAttribute("aria-busy")).toBe("true"));
    await act(async () => {
      release("/v1/campaigns/c1/script/proposal/p1");
    });
    expect(await screen.findByText("Discarded. Your script stays as it was.")).toBeTruthy();
  });

  it("an Inbound line keeps through its own keep-live route", async () => {
    const { calls } = stubDraftRoutes(READY_EVENTS);
    render(withQuery(<ScriptDraftLive session={SESSION} holder={{ kind: "inbound_line", id: "l1" }} proposalId="p1" />));
    const pressed = await screen.findByRole("button", { name: "Keep" });
    await act(async () => {
      fireEvent.click(pressed);
    });
    expect(calls).toContain("GET /v1/inbound-lines/l1/script-draft/stream");
    expect(calls).toContain("POST /v1/inbound-lines/l1/script-draft/p1/keep-live");
  });

  it("Stop writing posts the cancel route and stays pressed while it works", async () => {
    const { calls } = stubDraftRoutes([frame("phase", { phase: "writing", detail: null })]);
    render(withQuery(<ScriptDraftLive session={SESSION} holder={{ kind: "campaign", id: "c1" }} proposalId="p1" />));
    const cancel = await screen.findByRole("button", { name: "Stop writing" });
    await act(async () => {
      fireEvent.click(cancel);
    });
    expect(calls).toContain("POST /v1/campaigns/c1/script-draft/p1/cancel");
    await waitFor(() => expect(screen.getByRole("button", { name: "Stop writing" }).getAttribute("aria-busy")).toBe("true"));
  });
});

// ── On the campaign page ───────────────────────────────────────────────────────────────

describe("the campaign page", () => {
  const base = `/v1/campaigns/${FIXTURE_CAMPAIGN_ID}`;
  const drafting: CampaignProposal = {
    id: "0192f0aa-6666-7000-8000-000000000001",
    status: "drafting",
    requested_at: new Date().toISOString(),
    base_script: null,
    script: null,
    note: null,
    disclosure: null,
    left_out: [],
    reason: null,
    fixes: null,
    why: {},
  };
  const pageRoutes = (stream: unknown) => ({
    [`${base}/workspace`]: workspaceFixture({ proposal: drafting }),
    [`${base}/settings`]: settingsFixture(),
    "/v1/kb/notes": { notes: [] },
    "/v1/kb/uploads": [],
    "/v1/agents": [],
    "/v1/me": noReply(),
    [`GET ${base}/script-draft/stream`]: stream,
  });

  it("shows Pip writing live, the same view as the panel, while a draft is written", async () => {
    const events = [
      frame("phase", { phase: "reading", detail: null }),
      frame("phase", { phase: "writing", detail: null }),
      frame("line", { path: "opening_line", label: "Opening line", text: "Namaste, Sunrise Homes here." }),
    ];
    await renderClientPage(
      <CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />,
      pageRoutes(() => {
        const encoder = new TextEncoder();
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              for (const event of events) controller.enqueue(encoder.encode(event));
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }),
    );
    expect(await screen.findByText("Namaste, Sunrise Homes here.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stop writing" })).toBeTruthy();
    // The page's own writing line gives way to the live view.
    expect(screen.queryByText(/usually about a minute/)).toBeNull();
  });

  it("keeps its own writing line when the draft stream is not there", async () => {
    await renderClientPage(<CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />, {
      ...pageRoutes(null),
      [`GET ${base}/script-draft/stream`]: () =>
        new Response(JSON.stringify({ status: 404 }), { status: 404, headers: { "content-type": "application/problem+json" } }),
    });
    expect(await screen.findByText("Pip is writing the script.")).toBeTruthy();
  });
});

// ── Accessibility ─────────────────────────────────────────────────────────────────────

describe("accessibility", () => {
  it("the live thread, the settled steps and the waiting draft are axe-clean", async () => {
    const thought: ThoughtEntry = { kind: "thought", id: "t", text: "List the campaigns.", startedAt: T0, endedAt: null };
    const { container } = render(
      <div>
        <h2>Pip</h2>
        <RunHeader state="working" since={T0} now={T0 + 4_000} reduced={false} onStop={() => {}} />
        <RunTimeline
          entries={[thought, { kind: "step", id: "s1", startedAt: T0 }]}
          steps={[step({ results: RESULTS })]}
          now={T0 + 4_000}
          live
          reduced={false}
        />
        <StepList steps={[step({ id: "s2", results: RESULTS })]} />
        <ScriptDraftView state={readyState()} now={T0} reduced={false} keep={idle} discard={idle} outcome={null} />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Checked 1 thing/ }));
    fireEvent.click(screen.getByRole("button", { name: "2 unchanged lines" }));
    await expectNoA11yViolations(container, "pip live view");
  });
});
