import { formatCount } from "@/components/ui";

/**
 * A quiet comparison with the week before, for a dashboard hint: "12 more than the week
 * before", "3 fewer than the week before", "Same as the week before". Null when both
 * weeks are empty, because "same as the week before" over two zeroes says nothing.
 */
export function weekOnWeek(current: number, previous: number): string | null {
  // Not finite: an API older than this screen sent no previous week; say nothing.
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return null;
  if (current === 0 && previous === 0) return null;
  const diff = current - previous;
  if (diff === 0) return "same as the week before";
  return `${formatCount(Math.abs(diff))} ${diff > 0 ? "more" : "fewer"} than the week before`;
}
