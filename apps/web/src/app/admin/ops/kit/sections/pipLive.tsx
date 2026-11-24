"use client";

import { useEffect, useReducer, useRef, useState } from "react";

import type { FeedbackStatus } from "@/components/arc/feedback";
import { RunHeader } from "@/components/copilot/RunHeader";
import { RunTimeline } from "@/components/copilot/RunTimeline";
import { StepList } from "@/components/copilot/StepList";
import { ScriptDraftView, type DraftOutcome } from "@/components/scriptDraft/ScriptDraftView";
import { SECONDARY_BUTTON_SM } from "@/components/ui";
import { IDLE_RUN, liveRunReducer, type LiveAction } from "@/lib/copilot/liveEvents";
import type { CopilotStep } from "@/lib/copilot/types";
import { useNow } from "@/lib/copilot/useNow";
import {
  EMPTY_DRAFT_STREAM,
  draftStreamReducer,
  type DraftChange,
  type DraftStreamAction,
} from "@/lib/scriptDraft/stream";

import { KitDemo, KitGrid, KitSection } from "../kitLayout";

const CHANGES: DraftChange[] = [
  {
    path: "opening_line",
    label: "Opening line",
    op: "changed",
    before: "Hello, this is Sri Lakshmi Sweets calling about your order.",
    after: "Namaste, Sri Lakshmi Sweets here. Is this a good time to talk about your order?",
  },
  { path: "goal", label: "The goal", op: "same", before: "Confirm Saturday's delivery.", after: "Confirm Saturday's delivery." },
  { path: "stages.0.name", label: "Step 1", op: "same", before: "Greet and confirm the name", after: "Greet and confirm the name" },
  {
    path: "stages.1.sounds_like",
    label: "Step 2 · what the agent says",
    op: "added",
    before: null,
    after: "Shall we deliver between 10 and 12 on Saturday?",
  },
  { path: "faqs.2", label: "Quick fact", op: "removed", before: "We close at 8 on Sundays.", after: null },
];

const RESULTS = {
  kind: "list" as const,
  items: [
    { title: "Diwali sweets reminder", subtitle: "Running · 240 contacts", href: "#pip-live" },
    { title: "Saturday delivery check", subtitle: "Draft", href: "#pip-live" },
  ],
  total: 5,
};

const LOOKUP: CopilotStep = {
  id: "k1",
  tool: "campaigns_list",
  status: "running",
  args: "{}",
  label: "Checking your campaigns…",
};

type Scripted = { at: number; run?: LiveAction; step?: CopilotStep; draft?: DraftStreamAction };

/** A scripted run, so the live view can be watched without a backend. */
function script(t0: number): Scripted[] {
  return [
    { at: 0, run: { type: "run", frame: { run_id: "kit", started_at: new Date(t0).toISOString() }, now: t0 } },
    { at: 300, run: { type: "thought", delta: "The owner wants a warmer opening. ", now: t0 + 300 } },
    { at: 900, run: { type: "thought", delta: "I should read the campaign first, ", now: t0 + 900 } },
    { at: 1500, run: { type: "thought", delta: "then rewrite the script from its main task.", now: t0 + 1500 } },
    { at: 2200, run: { type: "step", id: "k1", now: t0 + 2200 }, step: LOOKUP },
    {
      at: 3600,
      step: { ...LOOKUP, status: "done", elapsed_ms: 1400, label: "Checked your campaigns", results: RESULTS },
    },
    { at: 4000, draft: { type: "phase", phase: "reading", detail: null, at: t0 + 4000 } },
    { at: 5600, draft: { type: "phase", phase: "writing", detail: null, at: t0 + 5600 } },
    {
      at: 6400,
      draft: { type: "line", line: { path: "opening_line", label: "Opening line", text: CHANGES[0].after ?? "" } },
    },
    { at: 7600, draft: { type: "line", line: { path: "stages.1.sounds_like", label: "Step 2 · what the agent says", text: CHANGES[3].after ?? "" } } },
    { at: 8600, draft: { type: "phase", phase: "checking", detail: null, at: t0 + 8600 } },
    { at: 9800, draft: { type: "phase", phase: "ready", detail: null, at: t0 + 9800 } },
    { at: 9800, draft: { type: "diff", diff: { changes: CHANGES, proposal_id: "kit" } } },
    { at: 10000, run: { type: "end", stopped: false, now: t0 + 10000 } },
  ];
}

function PlayedRun() {
  const [round, setRound] = useState(0);
  return (
    <div className="space-y-3">
      <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setRound((n) => n + 1)}>
        Play a run
      </button>
      {round > 0 ? <OneRun key={round} /> : null}
    </div>
  );
}

function OneRun() {
  const [runState, dispatchRun] = useReducer(liveRunReducer, IDLE_RUN);
  const [draft, dispatchDraft] = useReducer(draftStreamReducer, EMPTY_DRAFT_STREAM);
  const [steps, setSteps] = useState<CopilotStep[]>([]);
  const [keep, setKeep] = useState<FeedbackStatus>("idle");
  const [discard, setDiscard] = useState<FeedbackStatus>("idle");
  const [outcome, setOutcome] = useState<DraftOutcome>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const working = runState.phase === "working" || runState.phase === "stopping";
  const waiting = !working && draft.phase === "ready" && outcome === null;
  const [waitingSince, setWaitingSince] = useState(0);
  const now = useNow(working || waiting || (draft.phase !== null && draft.phase !== "ready"));
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const later = (ms: number, fn: () => void) => timers.current.push(setTimeout(fn, ms));
  useEffect(() => {
    dispatchRun({ type: "ask" });
    const t0 = Date.now();
    for (const event of script(t0)) {
      later(event.at, () => {
        if (event.run) dispatchRun(event.run);
        if (event.step) {
          const next = event.step;
          setSteps((previous) => [...previous.filter((s) => s.id !== next.id), next]);
        }
        if (event.draft) dispatchDraft(event.draft);
        if (event.draft?.type === "diff") setWaitingSince(Date.now());
      });
    }
    // Played once per mount; Play again remounts this run.
  }, []);
  const stop = () => {
    dispatchRun({ type: "stopping" });
    later(1200, () => {
      timers.current.forEach(clearTimeout);
      dispatchRun({ type: "end", stopped: true, now: Date.now() });
      dispatchDraft({ type: "phase", phase: "cancelled", detail: null, at: Date.now() });
    });
  };
  const settle = (set: (s: FeedbackStatus) => void, result: DraftOutcome) => {
    set("pending");
    later(1000, () => {
      set("idle");
      setOutcome(result);
    });
  };

  return (
    <div className="space-y-3">
      {working || waiting ? (
        <RunHeader
          state={waiting ? "waiting" : runState.phase === "stopping" ? "stopping" : "working"}
          since={waiting ? waitingSince : (runState.startedAt ?? now)}
          now={now}
          reduced={false}
          onStop={stop}
        />
      ) : null}
      <RunTimeline entries={runState.entries} steps={steps} now={now} live={working} reduced={false} realm="admin" />
      {!working && steps.length > 0 ? <StepList steps={steps} realm="admin" /> : null}
      {draft.phase !== null ? (
        <ScriptDraftView
          state={draft}
          now={now}
          reduced={false}
          outcome={outcome}
          keep={{ status: keep, run: () => settle(setKeep, "kept") }}
          discard={{ status: discard, run: () => settle(setDiscard, "discarded") }}
          cancel={{ status: "idle", run: stop }}
        />
      ) : null}
    </div>
  );
}

const T0 = Date.parse("2026-11-24T04:30:00Z");

export function PipLiveSection() {
  return (
    <KitSection
      id="pip-live"
      title="Pip at work"
      lead="Pip's live thread: the working header with Stop, thinking, lookups with results, and a script draft that ends in Keep or Discard. The same draft view sits on the campaign and line pages."
    >
      <KitGrid>
        <KitDemo label="A whole run · scripted" note="Plays a run through the real reducers and components." wide>
          <PlayedRun />
        </KitDemo>
        <KitDemo label="RunHeader · stopping">
          <RunHeader state="stopping" since={T0} now={T0 + 14_000} reduced={false} onStop={() => {}} />
        </KitDemo>
        <KitDemo label="Thinking · folded">
          <RunTimeline
            entries={[{ kind: "thought", id: "t", text: "Read the campaign, then rewrite.", startedAt: T0, endedAt: T0 + 3_000 }]}
            steps={[]}
            now={T0}
            live={false}
            reduced={false}
          />
        </KitDemo>
        <KitDemo label="Script draft · failed">
          <ScriptDraftView
            state={{ ...EMPTY_DRAFT_STREAM, phase: "failed", detail: "The writer stopped before it finished." }}
            now={T0}
            reduced={false}
            outcome={null}
            keep={{ status: "idle", run: () => {} }}
            discard={{ status: "idle", run: () => {} }}
          />
        </KitDemo>
        <KitDemo label="Script draft · kept">
          <ScriptDraftView
            state={{ ...EMPTY_DRAFT_STREAM, phase: "ready", diff: { changes: CHANGES, proposal_id: "k" } }}
            now={T0}
            reduced={false}
            outcome="kept"
            keep={{ status: "idle", run: () => {} }}
            discard={{ status: "idle", run: () => {} }}
          />
        </KitDemo>
      </KitGrid>
    </KitSection>
  );
}
