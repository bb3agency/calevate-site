/**
 * Screen mutations that predate the feedback standard (tests/feedbackGuard.test.ts), as
 * `file::name`. A ratchet: it only shrinks, and it is now empty. Nothing is ever added here;
 * a new mutation goes through `useActionFeedback`.
 */
export const FEEDBACK_BASELINE: readonly string[] = [];
