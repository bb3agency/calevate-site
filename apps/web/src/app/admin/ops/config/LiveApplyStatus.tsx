"use client";

import { CheckCircle2, Loader2, TriangleAlert } from "lucide-react";

import { MonoValue } from "@/app/admin/ops/opsLanguage";
import { formatIST } from "@/components/ui";
import { liveApplyLine, usePlatformLiveApply, type LiveApplyRun } from "@/lib/api/opsLiveApply";

/**
 * Where the newest ops console change that live agents carry has got to (D-720): "Applied
 * to N of M live agents", read from the run the server recorded when it was saved, and the
 * agents it could not update. Nothing renders until such a change has been made, and a read
 * that fails says nothing rather than a guess: the settings below are unaffected.
 */
export function LiveApplyStatus() {
  const query = usePlatformLiveApply();
  const run = query.data?.runs[0];
  if (!run) return null;
  return <LiveApplyLine run={run} />;
}

export function LiveApplyLine({ run }: { run: LiveApplyRun }) {
  const moving = run.status === "pending" || run.status === "running";
  const Icon = moving ? Loader2 : run.failed > 0 ? TriangleAlert : CheckCircle2;
  return (
    <div role="status" className="space-y-1 text-meta">
      <p className="flex items-center gap-1.5 text-ink">
        <Icon
          aria-hidden
          className={`h-3.5 w-3.5 ${moving ? "animate-spin text-ink-muted" : run.failed > 0 ? "text-warn" : "text-brand"}`}
        />
        <span>
          {liveApplyLine(run)} Changed: {run.reasons.map((reason, index) => (
            <span key={reason}>
              {index > 0 ? ", " : ""}
              <MonoValue>{reason}</MonoValue>
            </span>
          ))}
          , {formatIST(run.created_at)}. A call in progress finishes first.
        </span>
      </p>
      {run.failures.length > 0 && (
        <ul className="ml-5 list-disc text-ink-muted">
          {run.failures.map((failure) => (
            <li key={failure.agent_id}>
              {failure.agent_name ?? <MonoValue>{failure.agent_id}</MonoValue>} kept its previous
              settings (<MonoValue>{failure.code}</MonoValue>). Fix the cause, then republish it.
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
