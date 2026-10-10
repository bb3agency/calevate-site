"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { ProblemNotice, Skeleton } from "@/components/ui";
import { useCall, useCalls } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";

import { TranscriptCard } from "./calls/[callId]/TranscriptCard";
import { useRawTranscriptAccess } from "./calls/[callId]/transcriptAccess";

/**
 * THE TEST CALL, READ BACK WHERE IT WAS PLACED (founder, REDESIGN-2): after "Ring my phone",
 * the owner sees what was said without going to look for it.
 *
 * The trial endpoint answers with the engine's handle, not our call id, so the call is found
 * as this agent's newest call that started after the button was pressed (a minute's grace
 * for clock skew). Until it lands this renders nothing and the "Calling now" line above
 * speaks. The transcript is the call page's own `TranscriptCard`: redacted by default with
 * its notice above, and "Show full transcript" opens the call's page, where reading it raw
 * is audited.
 */
export function TestCallTranscript({ agentId, placedAt }: { agentId: string; placedAt: number }) {
  const session = useClientSession();
  const latest = useCalls(session, { agent_id: agentId, limit: 1 });
  const call = latest.data?.find(
    (c) => c.started_at !== null && c.started_at !== undefined && Date.parse(c.started_at) >= placedAt - 60_000,
  );
  if (!call) return null;
  return <TestCall callId={call.id} />;
}

function TestCall({ callId }: { callId: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const router = useRouter();
  const detail = useCall(session, callId);
  const rawAccess = useRawTranscriptAccess(session);
  const callHref = href(`/c/${session.orgSlug}/calls/${callId}`);

  if (detail.isPending) return <Skeleton rows={3} label="Getting your test call" />;
  if (detail.isError) return <ProblemNotice error={detail.error} onRetry={() => void detail.refetch()} />;
  const turns = detail.data.transcript ?? [];
  if (turns.length === 0) {
    return (
      <p role="status" className="text-meta text-ink-muted">
        Your test call has ended. What was said appears here once it is ready.
      </p>
    );
  }
  return (
    <div className="space-y-3 border-t border-line pt-6">
      <TranscriptCard
        turns={turns}
        showingRaw={false}
        showRaw={false}
        rawError={null}
        rawPending={false}
        onRetryRaw={() => undefined}
        rawAccess={rawAccess}
        onToggleRaw={() => router.push(callHref)}
        audioLoaded={false}
        playhead={null}
        onSeek={() => undefined}
      />
      <Link href={callHref} className="text-meta font-medium text-brand-strong hover:underline">
        Open this call
      </Link>
    </div>
  );
}
