import { formatCount, formatINR } from "@/components/ui";
import type { TenantSummary } from "@/lib/api/admin";

type Credit = Pick<TenantSummary, "plan_tier" | "credit_inr" | "minutes_left">;

/**
 * "Clear 240 min · Studio 80 min" — a client's minutes, one per voice quality, in the
 * catalogue order the server sends. Null when the server quotes none (an invoiced client,
 * or calling funded by a trial).
 */
export function minutesLine(credit: Credit): string | null {
  const tiers = credit.minutes_left;
  if (!tiers || tiers.length === 0) return null;
  return tiers.map((tier) => `${tier.label} ${formatCount(tier.minutes)} min`).join(" · ");
}

/**
 * CREDIT LEFT, MINUTES FIRST AND RUPEES SECOND (founder, 10 Oct 2026): minutes are what an
 * operator quotes to a client on the phone, the balance is the ledger fact behind them.
 *
 * - An invoiced client has no wallet: "Invoiced", never "₹0".
 * - A prepaid client on a trial has a balance and no minutes figure (D-536): "On trial".
 * - A row the server sent no credit for (an older API, or a surface that does not read the
 *   wallet) says nothing rather than a zero.
 */
export function CreditLeft({ credit, compact = false }: { credit: Credit; compact?: boolean }) {
  if (credit.credit_inr === undefined || (credit.credit_inr === null && credit.minutes_left == null)) {
    if (credit.plan_tier === "managed") return <span className="text-ink-muted">Invoiced</span>;
    return <span className="text-ink-muted">—</span>;
  }
  const tiers = credit.minutes_left && credit.minutes_left.length > 0 ? credit.minutes_left : null;
  const rupees = credit.credit_inr === null ? null : formatINR(credit.credit_inr);
  const overdrawn = credit.credit_inr !== null && credit.credit_inr.trim().startsWith("-");
  return (
    <span className={compact ? "inline" : "block"}>
      <span className="tabular-nums text-ink">
        {tiers
          ? tiers.map((tier, index) => (
              // One quality's figure never breaks across a line: "Studio 80 / min" read as
              // two facts in the narrow column of the roster.
              <span key={tier.voice_tier} className="whitespace-nowrap">
                {index > 0 ? " · " : ""}
                {tier.label} {formatCount(tier.minutes)} min
              </span>
            ))
          : "On trial"}
      </span>
      {rupees && (
        <span
          className={`tabular-nums ${compact ? "ml-2" : "block"} text-meta ${overdrawn ? "text-danger" : "text-ink-muted"}`}
        >
          {overdrawn && <span className="sr-only">Overdrawn: </span>}
          {rupees}
        </span>
      )}
    </span>
  );
}
