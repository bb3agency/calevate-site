"use client";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import { Section } from "@/components/console/section";
import { Disclosure } from "@/components/ui";
import { BASIS_NOTE, renderMeasurement, type QaReport } from "@/lib/api/quality";
import { StatusPill } from "@/components/console/statusPill";

import { WhyTip } from "../agreements/_ui/WhyTip";
import { QUALITY_COPY as COPY, monthEnding, tricky, verdictLine } from "./copy";

type ScenarioRow = NonNullable<QaReport["scenario_classes"]>[number];
type LimitRow = NonNullable<QaReport["known_limits"]>[number];

/**
 * The verdict, as the header's status. The headline is the DEFECT count, not the pass rate
 * (`scripts/qa_report.py`): the pass rate measures our offline stand-in extractor, the
 * defect count measures the promise we make. The words carry it; colour is the second
 * channel (WCAG 1.4.1).
 */
export function VerdictPill({ report }: { report: QaReport }) {
  const clean = report.defects === 0;
  return (
    <StatusPill tone={clean ? "ok" : "stop"}>
      {verdictLine(report.defects, report.scenarios_total)}
    </StatusPill>
  );
}

const SCENARIO_COLUMNS: DataColumn<ScenarioRow>[] = [
  {
    id: "label",
    header: COPY.colTests,
    cell: (row) => (
      <>
        <span className="font-medium text-ink">{row.label}</span>
        {/* On a phone the meaning folds under the label instead of scrolling sideways. */}
        <span className="mt-0.5 block text-ink-muted md:hidden">{row.meaning}</span>
      </>
    ),
  },
  { id: "count", header: COPY.colCount, align: "right", cell: (row) => row.count },
  {
    id: "meaning",
    header: COPY.colMeaning,
    hideBelow: "md",
    cell: (row) => <span className="text-ink-muted">{row.meaning}</span>,
  },
];

const LIMIT_COLUMNS: DataColumn<LimitRow>[] = [
  { id: "label", header: COPY.colDetail, cell: (row) => row.label },
  {
    id: "scenarios",
    header: COPY.colMissed,
    align: "right",
    cell: (row) => row.scenarios,
  },
];

/** One month's report: figures first, the tables after, the definitions disclosed. */
export function QualityReport({ report }: { report: QaReport }) {
  const clean = report.defects === 0;
  const scenarioClasses = report.scenario_classes ?? [];
  const knownLimits = report.known_limits ?? [];
  return (
    <div className="space-y-10">
      <div className="space-y-6">
        <div className="space-y-1 text-meta text-ink-muted">
          {!clean && (
            <p className="font-medium text-danger">{COPY.fixing}</p>
          )}
          <p>{monthEnding(monthEndLabel(report.as_of))}</p>
        </div>

        <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 sm:gap-x-10">
          <Metric label={COPY.problems} value={String(report.defects)} />
          <Metric label={COPY.captured} value={renderMeasurement(report.everything_captured)} />
          <Metric
            className="col-span-2 sm:col-span-1"
            label={COPY.blank}
            value={renderMeasurement(report.field_left_blank)}
            hint={
              <span className="inline-flex items-center gap-1">
                {COPY.blankHint}
                <InfoTip label="a blank field">
                  <p>{COPY.blankTip}</p>
                </InfoTip>
              </span>
            }
          />
        </div>

        <div className="space-y-1 text-meta text-ink-muted">
          {report.everything_captured.basis !== "measured" && (
            <p>{BASIS_NOTE[report.everything_captured.basis]}</p>
          )}
          <p>
            {COPY.sinceLast} {BASIS_NOTE[report.trend] || COPY.noChange}
          </p>
        </div>
      </div>

      <Section
        title={COPY.testedTitle}
        action={
          <p className="flex items-center gap-1 text-meta text-ink-muted">
            {tricky(report.red_team)}
            <InfoTip label="trick calls" align="end">
              <p>{COPY.trickyTip}</p>
            </InfoTip>
          </p>
        }
      >
        <DataTable
          className="border-y border-line"
          label={COPY.tableLabel}
          columns={SCENARIO_COLUMNS}
          rows={scenarioClasses}
          getRowId={(row) => String(row.scenario)}
        />
      </Section>

      <Section title={COPY.limitsTitle}>
        {knownLimits.length === 0 ? (
          <p className="text-meta text-ink-muted">{COPY.limitsNone}</p>
        ) : (
          <div className="space-y-4">
            <p className="flex flex-wrap items-center gap-x-1 text-meta text-ink-muted">
              {COPY.limitsIntro}
              <WhyTip about="blank details" label="Why?">
                <p>{COPY.limitsWhy}</p>
              </WhyTip>
            </p>
            <DataTable
              className="border-y border-line"
              label={COPY.limitsLabel}
              columns={LIMIT_COLUMNS}
              rows={knownLimits}
              getRowId={(row) => row.label}
            />
          </div>
        )}
      </Section>

      <div>
        <Disclosure
          variant="inline"
          headingLevel={2}
          title={COPY.defectTitle}
          subtitle={COPY.defectSubtitle}
        >
          <ul className="mb-3 list-disc space-y-1 pl-5 text-body text-ink-muted">
            <li>
              a caller&apos;s detail was recorded <strong>wrongly</strong> — a callback number
              that dials someone else is worse than a blank one;
            </li>
            <li>
              a detail was <strong>invented</strong> that the caller never gave;
            </li>
            <li>
              the <strong>recording and AI notice</strong> was not spoken, or an opt-out was not
              honoured;
            </li>
            <li>
              something identifying was <strong>left in a transcript</strong> that should have
              been masked.
            </li>
          </ul>
          <p className="mb-3 text-body text-ink-muted">
            None of them is acceptable at any price point.
          </p>
        </Disclosure>
        <Disclosure
          variant="inline"
          headingLevel={2}
          title={COPY.notTitle}
          subtitle={COPY.notSubtitle}
        >
          <ul className="mb-3 list-disc space-y-2 pl-5 text-body text-ink-muted">
            <li>
              <strong>It is not a measure of your live calls.</strong> It is a fixed set of
              scenarios, replayed. Your dashboard tells you how many callers booked this month.
            </li>
            <li>
              <strong>It contains nothing from a real call.</strong> No caller name, no number,
              no sentence anyone said. The scenarios are written by us and the callers in them
              are invented.
            </li>
            <li>
              <strong>It is not a trend yet.</strong> This is a point measurement. Once there
              are two reports there will be a comparison, and until then we are not going to
              draw one from a single month.
            </li>
          </ul>
        </Disclosure>
      </div>
    </div>
  );
}

/**
 * The API's `as_of` as a `Date` that means the SAME CALENDAR DAY in every timezone, or
 * null when the string is not one.
 *
 * `as_of` is a CALENDAR DATE (`format: date` — `scripts/qa_report.py` types it `date`),
 * and the trap `c/[slug]/page.tsx::formatDayLabel` records applies to it: `new
 * Date("2026-09-01")` parses as midnight UTC and then renders in the BROWSER's zone, so
 * a reader west of UTC was shown "August 2026" over September's report. It is the month
 * name on a document this product sends a client monthly to prove the agent was tested,
 * and nothing else on the page would contradict it.
 *
 * So the instant is BUILT in UTC and READ back in UTC by both labels below: the two
 * cancel, and the output is the day the string names wherever the reader is. `Intl` is
 * still what names the month, because "August" is a translation and a hand-written table
 * would be a second one.
 *
 * The parts are checked rather than the constructed instant: `Date.UTC` rolls a month of
 * 13 forward into the next year instead of refusing it, so the "Invalid Date"
 * fall-through a `new Date(string)` gives for free does not exist here.
 */
function calendarDay(asOf: string): Date | null {
  const [year, month, day] = asOf.split("-");
  const yearNumber = Number(year);
  const monthIndex = Number(month) - 1;
  const dayNumber = Number(day);
  if (!Number.isInteger(yearNumber) || !Number.isInteger(monthIndex)) return null;
  if (!Number.isInteger(dayNumber) || monthIndex < 0 || monthIndex > 11) return null;
  if (dayNumber < 1 || dayNumber > 31) return null;
  return new Date(Date.UTC(yearNumber, monthIndex, dayNumber));
}

/** "August 2026" — the month picker's label, in the reader's own words rather than a date. */
export function monthLabel(asOf: string): string {
  const at = calendarDay(asOf);
  if (at === null) return asOf;
  return at.toLocaleDateString("en-IN", { timeZone: "UTC", month: "long", year: "numeric" });
}

/**
 * "31 July 2026" — the day the report's month ends on.
 *
 * The line under the report used to interpolate `as_of` RAW, so the sentence a client
 * reads to find out which month they are looking at said "For the month ending
 * 2026-07-31" while the chip two inches above it said "July 2026". An ISO date is a wire
 * format: an owner reading dates as DD-MM-YYYY has to stop and work out which end the
 * year is on, and the two spellings of one fact on one screen is the drift that
 * eventually has them disagreeing.
 */
export function monthEndLabel(asOf: string): string {
  const at = calendarDay(asOf);
  if (at === null) return asOf;
  return at.toLocaleDateString("en-IN", {
    timeZone: "UTC",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
