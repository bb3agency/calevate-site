"use client";

import { useState } from "react";
import { Gauge, Timer, TriangleAlert } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import {
  Card,
  EmptyState,
  FilterChip,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  ScrollRegion,
  Skeleton,
  StatTile,
  formatCount,
} from "@/components/ui";
import {
  BASIS_COPY,
  DEFAULT_WINDOW_DAYS,
  WINDOW_CHOICES,
  budgetVerdict,
  formatMs,
  regionLabel,
  useEngineLatency,
  type BudgetVerdict,
  type EngineLatencyReport,
  type LatencyGroup,
} from "@/lib/api/engineLatency";
import { lookup } from "@/lib/lookup";

/**
 * WHAT THE VOICE ENGINE'S OWN PIPELINE COST, BY REGION — the console half of
 * `GET /v1/ops/engine-latency` (OPERATIONS §2 gate 4).
 *
 * ## Why this screen exists
 *
 * The endpoint shipped with no path in the console, so the two documents that need it
 * pointed at a curl: OPERATIONS §2 gate 4 ("place the calls, read `GET
 * /v1/ops/engine-latency` grouped by `region`") and `runbooks/alarm-index.md`, whose entry
 * for `engine_llm_ttft_degraded` opens *"Read `GET /v1/ops/engine-latency` first"*. That is
 * an operator hand-assembling a request against production, mid-incident, from the
 * document people follow when they are least careful — the exact argument
 * `app/admin/ops/page.tsx` makes for why the load-shed switch, the outbox replay and the
 * audit-chain verification are controls rather than curls.
 *
 * ## It is a REPORT, not a dashboard, and three things follow
 *
 * 1. **Nothing here is derived.** Every percentile, every count and the budget verdict are
 *    the server's own fields. `apps/api/ops/engine_latency.py` withholds a p95 below 20
 *    timed turns and a p50 below 5, and publishes `basis` so the withholding is a fact
 *    rather than a gap — a console that filled either in from the maximum would be
 *    printing the largest sample wearing a percentile's name, which is the one thing that
 *    module refuses to do.
 * 2. **`budget_breached` has THREE states and is rendered as three.** True is "the typical
 *    turn missed our target", false is "it did not", and `null`/absent is "the sample
 *    cannot support a median" — which must never render like the second. The budget itself
 *    is read off the payload (`llm_ttft_budget_ms`) rather than from a constant in this
 *    bundle, because a target restated in the browser is a target that quietly becomes
 *    whatever the last build believed.
 * 3. **§52 without exception.** Loading is a skeleton, a failed read is a refusal, and
 *    neither is "no turns were measured". "The engine reported nothing" is a claim about
 *    our own instrumentation — the sentence an operator would act on by going to look for
 *    a broken adapter — and a 500 is not evidence for it.
 *
 * ## What it deliberately does not say
 *
 * **Not voice-to-voice latency.** Both ends of that interval are on the PSTN leg this
 * stack is not in (D-25/D-33), which is why `calls.latency` was dropped and stays dropped.
 * These are the engine's numbers about the engine's own pipeline. The stopwatch that says
 * whether they resemble what a caller HEARS is gate 4's, and a human types it in.
 *
 * **Not gate 4's verdict.** The gate is answered by comparing two rows that both carry a
 * median, and the rule that counts them (`EngineLatencyReport.regions_measured`) is a
 * Python `@property` — not a wire field, and nothing reads it. Restating it in this bundle
 * would be a second spelling of a rule that already exists; the table shows each group's
 * own `basis` and the reader compares two rows.
 *
 * ## Permission
 *
 * `ops:manage`, which only `superadmin` holds (`core/rbac.py`), asked of `GET
 * /v1/admin/me` rather than derived from this screen's own 403 — so an `operator` sent
 * here by the runbook is told why in a sentence instead of being handed a refusal that
 * reads like an outage.
 *
 * Unlike `/admin/ops/dnc`, the answer gates the READ and not only a control: this screen
 * is one GET, so a session the server refuses has nothing left to look at, and firing the
 * request anyway would paint the permission as a red failure box with a retry button whose
 * only outcome is another 403. It is still a PREVIEW and never the enforcement — the API
 * refuses on its own, the `ProblemNotice` below stays as the backstop for every other way
 * a read can fail, and the withholding happens only on a definite refusal (see the hook
 * call for why `!refused` rather than `allowed`).
 *
 * No `<h1>`: the shell derives the title from the nav list it also renders the sidebar
 * from (`app/admin/layout.tsx`).
 */
export default function EngineLatencyPage() {
  const [days, setDays] = useState(DEFAULT_WINDOW_DAYS);
  /**
   * The READ carries `ops:manage` here, unlike `/admin/ops/dnc` where only the writes do
   * — this whole screen is one GET, so a session the server refuses has nothing left to
   * look at. That is why the answer gates the query rather than only a control.
   *
   * `!access.refused` and NOT `access.allowed`, and the difference is `access.ts`'s two
   * booleans doing the job they exist for. `refused` is the server having ANSWERED "you
   * may not"; `allowed` is false while the identity read is merely in flight or has
   * itself failed. Gating on `allowed` would make a slow or dead `/v1/admin/me` lock an
   * operator out of an incident read the API would have served — the failure the module
   * spells out as "navigation fails open, the API is the enforcement". So the report is
   * fetched on the unknown and withheld only on a refusal.
   */
  const access = useAdminAccess("ops:manage", "read the engine's latency report");
  const report = useEngineLatency(days, !access.refused);

  return (
    <div className="space-y-4 pb-12">
      <p className="text-sm text-ink-muted">
        How long the AI takes to start replying — its &ldquo;time to first reply&rdquo; —
        measured on each reply and grouped by the region the engine ran the call in. These
        are the engine&rsquo;s own figures about its own pipeline. They are not what a
        caller actually hears on the phone from end to end, which is a stopwatch
        measurement nobody can take from here.
      </p>

      {access.refused ? (
        /* The refusal INSTEAD of the report, never beside it. A disabled window picker
           over a red "we could not read this" box describes an outage, and this is a
           permission working exactly as designed — the distinction `admin/ops/dnc` draws
           for a control, applied to a screen whose entire subject is one refused read. */
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Choose a window"
          >
            {WINDOW_CHOICES.map((choice) => (
              <FilterChip
                key={choice}
                label={`Last ${windowLabel(choice)}`}
                active={choice === days}
                onClick={() => setDays(choice)}
              />
            ))}
          </div>

          {report.error != null && (
            <ProblemNotice error={report.error} onRetry={() => void report.refetch()} />
          )}

          {/* §52. `!report.data` covers all three ways to have no answer — in flight,
              failed, and the paused query a console tab open across a dropped connection
              produces (`lib/api/client.ts` calls that the normal case). Only the first
              gets a skeleton; the other two are answered by the refusal above. */}
          {!report.data ? (
            report.error ? null : (
              <Card>
                <Skeleton rows={6} label="Loading the engine's latency report" />
              </Card>
            )
          ) : (
            <Report report={report.data} />
          )}
        </>
      )}
    </div>
  );
}

/**
 * "7 days", and "1 day" rather than "1 days".
 *
 * One spelling for the chips and for the header tile, so the control an operator clicked
 * and the figure they are reading name the same period in the same words.
 */
function windowLabel(days: number): string {
  return `${formatCount(days)} ${days === 1 ? "day" : "days"}`;
}

/**
 * The report, given one that ARRIVED.
 *
 * Takes the payload rather than the query envelope for the reason every board in this
 * console does: each sentence below is a claim about what the engine measured, and a
 * component that cannot see `undefined` cannot accidentally make one out of it.
 */
function Report({ report }: { report: EngineLatencyReport }) {
  const budget = report.llm_ttft_budget_ms;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {/* The target is TRD §4's LLM time-to-first-token budget. Kept as a number,
            described in plain words on screen — the spec reference stays here, not there. */}
        <StatTile
          label="Target for the first reply"
          value={formatMs(budget)}
          icon={<Gauge aria-hidden className="h-5 w-5" />}
          hint="Our goal: the AI should start replying within this long. It's a target we set, not a measurement — this report is the first thing that can show whether we're meeting it."
        />
        <StatTile
          label="Rows in this window"
          /* NOT "rows measured": a row with three replies is IN the window and is
             precisely the one the server declined to summarise, so counting it under that
             word would state a measurement that was refused one column to the right. */
          value={formatCount(report.groups.length)}
          icon={<Timer aria-hidden className="h-5 w-5" />}
          hint="One row for each engine and region we saw in this window. Each row is judged on its own typical reply time."
        />
        {/* The window the SERVER answered for, not the one the chips asked for: the route
            clamps `days` to its own bounds, and a header quoting the request would describe
            a period the figures beside it are not about. */}
        <StatTile label="Window" value={windowLabel(report.window_days)} />
      </div>

      {/* The server says when it stopped counting. A subset described as a distribution is
          the defect `ExecutionListing.complete` exists for, and it is worse here than
          elsewhere: the rows it dropped are the busiest tenant's, which is the tenant whose
          latency an operator is most likely to be asked about. */}
      {!report.complete && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="These figures cover only part of the window"
        >
          <p className="mt-1">
            One or more accounts had so much traffic in this window that we only measured
            part of it, so the figures below are worked out from some of its calls rather
            than all of them. Narrow the window to get a complete answer.
          </p>
        </NoticeBox>
      )}

      <Card title="How quickly the AI starts replying, by engine and region" bodyClassName="p-2">
        {report.groups.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="No timed replies in this window"
              hint="The engine records these on every call, so an empty window means either that no calls finished in this period, or that the calls that did finish came back with no timings. Widen the window before assuming the second."
            />
          </div>
        ) : (
          <ScrollRegion label="How quickly the AI starts replying, by engine and region">
            <table className="w-full text-left text-xs">
              <thead className="text-ink-muted">
                <tr>
                  <HeadCell label="Engine" />
                  <HeadCell label="Region" />
                  <HeadCell label="Calls" />
                  <HeadCell label="Replies" gloss="One back-and-forth exchange" />
                  <HeadCell
                    label="Typical reply"
                    gloss="Half of replies were at least this fast"
                  />
                  {/* "p95" kept as the plain-English label an operator can act on, with the
                      technical term in parentheses and a one-line gloss beneath it. */}
                  <HeadCell
                    label="Slowest typical reply (95th percentile)"
                    gloss="95 out of 100 replies were at least this fast"
                  />
                  <HeadCell label="Worst reply" gloss="The single slowest reply" />
                  <HeadCell label="Over target" gloss="Replies slower than our target" />
                  <HeadCell label="Verdict" gloss="The typical reply vs our target" />
                </tr>
              </thead>
              <tbody>
                {report.groups.map((group) => (
                  <GroupRow key={`${group.engine}:${group.region ?? ""}`} group={group} />
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
        {/* The sample-size rule in words, with NO threshold in it. The two minimums are
            constants in `apps/api/ops/engine_latency.py` and are not on the wire, so a
            figure typed here would be a copy that goes stale silently — see
            `lib/api/engineLatency.ts::BASIS_COPY`. What a reader needs is which cells are
            a refusal and which are a number, and that does not depend on the value. */}
        <p className="mt-3 px-2 text-xs text-ink-muted">
          We don&rsquo;t show a typical or slowest-typical reply time until we&rsquo;ve
          timed enough replies to trust it, so a blank cell means we don&rsquo;t have enough
          replies yet — it is never zero. The worst single reply is shown no matter how few
          replies there are, because it is one real measurement rather than an estimate.
        </p>
      </Card>
    </div>
  );
}

/**
 * How each verdict reads, and how it is painted.
 *
 * Keyed by the union `budgetVerdict` returns, so a fourth state added there fails `tsc`
 * here rather than rendering a blank cell. The unknown arm is deliberately NOT muted into
 * invisibility: "we could not tell" is the answer an operator has to act on by placing
 * more calls, and a cell that looked empty would read as "nothing wrong".
 */
const VERDICT_COPY: Record<BudgetVerdict, { label: string; className: string }> = {
  over: {
    label: "over target",
    className: "font-semibold text-rose-600 dark:text-rose-400",
  },
  within: {
    label: "within target",
    className: "font-medium text-brand-strong dark:text-brand-bright",
  },
  unknown: {
    label: "not enough replies",
    className: "text-ink-muted",
  },
};

/**
 * One column header: a plain label, and an optional one-line gloss beneath it.
 *
 * A component rather than repeated `<th>` markup so the metric jargon is translated in
 * exactly one shape — the operator reading this screen is not an engineer, so "typical
 * reply" and "slowest typical reply (95th percentile)" carry a sentence saying what the
 * number actually means, right under the column it labels.
 */
function HeadCell({ label, gloss }: { label: string; gloss?: string }) {
  return (
    <th scope="col" className="py-1 pr-3 align-top font-medium">
      {label}
      {gloss && (
        <span className="mt-0.5 block text-[11px] font-normal text-ink-faint">{gloss}</span>
      )}
    </th>
  );
}

function GroupRow({ group }: { group: LatencyGroup }) {
  const verdict = VERDICT_COPY[budgetVerdict(group)];
  /**
   * `basis` comes off the wire, so it is read through `lookup` and not indexed
   * (`lib/lookup.ts`). TWO absences collapse to the same rendering — nothing — and both
   * are correct: `undefined` is a basis this build has no words for (a server that grew a
   * third one, where inventing a sentence is how a screen starts describing a state it has
   * never seen), and `null` is the table saying this state needs no sentence.
   */
  const basis = lookup(BASIS_COPY, group.basis);

  return (
    <tr className="border-t border-line align-top">
      {/* The engine is a vendor identifier an operator greps their own logs for, so it is
          shown fixed-width where 0/O and 1/l stay distinct. */}
      <td className="py-1.5 pr-3">
        <MonoValue>{group.engine}</MonoValue>
      </td>
      <td className="py-1.5 pr-3">
        {regionLabel(group.region)}
        {basis != null && (
          <span className="mt-0.5 block text-[11px] text-ink-faint">{basis}</span>
        )}
      </td>
      <td className="py-1.5 pr-3 tabular-nums">{formatCount(group.calls)}</td>
      <td className="py-1.5 pr-3 tabular-nums">{formatCount(group.turns)}</td>
      <td className="py-1.5 pr-3 tabular-nums">{formatMs(group.llm_ttft_p50_ms)}</td>
      <td className="py-1.5 pr-3 tabular-nums">{formatMs(group.llm_ttft_p95_ms)}</td>
      <td className="py-1.5 pr-3 tabular-nums">{formatMs(group.llm_ttft_max_ms)}</td>
      <td className="py-1.5 pr-3 tabular-nums">
        {formatCount(group.turns_over_budget)}
        {group.turns > 0 && (
          <span className="text-ink-faint"> of {formatCount(group.turns)}</span>
        )}
      </td>
      <td className={`py-1.5 pr-3 ${verdict.className}`}>{verdict.label}</td>
    </tr>
  );
}
