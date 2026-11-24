"use client";

import Link from "next/link";
import { CircleMinus, FileText, Loader2, PenLine, RotateCcw, Search, Sparkle } from "lucide-react";
import { createContext, useContext, type ReactNode } from "react";

import { consoleHref, formatWorkTime, stepDuration, stepResults, type StepResults } from "@/lib/copilot/liveEvents";
import type { CopilotStep } from "@/lib/copilot/types";

import { RowHead, TimelineRow } from "./TimelineRow";

/**
 * One tool call on Pip's thread: the server's own words for it (present tense while it
 * runs, past once done), how long it took, and, when it found things, the list it found
 * behind a chevron.
 */
export function StepRow({
  step,
  label,
  startedAt,
  now,
  live = false,
  arrived = false,
  retried = false,
  title,
  children,
}: {
  step: CopilotStep;
  /** The words for the step in its current tense (`StepList`'s `labelOf`). */
  label: string;
  /** When its first frame arrived, so a running step can count; omitted once settled. */
  startedAt?: number;
  now?: number;
  /** The run is still going: a step's results open as they arrive. */
  live?: boolean;
  /** Fade the row in: it arrived while the person watched, and motion is welcome. */
  arrived?: boolean;
  /** A failure Pip got past by trying again. */
  retried?: boolean;
  title?: string;
  /** The step's own sentence, always shown under its line (results sit behind the chevron). */
  children?: ReactNode;
}) {
  const results = stepResults(step);
  const running = step.status === "running";
  const failed = !retried && (step.status === "failed" || step.status === "refused");
  const duration = running
    ? startedAt !== undefined && now !== undefined
      ? formatWorkTime(now - startedAt)
      : null
    : stepDuration(step.elapsed_ms);
  const hasResults = results !== null && results.items.length > 0;
  return (
    <TimelineRow icon={<StepIcon step={step} retried={retried} />} arrived={arrived}>
      <RowHead
        label={<span className={failed || retried ? "text-ink-muted" : undefined}>{label}</span>}
        trailing={duration}
        body={hasResults ? <ResultList results={results} /> : null}
        defaultOpen={live}
        title={title}
      />
      {children ? <div className="text-meta text-ink-muted">{children}</div> : null}
    </TimelineRow>
  );
}

function StepIcon({ step, retried }: { step: CopilotStep; retried: boolean }) {
  const glyph = "h-3.5 w-3.5";
  if (step.status === "running") {
    return <Loader2 aria-hidden className={`${glyph} text-ink-faint motion-safe:animate-spin`} />;
  }
  if (retried) return <RotateCcw aria-hidden className={glyph} />;
  if (step.status === "failed" || step.status === "refused") return <CircleMinus aria-hidden className={glyph} />;
  const tool = step.tool;
  if (/search|find|lookup|match/.test(tool)) return <Search aria-hidden className={glyph} />;
  if (/fill|write|save|set|create|update|draft|rewrite|_do$/.test(tool)) return <PenLine aria-hidden className={glyph} />;
  if (/list|recent|read|get|show|open|summar/.test(tool)) return <FileText aria-hidden className={glyph} />;
  return <Sparkle aria-hidden className={glyph} />;
}

/** The account result links are filled in for; provided by the panel, null in the admin realm. */
export const ResultSlug = createContext<string | null>(null);

/** What a lookup found, each title a link to its own screen when it has one. */
export function ResultList({ results }: { results: StepResults }) {
  const slug = useContext(ResultSlug);
  const more = results.total - results.items.length;
  return (
    <ul className="space-y-1 border-l border-line py-0.5 pl-3">
      {results.items.map((item, index) => {
        const href = consoleHref(item.href, slug);
        return (
          <li key={`${index}-${item.title}`} className="min-w-0">
            {href ? (
              <Link
                href={href}
                className="font-medium text-ink underline decoration-line underline-offset-2 [overflow-wrap:anywhere] hover:decoration-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                {item.title}
              </Link>
            ) : (
              <span className="font-medium text-ink [overflow-wrap:anywhere]">{item.title}</span>
            )}
            {item.subtitle ? <span className="block [overflow-wrap:anywhere]">{item.subtitle}</span> : null}
          </li>
        );
      })}
      {more > 0 ? <li>and {more} more</li> : null}
    </ul>
  );
}
