"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Pencil } from "lucide-react";

import type { Lead } from "@/lib/api/leads";

/**
 * The lead's name: a link to its screen, and — for anyone who may write — an inline edit.
 *
 * SURFACES §2 asks for "inline edit … (exit via Enter/click-out; no modal for
 * single-field edits)". The status and owner selects already satisfied the no-modal half
 * because a `<select>` has no commit step; the TEXT field is where "exit via Enter or
 * click-out" is a real interaction and where it was missing. `LeadUpdateIn.name` has
 * accepted an edit since the route shipped and nothing on the table sent one.
 *
 * ## What the interaction is, precisely
 *
 * - **Enter commits. Blur (click-out) commits.** Both, because they are the two ways
 *   people leave a cell and a field that only honoured one would silently discard work.
 * - **Escape cancels** and restores the stored value. Without it there is no way out of a
 *   half-typed name except saving it.
 * - **A commit with no change sends nothing.** The API would answer 200 either way, but a
 *   PATCH bumps `updated_at`, which is this table's sort key — clicking into a cell and
 *   out of it must not re-order the client's screen.
 *
 * ## Failure is the ROW's, not this cell's
 *
 * A failed inline edit that reverts with no message is a lie the user cannot see. This
 * component does not render that message, though — the row does, once, in its first cell
 * (`page.tsx::rowFailure`), because status, owner and name share one mutation and one
 * error slot, and three cells each rendering it would print the same sentence three
 * times. What this component owns is `saving`, which is genuinely per-control.
 *
 * The link is kept and the edit is a separate control beside it. Making the name itself
 * a button would cost the row its only navigation to the lead's timeline, and a single
 * element cannot be both a link and a text box.
 */
export function InlineName({
  lead,
  href,
  canEdit,
  editReason,
  saving,
  onCommit,
}: {
  lead: Lead;
  href: string;
  canEdit: boolean;
  /** Why editing is refused, said on the control rather than a screenful away. */
  editReason: string | null;
  saving: boolean;
  onCommit: (name: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(lead.name ?? "");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) input.current?.focus();
  }, [editing]);

  // The stored value moving under an open editor means somebody else changed this lead;
  // the draft is left alone (it is the person's unsaved typing) and the closed cell
  // simply shows the new truth.
  useEffect(() => {
    if (!editing) setDraft(lead.name ?? "");
  }, [editing, lead.name]);

  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (next === (lead.name ?? "")) return;
    onCommit(next);
  };

  if (editing) {
    return (
      <span className="block">
        <input
          ref={input}
          value={draft}
          // The API caps the column at 120 characters and 422s beyond it.
          maxLength={120}
          aria-label={`Name for the lead on ${lead.phone_masked}`}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
            }
            if (e.key === "Escape") {
              e.preventDefault();
              setDraft(lead.name ?? "");
              setEditing(false);
            }
          }}
          className="w-full rounded-md border border-line bg-surface px-1.5 py-0.5 text-sm text-ink"
        />
        <span className="mt-0.5 block text-[11px] font-normal text-ink-faint">
          Enter to save, Escape to cancel
        </span>
      </span>
    );
  }

  return (
    <span className="block">
      <span className="flex items-center gap-1.5">
        {/* The lead's own screen, where the timeline lives. The href carries the lead ID
            and never the number — a URL reaches browser history, referrers and access
            logs, so hard rule 6 is stricter for a link than for text. */}
        <Link href={href} className="hover:underline">
          {lead.name ?? <span className="font-normal text-ink-faint">No name</span>}
        </Link>
        {lead.is_repeat_caller && (
          <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-semibold text-brand-strong">
            repeat
          </span>
        )}
        {canEdit && (
          <button
            type="button"
            disabled={saving}
            onClick={() => setEditing(true)}
            // Names the LEAD, like every other per-row control here: a screen reader
            // meeting a hundred buttons called "Edit" cannot tell which row it is on.
            aria-label={`Edit the name for the lead on ${lead.phone_masked}`}
            title={editReason ?? "Edit this name"}
            className="text-ink-faint hover:text-ink disabled:opacity-50"
          >
            <Pencil className="h-3 w-3" />
          </button>
        )}
      </span>
      {saving && (
        <span className="mt-0.5 block text-[11px] font-normal text-ink-faint">Saving…</span>
      )}
    </span>
  );
}
