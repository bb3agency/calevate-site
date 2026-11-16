"use client";

/**
 * PUTTING A NUMBER ON AN AGENT: one choice, the agent. The number does what that agent
 * does: an agent that answers calls answers it, one that makes calls calls out from it.
 * The server derives the number's direction from the agent, so the owner is never asked
 * what a number is "for" (the Retell/Vapi model: a number has an agent, nothing else).
 *
 * The form opens on the agent the number HAS. Opening on "No agent" made Save destructive:
 * pressed with nothing changed, it took the number off its agent.
 *
 * `AssignOut`'s counts are what the voice platform was TOLD, so a binding the platform
 * refused is reported as a failure rather than drawn from the request.
 *
 * A number on an Inbound line answers with that line, and the server refuses to move it
 * from here (`number_on_inbound_line`, D-1008), so the picker is replaced by a button to
 * the line. A number put on a line since the list loaded is refused with a button to
 * Inbound, and the list is read again, which turns the card into the line's.
 */

import Link from "next/link";
import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import {
  FIELD,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useAgents, type AgentDirection } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { NOT_ACTIVATED_CODE, ON_INBOUND_LINE_CODE, useAssignNumber } from "@/lib/api/numberProvisioning";
import { useClientRealm } from "@/lib/api/session";

/** Detach: the recovery path from a wrong choice. */
const NOBODY = "";

/** What each agent will do with the number, said in the option itself. */
const DOES: Record<AgentDirection, string> = {
  inbound: "answers calls",
  outbound: "makes calls",
  both: "answers and makes calls",
};

function refusalCode(error: unknown): unknown {
  if (!error || typeof error !== "object") return undefined;
  return (error as { code?: unknown }).code;
}

export function NumberAssignment({
  numberId,
  currentAgentId,
  line,
}: {
  numberId: string;
  /** `NumberOut.agent_id`: the agent the number is on now, or null. */
  currentAgentId: string | null;
  /** `NumberOut.inbound_line_id` / `inbound_line_name`: the line it answers with, or null. */
  line: { id: string; name: string } | null;
}) {
  const { session, href } = useClientRealm();
  const agents = useAgents(session);
  const assign = useAssignNumber(session);
  const assignFeedback = useActionFeedback(assign, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "choose which agent uses a number");
  const [agentId, setAgentId] = useState<string | null>(currentAgentId);

  if (line !== null) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="text-body text-ink-muted">
          {line.name ? `Answers with your Inbound line “${line.name}”.` : "Answers with one of your Inbound lines."}
        </p>
        <Link href={href(`/c/${session.orgSlug}/inbound/${line.id}`)} className={SECONDARY_BUTTON_SM}>
          Change in Inbound
        </Link>
      </div>
    );
  }
  if (agents.isLoading) return <Skeleton rows={1} label="Loading your agents" />;
  if (agents.error || !agents.data) {
    return <ProblemNotice error={agents.error ?? new Error("Your agents did not load.")} onRetry={() => agents.refetch()} />;
  }

  const offered = agents.data.filter((agent) => agent.status !== "archived");
  const unlisted = agentId !== null && !offered.some((agent) => agent.id === agentId) ? agentId : null;
  const result = assign.data;

  return (
    <div className="space-y-3">
      <div>
        <label className={FIELD_LABEL} htmlFor={`agent-${numberId}`}>
          Agent
        </label>
        <div className="mt-1.5 flex flex-col gap-2 sm:flex-row sm:items-center">
          <select
            id={`agent-${numberId}`}
            className={`${FIELD} sm:max-w-md`}
            value={agentId ?? NOBODY}
            disabled={!write.allowed}
            onChange={(event) => setAgentId(event.target.value === NOBODY ? null : event.target.value)}
          >
            <option value={NOBODY}>No agent</option>
            {unlisted !== null && <option value={unlisted}>Deleted agent</option>}
            {offered.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name} · {DOES[agent.direction]}
              </option>
            ))}
          </select>
          <ActionButton
            variant="primary-sm"
            // A 200 whose binding the voice platform refused is a failure to the owner.
            status={assignFeedback.status === "success" && (result?.failed ?? 0) > 0 ? "error" : assignFeedback.status}
            disabled={!write.allowed || agentId === currentAgentId}
            title={write.reason ?? undefined}
            onClick={() => assignFeedback.run({ numberId, agentId, direction: null })}
            pendingLabel="Saving…"
            successLabel="Saved"
          >
            Save
          </ActionButton>
        </div>
      </div>

      <RestrictionNote reason={write.reason} />

      {assign.error && (
        <div className="space-y-2">
          <ProblemNotice error={assign.error} />
          {/* The refusals the client can act on themselves, each with its way out. */}
          {refusalCode(assign.error) === NOT_ACTIVATED_CODE && (
            <Link href={href(`/c/${session.orgSlug}/verify-business`)} className={SECONDARY_BUTTON_SM}>
              Verify your business
            </Link>
          )}
          {refusalCode(assign.error) === ON_INBOUND_LINE_CODE && (
            <Link href={href(`/c/${session.orgSlug}/inbound`)} className={SECONDARY_BUTTON_SM}>
              Open Inbound
            </Link>
          )}
        </div>
      )}

      {result && result.failed > 0 && (
        <NoticeBox tone="stop">
          <p>Could not connect it to that agent. Try again.</p>
        </NoticeBox>
      )}
    </div>
  );
}
