"use client";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import { Disclosure } from "@/components/ui";
import { BASIS_NOTE, renderMeasurement, type QaReport } from "@/lib/api/quality";

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
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[13px] font-medium ${
        clean
          ? "border-brand/30 bg-brand-soft text-brand-strong"
          : "border-danger-line bg-danger-soft text-danger"
      }`}
    >
      {clean
        ? `No defects found across ${report.scenarios_total} scenarios`
        : `${report.defects} of ${report.scenarios_total} scenarios found a defect`}
    </span>
  );
}

const SCENARIO_COLUMNS: DataColumn<ScenarioRow>[] = [
  {
    id: "label",
    header: "What it tests",
    cell: (row) => (
      <>
        <span className="font-medium text-ink">{row.label}</span>
        {/* On a phone the meaning folds under the label instead of scrolling sideways. */}
        <span className="mt-0.5 block text-ink-muted md:hidden">{row.meaning}</span>
      </>
    ),
  },
  { id: "count", header: "Scenarios", align: "right", cell: (row) => row.count },
  {
    id: "meaning",
    header: "What a pass means",
    hideBelow: "md",
    cell: (row) => <span className="text-ink-muted">{row.meaning}</span>,
  },
];

const LIMIT_COLUMNS: DataColumn<LimitRow>[] = [
  { id: "label", header: "Your column", cell: (row) => row.label },
  {
    id: "scenarios",
    header: "Scenarios where it was not picked up",
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
    <div className="space-y-6">
      <div className="space-y-1 text-[13px] text-ink-muted">
        {!clean && (
          <p className="font-medium text-danger">
            These are being fixed and this report will be reissued.
          </p>
        )}
        <p>
          For the month ending {monthEndLabel(report.as_of)}. Measured with the {report.model}{" "}
          language model.
        </p>
      </div>

      <div className="grid gap-x-6 gap-y-5 border-b border-line pb-6 sm:grid-cols-3">
        <Metric label="Defects" value={String(report.defects)} />
        <Metric label="Everything captured" value={renderMeasurement(report.everything_captured)} />
        <Metric
          label="A field came back blank"
          value={renderMeasurement(report.field_left_blank)}
          hint={
            <span className="inline-flex items-center gap-1">
              A detail missed, not a wrong one
              <InfoTip label="a blank field">
                <p>
                  A blank field is not a failure of the call — it is a detail the agent did
                  not pick up, listed by column below. The two figures add up to every
                  scenario, and the first one is the one that matters: nothing was recorded
                  wrongly.
                </p>
              </InfoTip>
            </span>
          }
        />
      </div>

      <div className="space-y-1 text-[13px] text-ink-muted">
        {report.everything_captured.basis !== "measured" && (
          <p>{BASIS_NOTE[report.everything_captured.basis]}</p>
        )}
        <p>Change since last month: {BASIS_NOTE[report.trend] || "no change to report."}</p>
      </div>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[15px] font-semibold text-ink">What we tested</h2>
          <p className="flex items-center gap-1 text-[13px] text-ink-muted">
            {report.red_team} of those scenarios are adversarial
            <InfoTip label="adversarial scenarios" align="end">
              <p>
                A caller trying to talk the agent into skipping the recording notice, into
                reading out another customer&apos;s details, into ignoring an opt-out, or into
                writing something false into your leads list. Each one is checked against
                what the system did rather than against how the conversation sounded.
              </p>
            </InfoTip>
          </p>
        </div>
        <DataTable
          label="Scenario classes replayed against your agent, and what a pass proves"
          columns={SCENARIO_COLUMNS}
          rows={scenarioClasses}
          getRowId={(row) => String(row.scenario)}
        />
      </section>

      <section className="space-y-3">
        <h2 className="text-[15px] font-semibold text-ink">Known limits</h2>
        {knownLimits.length === 0 ? (
          <p className="text-[13px] text-ink-muted">
            None. Every field in your leads list was captured on every scenario that contained
            it.
          </p>
        ) : (
          <>
            <p className="text-[13px] text-ink-muted">
              Fields the agent does not yet reliably pick up. They come back{" "}
              <strong>blank</strong>, never wrong — a blank column is a call your staff can
              follow up, and a wrong one is a call they cannot.
            </p>
            <DataTable
              label="Fields the agent does not yet reliably pick up"
              columns={LIMIT_COLUMNS}
              rows={knownLimits}
              getRowId={(row) => row.label}
            />
          </>
        )}
      </section>

      <div>
        <Disclosure
          variant="inline"
          headingLevel={2}
          title="What counts as a defect"
          subtitle="A wrong or invented detail, a missing recording and AI notice or opt-out, or an unmasked detail."
        >
          <ul className="mb-3 list-disc space-y-1 pl-5 text-sm text-ink-muted">
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
          <p className="mb-3 text-sm text-ink-muted">
            None of them is acceptable at any price point.
          </p>
        </Disclosure>
        <Disclosure
          variant="inline"
          headingLevel={2}
          title="What this report does not tell you"
          subtitle="It is not a measure of your live calls, holds no real call data, and is not a trend yet."
        >
          <ul className="mb-3 list-disc space-y-2 pl-5 text-sm text-ink-muted">
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
