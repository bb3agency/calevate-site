"use client";

/**
 * THE VOICE VENDOR'S BILL, AS THE MONEY BOARD READS IT (D-547, plan Phase D).
 *
 * Two figures that must never be confused, and this module exists to keep them apart:
 *
 * - **ATTRIBUTED** — what we charged to calls. Under BYOK the engine bills us nothing for
 *   the synthesizer leg, so a Cartesia minute's cost is `attested ₹/1,000 chars × the
 *   characters our own transcript says the agent spoke`. It is real cost, allocated to the
 *   client whose call incurred it.
 * - **PLAN SPEND** — what the vendor actually took: a monthly commitment, paid whether or
 *   not the allotment is used. It belongs to the platform, not to any client.
 *
 * Their difference is the allotment nobody spoke into. A board showing only the first would
 * under-state what we pay; one showing only the second could not tell which client caused
 * it. Both are the SERVER's own figures — nothing here subtracts one from the other,
 * because a difference computed in a browser is float arithmetic on money (hard rule 7).
 *
 * ## Why the speaking rate is on this page at all
 *
 * The characters that price a Cartesia row are counted from OUR transcripts, and the
 * measured chars-per-minute card beside it is the same measurement at fleet scale. It is
 * therefore no longer only a check on TRD §10.1's assumed band: it is the quantity the
 * Cartesia rows are metered on, and an operator reading a Cartesia cost has to be able to
 * see how many characters it was struck from.
 */

import type { components } from "@/lib/api/schema";

/**
 * One voice vendor's month: what the plan cost, what the calls attributed, and the price
 * those calls were struck at — `TtsPlanSpendOut`, generated.
 *
 * **THE LOCAL INTERFACE AND `asTtsPlanSpend`/`ttsPlanSpendOf` ARE GONE.** They were written
 * while `tts_plan` was not on the wire, and the comment here said so; the field shipped with
 * D-547's Phase D.3 and the hand validator then re-checked what the compiler proves. What it
 * could NOT prove is unchanged and still matters: `plan_inr` is absent, never ₹0, when
 * nobody has attested the month's invoice — a fee defaulted to zero would show a fleet
 * margin that does not exist. The API expresses that by omitting the ROW, so an empty list
 * and a missing field are the same absence, and the card below renders it as one.
 */
export type TtsPlanSpend = components["schemas"]["TtsPlanSpendOut"];

/**
 * What the measured speaking rate means for ONE voice vendor — `SpeakingRateByProviderOut`,
 * generated.
 *
 * `pooled_inr_per_minute` is the SERVER's multiplication of its own two figures. The
 * browser does not multiply a chars/min string by a ₹/1k string — that is money arithmetic,
 * and the answer would be a third figure disagreeing with the meter's.
 *
 * **THE LOCAL INTERFACE AND `asSpeakingRateByProvider`/`speakingRateByProviderOf` ARE
 * GONE.** `TtsSpeakingRateOut.by_provider` is generated and REQUIRED, every field on the row
 * with it, so the hand validator re-checked what the compiler proves. The card reads
 * `rate.by_provider` off the typed response.
 */
export type SpeakingRateByProvider = components["schemas"]["SpeakingRateByProviderOut"];

/** The vendor, named — this is the admin console, and the invoice has a vendor on it. */
export function vendorName(provider: string): string {
  if (provider === "sarvam") return "Sarvam";
  if (provider === "cartesia") return "Cartesia";
  return provider;
}
