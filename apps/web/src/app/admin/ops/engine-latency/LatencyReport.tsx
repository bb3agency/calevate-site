"use client";

import { Section } from "@/components/console/section";
import { TriangleAlert } from "lucide-react";

import { MonoValue } from "@/app/admin/ops/opsLanguage";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { Disclosure, NoticeBox, formatCount } from "@/components/ui";
import {
  BASIS_COPY,
  BUDGET_GAP_BODY,
  BUDGET_GAP_TITLE,
  INHERITED_WAIT_NOTE,
  LEG_COPY,
  UNVERIFIED_UNIT_NOTE,
  budgetVerdict,
  formatMs,
  regionLabel,
  type BudgetVerdict,
  type EngineLatencyReport,
  type LatencyBudget,
  type LatencyGroup,
  type LegSummary,
} from "@/lib/api/engineLatency";
import { lookup } from "@/lib/lookup";

/**
 * The report, given one that arrived — a component that cannot see `undefined` cannot
 * make a claim out of it.
 *
 * The verdict line COUNTS the server's per-leg verdicts (`budgetVerdict`, three-state); it
 * derives no percentile. A row with any `over` leg is over; a row with an `unknown` leg and
 * no `over` one is counted separately, so "we could not tell" never reads as "fine".
 */
export function LatencyReport({
  report,
  windowLabel,
}: {
  report: EngineLatencyReport;
  windowLabel: string;
}) {
  const verdicts = report.groups.map((group) => group.legs.map(budgetVerdict));
  const rowsOver = verdicts.filter((v) => v.includes("over")).length;
  const rowsUnknown = verdicts.filter((v) => !v.includes("over") && v.includes("unknown")).length;

  return (
    <div className="space-y-5">
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-body text-ink">
        <span className={rowsOver > 0 ? "font-semibold text-danger" : "font-semibold"}>
          {formatCount(rowsOver)} of {formatCount(report.groups.length)}
        </span>
        <span>{report.groups.length === 1 ? "row" : "rows"} over target</span>
        {rowsUnknown > 0 && (
          <span className="text-ink-muted">
            · {formatCount(rowsUnknown)} more row(s) could not be judged — not the same as fine
          </span>
        )}
        <span className="text-ink-muted">
          · whole-reply target <span className="font-medium text-ink">{formatMs(report.budget.turn_ms)}</span>
        </span>
        {/* The window the SERVER answered for: the route clamps `days`, and a line quoting
            the request would describe a period the figures are not about. */}
        <span className="text-ink-muted">
          · last <span className="font-medium text-ink">{windowLabel}</span>
        </span>
        <InfoTip label="How rows are judged">
          <p>
            One row for each engine and region seen in this window. A row is over target when
            any of its stages is, by the server&apos;s own verdicts, each stage judged on its own
            typical time.
          </p>
          <p>
            The whole-reply target is our goal for the three stages the engine measures, added
            together — a target we set, not a measurement.
          </p>
        </InfoTip>
      </p>

      {/* The shortfall, stated where an operator will see it. `composes` is the server's
          verdict and the three figures are its fields: this states a gap, never works one
          out. Above everything else because it changes how every target should be read. */}
      {report.budget.composes === false && (
        <NoticeBox tone="warn" icon={<TriangleAlert aria-hidden className="h-5 w-5" />} title={BUDGET_GAP_TITLE}>
          <p className="mt-1">{BUDGET_GAP_BODY}</p>
          <dl className="mt-3 grid gap-3 sm:grid-cols-3">
            <BudgetItem
              label="What a caller should wait"
              value={report.budget.voice_to_voice_p50_ms}
              note="The end-to-end goal, from the caller finishing their sentence to hearing the reply begin."
            />
            <BudgetItem
              label="What the stages add up to, at best"
              value={report.budget.voice_to_voice_floor_ms}
              note="Every stage at the fastest figure its supplier publishes, plus the trip to the engine's servers and back."
            />
            {/* A sign flip, not a calculation: the headroom is the server's field and is
                negative when the stages overrun. "Short by 100 ms" is the fact an operator
                acts on; "-100 ms left over" reads as a rendering bug. */}
            <BudgetItem
              label="Short by"
              value={-report.budget.voice_to_voice_headroom_p50_ms}
              note="How much longer the stages take than the end-to-end goal allows. Nothing on this page can close it."
            />
          </dl>
        </NoticeBox>
      )}

      {/* The rows the server dropped are the busiest account's — the one an operator is
          most likely to be asked about — so a subset never reads as the whole. */}
      {!report.complete && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="These figures cover only part of the window"
        >
          <p className="mt-1">
            Some accounts had so much traffic that only part of it was measured. Narrow the
            window to get a complete answer.
          </p>
        </NoticeBox>
      )}

      {report.groups.length === 0 ? (
        <Section title="How long a reply takes, by engine and region">
          <EmptyState
            message={
              <>
                No timed replies in this window{" "}
                <InfoTip label="An empty window">
                  <p>It means one of three things, and they are not the same:</p>
                  <p>
                    no call finished in this period; calls finished and came back with no
                    timings; or the engine placing them reports no per-turn timings at all, in
                    which case this report will stay empty however wide the window.
                  </p>
                  <p>Widen the window before assuming either of the last two.</p>
                </InfoTip>
              </>
            }
          />
        </Section>
      ) : (
        report.groups.map((group) => (
          <GroupCard key={`${group.engine}:${group.region ?? ""}`} group={group} />
        ))
      )}

      <BudgetDisclosure budget={report.budget} />
    </div>
  );
}

/**
 * Every target TRD §4 declares, read straight off `report.budget` — the composed totals
 * and the headroom included, since those are `computed_field`s on the server. A budget
 * computed in a browser quietly becomes whatever the last build believed.
 *
 * Disclosed rather than shown: it is reference, and the rows above already carry each
 * measured stage's own target. A `<dl>`: these are labelled values, not a distribution.
 */
function BudgetDisclosure({ budget }: { budget: LatencyBudget }) {
  return (
    <Disclosure
      title="What we are aiming for"
      subtitle={`Whole reply ${formatMs(budget.turn_ms)}; a caller should hear ${formatMs(budget.voice_to_voice_p50_ms)} typically.`}
    >
      <p className="text-meta text-ink-muted">
        Every figure here is a goal we set, not something we have measured.
      </p>
      <dl className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {/* First because it happens first. No row in the tables: the engine reports no
            figure for it, and an empty row would read as fast. */}
        <BudgetItem
          label="Noticing the caller stopped"
          value={budget.endpointing_ms}
          note="How long we wait, after the caller stops making a sound, before deciding they have finished. Nothing measures this stage, and the setting we actually run is far higher — see below."
        />
        <BudgetItem label={LEG_COPY.stt.label} value={budget.stt_ms} note={LEG_COPY.stt.gloss} />
        <BudgetItem label={LEG_COPY.llm_ttft.label} value={budget.llm_ttft_ms} note={LEG_COPY.llm_ttft.gloss} />
        <BudgetItem label={LEG_COPY.tts_ttfa.label} value={budget.tts_ttfa_ms} note={LEG_COPY.tts_ttfa.gloss} />
        {/* A lookup CAN happen mid-reply (the in-process pack search, PIPECAT-MIGRATION §8.1),
            but nothing times it: `LatencyLeg` has no `retrieval` member. Shown because the
            sums below are cut from it. */}
        <BudgetItem
          label="Looking something up"
          value={budget.retrieval_ms}
          note="Our goal for a lookup in the middle of a reply. Nothing times this stage, so it has a goal here and no row above."
        />
        <BudgetItem label={LEG_COPY.turn.label} value={budget.turn_ms} note="The three stages the engine measures, added together." />
        <BudgetItem
          label="A reply that needed a lookup"
          value={budget.pipeline_ms}
          note="All four stages together — everything we have set a goal for."
        />
        <BudgetItem
          label="What the caller should hear, typically"
          value={budget.voice_to_voice_p50_ms}
          note="From the caller finishing their sentence to hearing the reply begin. Only a stopwatch on a real call can measure it."
        />
        <BudgetItem
          label="What the caller should hear, at worst"
          value={budget.voice_to_voice_p95_ms}
          note="The same, for the slowest 1 reply in 20 — and it needs far more calls than a pilot places."
        />
        <BudgetItem
          label="Getting to the engine and back"
          value={budget.india_us_transit_floor_ms}
          note="The shortest India-to-United-States round trip our rented voice platform publishes — a supplier figure, not a measurement. On a runtime hosted closer to the caller it overstates the trip."
        />
        <BudgetItem
          label="Everything, at best"
          value={budget.voice_to_voice_floor_ms}
          note="All the stages plus the trip, each at the fastest figure its supplier publishes."
        />
        <BudgetItem
          label="Left over for everything else"
          value={budget.voice_to_voice_headroom_p50_ms}
          note="What the typical-reply goal leaves for the caller's connection, their carrier and the untimed gaps. A negative figure means there is nothing left."
        />
        {/* A setting, not a goal, and in no total — the one number here an operator can
            change without changing a supplier. */}
        <BudgetItem label="What we actually wait today" value={budget.inherited_turn_detection_ms} note={INHERITED_WAIT_NOTE} />
      </dl>
    </Disclosure>
  );
}

/** One labelled target. The value is formatted, never computed. */
function BudgetItem({ label, value, note }: { label: string; value: number; note: string }) {
  return (
    <div>
      <dt className="text-meta text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-body font-medium tabular-nums">{formatMs(value)}</dd>
      <dd className="mt-0.5 text-meta text-ink-muted">{note}</dd>
    </div>
  );
}

/**
 * Keyed by `budgetVerdict`'s union, so a fourth state fails `tsc` here. The unknown arm is
 * not muted into invisibility: "we could not tell" is acted on by placing more calls, and
 * a blank-looking cell would read as "nothing wrong".
 */
const VERDICT_COPY: Record<BudgetVerdict, { label: string; className: string }> = {
  over: { label: "over target", className: "font-semibold text-danger" },
  within: { label: "within target", className: "font-medium text-brand-strong dark:text-brand-bright" },
  unknown: { label: "not enough replies", className: "text-ink-muted" },
};

/** A header whose explanation sits behind an ⓘ; the column's name stays its accessible name. */
function glossed(label: string, gloss: string) {
  return function GlossedHeader() {
    return (
      <span className="inline-flex items-center gap-0.5">
        <span aria-hidden>{label}</span>
        <InfoTip label={label}>{gloss}</InfoTip>
      </span>
    );
  };
}

/*
 * One row per stage, each judged against its OWN target (`leg.budget_ms` comes per row):
 * a single fleet-wide verdict is how a reply that spent its budget in the transcriber was
 * once reported as fine. Below `sm` the figures collapse into the stage cell.
 */
const COLUMNS: DataColumn<LegSummary>[] = [
  {
    id: "stage",
    header: "Stage",
    cell: (leg) => <StageCell leg={leg} />,
  },
  {
    id: "target",
    header: "Target",
    hideBelow: "sm",
    className: "tabular-nums",
    cell: (leg) => formatMs(leg.budget_ms),
  },
  {
    id: "replies",
    header: "Replies",
    renderHeader: glossed("Replies", "Replies that reported this stage."),
    hideBelow: "md",
    className: "tabular-nums",
    cell: (leg) => formatCount(leg.turns),
  },
  {
    id: "typical",
    header: "Typical",
    renderHeader: glossed("Typical", "Half of replies were at least this fast."),
    hideBelow: "sm",
    className: "tabular-nums",
    cell: (leg) => formatMs(leg.p50_ms),
  },
  {
    id: "p95",
    header: "Slowest typical",
    renderHeader: glossed("Slowest typical", "The 95th percentile: 95 out of 100 replies were at least this fast."),
    hideBelow: "sm",
    className: "tabular-nums",
    cell: (leg) => formatMs(leg.p95_ms),
  },
  {
    id: "worst",
    header: "Worst",
    renderHeader: glossed("Worst", "The single slowest reply, shown at any sample size."),
    hideBelow: "sm",
    className: "tabular-nums",
    cell: (leg) => formatMs(leg.max_ms),
  },
  {
    id: "over",
    header: "Over target",
    renderHeader: glossed("Over target", "Replies slower than the target."),
    hideBelow: "md",
    className: "tabular-nums",
    cell: (leg) => (
      <>
        {formatCount(leg.turns_over_budget)}
        {leg.turns > 0 && <span className="text-ink-muted"> of {formatCount(leg.turns)}</span>}
      </>
    ),
  },
  {
    id: "verdict",
    header: "Verdict",
    hideBelow: "sm",
    cell: (leg) => {
      const verdict = VERDICT_COPY[budgetVerdict(leg)];
      return <span className={verdict.className}>{verdict.label}</span>;
    },
  },
];

function legId(leg: LegSummary): string {
  return leg.leg;
}

function StageCell({ leg }: { leg: LegSummary }) {
  // `basis` and `leg` come off the wire, so both are read through `lookup`. A `null` basis
  // is the table saying "nothing to explain"; `undefined` is one this build has no words
  // for, and inventing a sentence for it would describe a state never seen.
  const basis = lookup(BASIS_COPY, leg.basis);
  const copy = lookup(LEG_COPY, leg.leg);
  const verdict = VERDICT_COPY[budgetVerdict(leg)];
  return (
    <div className="sm:min-w-[10rem] sm:max-w-[22rem]">
      <span className="font-medium text-ink">{copy?.label ?? <MonoValue>{leg.leg}</MonoValue>}</span>
      {copy && <span className="mt-0.5 block text-meta text-ink-muted">{copy.gloss}</span>}
      {basis != null && <span className="mt-0.5 block text-meta text-ink-muted">{basis}</span>}
      {/* The server's own doubt: a verdict on a number whose unit nobody has confirmed is
          not a verdict, so the row says so (hard rule 11). */}
      {!leg.unit_verified && <span className="mt-0.5 block text-meta text-warn">{UNVERIFIED_UNIT_NOTE}</span>}
      <span className="mt-1.5 block text-meta text-ink-muted sm:hidden">
        <span className={verdict.className}>{verdict.label}</span> · typical {formatMs(leg.p50_ms)} ·
        slowest typical {formatMs(leg.p95_ms)} · worst {formatMs(leg.max_ms)}
      </span>
    </div>
  );
}

function GroupCard({ group }: { group: LatencyGroup }) {
  const heading = `${group.engine} — ${regionLabel(group.region)}`;
  return (
    <Section title={heading}>
      <p className="flex flex-wrap items-center gap-x-1 px-4 text-meta text-ink-muted">
        {formatCount(group.calls)} {group.calls === 1 ? "call" : "calls"} ·{" "}
        {formatCount(group.turns)} timed {group.turns === 1 ? "reply" : "replies"} · a blank cell
        means too few replies yet, never zero
        <InfoTip label="Blank cells and counts">
          <p>
            We don&rsquo;t show a typical or slowest-typical time until we&rsquo;ve timed enough
            replies to trust it. The worst single reply is shown however few there are,
            because it is one real measurement rather than an estimate.
          </p>
          <p>Each stage counts only the replies that reported it, so the counts differ by row.</p>
        </InfoTip>
      </p>
      <DataTable
        rows={group.legs}
        columns={COLUMNS}
        getRowId={legId}
        label={`Reply stages for ${group.engine}, region ${group.region ?? "not reported"}`}
      />
    </Section>
  );
}
