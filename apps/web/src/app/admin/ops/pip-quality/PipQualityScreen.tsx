"use client";

import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { Metric, MetricRow } from "@/components/console/metric";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ProblemNotice, RestrictionNote, Skeleton, formatCount } from "@/components/ui";
import {
  LOW_LABELS,
  PIP_DEFAULT_WINDOW_DAYS,
  PIP_WINDOW_CHOICES,
  WHY_LABELS,
  areaLabel,
  reasonLabel,
  formatShare,
  usePipQuality,
  type PipAreaQuality,
  type PipQualityFigures,
  type PipQualityReport,
  type PipRealm,
  type PipToolQuality,
} from "@/lib/api/pipQuality";
import { formatMs } from "@/lib/api/replyTimes";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

const REALM_OPTIONS: { value: PipRealm; label: string }[] = [
  { value: "client", label: "Client Pip" },
  { value: "admin", label: "Admin Pip" },
];

/**
 * The console half of `GET /v1/ops/copilot-quality` (D-937): how Pip's answers went, per
 * area and per tool, over the last 7 or 30 days, for the client Pip or the admin Pip. Each
 * low score lists example answer ids to review. `ops:manage` gates the read.
 */
export function PipQualityScreen() {
  const [days, setDays] = useState(PIP_DEFAULT_WINDOW_DAYS);
  const [realm, setRealm] = useState<PipRealm>("client");
  const access = useAdminAccess("ops:manage", "read Pip's quality scores");
  const report = usePipQuality(realm, days, !access.refused);
  const data = report.data;

  useCopilotSurface({
    route: "/admin/ops/pip-quality",
    title: "Pip quality",
    realm: "admin",
    saves: "view",
    fields: [
      {
        id: "pip-quality-days",
        label: "Window (days)",
        type: "select",
        value: String(days),
        options: PIP_WINDOW_CHOICES.map((choice) => ({
          value: String(choice),
          label: `Last ${choice} days`,
        })),
      },
      {
        id: "pip-quality-realm",
        label: "Which Pip",
        type: "select",
        value: realm,
        options: REALM_OPTIONS,
      },
    ],
    facts: access.refused
      ? [{ key: "report", label: "The report", value: "withheld — this admin account may not read it" }]
      : data
        ? [
            { key: "answers", label: "Answers in the window", value: String(data.overall.answers) },
            { key: "done", label: "Share ending with the thing done", value: formatShare(data.overall.done_share) },
            {
              key: "thumbs",
              label: "Thumbs up / down",
              value: `${data.overall.thumbs_up} / ${data.overall.thumbs_down}`,
            },
            {
              key: "low_areas",
              label: "Areas with a low score",
              value:
                data.by_area
                  .filter((row) => row.figures.low.length > 0)
                  .map((row) => `${areaLabel(row.area)}: ${row.figures.low.map((l) => LOW_LABELS[l]).join(", ")}`)
                  .join("; ") || "none",
            },
          ]
        : [
            {
              key: "report",
              label: "The report",
              value: report.error ? "could not be read" : "still loading",
            },
          ],
    apply: (items) => {
      for (const item of items) {
        const value = asText(item.value);
        if (item.field_id === "pip-quality-days" && PIP_WINDOW_CHOICES.includes(Number(value))) {
          setDays(Number(value));
        }
        if (item.field_id === "pip-quality-realm" && (value === "client" || value === "admin")) {
          setRealm(value);
        }
      }
    },
  });

  return (
    <div className="max-w-6xl space-y-10 pb-12">
      <PageHeader
        description={
          <>
            How Pip&rsquo;s answers went: done, rated, failed or slow, by area and by tool.{" "}
            <InfoTip label="What these scores are">
              <p>
                An answer is done when an action it took is still in place, it opened a screen,
                or the person gave it a thumbs up.
              </p>
              <p>
                Actions count as done or undone from Pip&rsquo;s activity log, and as failed when
                the call itself failed. Proposals accepted are the confirm cards people ran in
                the same window.
              </p>
              <p>Answer ids only: what was said is never kept here.</p>
            </InfoTip>
          </>
        }
      />

      {access.refused ? (
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          <div className="flex flex-wrap gap-3">
            <SegmentedControl
              label="Which Pip"
              value={realm}
              onValueChange={(value) => setRealm(value === "admin" ? "admin" : "client")}
              options={REALM_OPTIONS}
            />
            <SegmentedControl
              label="Window"
              value={String(days)}
              onValueChange={(value) => setDays(Number(value))}
              options={PIP_WINDOW_CHOICES.map((choice) => ({
                value: String(choice),
                label: `Last ${choice} days`,
              }))}
            />
          </div>

          {report.error != null && (
            <ProblemNotice error={report.error} onRetry={() => void report.refetch()} />
          )}

          {!data ? (
            report.error ? null : <Skeleton rows={6} label="Loading Pip's scores" />
          ) : (
            <PipQualityReportView report={data} />
          )}
        </>
      )}
    </div>
  );
}

function lowTone(figures: PipQualityFigures) {
  return figures.low.length > 0 ? ("warn" as const) : ("default" as const);
}

function LowPills({ figures }: { figures: PipQualityFigures }) {
  if (figures.low.length === 0) return <span className="text-ink-faint">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {figures.low.map((low) => (
        <StatusPill key={low} tone="warn">
          {LOW_LABELS[low]}
        </StatusPill>
      ))}
    </span>
  );
}

function actions(figures: PipQualityFigures): string {
  return `${figures.actions_done} / ${figures.actions_undone} / ${figures.actions_failed}`;
}

const AREA_COLUMNS: DataColumn<PipAreaQuality>[] = [
  { id: "area", header: "Area", cell: (row) => areaLabel(row.area), sort: { value: (row) => areaLabel(row.area) } },
  {
    id: "answers",
    header: "Answers",
    align: "right",
    cell: (row) => formatCount(row.figures.answers),
    sort: { value: (row) => row.figures.answers },
  },
  {
    id: "done",
    header: "Done",
    align: "right",
    cell: (row) => formatShare(row.figures.done_share),
    sort: { value: (row) => row.figures.done_share },
  },
  {
    id: "thumbs",
    header: "Thumbs up / down",
    align: "right",
    cell: (row) => `${row.figures.thumbs_up} / ${row.figures.thumbs_down}`,
  },
  {
    id: "actions",
    header: "Actions done / undone / failed",
    align: "right",
    cell: (row) => actions(row.figures),
    hideBelow: "md",
  },
  {
    id: "first",
    header: "First word (typical)",
    align: "right",
    cell: (row) => formatMs(row.figures.first_token_typical_ms),
    hideBelow: "md",
  },
  { id: "low", header: "Low", cell: (row) => <LowPills figures={row.figures} /> },
];

const TOOL_COLUMNS: DataColumn<PipToolQuality>[] = [
  { id: "tool", header: "Tool", cell: (row) => <code className="text-xs">{row.tool}</code>, sort: { value: (row) => row.tool } },
  { id: "area", header: "Area", cell: (row) => areaLabel(row.area), hideBelow: "sm" },
  {
    id: "answers",
    header: "Answers",
    align: "right",
    cell: (row) => formatCount(row.figures.answers),
    sort: { value: (row) => row.figures.answers },
  },
  {
    id: "failed",
    header: "Failed / refused",
    align: "right",
    cell: (row) => `${row.figures.tool_failures} / ${row.figures.permission_refusals}`,
  },
  {
    id: "actions",
    header: "Done / undone / failed",
    align: "right",
    cell: (row) => (row.is_action ? actions(row.figures) : "—"),
    hideBelow: "md",
  },
  {
    id: "proposals",
    header: "Proposals accepted / left",
    align: "right",
    cell: (row) =>
      row.figures.proposals > 0 || row.figures.proposals_accepted > 0
        ? `${row.figures.proposals_accepted} / ${row.figures.proposals_abandoned}`
        : "—",
    hideBelow: "md",
  },
  { id: "low", header: "Low", cell: (row) => <LowPills figures={row.figures} /> },
];

/** The report itself, exported so a test can render it from a fixture. */
export function PipQualityReportView({ report }: { report: PipQualityReport }) {
  const overall = report.overall;
  if (report.questions === 0) {
    return (
      <EmptyState
        message="No questions in this window"
        hint="Scores appear once people ask Pip something."
      />
    );
  }
  const lowGroups = [
    ...report.by_area
      .filter((row) => row.figures.low.length > 0)
      .map((row) => ({ name: areaLabel(row.area), figures: row.figures })),
    ...report.by_tool
      .filter((row) => row.figures.low.length > 0)
      .map((row) => ({ name: row.tool, figures: row.figures })),
  ];
  const attempts = overall.actions_done + overall.actions_undone + overall.actions_failed;
  return (
    <div className="space-y-10">
      {!report.complete && (
        <p className="text-xs text-ink-muted">
          This window had more answers than one report reads; the newest are shown.
        </p>
      )}
      <MetricRow label="Overall">
        <Metric
          label="Ended with it done"
          value={formatShare(overall.done_share)}
          hint={`${formatCount(overall.done)} of ${formatCount(overall.answers)} answers`}
        />
        <Metric
          label="Thumbs down"
          value={formatShare(overall.thumbs_down_share)}
          tone={overall.low.includes("thumbs_down") ? "warn" : "default"}
          hint={`${overall.thumbs_up} up · ${overall.thumbs_down} down`}
        />
        <Metric
          label="Actions failed"
          value={formatShare(overall.action_failure_share)}
          tone={overall.low.includes("action_failures") ? "warn" : "default"}
          hint={`${overall.actions_failed} of ${attempts} · ${overall.actions_undone} undone`}
        />
        <Metric
          label="First word (typical)"
          value={formatMs(overall.first_token_typical_ms)}
          hint={`Slow ${formatMs(overall.first_token_slow_ms)} · whole answer ${formatMs(overall.total_typical_ms)}`}
        />
      </MetricRow>

      <MetricRow label="Refusals and backups">
        {report.refusals.length === 0 ? (
          <Metric label="Refused at the door" value="0" />
        ) : (
          report.refusals.map((row) => (
            <Metric key={row.reason} label={reasonLabel(row.reason)} value={formatCount(row.count)} />
          ))
        )}
        <Metric label="Permission refusals" value={formatCount(overall.permission_refusals)} />
        <Metric
          label="Answered by a backup model"
          value={formatCount(overall.fell_back)}
          hint={report.by_provider.map((row) => `${row.provider}: ${row.answers}`).join(" · ") || undefined}
        />
        <Metric
          label="Proposals accepted"
          value={`${overall.proposals_accepted} of ${overall.proposals}`}
          hint={`${overall.proposals_abandoned} left without a decision`}
        />
      </MetricRow>

      <Section
        title="By area"
        description={`Low: at least ${formatShare(report.thumbs_down_low_share)} thumbs down over ${report.min_votes} votes, or ${formatShare(report.action_failure_low_share)} of actions failing over ${report.min_attempts}.`}
      >
        <DataTable
          rows={report.by_area}
          columns={AREA_COLUMNS}
          getRowId={(row) => row.area}
          label="Pip's scores by area"
          rowClassName={(row) => (lowTone(row.figures) === "warn" ? "bg-warn/5" : "")}
        />
      </Section>

      <Section title="By tool">
        <DataTable
          rows={report.by_tool}
          columns={TOOL_COLUMNS}
          getRowId={(row) => row.tool}
          label="Pip's scores by tool"
        />
      </Section>

      {overall.reasons.length > 0 && (
        <Section title="Why people rated answers down">
          <ul className="space-y-1 text-sm text-ink">
            {overall.reasons.map((row) => (
              <li key={row.reason}>
                {reasonLabel(row.reason)}: {formatCount(row.count)}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section
        title="Answers to review"
        description="Example answer ids for each low score, rated-down first."
      >
        {lowGroups.length === 0 ? (
          <p className="text-sm text-ink-muted">No area or tool is low in this window.</p>
        ) : (
          <div className="space-y-4">
            {lowGroups.map((group) => (
              <div key={group.name}>
                <h3 className="text-sm font-medium text-ink">{group.name}</h3>
                <ul className="mt-1 space-y-1 text-xs text-ink-muted">
                  {group.figures.examples.map((example) => (
                    <li key={example.turn_id} className="flex flex-wrap gap-x-2">
                      <span>{WHY_LABELS[example.why]}</span>
                      <code className="[overflow-wrap:anywhere]">{example.turn_id}</code>
                      {example.tenant_id && (
                        <span className="[overflow-wrap:anywhere]">account {example.tenant_id}</span>
                      )}
                      {example.note && <span className="text-ink">&ldquo;{example.note}&rdquo;</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
