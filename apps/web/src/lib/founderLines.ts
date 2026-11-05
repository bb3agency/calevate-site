import data from "@/lib/founderLines.json";

/**
 * The founder's sample lines in Indian languages that the website shows (founder rule 2: never
 * hand-written in code). The words live in `founderLines.json`, which the founder edits; the
 * server's spoken lines are its own file (`calevate_shared/spoken_lines.json`).
 */
const LINES: Readonly<Record<string, string>> = data.lines;

export function founderLine(key: string): string {
  const line = LINES[key];
  if (line === undefined) throw new Error(`founderLines.json has no line ${key}`);
  return line;
}
