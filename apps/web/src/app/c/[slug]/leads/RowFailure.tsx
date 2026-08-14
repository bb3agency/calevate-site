"use client";

/**
 * "This edit did not save", said in the row it happened to.
 *
 * ## The defect
 *
 * An inline edit that fails and reverts is a lie the user cannot see. The `<select>` or
 * the text cell snaps back to the stored value — because the row re-renders from a cache
 * the server never changed — and unless something says so, the only evidence is a value
 * that did not stick. A single page-level `ProblemNotice` does not close it either: on a
 * hundred-row table it announces that AN edit failed without saying which, so a client
 * who moved four rows in a row cannot tell which three took.
 *
 * ## Why not `ProblemNotice`
 *
 * That component renders a full-width alert card with a remediation paragraph and a retry
 * button — correct at the top of a screen, and inside a table cell it would push every
 * other row down the page every time somebody's network blipped. This is one line, in
 * place, with the server's own sentence.
 *
 * ## Its own module rather than a helper inside `page.tsx`
 *
 * Next.js route modules may export only the page's own reserved names, so a shared helper
 * that lives in `page.tsx` is a `tsc` error — and the sentence is needed by the table row,
 * the board card, and any surface that grows an inline edit next.
 */

/** The server's own sentence for a row-level failure, or an honest fallback. */
export function errorSentence(error: unknown): string | null {
  if (error == null) return null;
  // `ApiProblem extends Error` and its `message` is the problem's `detail` — the sentence
  // the API wrote for a person to read. A request that never reached the API (a dropped
  // connection, a sleeping laptop) has no `detail` at all, so it gets a sentence about
  // the connection rather than a blank cell.
  if (error instanceof Error && error.message) return `Not saved — ${error.message}`;
  return "Not saved — we could not reach Calevate. Check your connection and try again.";
}

export function RowFailure({ error }: { error: unknown }) {
  const message = errorSentence(error);
  if (!message) return null;
  return (
    // `role="alert"` because it appears after an action the person took, and a change
    // that only exists as red text is a change a screen-reader user never learns about.
    <span
      role="alert"
      className="mt-0.5 block text-[11px] font-normal text-rose-700 dark:text-rose-400"
    >
      {message}
    </span>
  );
}
