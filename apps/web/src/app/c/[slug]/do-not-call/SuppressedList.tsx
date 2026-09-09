"use client";

import { useState } from "react";
import { Globe2, Lock, PhoneOff, Trash2 } from "lucide-react";

import {
  Card,
  EmptyState,
  MonoValue,
  ProblemNotice,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import {
  DNC_LIST_LIMIT,
  useDncList,
  useRemoveDncEntry,
  type DncEntry,
} from "@/lib/api/dnc";
import { lookup } from "@/lib/lookup";
import { type Session } from "@/lib/api/client";

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

  return (
    <>
      <Card
        title="Suppressed numbers"
        action={
          /* No count until the server has sent one. "0 entries" while the first request
             is in flight is a statement about the client's compliance posture, and it is
             the wrong one. */
          rows ? (
            <span className="text-xs text-ink-faint">
              {truncated
                ? `Showing the ${formatCount(DNC_LIST_LIMIT)} most recently added`
                : `${formatCount(rows.length)} ${rows.length === 1 ? "entry" : "entries"}`}
            </span>
          ) : undefined
        }
        bodyClassName="p-2"
      >
        {/* While the dialog is open the refusal belongs INSIDE it, where the decision is
            being made — rendering it here as well would say the same failure twice. */}
        {remove.error != null && unsuppressing == null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={remove.error} />
          </div>
        )}
        {entries.error != null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={entries.error} onRetry={() => entries.refetch()} />
          </div>
        )}

        {/* Loading is a skeleton, failure is the notice above and NOTHING ELSE, and the
            empty state is reached only through a `rows` the server actually sent. "Nobody
            is suppressed yet" under a failed request is the worst sentence on this
            screen: it reads as "nobody is suppressed", which is a compliance claim we
            would be making on no evidence. */}
        {entries.isLoading ? (
          <div className="p-4">
            <Skeleton rows={5} />
          </div>
        ) : !rows ? null : rows.length ? (
          <ul className="divide-y divide-line">
            {rows.map((entry) => (
              <EntryRow
                key={entry.id}
                entry={entry}
                canSuppress={canSuppress}
                removing={remove.isPending && remove.variables === entry.id}
                onRemove={() => setUnsuppressing(entry)}
              />
            ))}
          </ul>
        ) : (
          <EmptyState
            title="Nobody is suppressed yet"
            hint="Anyone who tells an agent to stop calling is added here automatically. You can also add numbers yourself."
          />
        )}
      </Card>

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
              {unsuppressing.phone_e164}
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

function EntryRow({
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
  // `DncEntryOut.source` is `string | null`; `lookup` absorbs the null too.
  const source = lookup(SOURCE_COPY, entry.source);
  const global = entry.scope === "global";

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          global ? "bg-black/5 text-ink-muted dark:bg-white/10" : "bg-brand-soft text-brand-strong"
        }`}
        aria-hidden
      >
        {global ? <Globe2 className="h-4 w-4" /> : <PhoneOff className="h-4 w-4" />}
      </span>
      {/* IN FULL (D-436) — a suppression list a client cannot read back is one they
          cannot check against the caller complaining that we rang them again. */}
      <MonoValue className="tabular-nums text-ink">{entry.phone_e164}</MonoValue>
      {global && (
        // Shown, never removable: it is not this account's entry, and hiding it would
        // leave a client wondering why a number they can't find is never dialled.
        <span className="rounded-full border border-line bg-app px-2 py-0.5 text-xs font-medium text-ink-muted">
          platform-wide
        </span>
      )}
      {/* Fails VISIBLE: a source this build cannot name still gets its row and its raw
          value, because a suppression the client cannot see is one they will ask us to
          explain. */}
      <span className="text-xs text-ink-muted">
        {source?.label ?? entry.source ?? "unknown reason"}
      </span>
      <span className="ml-auto whitespace-nowrap text-xs text-ink-faint">
        {formatIST(entry.added_at)}
      </span>
      {/* `removable` is the server's own `is_removable()` verdict, RENDERED rather than
          re-derived from `scope`/`source` here. Two rules that agree today drift apart
          the day one of them changes, and the direction this one drifts in is a Remove
          button on a consumer opt-out. */}
      {entry.removable ? (
        canSuppress ? (
          <button
            type="button"
            disabled={removing}
            onClick={onRemove}
            // Named for the row: forty buttons called "Remove" are forty identical
            // announcements to a screen reader, and "remove which one?" is exactly the
            // question a mis-click answers wrongly.
            aria-label={`Remove ${entry.phone_e164} from the do-not-call list`}
            className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-ink-muted hover:bg-black/5 disabled:opacity-50 dark:hover:bg-white/5"
          >
            <Trash2 className="h-3.5 w-3.5" />
            {removing ? "Removing…" : "Remove"}
          </button>
        ) : null
      ) : (
        <span className="flex items-center gap-1.5 text-xs text-ink-faint">
          <Lock className="h-3.5 w-3.5" aria-hidden />
          {global ? "removed by operations only" : "opt-out — cannot be undone"}
        </span>
      )}
    </li>
  );
}
