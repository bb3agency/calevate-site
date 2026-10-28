"use client";

import { useEffect, useState, type ReactNode } from "react";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { SelectionBar } from "@/components/arc/filter-toolbar";
import { ConfirmDialog } from "@/components/confirmDialog";
import { FIELD_INLINE, formatCount, NOTICE_BAR, NOTICE_BASE } from "@/components/ui";
import { TypedConfirmation } from "@/components/typedConfirmation";
import type {
  LeadBulkAction,
  LeadBulkBody,
  LeadBulkResult,
  LeadStatus,
  Member,
} from "@/lib/api/leads";

/**
 * Bulk actions on the leads table — the half slice Z deferred, and its guardrails.
 *
 * ## The one defect this component exists to not have
 *
 * "Select all" that could mean the visible PAGE or the whole filtered QUERY. This table
 * has facets and a 100-row page, so the two sets differ by orders of magnitude on a real
 * account, and the person cannot see the difference. The researched answer is not to
 * pick one — it is to give them two names and two controls:
 *
 * - **The header checkbox is PAGE-scoped.** PatternFly: "a checkbox in a table's header
 *   row will select … all items on the current page if pagination is in use."
 * - **Extending to the whole query is a SEPARATE, explicit act.** Helios: "bulk selection
 *   is global in scope … this is not a replacement for the selection in the header of the
 *   table, as where the selection is made implies a different scope". Gmail's banner is
 *   the interaction most people have already met — "All 50 conversations on this page are
 *   selected. Select all conversations that match this search" — and it is the shape used
 *   here, wording and all, because a familiar affordance is worth more than a novel one.
 *   GitLab's own enhanced-bulk-actions issue lists "select all results based on the
 *   current filter" as the missing half of exactly this.
 *
 * Every sentence below therefore names the scope AND the count, and after the action the
 * COUNT COMES BACK FROM THE SERVER (`LeadBulkOut.scope`, `.requested`) rather than from
 * what this component believed it had asked for.
 *
 * ## Confirmation proportional to the blast radius
 *
 * The ops console's big-red-switch idiom: consequences stated ABOVE the control, decision
 * made before the click. The escalation here is the SET, not the verb — nothing on this
 * table is irreversible (status and owner are single-value fields whose previous value
 * can be re-applied, which is why there is no undo token: re-running the action IS the
 * undo, and the server reports the rows that never moved as `unchanged`). What can go
 * badly wrong is agreeing to 1,240 rows while looking at 100.
 *
 * So above `TYPED_CONFIRMATION_FROM` rows the confirmation is TYPED, and what must be
 * typed is **the count** rather than a fixed word. That is a deliberate departure from
 * this repo's two existing typed confirmations (`ERASE` on the data-rights screen,
 * `HALT`/`RESUME` on the ops console) and it buys the thing those cannot: a fixed word
 * proves the person meant to press the button, and the risk here is not the button, it is
 * the number beside it. Typing "1240" cannot be done without reading it. (GitHub's
 * type-the-repository-name confirmation is the same reasoning applied to the same kind of
 * risk.) Below the threshold a plain confirm-with-count is proportionate; a ceremony
 * everybody performs on three rows is a ceremony nobody reads on twelve hundred.
 *
 * ## What is NOT here
 *
 * **Bulk delete.** `leads.deleted_at` exists and it would have been easy. Under DPDP the
 * client's erasure obligation runs through the data-rights screen — a `deletion_requests`
 * row, a worker that reaches calls, transcripts, extractions, storage and the engine, and
 * a certificate they hand to the person who asked — while `deleted_at` only hides the row
 * from this table. A button labelled "Delete" here would teach a client they had answered
 * an erasure request when they had not. `crm/service.py` carries the full argument.
 */

/** Above this many rows the confirmation is typed. See the header for why it is the count. */
export const TYPED_CONFIRMATION_FROM = 25;

/** Fixed enum (D-21) — the same six the table's chips and selects offer. */
const STATUSES: LeadStatus[] = ["new", "contacted", "interested", "hot", "won", "lost"];

export interface BulkSelection {
  /** Ticked row ids. Empty when the whole filtered query is selected instead. */
  ids: string[];
  /** True = the action is about every lead the current filters match, page or not. */
  wholeQuery: boolean;
}

export const EMPTY_SELECTION: BulkSelection = { ids: [], wholeQuery: false };

export function BulkActionBar({
  selection,
  filteredTotal,
  pageSize,
  members,
  canWrite,
  writeReason,
  runStatus,
  error,
  result,
  nameFor,
  onSelectWholeQuery,
  onClear,
  onRun,
  onDismissResult,
  renderPlan,
}: {
  selection: BulkSelection;
  /** The server's `total` for the current lens — `undefined` while it is unknown. */
  filteredTotal: number | undefined;
  /** How many rows are actually on screen, so "and N more" is never invented. */
  pageSize: number;
  members: Member[] | undefined;
  canWrite: boolean;
  writeReason: string | null;
  /** The batch's state, from the screen's `useActionFeedback`; shown on the confirm button. */
  runStatus: FeedbackStatus;
  /** A failure of the request itself, shown inside the confirmation. */
  error: unknown;
  result: LeadBulkResult | null;
  /** A loaded row's display name, for naming failures. `null` when it is not on screen. */
  nameFor: (leadId: string) => string | null;
  onSelectWholeQuery: () => void;
  onClear: () => void;
  onRun: (body: LeadBulkBody) => void;
  onDismissResult: () => void;
  /**
   * A filter too large for one request runs as an approved plan (D-893) and the answer
   * carries its id instead of counts; the screen draws the plan's own card for it.
   */
  renderPlan: (planId: string) => ReactNode;
}) {
  const [action, setAction] = useState<LeadBulkAction>("status");
  const [status, setStatus] = useState<LeadStatus>("contacted");
  /** "" is the real "Unassigned" option, which the API takes as an explicit `null`. */
  const [assignTo, setAssignTo] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");

  /**
   * HOW MANY ROWS THIS WILL TOUCH — and `undefined` when we do not know.
   *
   * In whole-query scope the number is the server's `total` for this lens, and if that
   * request has not landed there is no number: §52's rule applies to a confirmation
   * dialog more than anywhere else, because a manufactured `0` under "this will change N
   * leads" is the one number nobody would question.
   */
  const count = selection.wholeQuery ? filteredTotal : selection.ids.length;
  const active = selection.wholeQuery || selection.ids.length > 0;

  // A changed selection retracts a confirmation in progress. Without this, ticking two
  // more rows while the typed box is open would run the action against a set the person
  // confirmed a different size of.
  useEffect(() => {
    setConfirming(false);
    setTyped("");
  }, [selection]);

  const summary =
    result === null ? null : result.plan_id ? (
      <div className="mt-3">{renderPlan(result.plan_id)}</div>
    ) : (
      <BulkResultSummary result={result} nameFor={nameFor} onDismiss={onDismissResult} />
    );

  // Nothing selected and nothing to report: the bar is not on screen at all.
  if (!active && !result) return null;

  // THE RESULT OUTLIVES THE SELECTION. The screen clears the ticks once a batch runs —
  // leaving them invites a second run over rows that have already moved — so a summary
  // tied to the selection would vanish at the exact moment it had something to say, and
  // a partial failure would flash and disappear. It stays until dismissed.
  if (!active && result) {
    return (
      <div
        role="group"
        aria-label="Bulk actions"
        className="border-y border-line py-3"
      >
        {summary}
      </div>
    );
  }

  const needsTyping = count !== undefined && count >= TYPED_CONFIRMATION_FROM;
  const armed =
    count !== undefined && (!needsTyping || typed.trim() === String(count)) && canWrite;

  const verb =
    action === "status"
      ? `Set the stage to “${status}”`
      : assignTo === ""
        ? "Remove the owner"
        : `Give these to ${members?.find((m) => m.id === assignTo)?.name ?? "the chosen colleague"}`;

  const run = () => {
    const body: LeadBulkBody = selection.wholeQuery
      ? // The count the person just confirmed travels with the request. If the set has
        // moved since — a call landed, a colleague edited a row — the server refuses
        // (`lead_bulk_set_moved`) rather than spending their confirmation on a different
        // set of rows.
        { scope: "filter", action, expected_count: count }
      : { scope: "ids", ids: selection.ids, action };
    if (action === "status") body.status = status;
    // An ABSENT `assign_to` is refused by the API on purpose; `null` is what "unassign"
    // has to look like, and it must survive JSON serialisation as a real null.
    else body.assign_to = assignTo === "" ? null : assignTo;
    onRun(body);
  };

  return (
    <div className="space-y-2">
      {/* THE GMAIL BANNER, and the reason this component is not one ambiguous checkbox:
          it is offered only when there ARE rows off-screen, so the escape hatch never
          appears for a set the person can already see whole. Once taken, it says which
          set is chosen, because "1,240 leads selected" alone does not say which 1,240. */}
      {selection.wholeQuery && count !== undefined ? (
        <p className="rounded-md bg-ink/[0.03] px-4 py-2.5 text-body text-ink-muted">
          All {formatCount(count)} matching {count === 1 ? "lead" : "leads"} selected (
          {formatCount(Math.max(count - pageSize, 0))} on other pages).
        </p>
      ) : !selection.wholeQuery &&
        filteredTotal !== undefined &&
        selection.ids.length === pageSize &&
        filteredTotal > pageSize ? (
        <p className="rounded-md bg-ink/[0.03] px-4 py-2.5 text-body text-ink-muted">
          All {formatCount(pageSize)} on this page selected.{" "}
          <button
            type="button"
            onClick={onSelectWholeQuery}
            className="rounded-sm font-semibold text-brand-strong underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 dark:text-brand-bright touch:min-h-11"
          >
            Select all {formatCount(filteredTotal)} matching
          </button>
        </p>
      ) : null}

      {summary}

      {/* THE SCOPE, in the count's own words — never a bare "N selected", which does not
          say WHICH n. */}
      <SelectionBar
        count={count ?? pageSize}
        noun={selection.wholeQuery ? "matching lead" : "lead on this page"}
        nounPlural={selection.wholeQuery ? "matching leads" : "leads on this page"}
        onClear={onClear}
      >
        <select
          aria-label="Bulk action"
          value={action}
          onChange={(e) => setAction(e.target.value as LeadBulkAction)}
          className={`${FIELD_INLINE} touch:min-h-11`}
        >
          <option value="status">Change the stage</option>
          <option value="assign">Change the owner</option>
        </select>
        {action === "status" ? (
          <select
            aria-label="New stage"
            value={status}
            onChange={(e) => setStatus(e.target.value as LeadStatus)}
            className={`${FIELD_INLINE} capitalize touch:min-h-11`}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        ) : (
          <select
            aria-label="New owner"
            value={assignTo}
            onChange={(e) => setAssignTo(e.target.value)}
            className={`${FIELD_INLINE} touch:min-h-11`}
            // No picker when the team list did not load: an empty dropdown would say
            // "you have no colleagues", which is a claim about the business made from
            // a request that never landed (BUILD-LOG §52).
            disabled={!members}
          >
            <option value="">Unassigned</option>
            {(members ?? []).map((member) => (
              <option key={member.id} value={member.id}>
                {member.name ?? "Unnamed member"}
              </option>
            ))}
          </select>
        )}
        <ActionButton
          variant="primary-sm"
          disabled={!canWrite || count === undefined}
          title={writeReason ?? undefined}
          onClick={() => setConfirming(true)}
        >
          Review
        </ActionButton>
      </SelectionBar>
      {count === undefined ? (
        <p className="text-meta text-ink-muted">
          Couldn&apos;t count the matching leads. Reload to try again.
        </p>
      ) : null}

      {/* THE CONSEQUENCES, ABOVE THE CONTROL — the ops big-red-switch shape. The person
          reads what will happen, to how many rows, in which scope, and only then meets the
          button. */}
      {confirming && count !== undefined ? (
        <ConfirmDialog
          title={`${verb} for ${formatCount(count)} ${count === 1 ? "lead" : "leads"}?`}
          confirmLabel={`Apply to ${formatCount(count)}`}
          pendingLabel="Applying…"
          status={runStatus}
          confirmDisabled={!armed}
          error={error}
          onCancel={() => setConfirming(false)}
          onConfirm={run}
        >
          <p className="font-medium text-ink">
            {selection.wholeQuery ? "Every matching lead, not just this page." : "The leads you ticked."}
          </p>
          <p>Saved in each lead&rsquo;s history.</p>
          <p>{action === "status" ? "Leads already at that stage are skipped." : "Leads they already own are skipped."}</p>
          {needsTyping && (
            <TypedConfirmation phrase={String(count)} value={typed} onChange={setTyped} inputMode="numeric" />
          )}
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

/**
 * What the batch DID — three numbers and, when there are any, the rows it left behind.
 *
 * The rule this obeys: **never a green tick over a partial success.** A run with
 * failures is not styled or worded as a success; it names each row it could not move and
 * the reason the server gave, which is the same `(rule, reason)` pair a compliance
 * refusal on the dispatch button already renders.
 *
 * `unchanged` is reported in the same breath as `changed` and NOT as a problem: "3 were
 * already at that stage" is the batch doing what was asked (D-65), and colouring it as a
 * fault would teach a client to report correct behaviour as a bug — the same mistake as
 * painting the compliance gate rose instead of amber.
 */
function BulkResultSummary({
  result,
  nameFor,
  onDismiss,
}: {
  result: LeadBulkResult;
  nameFor: (leadId: string) => string | null;
  onDismiss: () => void;
}) {
  const noun = (n: number) => (n === 1 ? "lead" : "leads");
  const scope = result.scope === "filter" ? "matching" : "ticked";
  // THE COUNT COMES FROM THE INVARIANT, NOT FROM THE ARRAY'S LENGTH, and the generated
  // types are what forced the distinction into the open: `failures` is optional on the
  // wire (a server-side default), so reading `result.failures.length` would render an
  // ABSENT list as "nothing failed" — our ignorance printed as one of the server's
  // answers, which is the §52 defect one level down. The server's own contract is
  // `changed + unchanged + len(failures) == requested`, so the count is derivable even
  // when the list is not, and a batch that failed silently still says so.
  const failures = result.failures ?? [];
  const failed = Math.max(result.requested - result.changed - result.unchanged, failures.length);

  return (
    <div
      role="status"
      className={
        failed
          ? `mt-3 ${NOTICE_BASE} ${NOTICE_BAR.warn}`
          : `mt-3 ${NOTICE_BASE} ${NOTICE_BAR.ok}`
      }
    >
      <div className="flex items-start justify-between gap-2">
        <p className="flex items-start gap-2 font-medium">
          {/* Every number here is the SERVER's — including the scope, so this sentence
              cannot claim a set the request did not run over. */}
          <span>
            {formatCount(result.changed)} {noun(result.changed)} changed
            {result.unchanged > 0 && `, ${formatCount(result.unchanged)} already there`}
            {failed > 0 && `, ${formatCount(failed)} failed`} · of {formatCount(result.requested)} {scope}
          </span>
        </p>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss this result"
          className="rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 shrink-0 text-xs font-medium underline touch:min-h-11"
        >
          Dismiss
        </button>
      </div>
      {failed > 0 && (
        <ul className="mt-2 list-inside list-disc space-y-1">
          {failures.map((failure) => (
            <li key={failure.lead_id}>
              {/* Named where we can name it. A filter-scoped batch can fail on a row that
                  is not on this page, and inventing a name for it would be worse than a
                  truncated id — so the id is shown, and it is what support can search. */}
              <span className="font-medium">
                {nameFor(failure.lead_id) ?? `Lead ${failure.lead_id.slice(0, 8)}`}
              </span>{" "}
              — {failure.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
