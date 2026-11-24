"use client";

/**
 * Everything this agent's engine agents hold on the voice platform (D-868), one group per
 * engine agent carrying it (D-1019: its live lines, the campaigns holding one, its test copy,
 * its own while it still has one) and one row per item: the client's own (held, or missing
 * there), the client's live items not on it and why, and documents the platform holds that we
 * did not send. Only the last kind has a button: ours are removed from the client's page, so
 * our rows and the platform never disagree.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { lookup } from "@/lib/lookup";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { StatusPill } from "@/components/admin/kit";
import { ProblemNotice, Skeleton, type NoticeTone } from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  useAdminAgentKnowledge,
  useAdminRemoveAgentDocument,
  type AgentKnowledgeItem,
  type HolderKnowledge,
} from "@/lib/api/agentKnowledge";
import { resetIfSettled } from "@/app/admin/resetIfSettled";

const VERDICT: Record<AgentKnowledgeItem["verdict"], { label: string; tone: NoticeTone }> = {
  held: { label: "On it", tone: "ok" },
  missing: { label: "Missing on ThinnestAI", tone: "stop" },
  not_sent: { label: "Not on it", tone: "warn" },
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

function holderTitle(holder: HolderKnowledge): string {
  switch (holder.kind) {
    case "line":
      return `Inbound line: ${holder.name ?? "unnamed"}`;
    case "campaign":
      return `Campaign: ${holder.name ?? "unnamed"}`;
    case "test_copy":
      return "Test copy (the owner's test calls)";
    case "arm":
      return `Script test arm ${holder.name ?? ""}`.trim();
    default:
      return "The agent's own engine agent";
  }
}

interface Removal {
  holder: HolderKnowledge;
  item: AgentKnowledgeItem;
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
  // The delete happens on the voice platform and we hold no copy of a document we did not
  // send, so it cannot be undone from here: ask first.
  const [confirming, setConfirming] = useState<Removal | null>(null);

  if (state.isLoading) return <Skeleton rows={3} />;
  if (state.error || !state.data) {
    return (
      <ProblemNotice
        error={state.error ?? new Error("This agent's knowledge could not be read just now.")}
        onRetry={() => void state.refetch()}
      />
    );
  }
  const { holders } = state.data;
  if (holders.length === 0) {
    return (
      <p className="text-body text-ink-muted">
        Nothing carries this agent to callers yet: no live inbound line, campaign or test copy
        holds it, so no knowledge is on ThinnestAI for it.
      </p>
    );
  }
  const removing = (holder: HolderKnowledge, item: AgentKnowledgeItem) =>
    remove.variables?.holderRef === holder.engine_agent_ref &&
    remove.variables.handle === item.handle;
  return (
    <div className="space-y-6">
      {holders.map((holder) => (
        <section key={holder.engine_agent_ref} aria-label={holderTitle(holder)} className="space-y-2">
          <h4 className="text-body font-semibold text-ink">
            {holderTitle(holder)}{" "}
            <span className="font-mono text-meta font-normal text-ink-muted">{holder.engine_agent_ref}</span>
          </h4>
          {!holder.listed && (
            <p className="text-meta text-ink-muted">
              ThinnestAI&apos;s list could not be read. Rows show our records only.
            </p>
          )}
          {holder.items.length === 0 ? (
            <p className="text-body text-ink-muted">It holds no knowledge.</p>
          ) : (
            <SettingRows>
              {holder.items.map((item) => (
                <SettingRow
                  key={`${item.verdict}:${item.handle ?? item.source_id ?? ""}`}
                  label={rowLabel(item)}
                  hint={rowHint(item)}
                  value={<StatusPill tone={VERDICT[item.verdict].tone}>{VERDICT[item.verdict].label}</StatusPill>}
                  action={
                    item.verdict === "not_ours" && item.handle ? (
                      <ActionButton
                        variant="secondary-sm"
                        status={removing(holder, item) ? feedback.status : "idle"}
                        pendingLabel="Removing…"
                        successLabel="Removed"
                        disabled={!write.allowed}
                        waitingFor={
                          remove.isPending && !removing(holder, item)
                            ? "Waiting for the other removal to finish."
                            : null
                        }
                        onClick={() => {
                          resetIfSettled(remove);
                          setConfirming({ holder, item });
                        }}
                      >
                        Remove
                      </ActionButton>
                    ) : null
                  }
                />
              ))}
            </SettingRows>
          )}
        </section>
      ))}
      {confirming?.item.handle ? (
        <ConfirmDialog
          title={`Remove ${rowLabel(confirming.item)} from ${holderTitle(confirming.holder)}`}
          confirmLabel="Remove it"
          pendingLabel="Removing…"
          status={feedback.status}
          error={remove.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const handle = confirming.item.handle;
            if (handle) {
              remove.mutate(
                { holderRef: confirming.holder.engine_agent_ref, handle },
                { onSuccess: () => setConfirming(null) },
              );
            }
          }}
        >
          <p>
            It is deleted on ThinnestAI from this engine agent only. We did not send it and hold
            no copy, so it cannot be put back from here.
          </p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
