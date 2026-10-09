"use client";

/**
 * "Record this number" for one number the voice platform holds (D-691).
 *
 * The number itself comes from the platform's own list, so nothing is typed: the operator
 * says what it is for and which agent answers it. The server reads whether it is rented,
 * its handle and its series from the platform, prices a rented one at the attested monthly
 * rate (its first month is collected now) and tells the platform which agent answers it.
 */

import { useState } from "react";

import {
  FIELD_INLINE,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import { useRecordEngineNumber, type RecordedEngineNumber } from "@/lib/api/numbers";
import type { components } from "@/lib/api/schema";

import { firstPeriodPhrase } from "./firstPeriod";

type Agent = components["schemas"]["EngineAgentOut"];
type Direction = "inbound" | "outbound" | "both";

const NO_AGENT = "";

export function RecordEngineNumber({
  tenantId,
  e164,
  agents,
  canWrite,
}: {
  tenantId: string;
  e164: string;
  agents: Agent[];
  canWrite: boolean;
}) {
  const record = useRecordEngineNumber(tenantId);
  const [open, setOpen] = useState(false);
  const [direction, setDirection] = useState<Direction>("both");
  const [agentId, setAgentId] = useState(NO_AGENT);

  if (record.data) return <p className="text-xs text-ink-muted">{recordedSentence(record.data)}</p>;
  if (!open) {
    return (
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={!canWrite}
        onClick={() => setOpen(true)}
      >
        Record this number
      </button>
    );
  }
  return (
    <form
      noValidate
      className="flex w-full flex-wrap items-end gap-2"
      onSubmit={(ev) => {
        ev.preventDefault();
        record.mutate({
          e164,
          direction,
          agent_id: agentId === NO_AGENT ? null : agentId,
        });
      }}
    >
      <label className="flex flex-col gap-1">
        <span className={FIELD_LABEL}>Used for</span>
        <select
          className={FIELD_INLINE}
          value={direction}
          onChange={(ev) => setDirection(ev.target.value as Direction)}
        >
          <option value="both">Incoming and outgoing calls</option>
          <option value="inbound">Incoming calls only</option>
          <option value="outbound">Outgoing calls only</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className={FIELD_LABEL}>Agent</span>
        <select
          className={FIELD_INLINE}
          value={agentId}
          onChange={(ev) => setAgentId(ev.target.value)}
        >
          <option value={NO_AGENT}>None yet</option>
          {agents.map((agent) => (
            <option key={agent.agent_id} value={agent.agent_id}>
              {agent.name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="submit"
        className={SECONDARY_BUTTON_SM}
        disabled={!canWrite || record.isPending}
      >
        {record.isPending ? "Recording…" : "Record"}
      </button>
      {record.error && (
        <div className="w-full">
          <ProblemNotice error={record.error} />
        </div>
      )}
    </form>
  );
}

function recordedSentence(recorded: RecordedEngineNumber): string {
  const price =
    recorded.client_inr_per_month === null
      ? "Brought on a carrier account, so there is no monthly charge."
      : firstPeriodPhrase(recorded.first_period, recorded.client_inr_per_month);
  const platform =
    recorded.platform_attachment === "partial" || recorded.platform_attachment === "refused"
      ? " The voice platform did not take which agent answers it yet; the daily number check tries again."
      : recorded.platform_attachment === "other_workspace"
        ? " It is held in the platform account and the agent lives in the client's own workspace, so nobody answers it."
        : "";
  const held = recorded.platform_held ? " Held in the platform account (testing only)." : "";
  return `Recorded. ${price}${platform}${held}`;
}
