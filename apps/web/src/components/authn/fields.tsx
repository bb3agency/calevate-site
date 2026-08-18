"use client";

/**
 * The controls every authentication form is built from (D-174).
 *
 * Presentation only — no realm, no session, no fetch. They exist so the six forms cannot
 * each invent their own label wiring, their own error placement or their own password
 * hint, which is how one of six comes to be the unlabelled one.
 *
 * `FIELD`, `FIELD_LABEL` and `FIELD_HINT` are imported from `components/ui.tsx` rather
 * than re-declared. That is CLAUDE.md's one-way-per-problem rule, and it also keeps these
 * inside the tap-target guarantee `tests/responsive.test.ts` enforces on those constants —
 * a private copy would be a second class string nobody re-measured at 320px.
 */

import { useId, type ReactNode } from "react";

import { CircleAlert } from "lucide-react";

import { FIELD, FIELD_HINT, FIELD_LABEL, NoticeBox, ProblemNotice } from "@/components/ui";
import { signInMessage } from "@/lib/authn/problems";

/**
 * A labelled text input with an optional hint and an optional field-level message.
 *
 * The label is a real `<label htmlFor>`, never a placeholder. `tests/a11y.ts` says at
 * length that axe PASSES an input whose only accessible name is its placeholder, so a
 * green sweep is not evidence of a labelled field — and a placeholder disappears the
 * moment somebody types, which is WCAG 3.3.2's whole complaint. The one gate that would
 * not catch this is the reason to be explicit about it here.
 */
export function AuthField({
  label,
  hint,
  error,
  inputRef,
  ...input
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  /**
   * For DELIBERATE focus management across a view change — the sign-in form moving to its
   * code step, where the control that had focus has just unmounted and focus would
   * otherwise fall to `<body>`. Not `autoFocus`, which `jsx-a11y/no-autofocus` refuses in
   * this repo and which would also steal focus on first paint, where nothing changed.
   */
  inputRef?: React.Ref<HTMLInputElement>;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");

  return (
    <div>
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      <input
        id={id}
        ref={inputRef}
        className={FIELD}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        {...input}
      />
      {hint && (
        <span id={hintId} className={FIELD_HINT}>
          {hint}
        </span>
      )}
      {error && (
        // `role="alert"` so the message is announced when it appears rather than only
        // when focus happens to reach the field it describes.
        <p id={errorId} role="alert" className="mt-1 text-xs text-rose-600 dark:text-rose-400">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * A refusal from an authentication route, rendered the one way it is allowed to be.
 *
 * `signInMessage` returns FIXED copy keyed on the problem code — see
 * `lib/authn/problems.ts` for why the sign-in path must not pass the server's own
 * sentence through, and why `invalid_credentials` has exactly one entry covering an
 * unknown address, a wrong password and a deactivated account.
 *
 * Anything unrecognised falls through to `ProblemNotice`, which is the app's single
 * renderer for a failure nobody anticipated. Inventing a generic sentence here instead
 * would turn every unexpected failure into a confident claim about the credential.
 */
export function AuthProblemNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const message = signInMessage(error);
  if (message === null) return <ProblemNotice error={error} />;
  return (
    <NoticeBox
      tone="stop"
      icon={<CircleAlert aria-hidden className="h-4 w-4" />}
      title="That did not work"
    >
      {/* `role="alert"` on the sentence, not on the box: the box's title is decoration
          that repeats on every failure, and announcing it adds noise before the part a
          person needs. */}
      <p role="alert" className="mt-1">
        {message}
      </p>
    </NoticeBox>
  );
}
