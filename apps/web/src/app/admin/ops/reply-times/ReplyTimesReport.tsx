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
  SETTING_LABELS,
  SPLIT_STEPS,
  TIER_LABELS,
  formatDay,
  formatMs,
  settingValueLabel,
  windowLabel,
  type AgentReplyTimes,
  type AgentTurnSplit,
  type ClientReplyTimes,
  type DayReplyTimes,
  type ReplyTimeFigures,
  type ReplyTimeReport,
  type SettingReplyTimes,
  type SlowCall,
  type TierReplyTimes,
  type TurnSplit,
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
      header: "Calls with an answer time",
      renderHeader: glossed(
        "Calls with an answer time",
        "Calls the platform timed to the answer, of the calls that connected and finished. Calls before 27 Oct 2026 have none.",
      ),
      className: "tabular-nums",
      sort: { value: (row) => row.calls_answer_measured, kind: "number", first: "desc" },
      cell: (row) => (
        <>
          {formatCount(row.calls_answer_measured)}
          <span className="text-ink-muted"> of {formatCount(row.calls)}</span>
        </>
      ),
    },
    {
      id: "typical",
      header: "Typical answer",
      renderHeader: glossed(
        "Typical answer",
        "The middle of the calls' own typical waits for the first word of the answer. A filler line does not count.",
      ),
      hideBelow: "sm",
      className: "tabular-nums",
      sort: { value: (row) => row.answer_typical_ms, kind: "number", first: "desc" },
      cell: (row) => formatMs(row.answer_typical_ms),
    },
    {
      id: "slow",
      header: "Slow answer",
      renderHeader: glossed(
        "Slow answer",
        "Nine calls in ten had their slowest tenth of answers faster than this. Blank below ten calls with an answer time.",
      ),
      hideBelow: "sm",
      className: "tabular-nums",
      sort: { value: (row) => row.answer_slow_ms, kind: "number", first: "desc" },
      cell: (row) => formatMs(row.answer_slow_ms),
    },
    {
      id: "first-sound",
      header: "First sound",
      renderHeader: glossed(
        "First sound",
        "The typical wait for the agent's first sound of any kind, a filler line included. The gap to the answer is how long fillers held the line.",
      ),
      hideBelow: "md",
      className: "tabular-nums",
      sort: { value: (row) => row.first_sound_typical_ms, kind: "number", first: "desc" },
      cell: (row) => formatMs(row.first_sound_typical_ms),
    },
    {
      id: "first-token",
      header: "Model's first word",
      renderHeader: glossed(
        "Model's first word",
        "From the turn reaching the voice platform to the first speakable word, not from when the caller stopped.",
      ),
      hideBelow: "lg",
      className: "tabular-nums",
      sort: { value: (row) => row.first_token_typical_ms, kind: "number", first: "desc" },
      cell: (row) => formatMs(row.first_token_typical_ms),
    },
    {
      id: "over",
      header: "Over target",
      renderHeader: glossed(
        "Over target",
        "Calls where more than one answer in ten took longer than the slow target.",
      ),
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
      id: "lookups",
      header: "Knowledge lookups",
      renderHeader: glossed("Knowledge lookups", "Turns on which the agent looked something up in the client's knowledge."),
      hideBelow: "lg",
      className: "tabular-nums",
      sort: { value: (row) => row.knowledge_turns, kind: "number", first: "desc" },
      cell: (row) => formatCount(row.knowledge_turns),
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

function agentCell(row: { tenant_id: string; agent_name?: string | null; client_name: string }) {
  return (
    <div className="sm:min-w-[8rem]">
      <Link href={`/admin/tenants/${row.tenant_id}/agents`} className={TEXT_ACTION}>
        {row.agent_name ?? "Removed agent"}
      </Link>
      <span className="block text-meta text-ink-muted">{row.client_name}</span>
    </div>
  );
}

const AGENT_COLUMNS: DataColumn<AgentReplyTimes>[] = [
  {
    id: "agent",
    header: "Agent",
    sort: { value: (row) => row.agent_name },
    cell: agentCell,
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

const SETTING_COLUMNS: DataColumn<SettingReplyTimes>[] = [
  {
    id: "setting",
    header: "Setting",
    cell: (row) => (
      <span className="font-medium text-ink">{lookup(SETTING_LABELS, row.setting) ?? row.setting}</span>
    ),
  },
  {
    id: "value",
    header: "Value",
    cell: (row) => <span className="whitespace-nowrap">{settingValueLabel(row.value)}</span>,
  },
  ...figureColumns<SettingReplyTimes>(),
];

/** The step columns of a split table, after its own label columns. */
function splitColumns<T extends TurnSplit>(): DataColumn<T>[] {
  return [
    {
      id: "turns",
      header: "Turns timed",
      renderHeader: glossed("Turns timed", "Turns the platform timed step by step, and on how many calls."),
      className: "tabular-nums",
      sort: { value: (row) => row.turns_timed, kind: "number", first: "desc" },
      cell: (row) => (
        <>
          {formatCount(row.turns_timed)}
          <span className="block text-meta text-ink-muted">{formatCountOf(row.calls_timed, "call")}</span>
        </>
      ),
    },
    {
      id: "answer",
      header: "Answer",
      renderHeader: glossed(
        "Answer",
        "The middle turn's wait for the first word of the answer, and the point nine turns in ten were faster than (blank below ten turns).",
      ),
      className: "tabular-nums",
      sort: { value: (row) => row.answer_ms, kind: "number", first: "desc" },
      cell: (row) => (
        <>
          {formatMs(row.answer_ms)}
          {row.answer_slow_ms != null && (
            <span className="block text-meta text-ink-muted">slow {formatMs(row.answer_slow_ms)}</span>
          )}
        </>
      ),
    },
    ...SPLIT_STEPS.map(
      (step): DataColumn<T> => ({
        id: step.key,
        header: step.label,
        renderHeader: glossed(step.label, step.gloss),
        hideBelow: step.key === "wait_before_decision_ms" || step.key === "model_first_sentence_ms" ? "sm" : "md",
        className: "tabular-nums",
        sort: { value: (row) => row[step.key], kind: "number", first: "desc" },
        cell: (row) => formatMs(row[step.key]),
      }),
    ),
    {
      id: "filler-first",
      header: "Filler first",
      renderHeader: glossed(
        "Filler first",
        "Turns whose first sound was a filler line or an acknowledgement; their answer start is estimated from the audio queued behind it.",
      ),
      hideBelow: "lg",
      className: "tabular-nums",
      sort: { value: (row) => row.turns_filler_first, kind: "number", first: "desc" },
      cell: (row) => formatCount(row.turns_filler_first),
    },
  ];
}

const modeCell = (row: TurnSplit) => (
  <span className="whitespace-nowrap font-medium text-ink">{settingValueLabel(row.turn_detection)}</span>
);

const MODE_SPLIT_COLUMNS: DataColumn<TurnSplit>[] = [
  { id: "mode", header: "Turn detection", cell: modeCell },
  ...splitColumns<TurnSplit>(),
];

const AGENT_SPLIT_COLUMNS: DataColumn<AgentTurnSplit>[] = [
  { id: "agent", header: "Agent", sort: { value: (row) => row.agent_name }, cell: agentCell },
  { id: "mode", header: "Turn detection", cell: modeCell },
  ...splitColumns<AgentTurnSplit>(),
];

/** Over the target, when there is a figure to judge. */
function overTarget(value: number | null | undefined, target: number): boolean {
  return value !== null && value !== undefined && value > target;
}

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
    header: "Typical answer",
    hideBelow: "sm",
    className: "tabular-nums",
    cell: (row) => formatMs(row.answer_median_ms),
  },
  {
    id: "p90",
    header: "Slow answer",
    renderHeader: glossed(
      "Slow answer",
      "Nine answers in ten on this call came faster than this. Blank on a call from before answer times; it is then ranked by its first sound.",
    ),
    className: "tabular-nums",
    cell: (row) => formatMs(row.answer_p90_ms),
  },
  {
    id: "first-sound",
    header: "First sound, slow",
    hideBelow: "md",
    className: "tabular-nums",
    cell: (row) => formatMs(row.first_sound_p90_ms),
  },
  {
    id: "worst",
    header: "Longest answer",
    hideBelow: "sm",
    className: "tabular-nums",
    cell: (row) => formatMs(row.answer_max_ms),
  },
  {
    id: "lookups",
    header: "Knowledge lookups",
    hideBelow: "lg",
    className: "tabular-nums",
    cell: (row) => (row.knowledge_turns == null ? "—" : formatCount(row.knowledge_turns)),
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
          {formatCount(overall.calls_over_target)} of{" "}
          {formatCountOf(overall.calls_answer_measured, "call")} with an answer time
        </span>
        <span>over target</span>
        <span className="text-ink-muted">
          · targets: typical{" "}
          <span className="font-medium text-ink">{formatMs(report.typical_target_ms)}</span>, slow{" "}
          <span className="font-medium text-ink">{formatMs(report.slow_target_ms)}</span>
        </span>
        <span className="text-ink-muted">
          · last <span className="font-medium text-ink">{windowLabel(report.window_days)}</span>
        </span>
        <InfoTip label="How calls are judged">
          <p>
            The typical wait for an answer is judged against the typical target. A call is over
            target when more than one of its answers in ten took longer than the slow target.
            Calls from before answer times are not judged. Both targets are console settings.
          </p>
          <p>
            <Link href={CONFIG_HREF} className={TEXT_ACTION}>
              Change the targets in Configuration
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
              label="Typical wait for an answer"
              value={formatMs(overall.answer_typical_ms)}
              tone={overTarget(overall.answer_typical_ms, report.typical_target_ms) ? "warn" : "default"}
              hint={`Target ${formatMs(report.typical_target_ms)} · ${formatCountOf(overall.calls_answer_measured, "call")} of ${formatCount(overall.calls)}`}
            />
            <Metric
              label="Slow wait for an answer"
              value={formatMs(overall.answer_slow_ms)}
              tone={overTarget(overall.answer_slow_ms, report.slow_target_ms) ? "warn" : "default"}
              hint={
                overall.answer_slow_ms == null
                  ? "Needs ten calls with an answer time"
                  : `Target ${formatMs(report.slow_target_ms)} · nine calls in ten were faster`
              }
            />
            <Metric
              label="Typical first sound"
              value={formatMs(overall.first_sound_typical_ms)}
              hint={`A filler line counts · slow ${formatMs(overall.first_sound_slow_ms)}`}
            />
            <Metric
              label="Model's first word"
              value={formatMs(overall.first_token_typical_ms)}
              hint={`Slow: ${formatMs(overall.first_token_slow_ms)}`}
            />
            <Metric
              label="Longest answer"
              value={formatMs(overall.answer_worst_ms)}
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
            <Metric
              label="Knowledge lookups"
              value={formatCount(overall.knowledge_turns)}
              hint={`Over ${formatCountOf(overall.turns, "answered turn")}`}
            />
            <Metric label="Interruptions" value={formatCount(overall.interruptions)} hint="Caller spoke over the agent" />
            <Metric
              label="Long silences"
              value={formatCount(overall.long_silences)}
              hint={`Over ${formatCountOf(overall.turns, "answered turn")}`}
            />
          </MetricRow>

          <Section
            title="Where the wait goes"
            description="Medians over every timed turn, by the turn detection each call ran on. Steps overlap, so they do not add up to the answer."
          >
            {report.split_by_turn_detection.length === 0 ? (
              <EmptyState
                align="start"
                message="No turns timed step by step in this window"
                hint="The platform times each turn on its usual voice pipeline from 27 Oct 2026, a few minutes after each call."
              />
            ) : (
              <div className="space-y-6">
                <DataTable
                  rows={report.split_by_turn_detection}
                  columns={MODE_SPLIT_COLUMNS}
                  getRowId={(row) => row.turn_detection}
                  label="Where the wait goes, by turn detection"
                />
                <DataTable
                  rows={report.split_by_agent}
                  columns={AGENT_SPLIT_COLUMNS}
                  getRowId={(row) => `${row.tenant_id}:${row.agent_id ?? "none"}:${row.turn_detection}`}
                  label="Where the wait goes, by agent and turn detection"
                />
              </div>
            )}
          </Section>

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
            title="By call setting"
            description="Each call is counted under the settings its agent was published with when it began."
          >
            {report.by_setting.length === 0 ? (
              <EmptyState align="start" message="No calls in this window" />
            ) : (
              <DataTable
                rows={report.by_setting}
                columns={SETTING_COLUMNS}
                getRowId={(row) => `${row.setting}:${row.value}`}
                label="Reply times by call setting"
              />
            )}
          </Section>

          <Section
            title="Slowest calls"
            description="By each call's slow answer. Opening one views it as the client, with its turns step by step."
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
