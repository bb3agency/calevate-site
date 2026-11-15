/**
 * Does every word of `query` appear in at least one of `fields`, in any order, ignoring case
 * and accents? The campaign workspace's searches filter on every keystroke across several
 * fields at once (global rule 9).
 */
function fold(value: string): string {
  return value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function matchesWords(query: string, fields: ReadonlyArray<string | null | undefined>): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = fold(fields.filter(Boolean).join(" \u0000 "));
  return words.every((word) => haystack.includes(word));
}
