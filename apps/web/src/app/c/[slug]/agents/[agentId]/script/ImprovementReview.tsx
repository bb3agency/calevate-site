"use client";

/**
 * "IMPROVE MY AGENT": THE AI'S FIXES, KEPT OR LEFT ONE BY ONE (D-724).
 *
 * Script changes are listed from the proposal against the script it was made from
 * (`base_script`), so an edit the owner made since is never offered back as a "change", and
 * the kept ones are applied to the owner's current copy with the builder's own
 * `applyChanges`. Each change says which test it fixes and why.
 *
 * Facts are saved through the knowledge routes the Knowledge screen uses: pinned, so every
 * agent has them at once. A fact whose answer only the owner knows waits for them to type it.
 *
 * Nothing goes live by itself: kept changes land in the editor when `onKeepScript` is given;
 * otherwise (the Test section) they are saved to the draft, or put live only when the owner
 * presses "Keep and put live".
 */

import { useMemo, useState } from "react";

import {
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import {
  usePublishScript,
  useSaveDraft,
  useScript,
  type CallScript,
  type Improvement,
  type ProposedFact,
  type TestRun,
} from "@/lib/api/script";
import { useAddFact, useEditFact } from "@/lib/api/teach";

import { ChangeBody, headline } from "./ProposalReview";
import { applyChanges, diffScripts, type Change } from "./scriptDiff";

/** The proposal's note for one diffed change: `step:<id>` or a part of the script. */
export function noteFor(change: Change, improvement: Improvement) {
  return improvement.changes.find((note) => {
    if (note.target.startsWith("step:")) return change.id.endsWith(`:${note.target.slice(5)}`) && change.kind !== "part";
    return change.id === `part:${note.target}`;
  });
}

export function ImprovementReview({
  agentId,
  run,
  improvement,
  current,
  onKeepScript,
  onClose,
  onTestAgain,
}: {
  agentId: string;
  run: TestRun;
  improvement: Improvement;
  current?: CallScript;
  onKeepScript?: (next: CallScript) => void;
  onClose: () => void;
  onTestAgain: () => void;
}) {
  const session = useClientSession();
  const loaded = useScript(session, agentId);
  const saveDraft = useSaveDraft(session, agentId);
  const publish = usePublishScript(session, agentId);
  const addFact = useAddFact(session);
  const editFact = useEditFact(session);

  const changes = useMemo(
    () => diffScripts(improvement.base_script, improvement.script),
    [improvement.base_script, improvement.script],
  );
  const [kept, setKept] = useState<Set<string>>(() => new Set(changes.map((c) => c.id)));
  const [facts, setFacts] = useState(() =>
    improvement.facts.map((fact) => ({ fact, keep: fact.answer.trim() !== "", answer: fact.answer })),
  );
  const [done, setDone] = useState<null | "draft" | "live" | "editor">(null);
  const [saving, setSaving] = useState(false);

  const titles = new Map(run.results.map((r) => [r.key, r.title]));
  const working: CallScript | undefined =
    current ?? loaded.data?.draft?.script ?? loaded.data?.script ?? undefined;
  const keptFacts = facts.filter((f) => f.keep);
  // "Keep and put live" from the Test section only when there is no other unpublished draft, so
  // pressing it can never put live an edit the owner did not review here.
  const hasDraft = Boolean(loaded.data?.draft);
  const factMissingAnswer = keptFacts.some((f) => f.answer.trim() === "");
  const keptCount = changes.filter((c) => kept.has(c.id)).length + keptFacts.length;

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

  const keep = async (goLive: boolean) => {
    if (!working) return;
    setSaving(true);
    try {
      const scriptKept = changes.some((c) => kept.has(c.id));
      const next = applyChanges(working, improvement.script, kept);
      await saveFacts();
      if (scriptKept) {
        if (onKeepScript) {
          onKeepScript(next);
          setDone("editor");
        } else if (goLive) {
          await publish.mutateAsync({
            summary: "Improved from test results",
            script: next,
            expected_version: loaded.data?.version ?? null,
          });
          setDone("live");
        } else {
          await saveDraft.mutateAsync({ script: next, base_saved_at: loaded.data?.draft?.saved_at ?? null });
          setDone("draft");
        }
      } else {
        setDone(goLive ? "live" : "draft");
      }
    } catch {
      // Each mutation renders its own refusal below.
    } finally {
      setSaving(false);
    }
  };

  if (done) {
    return (
      <NoticeBox
        tone="ok"
        title="Kept"
        action={
          <>
            {done === "live" && (
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
          {done === "live"
            ? "Callers hear the changes from the next call. Facts you kept are live for every agent."
            : done === "editor"
              ? "The changes are in your script below. Put it live, then test again to see the difference."
              : "The changes are in your draft. Put it live from the script, then test again."}
        </p>
      </NoticeBox>
    );
  }

  const nothing = changes.length === 0 && facts.length === 0;
  return (
    <section aria-labelledby="improve-heading" className="space-y-4 rounded-card border border-line p-4">
      <div>
        <h4 id="improve-heading" className="text-heading text-ink">
          Suggested fixes
        </h4>
        <p className="mt-1 text-meta text-ink-muted">
          Untick anything you do not want. Script changes go into your{" "}
          {onKeepScript ? "script below" : "draft"}; callers hear them only after you put them live.
          {improvement.base === "live" && !onKeepScript ? " Made from the script callers hear now." : ""}
        </p>
        {improvement.disclosure && <p className="mt-1 text-meta text-ink-muted">{improvement.disclosure}</p>}
      </div>

      {nothing ? (
        <p className="text-body text-ink-muted">
          No script or fact change would fix these. Read the reasons below; if one says it is on
          our side, contact us.
        </p>
      ) : (
        <>
          {changes.length > 0 && (
            <ul className="divide-y divide-line border-y border-line">
              {changes.map((change) => {
                const note = noteFor(change, improvement);
                return (
                  <li key={change.id} className="py-3">
                    <label className="flex cursor-pointer items-start gap-3">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={kept.has(change.id)}
                        onChange={(e) => toggle(change.id, e.target.checked)}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block text-body font-medium text-ink">{headline(change)}</span>
                        {note?.why && <span className="block text-meta text-ink">{note.why}</span>}
                        {note?.because && titles.has(note.because) && (
                          <span className="block text-meta text-ink-muted">
                            For the test: {titles.get(note.because)}
                          </span>
                        )}
                        <ChangeBody change={change} />
                      </span>
                    </label>
                  </li>
                );
              })}
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

      {addFact.error && <ProblemNotice error={addFact.error} />}
      {editFact.error && <ProblemNotice error={editFact.error} />}
      {saveDraft.error && <ProblemNotice error={saveDraft.error} />}
      {publish.error && <ProblemNotice error={publish.error} />}
      <div className="flex flex-wrap gap-2">
        {!nothing && (
          <button
            type="button"
            className={PRIMARY_BUTTON_SM}
            disabled={keptCount === 0 || factMissingAnswer || saving || !working}
            title={factMissingAnswer ? "Type the answer for each fact you keep" : undefined}
            onClick={() => void keep(false)}
          >
            {saving ? "Saving…" : `Keep ${keptCount}`}
          </button>
        )}
        {!nothing && !onKeepScript && !hasDraft && (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={keptCount === 0 || factMissingAnswer || saving || !working}
            onClick={() => void keep(true)}
          >
            Keep and put live
          </button>
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
