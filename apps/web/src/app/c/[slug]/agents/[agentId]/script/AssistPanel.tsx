"use client";

/**
 * THE AI HELPER — a right-hand panel on a wide screen, a sheet on a phone.
 *
 * Two ways in. An empty script starts from five short questions only the owner can answer
 * (the server adds the business type, the direction, the call language and the lead
 * details). A script with something in it takes a change in the owner's own words. Either
 * way the answer is a PROPOSAL (`ProposalReview`): nothing in the draft changes until they
 * keep it, part by part.
 *
 * Every request spends the account's AI allowance, and the panel says so before the first
 * one, not after.
 */

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { FIELD, FIELD_LABEL, PRIMARY_BUTTON_SM, ProblemNotice, RestrictionNote } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import { useActAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  OWNER_QUESTIONS,
  useAssistScript,
  type AssistOut,
  type CallScript,
  type OwnerQuestionKey,
} from "@/lib/api/script";

import { hasContent } from "./scriptDraft";
import { ProposalReview } from "./ProposalReview";

const SUGGESTIONS = [
  "Handle callers who say the price is too high",
  "Make the opening line warmer and shorter",
  "Sound more like people talk here",
  "Ask for the delivery area before taking the order",
];

export function AssistPanel({
  agentId,
  script,
  onKeep,
}: {
  agentId: string;
  script: CallScript;
  onKeep: (next: CallScript) => void;
}) {
  const session = useClientSession();
  const assist = useAssistScript(session, agentId);
  // `org:manage` route, and it spends the account's AI allowance, which a view-as operator
  // may not (`billing.ai_assist`): both are refused with the reason on screen.
  const write = useActAccess(session, "org:manage", "billing.ai_assist", "ask the AI helper");
  const raw = script.raw_override !== null;
  const [fromQuestions, setFromQuestions] = useState(() => !hasContent(script));
  const [answers, setAnswers] = useState<Partial<Record<OwnerQuestionKey, string>>>({});
  const [change, setChange] = useState("");
  const [proposal, setProposal] = useState<AssistOut | null>(null);

  const written = fromQuestions ? Object.values(answers).join("").trim().length : change.trim().length;
  const ask = () => {
    setProposal(null);
    assist.mutate(fromQuestions ? { answers } : { answers: {}, current: script, change: change.trim() }, {
      onSuccess: (r) => setProposal(r),
    });
  };

  if (raw) {
    return (
      <p className="text-body text-ink-muted">
        Your script is hand-written. Use &ldquo;Turn this into sections&rdquo; under it, and the
        helper can work on the sections after that.
      </p>
    );
  }

  if (proposal) {
    return (
      <ProposalReview
        key={JSON.stringify(proposal.script.stages?.map((s) => s.id))}
        current={script}
        proposal={proposal.script}
        onApply={(next) => {
          onKeep(next);
          setProposal(null);
          setChange("");
        }}
        onDiscard={() => setProposal(null)}
      >
        {proposal.disclosure && <p className="text-meta text-ink-muted">{proposal.disclosure}</p>}
      </ProposalReview>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-meta text-ink-muted">
        Each request uses your account&apos;s AI allowance. You see every change before it goes
        into your draft.
      </p>
      <RestrictionNote reason={write.reason} />
      {fromQuestions ? (
        <>
          {OWNER_QUESTIONS.map((question) => (
            <div key={question.key}>
              <label className={FIELD_LABEL} htmlFor={`assist-${question.key}`}>
                {question.label}
              </label>
              <textarea
                id={`assist-${question.key}`}
                className={FIELD}
                rows={2}
                maxLength={600}
                disabled={!write.allowed}
                value={answers[question.key] ?? ""}
                onChange={(e) => setAnswers((a) => ({ ...a, [question.key]: e.target.value }))}
              />
            </div>
          ))}
          {hasContent(script) && (
            <button type="button" className={TEXT_ACTION} onClick={() => setFromQuestions(false)}>
              Ask for one change instead
            </button>
          )}
        </>
      ) : (
        <>
          <div>
            <label className={FIELD_LABEL} htmlFor="assist-change">
              What should change?
            </label>
            <textarea
              id="assist-change"
              className={FIELD}
              rows={3}
              maxLength={600}
              disabled={!write.allowed}
              value={change}
              placeholder="For example: when someone asks for a discount, offer free delivery instead."
              onChange={(e) => setChange(e.target.value)}
            />
          </div>
          <ul className="flex flex-wrap gap-1.5" aria-label="Ideas">
            {SUGGESTIONS.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  disabled={!write.allowed}
                  className="rounded-full border border-line px-2.5 py-1 text-meta text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50 touch:min-h-11"
                  onClick={() => setChange(s)}
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className={TEXT_ACTION} onClick={() => setFromQuestions(true)}>
            Draft the whole script from five questions
          </button>
        </>
      )}
      <button
        type="button"
        className={PRIMARY_BUTTON_SM}
        disabled={!write.allowed || assist.isPending || written < 10}
        title={write.reason ?? (written < 10 ? "Write a little more first." : undefined)}
        onClick={ask}
      >
        <Sparkles aria-hidden className="h-3.5 w-3.5" />
        {assist.isPending ? "Thinking…" : fromQuestions ? "Draft my script" : "Suggest the change"}
      </button>
      {assist.isPending && (
        <p role="status" className="text-meta text-ink-muted">
          This takes about half a minute.
        </p>
      )}
      {assist.error && <ProblemNotice error={assist.error} />}
    </div>
  );
}
