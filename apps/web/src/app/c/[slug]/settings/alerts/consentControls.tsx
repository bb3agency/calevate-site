"use client";

import { BellOff, BellRing, Lock } from "lucide-react";

import { SECONDARY_BUTTON } from "@/components/ui";
import { ActionButton } from "@/components/actionButton";

/**
 * The two halves of the consent, kept in one file because their ASYMMETRY is the
 * decision: giving it needs the server's exact notice and the channel working, taking it
 * back needs neither. Split across two files that argument stops being readable.
 */

/**
 * The agreement itself: the server's exact sentence, and a button that means it.
 *
 * A tick-box plus a separate Save was the alternative and is worse here — it produces a
 * screen state where the box is ticked and nothing is recorded, which looks exactly like
 * consent to the person who ticked it and is nothing at all to the ledger.
 */
export function GrantControl({
  notice,
  allowed,
  reason,
  pending,
  onGrant,
}: {
  notice: string;
  allowed: boolean;
  reason: string | null;
  pending: boolean;
  onGrant: () => void;
}) {
  return (
    <div className="space-y-3">
      <p className="rounded-card border border-line bg-surface p-4 text-sm text-ink">{notice}</p>
      {/* Shared ActionButton: the spinner rides `loading` while the opt-in is recorded, and
          the disabled logic is unchanged (`disabled || loading`). The accessible name stays
          "I agree…" through the write, so `whatsappAlerts.test.tsx`'s `/I agree/` — and a
          screen reader — never lose the control. */}
      <ActionButton type="button" loading={pending} disabled={!allowed} onClick={onGrant}>
        <BellRing aria-hidden className="h-4 w-4" />
        I agree — send me WhatsApp alerts
      </ActionButton>
      {!allowed && reason && (
        <p className="flex items-start gap-2 text-xs text-ink-muted">
          <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {reason}
        </p>
      )}
    </div>
  );
}

/**
 * Withdrawing — offered whenever alerts are on, and never gated on the channel working.
 *
 * The asymmetry with the grant is deliberate: consent that can be given more easily than
 * it can be taken back is not consent, and "our vendor connection is down" is our problem
 * rather than a reason to keep messaging somebody who has asked us to stop.
 */
export function WithdrawControl({
  allowed,
  reason,
  pending,
  onWithdraw,
}: {
  allowed: boolean;
  reason: string | null;
  pending: boolean;
  onWithdraw: () => void;
}) {
  return (
    <div className="space-y-3">
      {/*
       * `SECONDARY_BUTTON`, NOT `DANGER_BUTTON` — and the docstring above is why.
       *
       * This button used to be the only red one on the screen while GRANTING consent was
       * a friendly brand-green primary, which inverts the principle this component states
       * in its own header: consent that can be given more easily than it can be taken
       * back is not consent. Red is a deterrent signal, and pointing it at the
       * privacy-protective choice makes the safe answer look like the dangerous one.
       *
       * It also broke `DANGER_BUTTON`'s stated contract (`components/ui.tsx`): that
       * constant is reserved for "something a person cannot undo", and the sentence
       * directly below this button says the opposite — you can turn WhatsApp back on here
       * whenever you like. Grant and withdraw now sit in the same weight class, which is
       * what makes them an equal pair of choices rather than a nudge; nothing is hidden,
       * collapsed or made harder to reach.
       */}
      <button
        type="button"
        disabled={!allowed || pending}
        onClick={onWithdraw}
        className={SECONDARY_BUTTON}
      >
        <BellOff aria-hidden className="h-4 w-4" />
        {pending ? "Saving…" : "Stop sending me WhatsApp alerts"}
      </button>
      <p className="text-xs text-ink-faint">
        Hot leads keep reaching you by email and on your dashboard. You can turn WhatsApp
        back on here whenever you like.
      </p>
      {!allowed && reason && (
        <p className="flex items-start gap-2 text-xs text-ink-muted">
          <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {reason}
        </p>
      )}
    </div>
  );
}
