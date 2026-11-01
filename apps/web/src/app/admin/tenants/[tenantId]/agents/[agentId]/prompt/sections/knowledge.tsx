"use client";

/**
 * Everything this agent holds on the voice platform (D-868), one row per item: the client's
 * own (held, or missing there), the client's live items not on this agent and why, and
 * documents the platform holds that we did not send. Only the last kind has a button: ours
 * are removed from the client's page, so our rows and the platform never disagree.
 */

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { lookup } from "@/lib/lookup";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { StatusPill } from "@/components/admin/kit";
import { ProblemNotice, Skeleton, type NoticeTone } from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  useAdminAgentKnowledge,
  useAdminRemoveAgentDocument,
  type AgentKnowledgeItem,
} from "@/lib/api/agentKnowledge";

const VERDICT: Record<AgentKnowledgeItem["verdict"], { label: string; tone: NoticeTone }> = {
  held: { label: "On the agent", tone: "ok" },
  missing: { label: "Missing on ThinnestAI", tone: "stop" },
  not_sent: { label: "Not on this agent", tone: "warn" },
  not_ours: { label: "Not sent by us", tone: "warn" },
};

const KIND: Record<string, string> = {
  pdf: "PDF",
  url: "Link",
  text: "Typed",
  facts: "Business facts",
  image: "Photo",
};

function rowLabel(item: AgentKnowledgeItem): string {
  if (item.name) return item.name;
  return `Document ${item.handle ?? ""}`.trim();
}

function rowHint(item: AgentKnowledgeItem): string {
  const kind = item.kind ? (lookup(KIND, item.kind) ?? item.kind.toUpperCase()) : "Unknown origin";
  return item.detail ? `${kind} · ${item.detail}` : kind;
}

export function AgentKnowledgePanel({
  tenantId,
  agentId,
  write,
}: {
  tenantId: string;
  agentId: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const state = useAdminAgentKnowledge(tenantId, agentId);
  const remove = useAdminRemoveAgentDocument(tenantId, agentId);
  const feedback = useActionFeedback(remove, { errorDisplay: "inline", successToast: "Document removed" });

  if (state.isLoading) return <Skeleton rows={3} />;
  if (state.error || !state.data) {
    return (
      <ProblemNotice
        error={state.error ?? new Error("This agent's knowledge could not be read just now.")}
        onRetry={() => void state.refetch()}
      />
    );
  }
  const { items, listed } = state.data;
  return (
    <div className="space-y-3">
      {!listed && (
        <p className="text-meta text-ink-muted">
          ThinnestAI&apos;s list could not be read. Rows show our records only.
        </p>
      )}
      {feedback.error ? <ProblemNotice error={feedback.error} /> : null}
      {items.length === 0 ? (
        <p className="text-body text-ink-muted">This agent holds no knowledge.</p>
      ) : (
        <SettingRows>
          {items.map((item) => (
            <SettingRow
              key={`${item.verdict}:${item.handle ?? item.source_id ?? ""}`}
              label={rowLabel(item)}
              hint={rowHint(item)}
              value={<StatusPill tone={VERDICT[item.verdict].tone}>{VERDICT[item.verdict].label}</StatusPill>}
              action={
                item.verdict === "not_ours" && item.handle ? (
                  <ActionButton
                    variant="secondary-sm"
                    status={remove.variables === item.handle ? feedback.status : "idle"}
                    pendingLabel="Removing…"
                    successLabel="Removed"
                    disabled={!write.allowed}
                    onClick={() => item.handle && feedback.run(item.handle)}
                  >
                    Remove
                  </ActionButton>
                ) : null
              }
            />
          ))}
        </SettingRows>
      )}
    </div>
  );
}
