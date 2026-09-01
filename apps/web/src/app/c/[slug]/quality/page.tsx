"use client";

import { useState } from "react";
import { ShieldCheck, TriangleAlert } from "lucide-react";

import {
  Card,
  EmptyState,
  FilterChip,
  NoticeBox,
  ProblemNotice,
  ScrollRegion,
  Skeleton,
  StatTile,
} from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import {
  BASIS_NOTE,
  renderMeasurement,
  useQualityReports,
  type QaReport,
} from "@/lib/api/quality";

/**
 * The monthly quality report, in-app (SURFACES §2 trust surfaces, D-15).
 *
 * The document already existed as `make qa-report` — a Markdown file somebody emails.
 * SURFACES §2 asks for it "rendered in-app, not just PDF", and the point of the surface
 * is that a client can check the claim we sell on ("we regression-test your agent before
 * every change") without asking us for a file.
 *
 * Three things this screen refuses to do, in the order the damage runs:
 *
 * 1. **Invent a clean run.** An account the harness has never run against gets the
 *    "not run yet" state, never a report of zero defects across zero scenarios. That
 *    sentence would be the most reassuring lie in the product, so the API sends nothing
 *    and this screen says nothing.
 * 2. **Print a percentage the numbers do not support.** `basis` travels with every
 *    measurement, and `renderMeasurement` prints the count alone below the floor — the
 *    same rule the emailed document follows, spelled once in `lib/api/quality.ts`.
 * 3. **Render a report under a failed read.** Loading is a skeleton and failure is a
 *    refusal (§52). "Nothing to report" and "we could not read your reports" point an
 *    owner in opposite directions and only one of them is true.
 *
 * The headline is the DEFECT count, not the pass rate — the report's own doctrine
 * (`scripts/qa_report.py`): the pass rate measures our offline stand-in extractor, the
 * defect count measures the promise we actually make.
 *
 * The page carries no `<h1>`: the shell prints the title from the nav list it renders
 * the sidebar from, so a heading here would be the same word twice and a second place
 * for it to be renamed.
 */
export default function QualityPage() {
  const session = useClientSession();
  const reports = useQualityReports(session);
  const [month, setMonth] = useState<string | null>(null);

  const all = reports.data ?? [];
  // The newest month unless the reader picked another. Kept as the as_of STRING rather
  // than an index so a refetch that adds this month's report cannot silently move the
  // selection to a different document under the reader.
  const shown = all.find((report) => report.as_of === month) ?? all[0];

  /*
   * THE QUALITY REPORT ON SHOW, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * WHICH MONTH is writable, and the options are the months the SERVER actually returned,
   * so the assistant cannot select a report this account does not have — a value outside
   * the list is dropped rather than written, exactly as `knowledge/page.tsx` drops an
   * agent id nobody has.
   *
   * Nothing on this screen is personal at all: the suite is a fixed set of recorded
   * scenarios and the report "contains nothing from any real call", which is the sentence
   * the screen opens with.
   */
  useCopilotSurface({
    route: "/c/{slug}/quality",
    title: "Quality report",
    realm: "client",
    fields: [
      {
        id: "quality-month",
        label: "Which report is on show",
        type: "select",
        value: shown?.as_of ?? "",
        options: all.map((report) => ({ value: report.as_of, label: report.as_of })),
        writable: all.length > 1,
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: shown
          ? "the report below has loaded"
          : reports.error || !reports.data
            ? "the reports failed to load — this is NOT evidence that the agent has never been tested"
            : reports.isLoading
              ? "still loading"
              : "the server answered, and this account has no report yet",
      },
      { key: "reports_available", label: "Reports on file", value: String(all.length) },
      ...(shown
        ? [
            { key: "as_of", label: "Report month", value: shown.as_of },
            { key: "vertical", label: "Scenario set (trade)", value: shown.vertical },
            { key: "model", label: "Model tested", value: shown.model },
            { key: "scenarios_total", label: "Scenarios replayed", value: String(shown.scenarios_total) },
            { key: "defects", label: "Defects found", value: String(shown.defects) },
            { key: "red_team", label: "Deliberate attacks in the run", value: String(shown.red_team) },
            {
              key: "everything_captured",
              label: "Scenarios where every required detail was captured",
              value: `${shown.everything_captured.passed} of ${shown.everything_captured.total} (${shown.everything_captured.basis})`,
            },
            {
              key: "field_left_blank",
              label: "Scenarios where a required field was left blank",
              value: `${shown.field_left_blank.passed} of ${shown.field_left_blank.total} (${shown.field_left_blank.basis})`,
            },
            { key: "trend", label: "Is there enough history to state a trend?", value: shown.trend },
            { key: "known_limits", label: "Known limits listed", value: String((shown.known_limits ?? []).length) },
          ]
        : []),
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id !== "quality-month") continue;
        const wanted = asText(item.value);
        if (all.some((report) => report.as_of === wanted)) setMonth(wanted);
      }
    },
  });

  return (
    <div className="space-y-4 pb-12">
      <p className="text-sm text-ink-muted">
        Before any change to your agent — a new script, a new model, a new knowledge base —
        we replay a fixed set of recorded call scenarios against it and check what it did.
        This is that run. It contains nothing from any real call.
      </p>

      {reports.error && (
        <ProblemNotice error={reports.error} onRetry={() => void reports.refetch()} />
      )}

      {reports.isLoading ? (
        <Card>
          <Skeleton rows={6} />
        </Card>
      ) : reports.error || !reports.data ? (
        /* Deliberately NOT the empty state. "No report yet" is a claim about your
           account, and a failed read is not evidence for it — a client told their agent
           has never been tested, because a token expired, has been misinformed about the
           thing this screen exists to prove.
           `|| !reports.data` because a failed read is not the only way to have no answer:
           a query TanStack has PAUSED because the browser is offline reports
           `isLoading === false` and `error === null` with no data, so `all` was `[]`,
           `shown` was undefined, and this screen told a client their agent had never been
           tested off a request that was never sent. */
        <Card>
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert className="h-5 w-5" />}
            title="Your quality reports could not be loaded"
          >
            <p className="mt-1">
              So we cannot show this month&apos;s results. This does not mean there are none —
              reload the page, and tell us if it keeps happening.
            </p>
          </NoticeBox>
        </Card>
      ) : !shown ? (
        <Card>
          <EmptyState
            title="No quality report yet"
            hint="Reports are produced when we run the scenario suite against your agent — usually monthly, and always before we change anything. Your first one appears here after that run."
          />
        </Card>
      ) : (
        <>
          {all.length > 1 && (
            <div
              className="flex flex-wrap items-center gap-2"
              role="group"
              aria-label="Choose a month"
            >
              {all.map((report) => (
                <FilterChip
                  key={`${report.as_of}-${report.vertical}`}
                  label={monthLabel(report.as_of)}
                  active={report.as_of === shown.as_of}
                  onClick={() => setMonth(report.as_of)}
                />
              ))}
            </div>
          )}
          <Report report={shown} />
        </>
      )}
    </div>
  );
}

function Report({ report }: { report: QaReport }) {
  const clean = report.defects === 0;
  // Both lists carry a server-side default, so Pydantic always serializes them and the
  // generated type marks them optional purely because a default exists. Normalised once
  // here rather than at each of the four use sites: this is a field on an already-loaded
  // document, NOT a query envelope, so it is not the `??` the §52 guard forbids — that
  // rule is about rendering a fallback INSTEAD of a load or a failure, and both of those
  // are handled above by the caller before this component is reached.
  const scenarioClasses = report.scenario_classes ?? [];
  const knownLimits = report.known_limits ?? [];
  return (
    <div className="space-y-4">
      <Card>
        <NoticeBox
          tone={clean ? "ok" : "stop"}
          icon={clean ? <ShieldCheck className="h-5 w-5" /> : <TriangleAlert className="h-5 w-5" />}
          title={
            clean
              ? `No defects found across ${report.scenarios_total} scenarios`
              : `${report.defects} of ${report.scenarios_total} scenarios found a defect`
          }
        >
          <p className="mt-1">
            {clean
              ? "A defect means one of four things, and none of them is acceptable at any price point:"
              : "These are being fixed and this report will be reissued. A defect means one of four things:"}
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
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
        </NoticeBox>
        <p className="mt-3 text-xs text-ink-faint">
          For the month ending {monthEndLabel(report.as_of)}. Measured with the {report.model}{" "}
          language model.
        </p>
      </Card>

      <div className="grid gap-3 sm:grid-cols-3">
        {/* The defect count leads, and it is the only tile that is a promise rather
            than a measurement. */}
        <StatTile label="Defects" value={String(report.defects)} />
        <StatTile
          label="Everything captured"
          value={renderMeasurement(report.everything_captured)}
        />
        <StatTile label="A field came back blank" value={renderMeasurement(report.field_left_blank)} />
      </div>

      {report.everything_captured.basis !== "measured" && (
        <p className="text-xs text-ink-faint">{BASIS_NOTE[report.everything_captured.basis]}</p>
      )}
      <p className="text-sm text-ink-muted">
        A blank field is not a failure of the call — it is a detail the agent did not pick up,
        listed by column below. The two figures add up to every scenario, and the first one is
        the one that matters: nothing was recorded wrongly.
      </p>
      <p className="text-xs text-ink-faint">
        Change since last month: {BASIS_NOTE[report.trend] || "no change to report."}
      </p>

      <Card title="What we tested" bodyClassName="p-0">
        <ScrollRegion label="What we tested">
          <table className="w-full min-w-[560px] text-sm">
            <caption className="sr-only">
              Scenario classes replayed against your agent, and what a pass proves
            </caption>
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                <th scope="col" className="px-6 py-3 font-semibold">
                  What it tests
                </th>
                <th scope="col" className="px-6 py-3 text-right font-semibold">
                  Scenarios
                </th>
                <th scope="col" className="px-6 py-3 font-semibold">
                  What a pass means
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {scenarioClasses.map((row) => (
                <tr key={row.scenario} className="align-top">
                  <td className="px-6 py-3 font-medium text-ink">{row.label}</td>
                  <td className="px-6 py-3 text-right tabular-nums text-ink">{row.count}</td>
                  <td className="px-6 py-3 text-ink-muted">{row.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      </Card>

      <Card title="Deliberate attacks">
        <p className="text-sm text-ink-muted">
          {report.red_team} of those scenarios are adversarial: a caller trying to talk the agent
          into skipping the recording notice, into reading out another customer&apos;s details,
          into ignoring an opt-out, or into writing something false into your leads list. Each one
          is checked against what the system did rather than against how the conversation sounded.
        </p>
      </Card>

      <Card title="Known limits" bodyClassName={knownLimits.length ? "p-0" : undefined}>
        {knownLimits.length === 0 ? (
          <p className="text-sm text-ink-muted">
            None. Every field in your leads list was captured on every scenario that contained it.
          </p>
        ) : (
          <ScrollRegion label="Fields the agent does not yet reliably pick up">
            <table className="w-full min-w-[420px] text-sm">
              <caption className="px-6 pt-4 text-left text-sm text-ink-muted">
                Fields the agent does not yet reliably pick up. They come back{" "}
                <strong>blank</strong>, never wrong — a blank column is a call your staff can
                follow up, and a wrong one is a call they cannot.
              </caption>
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th scope="col" className="px-6 py-3 font-semibold">
                    Your column
                  </th>
                  <th scope="col" className="px-6 py-3 text-right font-semibold">
                    Scenarios where it was not picked up
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {knownLimits.map((limit) => (
                  <tr key={limit.label}>
                    <td className="px-6 py-3 text-ink">{limit.label}</td>
                    <td className="px-6 py-3 text-right tabular-nums text-ink">
                      {limit.scenarios}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </Card>

      <Card title="What this report does not tell you">
        <ul className="list-disc space-y-2 pl-5 text-sm text-ink-muted">
          <li>
            <strong>It is not a measure of your live calls.</strong> It is a fixed set of
            scenarios, replayed. Your dashboard tells you how many callers booked this month.
          </li>
          <li>
            <strong>It contains nothing from a real call.</strong> No caller name, no number, no
            sentence anyone said. The scenarios are written by us and the callers in them are
            invented.
          </li>
          <li>
            <strong>It is not a trend yet.</strong> This is a point measurement. Once there are
            two reports there will be a comparison, and until then we are not going to draw one
            from a single month.
          </li>
        </ul>
      </Card>
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
function monthLabel(asOf: string): string {
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
function monthEndLabel(asOf: string): string {
  const at = calendarDay(asOf);
  if (at === null) return asOf;
  return at.toLocaleDateString("en-IN", {
    timeZone: "UTC",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
