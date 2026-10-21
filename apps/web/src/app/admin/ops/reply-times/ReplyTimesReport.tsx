"use client";

import Link from "next/link";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { Metric, MetricRow } from "@/components/console/metric";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { NoticeBox, formatCount, formatCountOf, formatIST } from "@/components/ui";
import { viewAsHref } from "@/lib/api/session";
import {
  EMPTY_COPY,
  TIER_LABELS,
  formatDay,
  formatMs,
  windowLabel,
  type AgentReplyTimes,
  type ClientReplyTimes,
  type DayReplyTimes,
  type ReplyTimeFigures,
  type ReplyTimeReport,
  type SlowCall,
  type TierReplyTimes,
} from "@/lib/api/replyTimes";
import { lookup } from "@/lib/lookup";

const CONFIG_HREF = "/admin/ops/config?section=voice-engine";

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

/** The figure columns every breakdown shares, after its own label column. */
function figureColumns<T extends ReplyTimeFigures>(): DataColumn<T>[] {
  return [
    {
      id: "calls",
      header: "Calls measured",
      renderHeader: glossed("Calls measured", "Calls with reply times, of the calls that connected and finished."),
      className: "tabular-nums",
      sort: { value: (row) => row.calls_measured, kind: "number", first: "desc" },
      cell: (row) => (
        <>
          {formatCount(row.calls_measured)}
          <span className="text-ink-muted"> of {formatCount(row.calls)}</span>
        </>
      ),
    },
    {
      id: "typical",
      header: "Typical reply",
      renderHeader: glossed("Typical reply", "The middle of the calls' own typical (median) reply times."),
      hideBelow: "sm",
      className: "tabular-nums",
      sort: { value: (row) => row.reply_typical_ms, kind: "number", first: "desc" },
      cell: (row) => formatMs(row.reply_typical_ms),
    },
    {
      id: "slow",
      header: "Slow reply",
      renderHeader: glossed(
        "Slow reply",
        "Nine calls in ten had their slowest tenth of replies faster than this. Blank below ten measured calls.",
      ),
      hideBelow: "sm",
      className: "tabular-nums",
      sort: { value: (row) => row.reply_slow_ms, kind: "number", first: "desc" },
      cell: (row) => formatMs(row.reply_slow_ms),
    },
    {
      id: "first-token",
      header: "Model's first word",
      renderHeader: glossed(
        "Model's first word",
        "From the turn reaching the voice platform to the first speakable word, not from when the caller stopped.",
      ),
      hideBelow: "md",
      className: "tabular-nums",
      sort: { value: (row) => row.first_token_typical_ms, kind: "number", first: "desc" },
      cell: (row) => formatMs(row.first_token_typical_ms),
    },
    {
      id: "over",
      header: "Over target",
      renderHeader: glossed("Over target", "Calls where more than one reply in ten took longer than the target."),
      className: "tabular-nums",
      sort: { value: (row) => row.calls_over_target, kind: "number", first: "desc" },
      cell: (row) => (
        <span className={row.calls_over_target > 0 ? "font-semibold text-danger" : undefined}>
          {formatCount(row.calls_over_target)}
        </span>
      ),
    },
    {
      id: "slow-problems",
      header: "Replies over 5 s",
      renderHeader: glossed("Replies over 5 s", "Calls on which the platform reported a reply that took more than 5 seconds to start."),
      hideBelow: "md",
      className: "tabular-nums",
      sort: { value: (row) => row.slow_reply_problems, kind: "number", first: "desc" },
      cell: (row) => formatCount(row.slow_reply_problems),
    },
    {
      id: "errors",
      header: "Model errors",
      renderHeader: glossed("Model errors", "Turns the agent apologised for because no model answered."),
      hideBelow: "lg",
      className: "tabular-nums",
      sort: { value: (row) => row.model_errors, kind: "number", first: "desc" },
      cell: (row) => formatCount(row.model_errors),
    },
  ];
}

const CLIENT_COLUMNS: DataColumn<ClientReplyTimes>[] = [
  {
    id: "client",
    header: "Client",
    sort: { value: (row) => row.client_name },
    cell: (row) => (
      <Link href={`/admin/tenants/${row.tenant_id}`} className={TEXT_ACTION}>
        {row.client_name}
      </Link>
    ),
  },
  ...figureColumns<ClientReplyTimes>(),
];

const AGENT_COLUMNS: DataColumn<AgentReplyTimes>[] = [
  {
    id: "agent",
    header: "Agent",
    sort: { value: (row) => row.agent_name },
    cell: (row) => (
      <div className="sm:min-w-[8rem]">
        <Link href={`/admin/tenants/${row.tenant_id}/agents`} className={TEXT_ACTION}>
          {row.agent_name ?? "Removed agent"}
        </Link>
        <span className="block text-meta text-ink-muted">{row.client_name}</span>
      </div>
    ),
  },
  ...figureColumns<AgentReplyTimes>(),
];

const TIER_COLUMNS: DataColumn<TierReplyTimes>[] = [
  {
    id: "tier",
    header: "Voice",
    cell: (row) => <span className="font-medium text-ink">{lookup(TIER_LABELS, row.tier) ?? row.tier}</span>,
  },
  ...figureColumns<TierReplyTimes>(),
];

const DAY_COLUMNS: DataColumn<DayReplyTimes>[] = [
  {
    id: "day",
    header: "Day (IST)",
    sort: { value: (row) => row.day, first: "desc" },
    cell: (row) => <span className="whitespace-nowrap">{formatDay(row.day)}</span>,
  },
  ...figureColumns<DayReplyTimes>(),
];

const CALL_COLUMNS: DataColumn<SlowCall>[] = [
  {
    id: "call",
    header: "Call",
    cell: (row) => (
      <div className="sm:min-w-[10rem]">
        <a href={viewAsHref(row.client_slug, `/calls/${row.call_id}`)} className={TEXT_ACTION}>
          {formatIST(row.started_at)}
        </a>
        <span className="block text-meta text-ink-muted">
          {row.client_name} · {row.agent_name ?? "Removed agent"}
        </span>
      </div>
    ),
  },
  {
    id: "voice",
    header: "Voice",
    hideBelow: "md",
    cell: (row) => lookup(TIER_LABELS, row.voice_tier) ?? row.voice_tier,
  },
  {
    id: "typical",
    header: "Typical reply",
    hideBelow: "sm",
    className: "tabular-nums",
    cell: (row) => formatMs(row.reply_median_ms),
  },
  {
    id: "p90",
    header: "Slow reply",
    renderHeader: glossed("Slow reply", "Nine replies in ten on this call were faster than this."),
    className: "tabular-nums",
    cell: (row) => formatMs(row.reply_p90_ms),
  },
  {
    id: "worst",
    header: "Slowest reply",
    hideBelow: "sm",
    className: "tabular-nums",
    cell: (row) => formatMs(row.reply_max_ms),
  },
  {
    id: "model",
    header: "Model's first word, slow",
    hideBelow: "lg",
    className: "tabular-nums",
    cell: (row) => formatMs(row.first_token_p90_ms),
  },
  {
    id: "flags",
    header: "Problems",
    hideBelow: "md",
    cell: (row) =>
      row.slow_reply || row.model_errors ? (
        <span className="flex flex-wrap gap-x-3 gap-y-1">
          {row.slow_reply && <StatusPill tone="warn">A reply over 5 s</StatusPill>}
          {row.model_errors ? (
            <StatusPill tone="warn">{formatCountOf(row.model_errors, "model error")}</StatusPill>
          ) : null}
        </span>
      ) : (
        <span className="text-meta text-ink-muted">None</span>
      ),
  },
];

/** The report, given one that arrived. Every figure is the server's. */
export function ReplyTimesReport({ report }: { report: ReplyTimeReport }) {
  const overall = report.overall;
  const empty = report.empty_reason ? lookup(EMPTY_COPY, report.empty_reason) : undefined;

  return (
    <div className="space-y-10">
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-body text-ink">
        <span className={overall.calls_over_target > 0 ? "font-semibold text-danger" : "font-semibold"}>
          {formatCount(overall.calls_over_target)} of {formatCountOf(overall.calls_measured, "measured call")}
        </span>
        <span>over target</span>
        <span className="text-ink-muted">
          · target <span className="font-medium text-ink">{formatMs(report.target_ms)}</span>
        </span>
        <span className="text-ink-muted">
          · last <span className="font-medium text-ink">{windowLabel(report.window_days)}</span>
        </span>
        <InfoTip label="How calls are judged">
          <p>
            A call is over target when more than one of its replies in ten kept the caller
            waiting longer than the target. The target is a console setting.
          </p>
          <p>
            <Link href={CONFIG_HREF} className={TEXT_ACTION}>
              Change the target in Configuration
            </Link>
          </p>
        </InfoTip>
      </p>

      {!report.complete && (
        <NoticeBox tone="warn" title="These figures cover only the most recent calls">
          <p className="mt-1">
            This window held more calls than one report reads. Narrow the window for a complete answer.
          </p>
        </NoticeBox>
      )}

      {empty ? (
        <Section title="Reply times">
          <EmptyState message={empty.message} hint={empty.hint} />
        </Section>
      ) : (
        <>
          <MetricRow label="Across every client">
            <Metric
              label="Typical reply"
              value={formatMs(overall.reply_typical_ms)}
              hint={`${formatCountOf(overall.calls_measured, "measured call")} of ${formatCount(overall.calls)}`}
            />
            <Metric
              label="Slow reply"
              value={formatMs(overall.reply_slow_ms)}
              hint={overall.reply_slow_ms == null ? "Needs ten measured calls" : "Nine calls in ten were faster"}
            />
            <Metric
              label="Model's first word"
              value={formatMs(overall.first_token_typical_ms)}
              hint={`Slow: ${formatMs(overall.first_token_slow_ms)}`}
            />
            <Metric
              label="Slowest reply"
              value={formatMs(overall.reply_worst_ms)}
              hint="One reply, on one call"
            />
            <Metric
              label="Replies over 5 s"
              value={formatCount(overall.slow_reply_problems)}
              tone={overall.slow_reply_problems > 0 ? "warn" : "default"}
              hint="Calls the platform flagged live"
            />
            <Metric
              label="Model errors"
              value={formatCount(overall.model_errors)}
              tone={overall.model_errors > 0 ? "warn" : "default"}
              hint={`${formatCountOf(overall.rescues, "turn")} answered by a backup model`}
            />
            <Metric label="Interruptions" value={formatCount(overall.interruptions)} hint="Caller spoke over the agent" />
            <Metric
              label="Long silences"
              value={formatCount(overall.long_silences)}
              hint={`Over ${formatCountOf(overall.turns, "answered turn")}`}
            />
          </MetricRow>

          <Section title="By day" description="Calls by the IST day they started.">
            <DataTable
              rows={report.by_day}
              columns={DAY_COLUMNS}
              getRowId={(row) => row.day}
              label="Reply times by day"
              defaultSort={{ id: "day", direction: "desc" }}
            />
          </Section>

          <Section title="By client" description="Most calls over target first.">
            <DataTable
              rows={report.by_client}
              columns={CLIENT_COLUMNS}
              getRowId={(row) => row.tenant_id}
              label="Reply times by client"
            />
          </Section>

          <Section
            title="By agent"
            description={
              report.agents_total > report.by_agent.length
                ? `The ${formatCount(report.by_agent.length)} agents with the most calls over target, of ${formatCount(report.agents_total)}.`
                : "Most calls over target first."
            }
          >
            <DataTable
              rows={report.by_agent}
              columns={AGENT_COLUMNS}
              getRowId={(row) => `${row.tenant_id}:${row.agent_id ?? "none"}`}
              label="Reply times by agent"
            />
          </Section>

          <Section title="By voice" description="Clear and Studio, by the rung each call was billed on.">
            <DataTable
              rows={report.by_tier}
              columns={TIER_COLUMNS}
              getRowId={(row) => row.tier}
              label="Reply times by voice"
            />
          </Section>

          <Section
            title="Slowest calls"
            description="By each call's slow reply. Opening one views it as the client."
          >
            {report.worst_calls.length === 0 ? (
              <EmptyState align="start" message="No measured calls in this window" />
            ) : (
              <DataTable
                rows={report.worst_calls}
                columns={CALL_COLUMNS}
                getRowId={(row) => row.call_id}
                label="Slowest calls"
              />
            )}
          </Section>
        </>
      )}
    </div>
  );
}
