"use client";

import { CheckCircle2 } from "lucide-react";

import type { CopilotAction } from "@/lib/copilot/types";

/**
 * What the assistant HAS ALREADY DONE — a receipt, never an offer.
 *
 * ## The one thing this component must not be mistaken for
 *
 * `ProposalCard` and this render two opposite promises and must not look alike. A proposal
 * is an offer with a Confirm button and nothing behind it yet; this is a record of a
 * database write that has happened. So there is no button here, the heading says "Done"
 * rather than "Suggestion", and nothing on it is clickable — a card that offered any
 * control at all would invite somebody to look for the undo that is described in words
 * beside it.
 *
 * The server only sends one of these for a TIER 1 action: reversible, reaching no caller,
 * spending no money (`apps/api/copilot/actions.py`). Anything that dials, publishes or
 * costs arrives as a proposal instead, and that separation is enforced in the server's
 * registry rather than here.
 *
 * ## Why `reversal` and `where` are rendered and not summarised
 *
 * They are the two the person needs and neither is derivable in this file. `reversal` is
 * the honest answer to "can I take that back", written by whoever wrote the action — the
 * panel's Undo button belongs to a FIELD FILL and does not reach a database write, so a
 * person who has learned that Undo exists must be told, in words, what applies here.
 * `where` is the founder's cross-screen rule: the assistant acts from whatever screen
 * somebody is on and then says where the result lives, rather than navigating them or
 * pre-filling a form for them to save.
 *
 * `applied: false` is a real outcome and not a failure (D-65) — the world was already in
 * that state — and `detail` is the server's own sentence about which of the two happened.
 * The browser adds only chrome.
 */
export function ActionReceipt({ action }: { action: CopilotAction }) {
  return (
    <div className="rounded-lg border border-line bg-app px-3 py-2">
      <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
        <CheckCircle2 aria-hidden className="h-3.5 w-3.5 text-ink-faint" />
        {action.applied ? "Done" : "Already done"}
      </p>
      <p className="mt-0.5 text-xs text-ink">{action.title}</p>
      <p className="mt-0.5 text-xs text-ink-muted">{action.detail}</p>
      <dl className="mt-1.5 space-y-1 text-xs">
        <div className="flex gap-1.5">
          <dt className="shrink-0 text-ink-faint">Where</dt>
          <dd className="text-ink-muted">{action.where}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="shrink-0 text-ink-faint">Undo</dt>
          <dd className="text-ink-muted">{action.reversal}</dd>
        </div>
      </dl>
    </div>
  );
}
