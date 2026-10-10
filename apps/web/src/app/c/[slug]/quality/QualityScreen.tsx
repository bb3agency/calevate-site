"use client";

import { useState } from "react";
import { TriangleAlert } from "lucide-react";

import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { NoticeBox, ProblemNotice, Skeleton } from "@/components/ui";
import { useQualityReports } from "@/lib/api/quality";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { QualityReport, VerdictPill, monthLabel } from "./QualityReport";

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
export function QualityScreen() {
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
              : "loaded, and this account has no report yet",
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
    <div className="max-w-4xl space-y-8 pb-12">
      <PageHeader
        status={shown ? <VerdictPill report={shown} /> : undefined}
        description={
          <>
            A replay of our test scenarios against your agent. Nothing here comes from a real
            call.{" "}
            <InfoTip label="this report" className="-my-3">
              <p>
                Before any change to your agent — a new script, a new model, a new knowledge
                base — we replay a fixed set of recorded call scenarios against it and check
                what it did. This is that run. It contains nothing from any real call.
              </p>
            </InfoTip>
          </>
        }
        actions={
          shown && all.length > 1 ? (
            /* D-655: each month is a complete report and the reader picks one. */
            <SegmentedControl
              label="Choose a month"
              value={shown.as_of}
              onValueChange={setMonth}
              options={all.map((report) => ({
                value: report.as_of,
                label: monthLabel(report.as_of),
              }))}
            />
          ) : undefined
        }
      />

      {reports.error && (
        <ProblemNotice error={reports.error} onRetry={() => void reports.refetch()} />
      )}

      {reports.isLoading ? (
        <Skeleton rows={6} label="Loading your quality reports" />
      ) : reports.error || !reports.data ? (
        /* Deliberately NOT the empty state. "No report yet" is a claim about the account,
           and a failed read is not evidence for it. `|| !reports.data` because a query
           TanStack has PAUSED (browser offline) has no error and no data either. */
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
      ) : !shown ? (
        <EmptyState
          className="border-y border-line"
          message={
            <>
              <span className="block font-medium text-ink">No quality report yet</span>
              <span className="mt-1 block">
                Your first report appears after our first test run — usually monthly, and
                always before we change your agent.
              </span>
            </>
          }
        />
      ) : (
        /* Keyed by month so a switch replaces the report as a pane (`settings-enter`)
           rather than changing numbers under the reader. */
        <div key={shown.as_of} className="settings-enter">
          <QualityReport report={shown} />
        </div>
      )}
    </div>
  );
}
