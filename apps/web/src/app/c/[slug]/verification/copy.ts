/**
 * The words and the class names both halves of the Verification screen share.
 *
 * React-free on purpose (UX-DOCTRINE §6): every function here is a pure mapping from a
 * wire record to a sentence, so it is the half a test can drive without a render — and
 * `verdictCopy` is the one piece of logic on this screen that has already been wrong in
 * the expensive direction, so it is worth being able to drive.
 */

import { formatIST } from "@/components/ui";
import {
  KYC_STATUS_COPY,
  documentKindLabel,
  isKnownKycStatus,
  type KycRecord,
  type KycStatusCopy,
} from "@/lib/api/kyc";

/**
 * What the client is told, which is everything in the shared table except the label an
 * operator picks from a dropdown — no realm renders the other's words.
 */
export type VerdictCopy = Pick<KycStatusCopy, "label" | "headline" | "next" | "tone">;

/** The state of a business that has never been filed — no row, which is a 200. */
export const NOT_RECORDED: VerdictCopy = {
  label: "Not on file",
  headline: "We have not verified your business yet.",
  next: "Send us your business registration details and we will verify the account.",
  tone: "neutral",
};

/** What we can say about a record whose status this build cannot name. */
export const UNNAMED_STATUS: VerdictCopy = {
  ...NOT_RECORDED,
  headline: "Your business is not verified yet.",
  next: "Ask your account manager where your verification stands.",
};

/** The lead-in of a list item: the claim, before the paragraph that qualifies it. */
export const LEAD_IN = "font-semibold text-ink";
export const LIST = "space-y-3 text-sm text-ink-muted";

/**
 * The words for this state — with `is_verified` choosing the DIRECTION and `status`
 * only choosing the wording within it.
 *
 * This used to be `KYC_STATUS_COPY[status]` outright, which handed the headline and the
 * tone to the status label alone. That is the re-derivation the screen's module docstring
 * forbids, and it fails in the expensive direction: a record still labelled `verified`
 * whose `is_verified` has gone false rendered a GREEN box saying "Your business is
 * verified. Nothing here is holding up your calls." while `check_dispatch` refused every
 * outbound call on the same account. The remediation cards already keyed on the boolean,
 * so the screen contradicted itself in the same scroll.
 *
 * `is_verified` is today `status == "verified"` (`compliance/kyc.py`), so the two cannot
 * yet disagree — which is exactly why this is worth pinning now rather than after an
 * expiry clause lands in that property and a client is told they are cleared for a week.
 *
 * Both directions are covered on purpose: a status we cannot name under a TRUE
 * `is_verified` gets the cleared copy, because refusing to say "you are verified" when
 * the gate says so sends a client chasing a block that does not exist.
 */
export function verdictCopy(record: KycRecord): VerdictCopy {
  if (!record.recorded) return NOT_RECORDED;
  const status = record.status;
  const named = status !== null && isKnownKycStatus(status) ? KYC_STATUS_COPY[status] : null;
  if (record.is_verified) return named?.tone === "ok" ? named : KYC_STATUS_COPY.verified;
  return named !== null && named.tone !== "ok" ? named : UNNAMED_STATUS;
}

export function describeVerification(record: KycRecord): string {
  const kind = documentKindLabel(record.document_kind);
  const when = record.verified_at ? formatIST(record.verified_at) : null;
  if (kind && when) return `We checked your ${kind} on ${when}.`;
  if (when) return `Verified on ${when}.`;
  return "";
}

export function stateLabel(record: KycRecord): string {
  const status = record.status;
  if (status !== null && isKnownKycStatus(status)) return KYC_STATUS_COPY[status].label;
  return status ?? NOT_RECORDED.label;
}

export function joinDocument(kind: string | null, ref: string | null): string | null {
  if (kind && ref) return `${kind} ${ref}`;
  return kind ?? ref;
}
