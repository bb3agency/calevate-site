"use client";

import { useState } from "react";
import { CheckCircle2 } from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { useAdminAccess } from "@/app/admin/access";
import { useSetPlanTier, type SettablePlanTier } from "@/lib/api/admin";

/**
 * Which BILLING MOTION this client is on — the caller `POST /v1/admin/tenants/{id}/
 * plan-tier` shipped without.
 *
 * The route was audited, reason-required, idempotent and tested from the day it landed,
 * and no screen in this console sent it: the only way to move a client between prepaid
 * credit and an invoiced retainer was a hand-assembled request against production. That is
 * precisely the state the route's own docstring says D-521 exists to end — "a decision that
 * can only be carried out by an UPDATE typed into a production database is not a decision
 * the product supports, it is one an operator performs unaudited, at speed, on the wrong
 * row". The API half was finished; this is the seam.
 *
 * ## Why it is on Commercials and not on Account state
 *
 * Both were arguable and the tie is broken by what the screens are FOR. Account state
 * holds the controls that stop and start an account — suspend, reactivate, and a pointer
 * at the close. This is not one of those: it is the shape of the commercial relationship,
 * the thing the invoice beneath it is derived from and the thing that decides whether the
 * wallet on the Credits screen exists at all. An operator asking "how is this client
 * billed" is on this screen already.
 *
 * ## What the copy has to say, because nothing else will say it
 *
 * The dangerous direction is `prepaid` onto an account with no credit: since D-551 an
 * empty wallet stops the agents ANSWERING as well as dialling, so a tier change made to
 * tidy up the billing can take a clinic's phone line down within a tick. The other
 * direction is money in the opposite sense — Calevate carries the calling on an invoice.
 * Neither is guessable from the word in a dropdown, so both are printed under it.
 *
 * ## No typed confirmation, deliberately
 *
 * The API asks for none, and that is its reasoning rather than an omission on this screen:
 * both directions are reversible by this same control in one call and neither destroys
 * anything. The reason IS required — in both directions, by the API, and previewed here so
 * an operator is refused before typing rather than after.
 */

/** What each motion does, in the terms an operator is deciding between. */
const MOTION: Record<SettablePlanTier, { label: string; consequence: string }> = {
  prepaid: {
    label: "Prepaid — pays from a credit wallet",
    consequence:
      "Calling is drawn down from a credit balance. An empty wallet stops this client's outbound dialling at the next dial AND stops their agents answering incoming calls, so check the balance before moving an account on to it.",
  },
  managed: {
    label: "Managed — invoiced on a retainer",
    consequence:
      "No wallet, and nothing stops this client's calling for want of credit — Calevate carries their minutes on an invoice until the month is billed.",
  },
};

const MOTIONS = Object.keys(MOTION) as SettablePlanTier[];

/** The two motions an operator may set. Anything else on the row (a `self_serve` or
 * `trial` signup state) is a state to move OFF, never one to move to — the API answers
 * 422 for either, and this control cannot offer them. */
function isSettable(tier: string): tier is SettablePlanTier {
  return (MOTIONS as string[]).includes(tier);
}

export function BillingMotionPanel({
  tenantId,
  currentTier,
}: {
  tenantId: string;
  /** From the client's own directory row, never from this component's memory of the last
   * write — a tier the server did not confirm is a tier nobody is on. */
  currentTier: string;
}) {
  const move = useSetPlanTier(tenantId);
  const write = useAdminAccess("admin:tenants", "change how this client is billed");
  // Opens on the OTHER motion, so the control names the move rather than restating the
  // status. An account on neither (a `self_serve` signup) opens on prepaid, which is the
  // motion this product actually sells (D-521).
  const [tier, setTier] = useState<SettablePlanTier>(
    currentTier === "prepaid" ? "managed" : "prepaid",
  );
  const [reason, setReason] = useState("");
  // The API refuses a reasonless change with a 422 in BOTH directions. Previewed, and
  // still enforced server-side.
  const blocked = reason.trim().length < 3;
  const current = isSettable(currentTier) ? MOTION[currentTier].label : currentTier;

  return (
    <Card title="Billing motion">
      <p className="text-xs text-ink-muted">
        Currently <span className="font-medium text-ink">{current}</span>. This is not a
        price — the dated agreements below are — it is which way the money moves, and it
        takes effect at the next dial rather than at the next invoice.
      </p>

      <form
        className="mt-4 space-y-4"
        // No rule here the browser can refuse in its own words; ours are beside each
        // control. Same reason as the account-state form.
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          move.mutate({ plan_tier: tier, reason: reason.trim() });
        }}
      >
        <RestrictionNote reason={write.reason} />

        <div>
          <label htmlFor="billing-motion" className={FIELD_LABEL}>
            Move to
          </label>
          <div className="mt-1">
            <select
              id="billing-motion"
              value={tier}
              disabled={!write.allowed}
              onChange={(event) => {
                setTier(event.target.value as SettablePlanTier);
                move.reset();
              }}
              className={FIELD}
            >
              {MOTIONS.map((choice) => (
                <option key={choice} value={choice}>
                  {MOTION[choice].label}
                </option>
              ))}
            </select>
          </div>
          <span className={FIELD_HINT}>{MOTION[tier].consequence}</span>
        </div>

        <div>
          <label htmlFor="billing-motion-reason" className={FIELD_LABEL}>
            Why
          </label>
          <div className="mt-1">
            <textarea
              id="billing-motion-reason"
              rows={3}
              maxLength={500}
              value={reason}
              disabled={!write.allowed}
              onChange={(event) => {
                setReason(event.target.value);
                move.reset();
              }}
              className={FIELD}
            />
          </div>
          <span className={FIELD_HINT}>
            Required in both directions, and recorded verbatim in the audit log. The
            plan tier column keeps no history, so that row is the only record of why a
            business is invoiced rather than credit-gated.
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <ActionButton type="submit" loading={move.isPending} disabled={blocked || !write.allowed}>
            Change billing motion
          </ActionButton>
          {blocked && (
            <span className="text-xs text-amber-700 dark:text-amber-400">
              A reason is required before this can be applied.
            </span>
          )}
        </div>
      </form>

      {/* `ProblemNotice` and not `WriteFailure`, which is for writes that SEND an
          `X-Confirm-Action` header: this one sends none (the API asks for none), so a
          step-up refusal here could not mean the version skew that panel explains. The
          account-state screen's status write makes the same choice for the same reason. */}
      {move.error != null && (
        <div className="mt-4">
          <ProblemNotice error={move.error} />
        </div>
      )}
      {move.data && (
        <div className="mt-4">
          <NoticeBox
            tone={move.data.changed ? "ok" : "neutral"}
            icon={<CheckCircle2 className="h-5 w-5" />}
          >
            <p className="text-xs">
              {move.data.changed
                ? `Moved from ${move.data.previous_plan_tier} to ${move.data.plan_tier}. The dial gate reads it from the next request.`
                : `This account was already ${move.data.plan_tier} — nothing changed, and no audit row was written.`}
            </p>
          </NoticeBox>
        </div>
      )}
    </Card>
  );
}
