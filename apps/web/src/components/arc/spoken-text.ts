/**
 * What a call script may contain: plain spoken words and `{{variable}}` tokens, nothing a
 * voice cannot say.
 *
 * Everything a script editor accepts is read by the agent and turned into speech, and
 * markdown, list markers, HTML and emoji are read aloud literally or produce silence
 * (`calevate_shared/engine.py`: "No markdown, emoji, brackets, dashes, slashes, ellipses,
 * lists, links"). The engine's prompt already forbids the MODEL from producing them; this
 * stops the CLIENT's own text from carrying them in. It is deliberately narrower than the
 * model rule: a client's instruction may contain a dash or a slash ("call back Mon/Tue"),
 * which is guidance for the agent rather than a sentence it speaks verbatim, so only what is
 * never meaningful in a spoken script is removed.
 *
 * Pure functions, so the paste handler, the input handler and a test all use the same rule.
 */

/** `{{key}}`: the token the script builder inserts and the server fills (`ScriptBuilder`). */
export const VARIABLE_PATTERN = /\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}/g;

const PICTOGRAPH = /[\p{Extended_Pictographic}\u{FE0F}\u{200D}\u{20E3}]/gu;
const HTML_TAG = /<\/?[a-zA-Z][^>]*>/g;
const LIST_MARKER = /^[ \t]*(?:[-*+\u2022\u25AA\u25E6\u2023]|\d{1,3}[.)])[ \t]+/gm;
const HEADING = /^[ \t]*#{1,6}[ \t]*/gm;
const QUOTE = /^[ \t]*>[ \t]?/gm;

/** Emphasis markers around words, outside `{{…}}` so a key like `caller_name` survives. */
function stripEmphasis(text: string): string {
  return text
    .split(/(\{\{[^}]*\}\})/)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part
            .replace(/(\*\*|__|\*|_|~~|`+)(?=\S)([^\n]*?\S)\1/g, "$2")
            .replace(/[*`~]/g, ""),
    )
    .join("");
}

/**
 * The text with markdown, list markers, HTML tags and emoji removed. Line breaks are kept
 * (a client may separate thoughts), runs of spaces are collapsed, and Indian scripts are
 * untouched (none of their letters is a pictograph).
 */
export function toSpokenPlainText(text: string): string {
  return stripEmphasis(
    text
      .replace(HTML_TAG, "")
      .replace(PICTOGRAPH, "")
      .replace(HEADING, "")
      .replace(QUOTE, "")
      .replace(LIST_MARKER, ""),
  ).replace(/[ \t]{2,}/g, " ");
}

/** The variable keys a text uses, in order of first use. */
export function variablesIn(text: string): string[] {
  const seen = new Set<string>();
  for (const match of text.matchAll(VARIABLE_PATTERN)) seen.add(match[1]);
  return [...seen];
}

/** The text with each known variable replaced by its sample; unknown ones stay as written. */
export function fillVariables(text: string, samples: Record<string, string>): string {
  return text.replace(VARIABLE_PATTERN, (whole, key: string) =>
    Object.prototype.hasOwnProperty.call(samples, key) ? samples[key] : whole,
  );
}

const BREAK = "[,.!?।]";
const NAME_WITH_TITLE = new RegExp(
  String.raw`\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}(?:[ \t]+[^\s,.!?।{}]+)?(?=[ \t]*[,.!?।])`,
  "g",
);

/** Does `text` use a field holding a person's name (`{{lead_name}}`, a list's `{{name}}`)? */
export function usesName(text: string): boolean {
  return variablesIn(text).some((key) => key.includes("name"));
}

/**
 * A line said word for word, filled the way a call we place fills it
 * (`calevate_shared.call_script.fill_spoken_line`; both read `tests/fixtures/
 * spoken_name_cases.json`): a name with no value goes with its title, any other field with
 * no value goes alone, and the breaks left behind are tidied.
 */
export function fillSpokenLine(text: string, values: Record<string, string | null | undefined>): string {
  const filled = (key: string) => {
    const value = values[key];
    return typeof value === "string" && value.trim() !== "" ? value : null;
  };
  return text
    .replace(NAME_WITH_TITLE, (whole, key: string) => (key.includes("name") && filled(key) === null ? "" : whole))
    .replace(VARIABLE_PATTERN, (_whole, key: string) => filled(key) ?? "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(new RegExp(`[ \\t]+(${BREAK})`, "g"), "$1")
    .replace(new RegExp(`,[ \\t]*(${BREAK})`, "g"), "$1")
    .replace(new RegExp(`(${BREAK})[ \\t]*,`, "g"), "$1")
    .replace(/^[\s,]+/, "")
    .trim();
}

/** Python's `len`: code points, so a counter agrees with the server on any script. */
export function codePoints(text: string): number {
  return [...text].length;
}
