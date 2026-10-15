"use client";

// Adapted from interior.dev (github.com/ddoemonn/interior @3148000), MIT License,
// Copyright (c) 2026 ozzy. Full notice: ./LICENSE.

import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

const POP = { type: "spring", stiffness: 640, damping: 22, mass: 0.7 } as const;
const CELL = { type: "spring", stiffness: 520, damping: 34, mass: 0.45 } as const;
const STILL = { duration: 0 } as const;

export type TaskStep = {
  id: string;
  label: string;

  meta?: string;
};

export type TaskStepStatus = "pending" | "active" | "done" | "error" | "paused" | "stopped";

/**
 * A current step that is not moving and has not failed: "paused" (it will go on: a
 * campaign paused for credit) or "stopped" (it will not: a campaign stopped for good).
 * Without these a held job had to be drawn as a spinner, which says it is working, or as
 * an error, which says something broke.
 */
export type TaskStepHold = "paused" | "stopped";

export type UseTaskStepsOptions = {
  steps: TaskStep[];

  current: number;

  failed?: boolean;

  hold?: TaskStepHold;
};

const STATUS_WORDS: Record<TaskStepStatus, string> = {
  pending: "Not started",
  active: "In progress",
  done: "Done",
  error: "Failed",
  paused: "Paused",
  stopped: "Stopped",
};

export function useTaskSteps({ steps, current, failed = false, hold }: UseTaskStepsOptions) {
  const complete = !failed && !hold && current >= steps.length;

  const rows = steps.map((step, i) => ({
    ...step,
    status: (i < current
      ? "done"
      : i === current && failed
        ? "error"
        : i === current && hold
          ? hold
          : i === current && !complete
            ? "active"
            : "pending") as TaskStepStatus,
  }));

  const active = rows.find((r) => r.status === "active");
  const held = rows.find((r) => r.status === "paused" || r.status === "stopped");
  const sentence = failed
    ? `Failed at ${steps[Math.min(current, steps.length - 1)]?.label ?? "step"}`
    : held
      ? `${STATUS_WORDS[held.status]} at ${held.label}`
      : complete
        ? `All ${steps.length} steps complete`
        : active
          ? `${active.label}, step ${current + 1} of ${steps.length}`
          : "";

  return { rows, complete, failed, sentence };
}

const Tick = (
  <svg viewBox="0 0 256 256" width="11" height="11" fill="none" aria-hidden>
    <polyline
      points="216 72 104 184 48 128"
      stroke="currentColor"
      strokeWidth="26"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const Cross = (
  <svg viewBox="0 0 256 256" width="10" height="10" fill="none" aria-hidden>
    <path
      d="M200 56 56 200 M56 56l144 144"
      stroke="currentColor"
      strokeWidth="26"
      strokeLinecap="round"
    />
  </svg>
);

const PauseGlyph = (
  <svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor" aria-hidden>
    <rect x="3.5" y="3" width="3" height="10" rx="1" />
    <rect x="9.5" y="3" width="3" height="10" rx="1" />
  </svg>
);

const StopGlyph = (
  <svg viewBox="0 0 16 16" width="8" height="8" fill="currentColor" aria-hidden>
    <rect x="2" y="2" width="12" height="12" rx="2" />
  </svg>
);

const Arc = ({ spin }: { spin: boolean }) => (
  <motion.svg
    viewBox="0 0 16 16"
    className="size-3"
    aria-hidden
    animate={spin ? { rotate: 360 } : { rotate: 0 }}
    transition={spin ? { duration: 0.8, ease: "linear", repeat: Infinity } : STILL}
  >
    <circle
      cx="8"
      cy="8"
      r="6"
      fill="none"
      stroke="currentColor"
      strokeOpacity="0.25"
      strokeWidth="2"
    />
    <path
      d="M8 2 a6 6 0 0 1 6 6"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
  </motion.svg>
);

export type TaskStepsProps = UseTaskStepsOptions & {
  label?: string;
  className?: string;
  /**
   * "sm" is the compact list a side panel holds. "md" is the same list as a screen's own
   * subject: body-size labels, and the meta of the step in progress shown too, because on
   * a live job that is the figure the reader came for ("320 of 1,200").
   */
  size?: "sm" | "md";
};

export function TaskSteps({
  steps,
  current,
  failed = false,
  hold,
  label = "Task progress",
  className = "",
  size = "sm",
}: TaskStepsProps) {
  const { rows, complete, sentence } = useTaskSteps({ steps, current, failed, hold });
  const md = size === "md";
  const reduced = useReducedMotion() === true;

  const [spoken, setSpoken] = useState("");
  useEffect(() => {
    if (!sentence) return;
    const t = setTimeout(() => setSpoken(sentence), 500);
    return () => clearTimeout(t);
  }, [sentence]);

  return (
    <div className={`w-full ${className}`}>
      <ol aria-label={label} className={md ? "space-y-1" : "space-y-0.5"}>
        {rows.map((row) => {
          const tone =
            row.status === "done"
              ? "text-ink-muted"
              : row.status === "active"
                ? "font-medium text-ink"
                : row.status === "error"
                  ? "font-medium text-danger"
                  : row.status === "paused" || row.status === "stopped"
                    ? "font-medium text-ink"
                    : md
                      ? "text-ink-muted"
                      : "text-ink-faint";
          const showMeta =
            row.status === "done" || (md && row.status !== "pending");

          return (
            <li
              key={row.id}
              aria-current={row.status === "active" ? "step" : undefined}
              className={md ? "flex min-h-9 flex-wrap items-center gap-x-3 py-1" : "flex h-7 items-center gap-2.5 px-1"}
            >
              <span className="relative grid size-4 shrink-0 place-items-center">
                <AnimatePresence initial={false}>
                  {row.status === "done" ? (
                    <motion.span
                      key="done"
                      className="col-start-1 row-start-1 grid size-4 place-items-center rounded-[5px] bg-brand/[0.14] text-brand"
                      initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.4 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, transition: STILL }}
                      transition={reduced ? STILL : POP}
                    >
                      {Tick}
                    </motion.span>
                  ) : row.status === "error" ? (
                    <motion.span
                      key="error"
                      className="col-start-1 row-start-1 grid size-4 place-items-center rounded-[5px] bg-danger-soft text-danger"
                      initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.4 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, transition: STILL }}
                      transition={reduced ? STILL : POP}
                    >
                      {Cross}
                    </motion.span>
                  ) : row.status === "paused" || row.status === "stopped" ? (
                    <motion.span
                      key={row.status}
                      className={`col-start-1 row-start-1 grid size-4 place-items-center rounded-[5px] ${
                        row.status === "paused" ? "bg-warn-soft text-warn" : "bg-ink/[0.08] text-ink-muted"
                      }`}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0, transition: STILL }}
                      transition={reduced ? STILL : CELL}
                    >
                      {row.status === "paused" ? PauseGlyph : StopGlyph}
                    </motion.span>
                  ) : row.status === "active" ? (
                    <motion.span
                      key="active"
                      className="col-start-1 row-start-1 text-ink-muted"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0, transition: STILL }}
                      transition={reduced ? STILL : CELL}
                    >
                      {/* Reduced motion keeps the arc and drops the turn: the words beside
                          it already say the step is in progress. */}
                      <Arc spin={!reduced} />
                    </motion.span>
                  ) : (
                    <motion.span
                      key="pending"
                      className="col-start-1 row-start-1 size-[5px] rounded-[2px] bg-ink/20"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0, transition: STILL }}
                      transition={STILL}
                    />
                  )}
                </AnimatePresence>
              </span>

              {/* A still label: the arc beside it already says the step is working, and a
                  shimmer sweeping the words forever only made them harder to read. */}
              <span
                className={`min-w-0 flex-1 transition-colors duration-200 ${
                  md ? "text-body [overflow-wrap:anywhere]" : "truncate text-[12.5px]"
                } ${tone}`}
              >
                {row.label}
                <span className="sr-only">, {STATUS_WORDS[row.status]}</span>
              </span>

              {row.meta ? (
                <span
                  className={`shrink-0 tabular-nums transition-opacity duration-200 ${
                    md
                      ? `basis-full pl-7 text-meta text-ink-muted sm:basis-auto sm:pl-0 ${showMeta ? "" : "hidden"}`
                      : "font-mono text-[10.5px] text-ink-faint"
                  } ${showMeta ? "opacity-100" : "opacity-0"}`}
                  aria-hidden={!showMeta}
                >
                  {row.meta}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      <span role="status" className="sr-only">
        {spoken}
      </span>
      <span className="sr-only" aria-live={complete || failed ? "polite" : "off"}>
        {complete ? "Run complete" : failed ? "Run failed" : ""}
      </span>
    </div>
  );
}
