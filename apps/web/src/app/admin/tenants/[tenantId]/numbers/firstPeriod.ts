import { formatINR } from "@/components/ui";
import type { components } from "@/lib/api/schema";

export type FirstPeriod = components["schemas"]["RecordedEngineNumberOut"]["first_period"];

/**
 * What recording or buying a rented number did to the client's account, for the operator.
 *
 * Worded from the server's `first_period` — what the charge ACTUALLY did — because a trial
 * account, an invoiced account and a closed one are not charged now, and "charged from
 * today" on those was a claim about money that had not moved.
 */
export function firstPeriodPhrase(period: FirstPeriod | undefined, inrPerMonth: string): string {
  const monthly = formatINR(inrPerMonth);
  switch (period) {
    case "charged":
      return `${monthly} charged now for the first month, then monthly.`;
    case "invoiced":
      return `${monthly} a month, first month invoiced.`;
    case "trial":
      return `${monthly} a month, free during the trial; charging starts at the first renewal after it.`;
    case "closed":
      return "Account closed: nothing charged.";
    case "replayed":
      return "Already charged for this period.";
    default:
      return `${monthly} a month.`;
  }
}
