"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useCall, useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { testCallIsLive } from "@/lib/api/trialCalls";

import { initialView, useRetryEnglish, type CallView } from "./calls/[callId]/callEnglish";
import { TranscriptCard } from "./calls/[callId]/TranscriptCard";
import { useRawTranscriptAccess } from "./calls/[callId]/transcriptAccess";

/**
 * THE TEST CALL, READ BACK WHERE IT WAS PLACED (founder, REDESIGN-2): after "Ring my phone",
 * the owner sees what was said without going to look for it.
 *
 * The call is our id from the test-call endpoint (D-885), not a guess at "this agent's newest
 * call", which a second call or a slow clock could get wrong. The transcript is the call
 * page's own `TranscriptCard`: redacted by default with its notice above, and "Show full
 * transcript" opens the call's page, where reading it raw is audited.
 */
export function TestCallTranscript({ callId }: { callId: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const router = useRouter();
  const detail = useCall(session, callId);
  const rawAccess = useRawTranscriptAccess(session);
  const callHref = href(`/c/${session.orgSlug}/calls/${callId}`);
  const englishWrite = useWriteAccess(session, "org:manage", "prepare the English of a call");
  const retryEnglish = useRetryEnglish(session, callId);
  // `TranscriptCard` shows the failure beside its retry control, so it is not toasted.
  const retryFeedback = useActionFeedback(retryEnglish, { errorDisplay: "inline" });
  const [view, setView] = useState<CallView>(initialView);

  if (detail.isPending) return <Skeleton rows={3} label="Getting your test call" />;
  if (detail.isError) return <ProblemNotice error={detail.error} onRetry={() => void detail.refetch()} />;
  // While it runs there is nothing to read yet, and the call's status line says so.
  if (testCallIsLive(detail.data)) return null;
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
        detail={detail.data}
        turns={turns}
        view={view}
        onViewChange={setView}
        english={{
          access: englishWrite,
          onRetry: () => retryFeedback.run(),
          pending: retryFeedback.status === "pending",
          error: retryEnglish.error,
        }}
        player={null}
        noRecording={false}
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
