"use client";

import { useState } from "react";
import { Lock, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import {
  MonoValue,
  ProblemNotice,
  Skeleton,
  formatCount,
  formatIST,
  formatPhone,
} from "@/components/ui";
import { type Session } from "@/lib/api/client";
import {
  DNC_LIST_LIMIT,
  useDncList,
  useRemoveDncEntry,
  type DncEntry,
} from "@/lib/api/dnc";
import { lookup } from "@/lib/lookup";

import { SOURCE_COPY } from "./sources";

/**
 * Every number this account will not dial, and the one control that takes one off.
 *
 * **Each row says whether it may be undone.** A `global` entry is a Calevate
 * platform-wide suppression — a number we will not dial for ANY account, on a regulator
 * or operator instruction or on our own permanent refusal after a complaint. It is
 * emphatically NOT the national DND register: `compliance/dnc.py` says so in terms
 * ("deliberately NOT the national DND register"), and SEC-COMP §152 repeats it, because
 * NCPR preferences are category-scoped and expire daily and the national scrub is a
 * different mechanism entirely (`preference_scrub.py`). This screen called it "the
 * national list" in three places, which told the one audience that quotes us back to a
 * complaining caller that our internal refusal was a statutory registration. An entry
 * that records a consumer's opt-out is permanent. Both are SHOWN — a number you cannot
 * un-suppress is still a number you should know is suppressed — and neither gets a Remove
 * button, because the API refuses those (`dnc_global_entry`, `dnc_consumer_optout`) and a
 * button that 400s teaches a client that our compliance rules are a bug.
 *
 * WHERE A NUMBER MAY GO, which D-436 changed in one direction only. The list renders
 * numbers IN FULL — a client checking "did we suppress the person shouting at me?"
 * cannot do it against dots. What has NOT changed is the URL rule (hard rule 6).
 */
export function SuppressedList({
  session,
  canSuppress,
}: {
  session: Session;
  canSuppress: boolean;
}) {
  const entries = useDncList(session);
  const remove = useRemoveDncEntry(session);

  /**
   * The entry a client has asked to un-suppress, held until they confirm it. 🔒
   *
   * "Remove" used to call `remove.mutate(entry.id)` on one click, and the consequence is
   * that agents will dial that person again — this screen's own header says the list is
   * checked live before every single call, so a removal takes effect just as immediately
   * as an addition does. Under TCCCPR a wrongly-removed suppression is a call that should
   * not have happened.
   *
   * The friction on this lane was inverted before this: `/data-rights` makes a client type
   * the word ERASE, so destroying a person's data was harder than putting a person back in
   * the dial pool. This does not equalise them — a typed keyword is still the heavier
   * ceremony, and erasure deserves it — but it stops the consequential action being the
   * cheaper one.
   *
   * A modal rather than an inline two-step row swap, which was the other candidate: this
   * console has exactly one dialog idiom (`components/confirmDialog.tsx`, focus-trapped
   * per the WAI-ARIA APG), and a bespoke per-row interaction would be a second answer to
   * "how does this product ask are-you-sure" — the drift CLAUDE.md's one-way-per-problem
   * rule is about. The dialog names the number, so it confirms target as well as intent.
   */
  const [unsuppressing, setUnsuppressing] = useState<DncEntry | null>(null);

  /* `entries.data`, not `entries.data ?? []`: the difference between "the server said
     none" and "the server did not answer" is the whole of this screen's honesty, and an
     empty array erases it. */
  const rows = entries.data;
  /* At the endpoint's ceiling the row count stops being a total (no offset, clamped
     limit), so the header says which of the two it is showing. */
  const truncated = rows !== undefined && rows.length >= DNC_LIST_LIMIT;

  const columns: DataColumn<DncEntry>[] = [
    {
      id: "number",
      header: "Number",
      sort: { value: (entry) => entry.phone_e164 },
      cell: (entry) => (
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {/* IN FULL (D-436): a list a client cannot read back is one they cannot check
              against the caller complaining that we rang them again. */}
          <MonoValue className="tabular-nums text-ink">{formatPhone(entry.phone_e164)}</MonoValue>
          {entry.scope === "global" && (
            // Shown, never removable: it is not this account's entry, and hiding it would
            // leave a client wondering why a number they can't find is never dialled.
            <span className="rounded-full border border-line px-2 py-0.5 text-[11px] font-medium text-ink-muted">
              platform-wide
            </span>
          )}
        </span>
      ),
    },
    {
      id: "reason",
      header: "Reason",
      // Fails VISIBLE: a source this build cannot name still shows its raw value.
      sort: { value: (entry) => lookup(SOURCE_COPY, entry.source)?.label ?? entry.source ?? "" },
      cell: (entry) => (
        <span className="text-ink-muted">
          {lookup(SOURCE_COPY, entry.source)?.label ?? entry.source ?? "unknown reason"}
        </span>
      ),
    },
    {
      id: "added",
      header: "Added",
      hideBelow: "sm",
      sort: { value: (entry) => entry.added_at, kind: "time", first: "desc" },
      cell: (entry) => <span className="whitespace-nowrap text-ink-faint">{formatIST(entry.added_at)}</span>,
    },
    {
      id: "action",
      header: "Action",
      align: "right",
      cell: (entry) => (
        <RowAction
          entry={entry}
          canSuppress={canSuppress}
          removing={remove.isPending && remove.variables === entry.id}
          onRemove={() => setUnsuppressing(entry)}
        />
      ),
    },
  ];

  return (
    <>
      <div className="space-y-2">
        <div className="flex items-baseline justify-between gap-3">
          <h2 id="dnc-list-heading" className="text-[15px] font-semibold text-ink">
            Suppressed numbers
          </h2>
          {/* No count until the server has sent one: "0 entries" while the first request is
              in flight is a statement about the client's compliance posture. */}
          {rows && (
            <span className="text-[12px] text-ink-faint">
              {truncated
                ? `Showing the ${formatCount(DNC_LIST_LIMIT)} most recently added`
                : `${formatCount(rows.length)} ${rows.length === 1 ? "entry" : "entries"}`}
            </span>
          )}
        </div>
        {/* While the dialog is open the refusal belongs INSIDE it, where the decision is
            being made. */}
        {remove.error != null && unsuppressing == null && <ProblemNotice error={remove.error} />}
        {entries.error != null && <ProblemNotice error={entries.error} onRetry={() => entries.refetch()} />}

        {/* Loading is a skeleton, failure is the notice above and NOTHING ELSE, and the empty
            state is reached only through rows the server actually sent: "Nobody is
            suppressed yet" under a failed request would be a compliance claim made on no
            evidence. */}
        {entries.isLoading ? (
          <Skeleton rows={5} />
        ) : !rows ? null : rows.length ? (
          <div className="rounded-card border border-line bg-surface">
            <DataTable
              rows={rows}
              columns={columns}
              getRowId={(entry) => entry.id}
              label="Suppressed numbers"
              partialNote={truncated ? "Sorted within the 500 most recently added." : undefined}
            />
          </div>
        ) : (
          <div className="rounded-card border border-line bg-surface">
            <EmptyState
              message="Nobody is suppressed yet"
              action={
                <p className="max-w-md text-[13px] text-ink-faint">
                  Anyone who tells an agent to stop calling is added here automatically. You
                  can also add numbers yourself.
                </p>
              }
            />
          </div>
        )}
      </div>

      {/* The consequence, not a restatement of the command (NN/g, *Preventing User
          Errors*, read 25 Aug 2026). Closes only on success: a failed removal leaves the
          number suppressed, and closing would imply it no longer was. */}
      {unsuppressing && (
        <ConfirmDialog
          title="Let agents call this number again?"
          confirmLabel="Un-suppress this number"
          pendingLabel="Removing…"
          cancelLabel="Keep it suppressed"
          pending={remove.isPending}
          error={remove.error}
          onCancel={() => {
            remove.reset();
            setUnsuppressing(null);
          }}
          onConfirm={() =>
            remove.mutate(unsuppressing.id, { onSuccess: () => setUnsuppressing(null) })
          }
        >
          <p>
            <MonoValue className="tabular-nums text-ink">
              {formatPhone(unsuppressing.phone_e164)}
            </MonoValue>{" "}
            comes off your do-not-call list.
          </p>
          <p>
            This list is checked live before every single call, so the change takes effect
            straight away:{" "}
            <strong className="font-semibold text-ink">
              your agents will be able to ring this person again
            </strong>
            . Only do this if you know they are happy to be called.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}

function RowAction({
  entry,
  canSuppress,
  removing,
  onRemove,
}: {
  entry: DncEntry;
  canSuppress: boolean;
  removing: boolean;
  onRemove: () => void;
}) {
  // `removable` is the server's own `is_removable()` verdict, RENDERED rather than
  // re-derived from `scope`/`source`: the direction a second rule drifts in is a Remove
  // button on a consumer opt-out.
  if (!entry.removable) {
    return (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] text-ink-faint">
        <Lock className="h-3.5 w-3.5" aria-hidden />
        {entry.scope === "global" ? "removed by operations only" : "opt-out — cannot be undone"}
      </span>
    );
  }
  if (!canSuppress) return null;
  return (
    <button
      type="button"
      disabled={removing}
      onClick={onRemove}
      // Named for the row: forty buttons called "Remove" are forty identical announcements.
      aria-label={`Remove ${formatPhone(entry.phone_e164)} from the do-not-call list`}
      className="press inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[13px] font-medium text-ink-muted enabled:hover:bg-ink/[0.05] enabled:hover:text-danger disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
    >
      <Trash2 className="h-3.5 w-3.5" aria-hidden />
      {removing ? "Removing…" : "Remove"}
    </button>
  );
}
