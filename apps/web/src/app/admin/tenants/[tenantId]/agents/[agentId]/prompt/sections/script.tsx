"use client";

import { EmptySketch } from "@/components/console/emptySketch";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { useFormValidation } from "@/components/formValidation";
import { HAIRLINE_LIST, StatusPill } from "@/components/admin/kit";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  usePromptHistory,
  useRollbackPrompt,
  useWritePrompt,
  type PromptVersion,
} from "@/lib/api/prompts";
import type { PendingState } from "@/lib/api/publishing";

/** The rollback consequence, said in the list and again in the confirmation. */
const ROLLBACK_RULE =
  "Rolling back creates a NEW version with that content — history is never rewritten — and it applies IMMEDIATELY, because a rollback is how you recover from a bad change, so it does not wait behind Apply.";

/**
 * THE SCRIPT SECTION: write the next version, and the history it joins.
 *
 * The editor is the screen's primary surface (UX §1: the most-edited control is the one
 * that is found first) and its draft is OWNED BY THE PAGE, not by this section, so moving
 * to Voice and back never loses typing and the screen assistant's fill lands in the same
 * state the textarea renders.
 *
 * Saving STAGES; a rollback does not — it goes live at once, which is why it alone asks
 * first and repeats the rule inside the question.
 */
export function ScriptSection({
  tenantId,
  agentId,
  pending,
  write,
  body,
  notes,
  onBody,
  onNotes,
  onWritten,
}: {
  tenantId: string;
  agentId: string;
  pending: PendingState | undefined;
  write: ReturnType<typeof useAdminAccess>;
  body: string;
  notes: string;
  onBody: (value: string) => void;
  onNotes: (value: string) => void;
  /** Saving or rolling back moves the staged state the Live section renders. */
  onWritten: () => void;
}) {
  const history = usePromptHistory(tenantId, agentId);
  const newVersion = useWritePrompt(tenantId, agentId);
  const rollback = useRollbackPrompt(tenantId, agentId);
  const valid = useFormValidation();
  const [confirming, setConfirming] = useState<PromptVersion | null>(null);

  return (
    <div className="space-y-10">
      <Section title="New version" headingLevel={3}>
        <RestrictionNote reason={write.reason} />
        {newVersion.error && <ProblemNotice error={newVersion.error} />}
        <form
          className="space-y-4"
          noValidate
          onSubmit={valid.onSubmit(() => {
            newVersion.mutate(
              { body, ...(notes.trim() ? { notes: notes.trim() } : {}) },
              {
                onSuccess: () => {
                  onBody("");
                  onNotes("");
                  onWritten();
                },
              },
            );
          })}
        >
          <label className="block">
            <span className={FIELD_LABEL}>The agent&apos;s instructions</span>
            <textarea
              {...valid.field("body", "Write the agent's instructions.")}
              required
              minLength={20}
              rows={12}
              value={body}
              disabled={!write.allowed}
              onChange={(ev) => onBody(ev.target.value)}
              placeholder="The full system prompt for this agent (min 20 characters)."
              className={`${FIELD} font-mono text-meta leading-relaxed`}
            />
          </label>
          {valid.error("body")}
          <label className="block">
            <span className={FIELD_LABEL}>What changed and why (optional)</span>
            <input
              value={notes}
              disabled={!write.allowed}
              onChange={(ev) => onNotes(ev.target.value)}
              maxLength={200}
              placeholder="Notes (optional) — what changed and why"
              className={FIELD}
            />
          </label>
          <div className="flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-end">
            <button
              type="submit"
              /* The 20-character rule is the field's, so the button stays live and a press
                 produces a sentence rather than nothing. */
              disabled={newVersion.isPending || !write.allowed}
              className={`${PRIMARY_BUTTON} max-sm:justify-center`}
            >
              {newVersion.isPending ? "Saving…" : "Save as new version"}
            </button>
            {/* Under two-speed publishing a save STAGES, it does not go live — the single
                most expensive thing this screen could get wrong, so it is said beside the
                button rather than behind an ⓘ. */}
            <p className="text-meta text-ink-muted">
              Saving stages the version. Callers keep hearing the live one until you press
              Apply to live calls, in Live.
            </p>
          </div>
        </form>
      </Section>

      {rollback.error && <ProblemNotice error={rollback.error} />}

      <Section title="Version history" headingLevel={3} description={ROLLBACK_RULE}>
        <RestrictionNote reason={write.reason} />
        {history.isLoading ? (
          <Skeleton rows={4} />
        ) : history.error || !history.data ? (
          /* A failed read AND a paused one (offline: not loading, `error === null`,
             `data === undefined`) both refuse. `?.length` alone collapsed the paused case
             into "No prompt versions yet" — a false claim, on the screen where an operator
             would then write what they believe is the first version (§52). */
          <ProblemNotice
            error={history.error ?? new Error("The version history could not be loaded.")}
            onRetry={() => history.refetch()}
          />
        ) : history.data.length ? (
          <ul className={HAIRLINE_LIST}>
            {history.data.map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 sm:px-2">
                <span className="font-mono text-body font-semibold text-ink">v{entry.version}</span>
                <VersionBadges entry={entry} pending={pending} />
                <span className="text-meta text-ink-muted">{formatIST(entry.created_at)}</span>
                {entry.notes && (
                  <span className="min-w-0 basis-full text-meta text-ink-muted sm:basis-auto">
                    {entry.notes}
                  </span>
                )}
                {!entry.active && (
                  <button
                    type="button"
                    disabled={rollback.isPending || !write.allowed}
                    onClick={() => {
                      rollback.reset();
                      setConfirming(entry);
                    }}
                    className={`ml-auto ${SECONDARY_BUTTON_SM}`}
                  >
                    Roll back to this
                  </button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            message="No prompt versions yet. Write the first one above."
            illustration={
              <EmptySketch kind="knowledge" />
            }
          />
        )}
      </Section>

      {confirming && (
        <ConfirmDialog
          title={`Roll back to v${confirming.version}?`}
          confirmLabel={`Roll back to v${confirming.version}`}
          pendingLabel="Rolling back…"
          pending={rollback.isPending}
          error={rollback.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() =>
            rollback.mutate(
              { version: confirming.version },
              {
                onSuccess: () => {
                  setConfirming(null);
                  onWritten();
                },
              },
            )
          }
        >
          <p>{ROLLBACK_RULE}</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

/**
 * Which version is staged and which one callers hear.
 *
 * `active` on a history row is the DRAFT pointer (`prompts.py::list_prompt_versions`
 * derives it from `system_prompt_id`), so labelling it "live" — as this page did
 * before two-speed publishing — now says the opposite of the truth. The live version
 * NUMBER comes from the pending read, which is the server's answer; the only
 * inference made here is that with nothing pending the two pointers are equal, which
 * is the definition of `has_pending` and not a second rule.
 *
 * While the pending read is unavailable the badge says "draft" and claims nothing
 * about live: a wrong green badge is worse than a missing one.
 */
export function VersionBadges({
  entry,
  pending,
}: {
  entry: PromptVersion;
  pending: PendingState | undefined;
}) {
  // The live version NUMBER as the server reports it: while a script change is staged
  // the pending row carries it. With nothing staged the two pointers are equal — that
  // is the definition of `has_pending`, not a second rule — so the draft row is live.
  const liveVersion = pending?.pending.find((c) => c.field === "script")?.live_version ?? null;
  const isStaged = pending?.has_pending === true && entry.active;
  const isLive =
    pending !== undefined &&
    (pending.has_pending ? entry.version === liveVersion : entry.active);

  return (
    <>
      {isLive && <StatusPill tone="ok">Live</StatusPill>}
      {isStaged && <StatusPill tone="warn">Staged</StatusPill>}
      {entry.active && !isLive && !isStaged && <StatusPill tone="neutral">Draft</StatusPill>}
    </>
  );
}
