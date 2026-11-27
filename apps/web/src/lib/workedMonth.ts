import type { components } from "@/lib/api/schema";
import { formatINRExact } from "@/lib/numberDisplay";

type WorkedMonth = components["schemas"]["WorkedMonthOut"];
type WorkedMonthVoice = components["schemas"]["WorkedMonthVoiceOut"];
type Voice = WorkedMonthVoice["voice"];

/**
 * The all-in worked month (`CreditPacksOut.worked_month`) as sentences, shared by `/pricing`
 * and the console's "What calls cost".
 *
 * Every figure is a string the server computed in NUMERIC and rounded once; this module
 * only formats it, and says each figure once. Money is shown to the paisa
 * (`formatINRExact`) because a reader checks these lines against each other: ₹4.50 x 3,000
 * must visibly equal the talk-time figure, which the one-decimal display rule would blur.
 * The voice names are the card's own labels, passed in, so the month cannot name a voice
 * differently from the table beside it.
 */
export interface WorkedMonthLines {
  voice: Voice;
  /** "A month of 3,000 minutes on Clear: ₹13,899.00, nothing added". */
  headline: string;
  /** How the figure is made up, one sentence. */
  breakdown: string;
}

export function workedMonthLines(
  month: WorkedMonth,
  row: WorkedMonthVoice,
  labels: Record<Voice, string>,
): WorkedMonthLines {
  const opening = `A month of ${month.minutes.toLocaleString("en-IN")} minutes on ${labels[row.voice]}`;
  const rate = `${formatINRExact(row.inr_per_min)} a minute`;
  if (row.total_inr === null || row.all_in_inr_per_min === null || month.number_inr_per_month === null) {
    return {
      voice: row.voice,
      headline: `${opening}: ${formatINRExact(row.talk_inr)} of talk time`,
      breakdown: `That is ${rate}. Your phone number's monthly fee is added to it, and shown before you buy the number.`,
    };
  }
  const number =
    month.numbers === 1
      ? `one phone number at ${formatINRExact(month.number_inr_per_month)}`
      : `${month.numbers} phone numbers at ${formatINRExact(month.number_inr_per_month)} each`;
  const fee =
    month.platform_fee_inr_per_month === null
      ? ""
      : ` and the ${formatINRExact(month.platform_fee_inr_per_month)} monthly platform fee`;
  return {
    voice: row.voice,
    headline: `${opening}: ${formatINRExact(row.total_inr)}, nothing added`,
    breakdown: `${formatINRExact(row.talk_inr)} of talk time at ${rate}, ${number}${fee}. That is ${formatINRExact(row.all_in_inr_per_min)} a minute with everything in it.`,
  };
}

/** The rows in the order a page shows them, `lead` (the voice the page headlines) first. */
export function workedMonthRows(
  month: WorkedMonth,
  lead: Voice | null,
  labels: Record<Voice, string>,
): WorkedMonthLines[] {
  const rows = [...month.voices].sort((a, b) => Number(b.voice === lead) - Number(a.voice === lead));
  return rows.map((row) => workedMonthLines(month, row, labels));
}

/** Said beside every worked month: it illustrates the card and promises nothing. */
export const WORKED_MONTH_CAVEAT =
  "An example, not a quote: you pay for the minutes your agents actually talk, and a call nobody answers costs nothing.";
