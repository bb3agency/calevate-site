"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { formatDuration, formatIST } from "@/components/ui";
import { CopyButton } from "@/components/interior/copy-button";
import { LiveDot } from "@/components/console/liveCalls";
import type { CallDetail } from "@/lib/api/client";

import { CallState, isLive } from "../callColumns";

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/**
 * WHAT HAPPENED ON THIS CALL, in one block: who, when, how it ended, the summary and the
 * details the agent captured. These are the answer most visits want, so they sit together
 * above everything else rather than in separate panels down the page.
 *
 * The number is printed in full (D-436) and is TEXT, never an `href` (hard rule 6). The
 * summary is the API's redacted text; the captured fields are the agent's extraction
 * schema, the same keys that become the Leads columns.
 */
export function CallHeader({ detail, leadHref }: { detail: CallDetail; leadHref: string | null }) {
  const captured = Object.entries((detail.extraction ?? {}) as Record<string, unknown>);
  return (
    <section
      aria-label="Call summary"
      className="rounded-card border border-line bg-surface p-4 shadow-card sm:p-5"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {isLive(detail) && <LiveDot />}
        <span className="text-xl font-semibold tabular-nums tracking-tight text-ink">
          {detail.caller_e164 ?? "Unknown number"}
        </span>
        {detail.caller_e164 && <CopyButton value={detail.caller_e164} label="Copy phone number" />}
        <CallState call={detail} />
      </div>
      <p className="mt-1 text-[13px] text-ink-muted">
        {formatIST(detail.started_at)} · {formatDuration(detail.duration_s)} ·{" "}
        {detail.agent_name ?? "Agent"} · <span className="capitalize">{detail.direction}</span>
        {detail.sentiment ? (
          <>
            {" · "}
            <span className="capitalize">{detail.sentiment}</span>
          </>
        ) : null}
      </p>

      {(detail.summary || leadHref) && (
        <div className="mt-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          {detail.summary && (
            <p className="max-w-prose text-[15px] leading-relaxed text-ink">{detail.summary}</p>
          )}
          {leadHref && (
            <Link
              href={leadHref}
              className="inline-flex items-center gap-1 rounded-sm text-sm font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
            >
              Open the lead
              <ArrowRight aria-hidden className="h-3.5 w-3.5" />
            </Link>
          )}
        </div>
      )}

      {captured.length > 0 && (
        <div className="mt-4 border-t border-line pt-4">
          <h2 className="mb-2 text-[13px] font-medium text-ink-muted">Captured details</h2>
          {/* dt/dd are DIRECT children of one wrapper div each — a <dl> accepts a div that
              groups a dt/dd pair and nothing deeper (axe definition-list / dlitem). */}
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 lg:grid-cols-3">
            {captured.map(([key, value]) => {
              // A field the extractor flagged for a person to confirm before acting on it.
              // The value still shows — it is usable — with the reason beneath it.
              const review = detail.extraction_needs_review?.[key];
              return (
                <div key={key} className="min-w-0">
                  <dt className="text-[12px] capitalize text-ink-faint">{key.replace(/_/g, " ")}</dt>
                  <dd className="break-words text-sm font-medium text-ink">{formatValue(value)}</dd>
                  {review && <dd className="mt-1 text-xs text-warn">{review}</dd>}
                </div>
              );
            })}
          </dl>
          {!detail.extraction_valid && (
            <p className="mt-3 text-xs text-warn">
              We could not capture some details cleanly from this call.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
