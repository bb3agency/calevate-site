/**
 * A cache share as the server sends it (a fraction to four places, "0.6200") in words for an
 * operator: "62% cached". A display figure, never money.
 */
export function formatCacheShare(share: string): string {
  const percent = Math.round(Number(share) * 1000) / 10;
  return `${Number.isInteger(percent) ? percent.toFixed(0) : percent.toFixed(1)}% cached`;
}
