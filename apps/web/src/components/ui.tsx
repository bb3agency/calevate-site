"use client";

/**
 * The small set of primitives every client screen is built from.
 *
 * Deliberately hand-rolled rather than pulled from shadcn/ui for M1: these are five
 * components, and the ones that matter (`ProblemNotice`, `StatusBadge`) encode OUR
 * rules — problem+json has `remediation` and `retryable` fields that a generic alert
 * component would throw away, and the lead status set is a fixed enum (D-21) that
 * should not be stringly-typed at every call site. shadcn lands with the design pass.
 */

import clsx from "clsx";
import type { ReactNode } from "react";

import { ApiProblem } from "@/lib/api/client";

export function Card({
  title,
  action,
  children,
  className,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={clsx(
        "rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900",
        className,
      )}
    >
      {(title || action) && (
        <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          {title && <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h2>}
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number | null | undefined;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-50">
        {value ?? "—"}
      </div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

const LEAD_STATUS_STYLES: Record<string, string> = {
  new: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  contacted: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  interested: "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300",
  hot: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  won: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  lost: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
};

const CALL_STATUS_STYLES: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  in_progress: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  queued: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  ringing: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  no_answer: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  busy: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  voicemail: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  failed: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
};

export function StatusBadge({ value, kind = "lead" }: { value: string; kind?: "lead" | "call" }) {
  const styles = kind === "lead" ? LEAD_STATUS_STYLES : CALL_STATUS_STYLES;
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        styles[value] ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
      )}
    >
      {value.replace(/_/g, " ")}
    </span>
  );
}

/**
 * Renders an RFC-9457 problem the way its fields intend.
 *
 * The reason this exists instead of `alert(error.message)`: the API distinguishes a
 * compliance refusal ("this number is on the do-not-call list") from a transient
 * failure, and tells us which is which via `retryable` + `remediation`. Flattening
 * both into "something went wrong" would make the compliance gate look like a bug.
 */
export function ProblemNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const problem = error instanceof ApiProblem ? error : null;
  const title = problem?.message ?? "Something went wrong.";
  // Anything that is not an ApiProblem never reached the API — a dropped connection,
  // a DNS failure, a laptop that slept. The API's `retryable` cannot speak for those,
  // and they are the most retryable failures there are, so the button must not depend
  // on it: without this, a client on a train watches a screen with no way forward
  // except reloading the page.
  const canRetry = Boolean(onRetry) && (problem === null || problem.retryable);
  return (
    <div
      role="alert"
      className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200"
    >
      <p className="font-medium">{title}</p>
      {problem?.remediation && <p className="mt-1 text-rose-800 dark:text-rose-300">{problem.remediation}</p>}
      {problem === null && (
        <p className="mt-1 text-rose-800 dark:text-rose-300">
          We could not reach Calevate. Check your connection and try again.
        </p>
      )}
      {problem?.fields?.length ? (
        <ul className="mt-2 list-inside list-disc">
          {problem.fields.map((f) => (
            <li key={f.field}>
              <span className="font-medium">{f.field}</span>: {f.message}
            </li>
          ))}
        </ul>
      ) : null}
      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-md bg-rose-600 px-2 py-1 text-xs font-medium text-white hover:bg-rose-700"
        >
          Try again
        </button>
      )}
      {problem?.traceId && (
        <p className="mt-2 font-mono text-[11px] text-rose-700 dark:text-rose-400">
          ref {problem.traceId}
        </p>
      )}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="py-10 text-center">
      <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{title}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
      ))}
    </div>
  );
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Times are stored UTC and shown IST at the edge (CLAUDE.md conventions). */
export function formatIST(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
