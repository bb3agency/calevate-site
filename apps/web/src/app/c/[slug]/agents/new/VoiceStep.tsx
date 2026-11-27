"use client";

import { ClientEngineVoices } from "@/components/engineCatalogueList";
import { PRIMARY_BUTTON, ProblemNotice, Skeleton } from "@/components/ui";
import { useAgent } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";

import { SetupStep, SkipButton } from "./setupStep";

/**
 * STEP 2: THE VOICE. The agent's own voice picker (`ClientEngineVoices`): the voices the
 * admin enabled, Clear then Studio, each with its sample, its price a minute
 * (`lib/voiceMinutePrice.ts`) and the same save. Saving a voice moves the flow on; Skip
 * leaves the agent on none, changeable in its Voice tab.
 */
export function VoiceStep({ agentId, onNext, onSkip }: { agentId: string; onNext: () => void; onSkip: () => void }) {
  const session = useClientSession();
  const agent = useAgent(session, agentId);

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
    body = <ClientEngineVoices session={session} agentId={agentId} onSaved={onNext} />;
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
