"use client";

/**
 * THE AGENT'S MAIN TASK, UNDER ITS NAME (founder, 9 Nov 2026): what this agent is for, so an
 * owner with several agents sees it at once, with the two things they do about it.
 *
 * - The task is the script's `goal`, read from the working copy (the draft when there is
 *   one), so a task just edited here shows at once; "Not live yet" says callers do not
 *   hear it until it is put live.
 * - **Edit** saves the new task into the draft through the builder's own autosave
 *   (`PUT .../script/draft`, a compare-and-set on the draft's stamp), so it is reviewed
 *   and put live like any other script edit, never a second way to change a script.
 * - **Re-adjust script** asks Pip to rewrite the script to fit the task. It is a
 *   suggestion like any other (`POST .../proposal/main-task`): reviewed change by change on
 *   the Script tab, kept into the draft, then put live. It spends the AI help allowance,
 *   so it is asked first.
 *
 * Both need `org:manage`; a person without it sees the task and no controls (the header's
 * `RestrictionNote` says why).
 */

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ExpandableText } from "@/components/arc/expandable-text";
import { Field } from "@/components/arc/field";
import { ConfirmDialog } from "@/components/confirmDialog";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { PipMark } from "@/components/illustration/pip";
import { FIELD, ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import {
  scriptKeys,
  useReadjustToMainTask,
  useSaveDraft,
  withDraft,
  type ScriptOut,
} from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { workingCopy } from "../script/scriptDraft";

/** `CallScript.goal`'s server bound (`call_script.py`). */
export const MAIN_TASK_MAX = 1000;

/** Lines of the task shown before "Show more". */
export const MAIN_TASK_LINES = 3;

export function MainTask({
  agentId,
  out,
  canWrite,
  openScript,
}: {
  agentId: string;
  /** The script read (`GET .../script`). */
  out: ScriptOut;
  canWrite: boolean;
  /** Opens the Script tab, where a suggestion is reviewed. */
  openScript: () => void;
}) {
  const session = useClientSession();
  const queryClient = useQueryClient();
  const working = workingCopy(out);
  const goal = working.script.goal?.trim() ?? "";
  const waiting = goal !== (out.script.goal?.trim() ?? "");
  // A script written as one text has no parts for a task to steer, and Pip edits steps.
  const steps = working.script.raw_override === null;

  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(goal);
  const field = useRef<HTMLTextAreaElement>(null);
  // The field takes the focus when the owner presses Edit, and Edit takes it back after.
  const editButton = useRef<HTMLButtonElement>(null);
  const opened = useRef(false);
  useEffect(() => {
    if (editing) field.current?.focus();
    else if (opened.current) editButton.current?.focus();
    opened.current = editing;
  }, [editing]);
  const [tried, setTried] = useState(false);
  const save = useSaveDraft(session, agentId);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });

  const [asking, setAsking] = useState(false);
  const readjust = useReadjustToMainTask(session, agentId);
  const readjustFeedback = useActionFeedback(readjust, { errorDisplay: "inline" });

  const empty = text.trim() === "";
  const startEditing = () => {
    setText(goal);
    setTried(false);
    save.reset();
    setEditing(true);
  };

  const submit = () => {
    setTried(true);
    if (empty) return;
    const sent = { ...working.script, goal: text.trim() };
    save.mutate(
      { script: sent, base_saved_at: working.savedAt },
      {
        onSuccess: (saved) => {
          queryClient.setQueryData<ScriptOut>(scriptKeys.one(session.orgSlug, agentId), (old) =>
            old ? withDraft(old, { script: sent, saved_at: saved.saved_at }) : old,
          );
          setEditing(false);
        },
        onError: (error) => {
          // Somebody saved the draft since this read: read it again, keep the typed text.
          if (error instanceof ApiProblem && error.code === "script_changed_elsewhere") {
            void queryClient.invalidateQueries({ queryKey: scriptKeys.one(session.orgSlug, agentId) });
          }
        },
      },
    );
  };

  if (editing) {
    return (
      <form
        className="mb-2 space-y-2 text-ink"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          label="Main task"
          hint="What this agent is for, in a sentence or two."
          error={tried && empty ? "Write its main task, or cancel." : null}
        >
          {(control) => (
            <textarea
              {...control}
              ref={field}
              rows={4}
              maxLength={MAIN_TASK_MAX}
              className={`${FIELD} resize-y`}
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setEditing(false);
              }}
            />
          )}
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            type="submit"
            variant="primary-sm"
            status={saveFeedback.status}
            pendingLabel="Saving…"
            successLabel="Saved"
          >
            Save
          </ActionButton>
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
        <p className="text-meta text-ink-muted">Saved to your draft. Callers hear it once you put it live.</p>
        {save.error && <ProblemNotice error={save.error} />}
      </form>
    );
  }

  if (!goal) {
    return (
      <div className="mb-1 flex flex-wrap items-center gap-x-3 text-ink">
        <span>No main task yet.</span>
        {canWrite && steps && (
          <button type="button" className={TEXT_ACTION_SM} onClick={startEditing}>
            Add its main task
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="mb-1.5 text-ink">
      <ExpandableText lines={MAIN_TASK_LINES} moreLabel="Show more" lessLabel="Show less" textClassName="whitespace-pre-line">
        <span className="font-medium">Main task:</span> {goal}
      </ExpandableText>
      {(waiting || (canWrite && steps)) && (
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          {waiting && <span className="text-meta text-ink-muted">Not live yet</span>}
          {canWrite && steps && (
            <>
              <button
                ref={editButton}
                type="button"
                className={TEXT_ACTION_SM}
                aria-label="Edit main task"
                onClick={startEditing}
              >
                <Pencil aria-hidden className="h-3.5 w-3.5" />
                Edit
              </button>
              <button type="button" className={TEXT_ACTION_SM} onClick={() => setAsking(true)}>
                <PipMark size={14} className="shrink-0" />
                Re-adjust script
              </button>
            </>
          )}
        </div>
      )}
      {asking && (
        <ConfirmDialog
          title="Re-adjust the script to this main task?"
          confirmLabel="Re-adjust script"
          pendingLabel={`Asking ${ASSISTANT_NAME}…`}
          status={readjustFeedback.status}
          error={readjust.error}
          onCancel={() => {
            setAsking(false);
            readjust.reset();
          }}
          onConfirm={() =>
            readjust.mutate(undefined, {
              onSuccess: () => {
                setAsking(false);
                openScript();
              },
            })
          }
        >
          <p>{ASSISTANT_NAME} rewrites the script so each step serves the main task.</p>
          <p>You see every change on the Script tab before it goes into your draft. Nothing goes live until you put it live.</p>
          <p>Uses your AI help allowance.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
