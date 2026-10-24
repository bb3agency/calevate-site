"use client";

/**
 * RULES TAUGHT IN KNOWLEDGE, waiting for a place in this script.
 *
 * When an owner teaches "never promise Sunday delivery" in Knowledge, it is a rule about how
 * the agent behaves, not a fact, so it lands here for this agent rather than in knowledge.
 * The script has no "at any time" list, so the owner picks where it goes: its role (said
 * as part of who it is, so it holds for the whole call) or a section of its own. Either
 * writes the draft; the rule is marked used, and callers hear it once the draft is live.
 */

import { useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import type { CallScript } from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";
import { useProposedRules, useResolveRule } from "@/lib/api/teach";

import { addSection } from "./scriptModel";

const IDENTITY_MAX = 1000;

function sectionName(text: string): string {
  const words = text.trim().split(/\s+/).slice(0, 6).join(" ");
  return (words.length > 60 ? words.slice(0, 60) : words) || "A rule to follow";
}

export function TaughtRules({
  agentId,
  script,
  canWrite,
  onChange,
}: {
  agentId: string;
  script: CallScript;
  canWrite: boolean;
  onChange: (next: CallScript) => void;
}) {
  const session = useClientSession();
  const rules = useProposedRules(session, agentId);
  const resolve = useResolveRule(session, agentId);
  // The rule leaves this list when it is placed or set aside, so that is said in a toast.
  const resolveFeedback = useActionFeedback(resolve, {
    errorDisplay: "inline",
    successToast: (_, vars) =>
      vars.status === "dismissed" ? "Rule set aside for this agent" : "Rule added to your draft",
  });
  const busy = resolveFeedback.status === "pending";
  if (rules.error) return <ProblemNotice error={rules.error} onRetry={() => void rules.refetch()} />;
  // Nothing is said about taught rules until the list has arrived.
  if (!rules.data) return null;
  const waiting = rules.data.filter((r) => r.status !== "applied" && r.status !== "dismissed");
  if (waiting.length === 0) return null;

  const toRole = (text: string) => {
    const identity = [script.identity.trim(), text.trim()].filter(Boolean).join(" ");
    return identity.length <= IDENTITY_MAX ? { ...script, identity } : null;
  };

  return (
    <section aria-labelledby="taught-heading" className="rounded-card border border-line px-4 py-3">
      <h3 id="taught-heading" className="text-sm font-semibold text-ink">
        Rules you taught
      </h3>
      <p className="mt-1 text-meta text-ink-muted">
        Rules you taught this agent on What your agents know. Choose where each one goes in the script.
      </p>
      <ul className="mt-2 divide-y divide-line">
        {waiting.map((rule) => {
          const withRole = toRole(rule.text);
          return (
            <li key={rule.id} className="py-2.5">
              <p className="text-body text-ink">{rule.text}</p>
              {canWrite && (
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                  <button
                    type="button"
                    className={TEXT_ACTION}
                    disabled={withRole === null || busy}
                    title={withRole === null ? "Its role is too long to add this. Add it as a step." : undefined}
                    onClick={() => {
                      if (!withRole) return;
                      onChange(withRole);
                      resolveFeedback.run({ ruleId: rule.id, status: "applied" });
                    }}
                  >
                    Add to its role
                  </button>
                  <button
                    type="button"
                    className={TEXT_ACTION}
                    disabled={busy || (script.stages?.length ?? 0) >= 12}
                    onClick={() => {
                      onChange(
                        addSection(script, { name: sectionName(rule.text), instruction: rule.text.slice(0, 600) }).script,
                      );
                      resolveFeedback.run({ ruleId: rule.id, status: "applied" });
                    }}
                  >
                    Add as a step
                  </button>
                  <button
                    type="button"
                    className={TEXT_ACTION}
                    disabled={busy}
                    onClick={() => resolveFeedback.run({ ruleId: rule.id, status: "dismissed" })}
                  >
                    Not for this agent
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {resolve.error && <ProblemNotice error={resolve.error} />}
    </section>
  );
}
