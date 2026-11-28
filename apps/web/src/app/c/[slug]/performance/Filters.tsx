"use client";

import { FIELD } from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useCampaigns } from "@/lib/api/campaigns";
import type { Session } from "@/lib/api/client";
import { useInboundLines } from "@/lib/api/inboundLines";
import { DIRECTIONS, type CallDirection } from "@/lib/callFilters";

/** What the Performance screen is narrowed to, beside its dates (W8.2). */
export type Narrowing = {
  agentId?: string;
  campaignId?: string;
  lineId?: string;
  direction?: CallDirection;
};

export const isNarrowed = (n: Narrowing): boolean =>
  Boolean(n.agentId || n.campaignId || n.lineId || n.direction);

/** "campaign:<id>" or "line:<id>" for the one select that offers both. */
function sourceValue(n: Narrowing): string {
  if (n.campaignId) return `campaign:${n.campaignId}`;
  if (n.lineId) return `line:${n.lineId}`;
  return "";
}

function sourceOf(value: string): Pick<Narrowing, "campaignId" | "lineId"> {
  const [kind, id] = value.split(":");
  if (kind === "campaign" && id) return { campaignId: id, lineId: undefined };
  if (kind === "line" && id) return { campaignId: undefined, lineId: id };
  return { campaignId: undefined, lineId: undefined };
}

export const FILTER_COPY = {
  agent: "Agent",
  anyAgent: "Every agent",
  source: "Campaign or line",
  anySource: "Every campaign and line",
  lines: "Inbound lines",
  campaigns: "Campaigns",
  direction: "Which way",
  bothWays: "Both ways",
  clear: "Clear filters",
  unread: "We could not list your agents, lines and campaigns.",
} as const;

/**
 * Agent, campaign or line, and which way: one row of native selects, the call log's own
 * pattern (`calls/CallsScreen.tsx`), so the two screens filter alike. Every analytics read
 * on the page takes the same three.
 */
export function PerformanceFilters({
  session,
  value,
  onChange,
}: {
  session: Session;
  value: Narrowing;
  onChange: (next: Narrowing) => void;
}) {
  const agents = useAgents(session);
  const campaigns = useCampaigns(session);
  const lines = useInboundLines(session);
  const unread = agents.isError || campaigns.isError || lines.isError;
  const campaignChoices = (campaigns.isSuccess ? campaigns.data : []).filter((c) => !c.archived_at || c.id === value.campaignId);
  const lineChoices = lines.isSuccess ? lines.data : [];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="block min-w-0 max-w-full">
        <span className="sr-only">{FILTER_COPY.agent}</span>
        <select
          value={value.agentId ?? ""}
          onChange={(e) => onChange({ ...value, agentId: e.target.value || undefined })}
          className={`${FIELD} mt-0 w-auto max-w-full`}
        >
          <option value="">{FILTER_COPY.anyAgent}</option>
          {(agents.isSuccess ? agents.data : []).map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block min-w-0 max-w-full">
        <span className="sr-only">{FILTER_COPY.source}</span>
        <select
          value={sourceValue(value)}
          onChange={(e) => onChange({ ...value, ...sourceOf(e.target.value) })}
          className={`${FIELD} mt-0 w-auto max-w-full`}
        >
          <option value="">{FILTER_COPY.anySource}</option>
          {lineChoices.length > 0 ? (
            <optgroup label={FILTER_COPY.lines}>
              {lineChoices.map((line) => (
                <option key={line.id} value={`line:${line.id}`}>
                  {line.name}
                </option>
              ))}
            </optgroup>
          ) : null}
          {campaignChoices.length > 0 ? (
            <optgroup label={FILTER_COPY.campaigns}>
              {campaignChoices.map((campaign) => (
                <option key={campaign.id} value={`campaign:${campaign.id}`}>
                  {campaign.name}
                </option>
              ))}
            </optgroup>
          ) : null}
        </select>
      </label>
      <label className="block">
        <span className="sr-only">{FILTER_COPY.direction}</span>
        <select
          value={value.direction ?? ""}
          onChange={(e) =>
            onChange({ ...value, direction: DIRECTIONS.find((d) => d.value === e.target.value)?.value })
          }
          className={`${FIELD} mt-0 w-auto`}
        >
          <option value="">{FILTER_COPY.bothWays}</option>
          {DIRECTIONS.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </select>
      </label>
      {isNarrowed(value) ? (
        <button
          type="button"
          onClick={() => onChange({})}
          className="text-meta font-medium text-ink underline underline-offset-2 hover:text-ink-muted"
        >
          {FILTER_COPY.clear}
        </button>
      ) : null}
      {unread ? <p className="w-full text-meta text-ink-muted">{FILTER_COPY.unread}</p> : null}
    </div>
  );
}
