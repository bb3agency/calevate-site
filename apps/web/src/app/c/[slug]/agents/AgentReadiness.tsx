"use client";

/**
 * THE READINESS SCORE (D-870) on the agent pages: the kit `Gauge` with what to fix on one
 * agent's Overview, and a compact score on each row of the roster.
 *
 * The score, its parts and the fixes are the server's (`GET /v1/agents/{id}/readiness`,
 * `GET /v1/readiness`); nothing here recomputes them. Each fix's `href` is realm-relative
 * ("/agents/{id}?section=script"), so it is joined to this account's `/c/{slug}` and then
 * passed through the realm's `href()`, which keeps an operator's view-as on the link.
 */

import clsx from "clsx";

import { Gauge, READINESS_BANDS, type GaugeBand } from "@/components/arc/gauge";
import { Disclosure, ProblemNotice, Skeleton } from "@/components/ui";
import { useAgentReadiness, type AgentReadiness } from "@/lib/api/readiness";
import { useClientRealm, useClientSession } from "@/lib/api/session";

/** The band a score falls in, by the same bands the gauge draws. */
export function readinessBand(score: number, bands: GaugeBand[] = READINESS_BANDS): GaugeBand | undefined {
  return [...bands].sort((a, b) => b.from - a.from).find((b) => score >= b.from);
}

const BAND_PILL = {
  danger: "bg-danger-soft text-danger",
  warn: "bg-warn-soft text-warn",
  good: "bg-brand-soft text-brand-strong",
} as const;

/**
 * The roster's score: the number and the band in words, so colour is never the only
 * signal. `null` (no score in the read) renders nothing rather than a guess.
 */
export function ReadinessScore({ score }: { score: number | null | undefined }) {
  if (score === null || score === undefined) return null;
  const band = readinessBand(score);
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-meta font-medium tabular-nums",
        band ? BAND_PILL[band.tone] : "bg-surface-muted text-ink-muted",
      )}
    >
      <span className="sr-only">Readiness </span>
      {score}
      <span aria-hidden>·</span>
      <span className="sr-only">out of 100,</span>
      {band?.label}
    </span>
  );
}

export function fixesFor(data: AgentReadiness, link: (path: string) => string) {
  return data.fixes.map((fix, index) => ({
    id: `${fix.component}-${index}`,
    label: fix.action,
    points: fix.points,
    href: link(fix.href),
  }));
}

/** One agent's score with what to fix, on its Overview. */
export function AgentReadinessPanel({ agentId, slug }: { agentId: string; slug: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const readiness = useAgentReadiness(session, agentId);
  const link = (path: string) => href(`/c/${slug}${path}`);

  return (
    <section aria-labelledby="readiness-heading" className="space-y-3">
      <h2 id="readiness-heading" className="text-heading text-ink">
        How ready it is
      </h2>
      {readiness.isLoading ? (
        <Skeleton rows={3} label="Working out how ready it is" />
      ) : readiness.error ? (
        <ProblemNotice error={readiness.error} onRetry={() => void readiness.refetch()} />
      ) : readiness.data ? (
        <>
          <Gauge
            value={readiness.data.score}
            label="Readiness"
            fixes={fixesFor(readiness.data, link)}
            fixesTitle="Fix these to raise it"
            allDoneText="Nothing to fix. Ready for callers."
            pointsLabel={(points) => `+${points}`}
          />
          <Disclosure variant="inline" headingLevel={3} title="How the score is made">
            <ul className="divide-y divide-line">
              {readiness.data.components.map((part) => (
                <li key={part.key} className="flex items-start justify-between gap-3 py-2">
                  <span className="min-w-0">
                    <span className="block text-body text-ink">{part.label}</span>
                    <span className="block text-meta text-ink-muted">{part.detail}</span>
                  </span>
                  <span className="shrink-0 text-meta font-medium tabular-nums text-ink">
                    {part.points} of {part.max_points}
                  </span>
                </li>
              ))}
            </ul>
          </Disclosure>
        </>
      ) : null}
    </section>
  );
}
