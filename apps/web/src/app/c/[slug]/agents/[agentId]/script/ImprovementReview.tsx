"use client";

/**
 * "IMPROVE MY AGENT": THE AI'S FIXES, KEPT OR LEFT ONE BY ONE (D-724, D-823).
 *
 * Each suggestion is one small edit (a step's instruction, a new step, an objection line, a
 * part of the script) with its own tick box, the test it fixes and why. The kept ones are
 * applied to the owner's current copy by the server (`.../improvement/apply`), the same code
 * that checked each edit when it was suggested, so an edit made since is never undone and an
 * edit that no longer fits is left out and named.
 *
 * Facts are saved through the knowledge routes the Knowledge screen uses: pinned, so every
 * agent has them at once. A fact whose answer only the owner knows waits for them to type it.
 *
 * Nothing goes live by itself: kept changes are saved to the draft, or put live only when the
 * owner presses "Keep and put live".
 */

import { useState } from "react";

import { ActionButton, useActionFeedback, useAsyncAction } from "@/components/arc/feedback";
import {
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import {
  useApplySuggestedEdits,
  usePublishScript,
  useSaveDraft,
  useScript,
  useSettleImprovement,
  type CallScript,
  type Improvement,
  type ProposedFact,
  type ScriptEdit,
  type TestRun,
} from "@/lib/api/script";
import { useAddFact, useEditFact } from "@/lib/api/teach";

/** The kept edit ids, in the order they were suggested. */
export function keptEdits(improvement: Improvement, kept: ReadonlySet<string>): string[] {
  return improvement.edits.filter((edit) => kept.has(edit.id)).map((edit) => edit.id);
}

/** What happened to the kept edits, in the owner's words, when some no longer fit. */
export function skippedNote(skipped: readonly string[], improvement: Improvement): string | null {
  if (skipped.length === 0) return null;
  const labels = improvement.edits.filter((e) => skipped.includes(e.id)).map((e) => e.label);
  const which = labels.length > 0 ? `: ${labels.join("; ")}` : "";
  return `${skipped.length === 1 ? "One change no longer fits" : `${skipped.length} changes no longer fit`} your script, so ${skipped.length === 1 ? "it was" : "they were"} left out${which}. ${skipped.length === 1 ? "The part it changed was" : "The parts they changed were"} removed or edited since.`;
}

export function ImprovementReview({
  agentId,
  run,
  improvement,
  onClose,
  onTestAgain,
}: {
  agentId: string;
  run: TestRun;
  improvement: Improvement;
  onClose: () => void;
  onTestAgain: () => void;
}) {
  const session = useClientSession();
  const loaded = useScript(session, agentId);
  const saveDraft = useSaveDraft(session, agentId);
  const publish = usePublishScript(session, agentId);
  const apply = useApplySuggestedEdits(session, agentId);
  const settle = useSettleImprovement(session, agentId);
  const addFact = useAddFact(session);
  const editFact = useEditFact(session);
  // Each step's refusal is drawn below the list; the two Keep buttons carry the chain's state.
  useActionFeedback(saveDraft, { errorDisplay: "inline" });
  useActionFeedback(publish, { errorDisplay: "inline" });
  useActionFeedback(apply, { errorDisplay: "inline" });
  useActionFeedback(settle, { errorDisplay: "inline" });
  useActionFeedback(addFact, { errorDisplay: "inline" });
  useActionFeedback(editFact, { errorDisplay: "inline" });

  const [kept, setKept] = useState<Set<string>>(() => new Set(improvement.edits.map((e) => e.id)));
  const [facts, setFacts] = useState(() =>
    improvement.facts.map((fact) => ({ fact, keep: fact.answer.trim() !== "", answer: fact.answer })),
  );
  const [done, setDone] = useState<null | { where: "draft" | "live"; skipped: string | null; facts: boolean }>(
    null,
  );
  const [pressed, setPressed] = useState<"draft" | "live">("draft");

  const titles = new Map(run.results.map((r) => [r.key, r.title]));
  const working: CallScript | undefined = loaded.data?.draft?.script ?? loaded.data?.script ?? undefined;
  const keptFacts = facts.filter((f) => f.keep);
  // "Keep and put live" only when there is no other unpublished draft, so pressing it can
  // never put live an edit the owner did not review here.
  const hasDraft = Boolean(loaded.data?.draft);
  const factMissingAnswer = keptFacts.some((f) => f.answer.trim() === "");
  const keptIds = keptEdits(improvement, kept);
  const keptCount = keptIds.length + keptFacts.length;

  const toggle = (id: string, on: boolean) =>
    setKept((k) => {
      const next = new Set(k);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const saveFacts = async () => {
    for (const { fact, answer } of keptFacts) {
      if (fact.action === "fix" && fact.fact_id) {
        await editFact.mutateAsync({ id: fact.fact_id, text: answer.trim(), question: fact.question });
      } else {
        await addFact.mutateAsync({ text: answer.trim(), question: fact.question, pinned: true });
      }
    }
  };

  const keepChain = async (goLive: boolean) => {
    if (!working) return;
    let skipped: string | null = null;
    if (keptIds.length > 0) {
      const applied = await apply.mutateAsync({ runId: run.id, script: working, edits: keptIds });
      skipped = skippedNote(applied.skipped, improvement);
      await saveFacts();
      if (goLive) {
        await publish.mutateAsync({
          summary: "Improved from test results",
          script: applied.script,
          expected_version: loaded.data?.version ?? null,
        });
      } else {
        await saveDraft.mutateAsync({ script: applied.script, base_saved_at: loaded.data?.draft?.saved_at ?? null });
      }
    } else {
      await saveFacts();
    }
    await settle.mutateAsync({ runId: run.id });
    setDone({ where: goLive ? "live" : "draft", skipped, facts: keptFacts.length > 0 });
  };
  const keep = useAsyncAction((goLive: boolean) => keepChain(goLive), { errorDisplay: "inline" });
  const saving = keep.status === "pending";
  const startKeep = (goLive: boolean) => {
    if (saving) return;
    setPressed(goLive ? "live" : "draft");
    keep.run(goLive);
  };

  if (done) {
    return (
      <NoticeBox
        tone="ok"
        title="Kept"
        action={
          <>
            {done.where === "live" && (
              <button type="button" className={PRIMARY_BUTTON_SM} onClick={onTestAgain}>
                Test again
              </button>
            )}
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={onClose}>
              Close
            </button>
          </>
        }
      >
        <p>
          {done.where === "live"
            ? "Callers hear the changes from the next call. Facts you kept are live for every agent."
            : "The changes are in your draft. Put it live from the script, then test again."}
          {done.where === "draft" && done.facts && " Facts you kept are already live for every agent."}
        </p>
        {done.skipped && <p className="mt-1">{done.skipped}</p>}
      </NoticeBox>
    );
  }

  const nothing = improvement.edits.length === 0 && facts.length === 0;
  return (
    <section aria-labelledby="improve-heading" className="space-y-4 rounded-card border border-line p-4">
      <div>
        <h4 id="improve-heading" className="text-heading text-ink">
          Suggested fixes
        </h4>
        <p className="mt-1 text-meta text-ink-muted">
          Each one is a small change you keep or leave. Untick anything you do not want. Script changes go into your
          draft; callers hear them only after you put them live.
          {improvement.base === "live" ? " Made from the script callers hear now." : ""}
        </p>
        {!improvement.tested && (
          <p className="mt-1 text-meta text-ink-muted">
            Not tested yet. To check them, put the ones you keep live and test again.
          </p>
        )}
        {improvement.disclosure && <p className="mt-1 text-meta text-ink-muted">{improvement.disclosure}</p>}
      </div>

      {nothing ? (
        <p className="text-body text-ink-muted">
          No change to the script or your facts would fix these tests. Each result below says why it failed and who can
          fix it.
        </p>
      ) : (
        <>
          {improvement.edits.length > 0 && (
            <ul className="divide-y divide-line border-y border-line">
              {improvement.edits.map((edit) => (
                <EditRow
                  key={edit.id}
                  edit={edit}
                  kept={kept.has(edit.id)}
                  testTitle={edit.because ? titles.get(edit.because) : undefined}
                  onToggle={(on) => toggle(edit.id, on)}
                />
              ))}
            </ul>
          )}
          {facts.length > 0 && (
            <ul className="divide-y divide-line border-y border-line">
              {facts.map((row, index) => (
                <FactRow
                  key={`${row.fact.question}-${index}`}
                  fact={row.fact}
                  keep={row.keep}
                  answer={row.answer}
                  testTitle={row.fact.because ? titles.get(row.fact.because) : undefined}
                  onChange={(patch) =>
                    setFacts((all) => all.map((f, i) => (i === index ? { ...f, ...patch } : f)))
                  }
                />
              ))}
            </ul>
          )}
        </>
      )}

      {apply.error && <ProblemNotice error={apply.error} />}
      {addFact.error && <ProblemNotice error={addFact.error} />}
      {editFact.error && <ProblemNotice error={editFact.error} />}
      {saveDraft.error && <ProblemNotice error={saveDraft.error} />}
      {publish.error && <ProblemNotice error={publish.error} />}
      {settle.error && <ProblemNotice error={settle.error} />}
      <div className="flex flex-wrap gap-2">
        {!nothing && (
          <ActionButton
            variant="primary-sm"
            status={pressed === "draft" ? keep.status : "idle"}
            pendingLabel="Saving…"
            successLabel="Kept"
            disabled={keptCount === 0 || factMissingAnswer || !working || (saving && pressed !== "draft")}
            title={factMissingAnswer ? "Type the answer for each fact you keep" : undefined}
            onClick={() => startKeep(false)}
          >
            {`Keep ${keptCount}`}
          </ActionButton>
        )}
        {!nothing && !hasDraft && (
          <ActionButton
            variant="secondary-sm"
            status={pressed === "live" ? keep.status : "idle"}
            pendingLabel="Putting it live…"
            successLabel="Live"
            disabled={keptCount === 0 || factMissingAnswer || !working || (saving && pressed !== "live")}
            onClick={() => startKeep(true)}
          >
            Keep and put live
          </ActionButton>
        )}
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onClose}>
          Not now
        </button>
      </div>
      {factMissingAnswer && (
        <p className="text-meta text-ink-muted">Type the answer for each fact you keep, or untick it.</p>
      )}
    </section>
  );
}

function EditRow({
  edit,
  kept,
  testTitle,
  onToggle,
}: {
  edit: ScriptEdit;
  kept: boolean;
  testTitle?: string;
  onToggle: (on: boolean) => void;
}) {
  return (
    <li className="py-3">
      <label className="flex cursor-pointer items-start gap-3">
        <input type="checkbox" className="mt-1" checked={kept} onChange={(e) => onToggle(e.target.checked)} />
        <span className="min-w-0 flex-1 space-y-1">
          <span className="block text-body font-medium text-ink">{edit.label}</span>
          {edit.why && <span className="block text-meta text-ink">{edit.why}</span>}
          {testTitle && <span className="block text-meta text-ink-muted">For the test: {testTitle}</span>}
          {edit.before && (
            <span className="block whitespace-pre-wrap break-words text-meta text-ink-muted line-through">
              <span className="sr-only">Now: </span>
              {edit.before}
            </span>
          )}
          <span className="block whitespace-pre-wrap break-words text-body text-ink">
            <span className="sr-only">Suggested: </span>
            {edit.after}
          </span>
        </span>
      </label>
    </li>
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
  const id = `fact-${fact.question.slice(0, 24)}`;
  return (
    <li className="py-3">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-1"
          aria-labelledby={`${id}-label`}
          checked={keep}
          onChange={(e) => onChange({ keep: e.target.checked })}
        />
        <div className="min-w-0 flex-1 space-y-1">
          <p id={`${id}-label`} className="text-body font-medium text-ink">
            {fact.action === "fix" ? "Correct a pinned fact" : "Pin a fact"}: {fact.question}
          </p>
          {fact.why && <p className="text-meta text-ink">{fact.why}</p>}
          {testTitle && <p className="text-meta text-ink-muted">For the test: {testTitle}</p>}
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
