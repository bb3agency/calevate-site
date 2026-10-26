"use client";

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Drawer } from "@/components/console/drawer";
import { FIELD_LABEL, ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import type { useAgents } from "@/lib/api/agents";
import { useSetLeadSourceAgent, type LeadSource } from "@/lib/api/leadSources";

import { rowName } from "./SourcesList";
import { FIELD } from "./styles";

/**
 * WHO ANSWERS ONE SOURCE'S LEADS. Opens on the agent the source names now, so Save with
 * nothing changed changes nothing. "Not yet" is a real choice and says what it costs: the
 * source keeps saving leads and calls nobody. The secret and the address do not change.
 *
 * The lead-calling plan's own agent, when one is chosen there, still calls every source's
 * leads; this is the agent used when it is not.
 */
export function AgentDrawer({
  source,
  agents,
  session,
  onClose,
}: {
  source: LeadSource;
  agents: ReturnType<typeof useAgents>;
  session: Session;
  onClose: () => void;
}) {
  const save = useSetLeadSourceAgent(session);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved" });
  const [agentId, setAgentId] = useState(source.agent_id ?? "");
  const unread = agents.error != null || (!agents.isLoading && !agents.data);

  return (
    <Drawer
      open
      onClose={onClose}
      title="Who answers these leads"
      description={rowName(source)}
      footer={
        <>
          <button type="button" onClick={onClose} className={SECONDARY_BUTTON}>
            Cancel
          </button>
          <ActionButton
            type="button"
            status={feedback.status}
            disabled={unread || agents.isLoading}
            pendingLabel="Saving…"
            successLabel="Saved"
            onClick={() =>
              save.mutate(
                { webhookId: source.id, agentId: agentId || null },
                { onSuccess: onClose },
              )
            }
          >
            Save
          </ActionButton>
        </>
      }
    >
      <div className="space-y-3">
        {save.error && <ProblemNotice error={save.error} />}
        {unread ? (
          <ProblemNotice
            error={agents.error ?? new Error("Your agents could not be loaded.")}
            onRetry={() => void agents.refetch()}
          />
        ) : (
          <label className="block">
            <span className={FIELD_LABEL}>Agent</span>
            <select
              value={agentId}
              disabled={agents.isLoading}
              onChange={(e) => setAgentId(e.target.value)}
              className={`${FIELD} mt-1 block w-full`}
            >
              <option value="">
                {agents.isLoading ? "Reading your agents…" : "Not yet — save leads, don't call"}
              </option>
              {(agents.data ?? []).map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <p className="text-meta text-ink-muted">
          New leads from this source go to the agent you choose. Leads already called are not
          called again.
        </p>
      </div>
    </Drawer>
  );
}
