/**
 * Screen mutations that predate the feedback standard (tests/feedbackGuard.test.ts), as
 * `file::name`. A ratchet: it only shrinks. The screen lanes remove entries as they move
 * each mutation onto `useActionFeedback`; nothing is ever added here.
 */
export const FEEDBACK_BASELINE: readonly string[] = [
  "src/components/authn/accountSections.tsx::signOut",
  "src/components/authn/accountSections.tsx::signOutAll",
  "src/components/authn/createAccountForm.tsx::finish",
  "src/components/authn/createAccountForm.tsx::resend",
  "src/components/authn/createAccountForm.tsx::start",
  "src/components/authn/emailVerificationPanel.tsx::requestCode",
  "src/components/authn/emailVerificationPanel.tsx::verify",
  "src/components/authn/passwordRow.tsx::submit",
  "src/components/authn/resetRequestForm.tsx::request",
  "src/components/authn/setPasswordForm.tsx::submit",
  "src/components/authn/sidebarSignOut.tsx::signOut",
  "src/components/authn/signInForm.tsx::resend",
  "src/components/authn/signInForm.tsx::signIn",
  "src/components/authn/signInForm.tsx::submitCode",
];
