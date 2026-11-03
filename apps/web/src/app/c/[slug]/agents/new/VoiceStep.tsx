"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import { ClientEngineVoices } from "@/components/engineCatalogueList";
import { PRIMARY_BUTTON, ProblemNotice, Skeleton, formatINR } from "@/components/ui";
import { useAgent } from "@/lib/api/agents";
import { usePendingChanges, voiceTierRate, type PendingState } from "@/lib/api/publishing";
import { useClientSession } from "@/lib/api/session";

import { SetupStep, SkipButton } from "./setupStep";

/**
 * STEP 2: THE VOICE. The agent Voice tab's own picker (`ClientEngineVoices`): the voices the
 * admin enabled, Clear then Studio, each with its sample, and the same save. Saving a voice
 * moves the flow on; Skip leaves the agent on none, changeable on its Voice tab.
 *
 * Each rung carries this account's rate for it, in the Voice tab's words ("Clear — ₹… / min",
 * `panels/publishing.VoiceNow`); the rate is the server's and is simply absent when it has none.
 */
export function VoiceStep({ agentId, onNext, onSkip }: { agentId: string; onNext: () => void; onSkip: () => void }) {
  const session = useClientSession();
  const agent = useAgent(session, agentId);
  const pending = usePendingChanges(session, agentId);

  let body;
  let next;
  if (agent.isLoading) {
    body = <Skeleton rows={4} />;
    next = <SkipButton onSkip={onSkip} />;
  } else if (agent.error || !agent.data) {
    body = (
      <ProblemNotice
        error={agent.error ?? new Error("Couldn't load your agent.")}
        onRetry={() => void agent.refetch()}
      />
    );
    next = <SkipButton onSkip={onSkip} />;
  } else {
    body = (
      <ClientEngineVoices
        session={session}
        agentId={agentId}
        onSaved={onNext}
        rungNote={(rung) => <RungRate rung={rung} pending={pending} />}
      />
    );
    next =
      agent.data.engine_voice_id != null ? (
        <button type="button" onClick={onNext} className={PRIMARY_BUTTON}>
          Continue
        </button>
      ) : (
        <SkipButton onSkip={onSkip} />
      );
  }

  return (
    <SetupStep title="Pick a voice" hint="Play a few, then pick one. You can change it later." actions={next}>
      {body}
    </SetupStep>
  );
}

function RungRate({ rung, pending }: { rung: "clear" | "studio"; pending: UseQueryResult<PendingState> }) {
  if (pending.isLoading) return null;
  if (pending.error || !pending.data) return <p className="mt-1 text-meta text-ink-muted">Its rate didn&apos;t load.</p>;
  const tier = voiceTierRate(pending.data.voice_tier_rates, rung);
  if (!tier) return null;
  return (
    <p className="mt-1 text-meta font-medium text-ink">
      {tier.inr_per_min === null
        ? `${tier.label}: no credit left, so no rate yet`
        : `${tier.label} — ${formatINR(tier.inr_per_min)} / min`}
    </p>
  );
}
