"use client";

import { ProblemNotice, ScrollRegion, Skeleton } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useTold } from "@/lib/api/rehearse";
import type { ScriptHolder } from "@/lib/api/scriptChecks";

/**
 * WHAT IT IS TOLD (W3.15): the owner's part of the agent's instructions, exactly as the saved
 * script becomes them, read-only. The platform's own rules (the truthful answers, keeping its
 * instructions private, the notices) are never shown here and cannot be changed by a script.
 */
export function ToldView({ session, holder, script }: { session: Session; holder: ScriptHolder; script: unknown }) {
  const told = useTold(session, holder, script, true);
  if (told.isPending) return <Skeleton rows={6} label="Reading what the agent is told" />;
  if (told.isError) return <ProblemNotice error={told.error} onRetry={() => void told.refetch()} />;
  return (
    <div className="space-y-3">
      <p className="text-meta text-ink-muted">
        Your script, as the agent reads it. Our own call rules are added around it and are not shown.
      </p>
      {told.data.told ? (
        <ScrollRegion
          label="What the agent is told"
          edgeCue={false}
          className="max-h-[60dvh] overflow-y-auto rounded-md border border-line bg-surface-muted p-3"
        >
          <pre className="whitespace-pre-wrap font-sans text-sm text-ink [overflow-wrap:anywhere]">{told.data.told}</pre>
        </ScrollRegion>
      ) : (
        <p className="text-body text-ink-muted">There is no saved script yet.</p>
      )}
    </div>
  );
}
