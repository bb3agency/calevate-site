"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";

import {
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import { useStruggles, type Struggle } from "@/lib/api/teach";

const KIND_LABEL: Record<string, string> = {
  didnt_know: "Didn't know",
  put_off: "Put it off to a call back",
  unanswered: "Left it unanswered",
  needed_you: "The call needed you",
};

/** Where in the script a fix for this kind of struggle usually goes. */
const SCRIPT_PLACE: Record<string, string> = {
  didnt_know: "stages",
  put_off: "policies",
  unanswered: "stages",
  needed_you: "policies",
};

/**
 * WHERE THE AGENTS STRUGGLED ON REAL CALLS, found from the calls themselves — never guessed.
 * Each item opens the call it came from and offers the two fixes: add the answer (opens the
 * teach box with the question filled in) or change how the agent behaves (its script).
 */
export function WhereItStruggled({
  canWrite,
  onAddAnswer,
}: {
  canWrite: boolean;
  onAddAnswer: (struggle: Struggle) => void;
}) {
  const session = useClientSession();
  const struggles = useStruggles(session);

  if (struggles.isLoading) return <Skeleton rows={4} label="Loading where your agents struggled" />;
  if (struggles.error || !struggles.data) {
    return (
      <ProblemNotice
        error={struggles.error ?? new Error("We could not load where your agents struggled.")}
        onRetry={() => void struggles.refetch()}
      />
    );
  }
  if (struggles.data.length === 0) {
    return (
      <p className="flex items-center gap-2 text-meta text-ink-muted">
        <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
        Nothing to fix. When an agent cannot answer a caller, it shows up here.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-meta text-ink-muted">Found from your real calls, newest problems first.</p>
      <ul className="divide-y divide-line border-y border-line" aria-label="Where your agents struggled">
        {struggles.data.map((struggle) => (
          <li key={struggle.id} className="space-y-2 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <h3 className="min-w-0 text-sm font-semibold text-ink [overflow-wrap:anywhere]">
                {struggle.topic}
              </h3>
              <span className="shrink-0 text-meta tabular-nums text-ink-faint">
                {struggle.times > 1
                  ? `${struggle.times} times on ${struggle.calls} call${struggle.calls === 1 ? "" : "s"}`
                  : formatIST(struggle.last_seen_at)}
              </span>
            </div>
            <p className="text-meta text-ink-muted">
              {lookup(KIND_LABEL, struggle.kind) ?? "Struggled"}
              {struggle.agent_name ? ` · ${struggle.agent_name}` : ""}
            </p>
            {struggle.question ? (
              <p className="border-l-2 border-line pl-3 text-meta text-ink">
                Caller: &ldquo;{struggle.question}&rdquo;
              </p>
            ) : null}
            {struggle.answer ? (
              <p className="border-l-2 border-line pl-3 text-meta text-ink-muted">
                Agent: &ldquo;{struggle.answer}&rdquo;
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2 pt-1">
              {canWrite ? (
                <button type="button" className={PRIMARY_BUTTON_SM} onClick={() => onAddAnswer(struggle)}>
                  Add the answer
                </button>
              ) : null}
              <Link
                className={SECONDARY_BUTTON_SM}
                href={`/c/${session.orgSlug}/agents/${struggle.agent_id}/script#${lookup(SCRIPT_PLACE, struggle.kind) ?? "stages"}`}
              >
                Fix in script
              </Link>
              {struggle.last_call_id ? (
                <Link className={SECONDARY_BUTTON_SM} href={`/c/${session.orgSlug}/calls/${struggle.last_call_id}`}>
                  Open the call
                </Link>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
