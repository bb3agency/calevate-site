"use client";

import { ArrowRight } from "lucide-react";

import type { CopilotNavigation } from "@/lib/copilot/types";

/**
 * WHERE THE ASSISTANT IS TAKING SOMEBODY — a receipt, never an offer. D-524.
 *
 * The sibling of `ActionReceipt`, and it is a separate component for one reason: the two say
 * different things about TIME. An action receipt is a record of something already written to
 * the database. This one is shown in the moment between the destination being decided and the
 * move happening — the browser may still have to ask about unsaved work first — so it says
 * "Opening", which is the server's own word, and never "Opened".
 *
 * No button, exactly like `ActionReceipt`: there is nothing to confirm. The screen change is
 * Tier 1 (`apps/api/copilot/actions.py`) — reversible with the back button, reaching no
 * caller, spending nothing — and the person asked for it. `reversal` is rendered rather than
 * summarised for `ActionReceipt`'s reason: the panel's Undo belongs to a field fill and does
 * not reach a route change, so what applies here has to be said in words.
 *
 * `route` is deliberately not rendered anywhere. It is an internal address, and route paths
 * are banned from everything a client reads; `where` is what a person is told, in the
 * console's own vocabulary ("Calling credit, under Settings & account in the left sidebar").
 */
export function NavigationReceipt({ navigation }: { navigation: CopilotNavigation }) {
  return (
    <div className="rounded-lg border border-line bg-app px-3 py-2">
      <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
        <ArrowRight aria-hidden className="h-3.5 w-3.5 text-ink-faint" />
        Opening
      </p>
      <p className="mt-0.5 text-xs text-ink">{navigation.screen}</p>
      <p className="mt-0.5 text-xs text-ink-muted">{navigation.detail}</p>
      <dl className="mt-1.5 space-y-1 text-xs">
        <div className="flex gap-1.5">
          <dt className="shrink-0 text-ink-faint">Back</dt>
          <dd className="text-ink-muted">{navigation.reversal}</dd>
        </div>
      </dl>
    </div>
  );
}
