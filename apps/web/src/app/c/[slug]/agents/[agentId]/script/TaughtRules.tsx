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

import { useRef } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import type { CallScript } from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";
import { useProposedRules, useResolveRule } from "@/lib/api/teach";

import { insertSection, sectionsOf, updateSection } from "./scriptModel";

const IDENTITY_MAX = 1000;

function sectionName(text: string): string {
  const words = text.trim().split(/\s+/).slice(0, 6).join(" ");
  return (words.length > 60 ? words.slice(0, 60) : words) || "A rule to follow";
}

export function TaughtRules({
  agentId,
  script,
  maxSections,
  canWrite,
  onChange,
}: {
  agentId: string;
  script: CallScript;
  /** The account's step limit (`limitsFrom`), never a number written here. */
  maxSections: number;
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
  const full = sectionsOf(script).length >= maxSections;
  // The draft takes the rule only once the server has marked it used: written first, a
  // refused mark left the rule both in the draft and on this list, and pressing it again
  // put it in twice. The change is made to the script as it is then, so an edit typed while
  // the mark was on its way is kept.
  const latest = useRef(script);
  latest.current = script;
  const place = (ruleId: string, change: (current: CallScript) => CallScript | null) =>
    resolve.mutate(
      { ruleId, status: "applied" },
      {
        onSuccess: () => {
          const next = change(latest.current);
          if (next) onChange(next);
        },
      },
    );
  if (rules.error) return <ProblemNotice error={rules.error} onRetry={() => void rules.refetch()} />;
  // Nothing is said about taught rules until the list has arrived.
  if (!rules.data) return null;
  const waiting = rules.data.filter((r) => r.status !== "applied" && r.status !== "dismissed");
  if (waiting.length === 0) return null;

  const toRole = (current: CallScript, text: string) => {
    const identity = [current.identity.trim(), text.trim()].filter(Boolean).join(" ");
    return identity.length <= IDENTITY_MAX ? { ...current, identity } : null;
  };
  const asStep = (current: CallScript, text: string) => {
    // `insertSection`, not `addSection`: a last step whose Then ends the call would never
    // reach a step appended after it.
    const made = insertSection(current, sectionsOf(current).length);
    return updateSection(made.script, made.id, { name: sectionName(text), instruction: text.slice(0, 600) });
  };

  return (
    <section aria-labelledby="taught-heading" className="rounded-card border border-line px-4 py-3">
      <h3 id="taught-heading" className="text-body font-semibold text-ink">
        Rules you taught
      </h3>
      <p className="mt-1 text-meta text-ink-muted">
        Choose where each one goes in the script.
      </p>
      <ul className="mt-2 divide-y divide-line">
        {waiting.map((rule) => {
          const withRole = toRole(script, rule.text);
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
                      if (withRole) place(rule.id, (current) => toRole(current, rule.text));
                    }}
                  >
                    Add to its role
                  </button>
                  <button
                    type="button"
                    className={TEXT_ACTION}
                    disabled={busy || full}
                    title={full ? `The script has ${maxSections} steps, the most it can hold.` : undefined}
                    onClick={() => place(rule.id, (current) => asStep(current, rule.text))}
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
