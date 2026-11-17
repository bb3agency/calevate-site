"use client";

/**
 * "IMPROVE MY AGENT": WHAT PIP WORKED OUT FROM THE FAILED TESTS (D-724, D-823, D-1017).
 *
 * Script fixes are not kept here. An agent has no script for the owner to edit (D-1005):
 * Pip writes them as a draft on the agent's Inbound line or campaign, the same way the healer
 * fixes a mistake on real calls, and the owner reviews and puts them live on that page. This
 * card says where the draft is (or why there is none) with one button to it.
 *
 * Facts are kept here, one tick box each, through the knowledge routes the Knowledge screen
 * uses: pinned, so every agent has them at once. A fact whose answer only the owner knows
 * waits for them to type it. Keeping, or "Done" when there is no fact, settles the round so
 * it is not offered again.
 */

import Link from "next/link";
import { useId, useRef, useState } from "react";

import { ActionButton, useActionFeedback, useAsyncAction } from "@/components/arc/feedback";
import { HowItWorks } from "@/components/console/howItWorks";
import {
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import {
  useSettleImprovement,
  type FixHolder,
  type Improvement,
  type ProposedFact,
  type TestRun,
} from "@/lib/api/script";
import { useAddFact, useEditFact } from "@/lib/api/teach";

/** The page a line's or campaign's draft is reviewed on. */
export function holderPath(slug: string, holder: Pick<FixHolder, "kind" | "id">): string {
  return holder.kind === "inbound_line" ? `/c/${slug}/inbound/${holder.id}` : `/c/${slug}/campaigns/${holder.id}`;
}

/** "the Inbound line “Main line”" / "the campaign “Reminders”". */
export function holderName(holder: Pick<FixHolder, "kind" | "name">): string {
  return `${holder.kind === "inbound_line" ? "the Inbound line" : "the campaign"} “${holder.name}”`;
}

/** Where this round's script fixes went, in one short line, or null when there were none. */
export function scriptFixLine(improvement: Improvement): string | null {
  const holder = improvement.holder;
  const count = improvement.edits.length;
  switch (improvement.script_fixes) {
    case "drafted":
      return holder ? `${count === 1 ? "1 fix" : `${count} fixes`} drafted on “${holder.name}”.` : null;
    case "draft_open":
      return holder ? `A Pip draft already waits on “${holder.name}”.` : null;
    case "no_holder":
      return "This agent has no line or campaign for script fixes.";
    case "choose":
      return "Choose where script fixes go, then ask again.";
    default:
      return null;
  }
}

export function ImprovementReview({
  agentId,
  slug,
  run,
  improvement,
  onClose,
}: {
  agentId: string;
  slug: string;
  run: TestRun;
  improvement: Improvement;
  onClose: () => void;
}) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const settle = useSettleImprovement(session, agentId);
  const addFact = useAddFact(session);
  const editFact = useEditFact(session);
  useActionFeedback(settle, { errorDisplay: "inline" });
  useActionFeedback(addFact, { errorDisplay: "inline" });
  useActionFeedback(editFact, { errorDisplay: "inline" });

  const [facts, setFacts] = useState(() =>
    improvement.facts.map((fact) => ({ fact, keep: fact.answer.trim() !== "", answer: fact.answer })),
  );
  const [done, setDone] = useState<null | { facts: number }>(null);

  // The name the test's card shows (D-917), so "Fixes:" points at a card the owner saw.
  const titles = new Map(run.results.map((r) => [r.key, r.short_title || r.title]));
  const keptFacts = facts.filter((f) => f.keep);
  const factMissingAnswer = keptFacts.some((f) => f.answer.trim() === "");
  const holder = improvement.holder ?? null;
  const scriptLine = scriptFixLine(improvement);

  // A Keep that failed part-way must not pin the same fact twice when pressed again.
  const written = useRef<Set<number>>(new Set());
  const keepChain = async () => {
    for (const [index, { fact, keep, answer }] of facts.entries()) {
      if (!keep || written.current.has(index)) continue;
      if (fact.action === "fix" && fact.fact_id) {
        await editFact.mutateAsync({ id: fact.fact_id, text: answer.trim(), question: fact.question });
      } else {
        await addFact.mutateAsync({ text: answer.trim(), question: fact.question, pinned: true });
      }
      written.current.add(index);
    }
    await settle.mutateAsync({ runId: run.id });
    setDone({ facts: keptFacts.length });
  };
  const keep = useAsyncAction(() => keepChain(), { errorDisplay: "inline" });
  const saving = keep.status === "pending";

  if (done) {
    return (
      <NoticeBox
        tone="ok"
        title={done.facts > 0 ? "Kept" : "Done"}
        action={
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={onClose}>
            Close
          </button>
        }
      >
        {done.facts > 0 && <p>Facts you kept are live for every agent.</p>}
        {holder && improvement.script_fixes === "drafted" && (
          <p className={done.facts > 0 ? "mt-1" : undefined}>Review the script fixes on {holderName(holder)}.</p>
        )}
      </NoticeBox>
    );
  }

  const nothing = improvement.edits.length === 0 && facts.length === 0 && scriptLine === null;
  return (
    <section aria-labelledby="improve-heading" className="space-y-4 rounded-card border border-line p-4">
      <div>
        <h4 id="improve-heading" className="text-heading text-ink">
          Suggested fixes
        </h4>
        {/* A disclosure about which model answered is required (D-127 G-6), so it stays visible. */}
        {improvement.disclosure && <p className="mt-1 text-meta text-ink-muted">{improvement.disclosure}</p>}
      </div>

      {nothing && <p className="text-body text-ink-muted">No change here would fix these. See each result below.</p>}

      {scriptLine && (
        <NoticeBox
          tone={improvement.script_fixes === "drafted" ? "ok" : "neutral"}
          title={scriptLine}
          action={
            holder && (improvement.script_fixes === "drafted" || improvement.script_fixes === "draft_open") ? (
              <Link href={href(holderPath(slug, holder))} className={PRIMARY_BUTTON_SM}>
                Review it
              </Link>
            ) : improvement.script_fixes === "no_holder" ? (
              <Link href={href(`/c/${slug}/inbound`)} className={PRIMARY_BUTTON_SM}>
                Set up a line
              </Link>
            ) : undefined
          }
        >
          {improvement.script_fixes === "drafted" && improvement.edits.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-meta text-ink [overflow-wrap:anywhere]">
              {improvement.edits.map((edit) => (
                <li key={edit.id}>{edit.label}</li>
              ))}
            </ul>
          )}
        </NoticeBox>
      )}

      {facts.length > 0 && (
        <div className="space-y-1">
          <p className="text-meta text-ink-muted">Untick any fact you do not want, then keep the rest.</p>
          <ul className="divide-y divide-line border-y border-line">
            {facts.map((row, index) => (
              <FactRow
                key={`${row.fact.question}-${index}`}
                fact={row.fact}
                keep={row.keep}
                answer={row.answer}
                testTitle={row.fact.because ? titles.get(row.fact.because) : undefined}
                onChange={(patch) => setFacts((all) => all.map((f, i) => (i === index ? { ...f, ...patch } : f)))}
              />
            ))}
          </ul>
        </div>
      )}

      {addFact.error && <ProblemNotice error={addFact.error} />}
      {editFact.error && <ProblemNotice error={editFact.error} />}
      {settle.error && <ProblemNotice error={settle.error} />}
      <div className="flex flex-wrap items-start gap-2">
        {facts.length > 0 ? (
          <ActionButton
            variant="primary-sm"
            status={keep.status}
            pendingLabel="Saving…"
            successLabel="Kept"
            disabled={keptFacts.length === 0 || factMissingAnswer}
            title={factMissingAnswer ? "Type the answer for each fact you keep" : undefined}
            onClick={() => !saving && keep.run()}
          >
            {keptFacts.length === 1 ? "Keep 1 fact" : `Keep ${keptFacts.length} facts`}
          </ActionButton>
        ) : (
          !nothing && (
            <ActionButton variant="primary-sm" status={keep.status} pendingLabel="Saving…" successLabel="Done" onClick={() => !saving && keep.run()}>
              Done
            </ActionButton>
          )
        )}
        {/* Closing mid-keep would hide where the facts went; it waits for the answer. */}
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={saving} onClick={onClose}>
          Not now
        </button>
      </div>
      {factMissingAnswer && <p className="text-meta text-ink-muted">Type the answer for each fact you keep, or untick it.</p>}
      <HowItWorks
        className="mt-0"
        items={[
          "Script fixes wait as a draft on the Inbound line or campaign. Callers hear them only once you keep them there and put it live.",
          ...(improvement.tested ? [] : ["Not tested yet. Test again once the draft is live."]),
          ...(facts.length > 0 ? ["Facts you keep are live for every agent at once."] : []),
        ]}
      />
    </section>
  );
}

function FactRow({
  fact,
  keep,
  answer,
  testTitle,
  onChange,
}: {
  fact: ProposedFact;
  keep: boolean;
  answer: string;
  testTitle?: string;
  onChange: (patch: { keep?: boolean; answer?: string }) => void;
}) {
  // From `useId`, never from the question: `aria-labelledby` is a list of ids split on
  // spaces, so an id holding the question's words named nothing.
  const id = useId();
  return (
    <li className="py-3">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4 shrink-0 cursor-pointer accent-[var(--brand-strong)] touch:h-5 touch:w-5"
          aria-labelledby={`${id}-label`}
          checked={keep}
          onChange={(e) => onChange({ keep: e.target.checked })}
        />
        <div className="min-w-0 flex-1 space-y-1">
          <p id={`${id}-label`} className="text-body font-medium text-ink">
            {fact.action === "fix" ? "Correct a pinned fact" : "Pin a fact"}: {fact.question}
          </p>
          {fact.why && <p className="text-meta text-ink">{fact.why}</p>}
          {testTitle && <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">Fixes: {testTitle}</p>}
          <label className="block">
            <span className="sr-only">Answer</span>
            <textarea
              className={FIELD}
              rows={2}
              value={answer}
              placeholder="Type the answer callers should hear"
              onChange={(e) => onChange({ answer: e.target.value, keep: keep || e.target.value.trim() !== "" })}
            />
          </label>
        </div>
      </div>
    </li>
  );
}
