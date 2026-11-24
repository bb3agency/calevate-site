"use client";

import { PenLine } from "lucide-react";
import { useCallback } from "react";

import { ScriptDraftLive } from "@/components/scriptDraft/ScriptDraftLive";
import type { Session } from "@/lib/api/client";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import type { DraftRef } from "@/lib/copilot/liveEvents";

import { TimelineRow } from "./TimelineRow";

/**
 * The script drafts this conversation started, inline in Pip's thread (`event: draft`),
 * drawn by the same component the campaign and Inbound line pages use.
 *
 * Drafts are kept on the client's own campaigns and lines, so the admin console's Pip, which
 * acts as the platform, says where the draft is rather than offering Keep on a client's
 * script from here.
 */
export function PanelDrafts({
  session,
  drafts,
  realm,
  onPhase,
}: {
  session: Session;
  drafts: readonly DraftRef[];
  realm: "client" | "admin";
  onPhase: (proposalId: string, phase: string, settled: boolean) => void;
}) {
  if (drafts.length === 0) return null;
  return (
    <div className="space-y-4">
      {drafts.map((draft) =>
        realm === "client" ? (
          <PanelDraft key={draft.proposal_id} session={session} draft={draft} onPhase={onPhase} />
        ) : (
          <ElsewhereNote key={draft.proposal_id} draft={draft} />
        ),
      )}
    </div>
  );
}

function PanelDraft({
  session,
  draft,
  onPhase,
}: {
  session: Session;
  draft: DraftRef;
  onPhase: (proposalId: string, phase: string, settled: boolean) => void;
}) {
  const id = draft.proposal_id;
  const report = useCallback((phase: string, settled: boolean) => onPhase(id, phase, settled), [onPhase, id]);
  return (
    <ScriptDraftLive
      session={session}
      holder={{ kind: draft.holder_kind, id: draft.holder_id }}
      proposalId={id}
      onPhase={report}
      fallback={<ElsewhereNote draft={draft} />}
    />
  );
}

function ElsewhereNote({ draft }: { draft: DraftRef }) {
  const where = draft.holder_kind === "campaign" ? "the campaign's page" : "the line's page";
  return (
    <TimelineRow as="div" icon={<PenLine aria-hidden className="h-3.5 w-3.5" />}>
      <p className="text-meta text-ink">
        {ASSISTANT_NAME} is writing a script. Find it on {where}.
      </p>
    </TimelineRow>
  );
}
