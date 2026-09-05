/**
 * SOURCE-SCANNING HELPERS — the one place a guard that reads this app's own source
 * learns to ignore its own documentation.
 *
 * ## Why this file exists rather than a third copy of the same six lines
 *
 * A guard that greps source text for a spelling has one predictable failure: a COMMENT
 * that names the spelling is not the spelling. It has now bitten this repository three
 * times, in three files, with the same shape each time — a comment written to explain a
 * fix being read as the defect the fix removed:
 *
 *  1. `responsive.test.ts` flagged `TopUp.tsx` for `min-w-[36rem]` that appears only in a
 *     docstring explaining that the TABLE it replaced needed one and a card does not.
 *  2. `formValidation.test.tsx` flagged the same file for a `<form>` that appears only in
 *     the comment "Not a `<form>`: there is nothing to submit and no request behind it."
 *  3. `tests/shared_state_assertion_guard_test.py::_code_only` exists in the Python tree
 *     for exactly this reason, and its comment says so.
 *
 * Twice is a coincidence; three times is a missing helper. CLAUDE.md's "one way per
 * problem" applies to test infrastructure as much as to product code, and a guard people
 * learn to disbelieve is worse than no guard — the first two both reported a real file
 * with a real line number and were both entirely wrong.
 *
 * The Python side keeps its own copy because it is a different language in a different
 * suite; if a fourth appears, that is the moment to reconsider, not now.
 */

/**
 * Blank every comment line, KEEPING THE ARRAY LENGTH so indices stay meaningful.
 *
 * In place rather than stripped, so a guard can match over the blanked copy and still
 * report `i + 1` as the real line in the real file — the property that makes this usable
 * by a check whose whole output is a file:line a person has to go and look at.
 *
 * Handles the two shapes this codebase uses: `//` line comments (including the
 * `// eslint-disable-next-line` directives that sit between a wrapper and its child) and
 * block comments, whether one line or many, bare or JSX-wrapped. Deliberately NOT a
 * parser — a regex that understood JSX would be a bigger thing to trust than the rules it
 * serves, and every consumer here is a tripwire on an obvious spelling rather than a
 * proof. It does not attempt trailing comments after code on the same line: no guard
 * needs it yet, and guessing at string literals is where this stops being cheap.
 */
export function blankComments(lines: string[]): string[] {
  let inBlock = false;
  return lines.map((line) => {
    const trimmed = line.trim();
    if (inBlock) {
      if (trimmed.includes("*/")) inBlock = false;
      return "";
    }
    if (trimmed.startsWith("/*") || trimmed.startsWith("{/*")) {
      if (!trimmed.includes("*/")) inBlock = true;
      return "";
    }
    if (trimmed.startsWith("//")) return "";
    return line;
  });
}

/** A file's source with every comment line blanked, as one string. */
export function codeOnly(source: string): string {
  return blankComments(source.split("\n")).join("\n");
}
