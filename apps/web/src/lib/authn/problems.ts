/**
 * The refusal vocabulary of `/v1/auth/**`, and what a person is told about each (D-174).
 *
 * `apps/api/authn/routes.py`'s module docstring is the contract this mirrors — a table of
 * condition → status → code, every one of them RFC-9457 problem+json. This file is the
 * browser's half of it, and it exists so that no screen decides on its own what a code
 * means. A ladder written per form is how one form comes to treat `invalid_credentials`
 * as a reason to end the session and another does not.
 *
 * ## Why the copy lives here and not in the server's `detail`
 *
 * Most screens in this app render `problem.detail` and that is right, because the API
 * writes user-safe sentences. **The sign-in path is the exception, and deliberately.**
 * §5.7 defect 2 of `docs/evidence/raghava-platform-teardown.md` is a user-enumeration
 * oracle: the reference implementation answers a known admin, a deactivated admin and an
 * unknown address three different ways and renders three different sentences. Ours
 * answers ONE way — `service.sign_in` equalises status, body AND wall-clock time — and a
 * frontend that passed the server's string through unexamined would still be one server
 * change away from leaking the distinction back. So the sign-in surfaces render a FIXED
 * sentence chosen by code, and the code is all they read. `tests/authnScreens.test.tsx`
 * drives two different upstream bodies through it and asserts the rendered output is
 * identical, character for character.
 */

import { ApiProblem } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

/**
 * Every code `apps/api/authn/` can raise, spelled once.
 *
 * Read off the source (`grep -o 'code="[a-z_]*"' apps/api/authn/*.py`) plus
 * `ProblemError.unauthorized`'s `unauthorized` and the rate-limit middleware's
 * `rate_limited`. `tests/authnSourceGuards.test.ts` re-derives the set from
 * `apps/api/authn/*.py` and fails if this drifts, so the list is pinned to its source
 * rather than to somebody's memory of it.
 */
export const AUTHN_CODES = {
  alreadyBootstrapped: "already_bootstrapped",
  crossSiteRequest: "cross_site_request",
  disabled: "first_party_auth_disabled",
  invalidBootstrapToken: "invalid_bootstrap_token",
  invalidCode: "invalid_code",
  invalidCredentials: "invalid_credentials",
  invalidResetToken: "invalid_reset_token",
  invalidSecondFactor: "invalid_second_factor",
  invitationAccountUnverified: "invitation_account_unverified",
  invitationInvalid: "invitation_invalid",
  passwordLength: "password_length",
  rateLimited: "rate_limited",
  reauthenticationRequired: "reauthentication_required",
  secondFactorRequired: "second_factor_required",
  tooManyAttempts: "too_many_attempts",
  unauthorized: "unauthorized",
} as const;

export type AuthnCode = (typeof AUTHN_CODES)[keyof typeof AUTHN_CODES];

/** The code on a refusal, or `""` for anything that is not an `ApiProblem`. */
export function codeOf(error: unknown): string {
  return error instanceof ApiProblem ? error.code : "";
}

/**
 * A refusal this browser produced rather than the server — no HTTP response happened.
 *
 * `ApiProblem` already models it (`status: 0`, via `AuthProblem`), and §5.7 defect 9 is
 * what makes the distinction load-bearing: `OpsSessionGate` rendered
 * `error ?? "Sign in to continue."` for every failure, so a dropped connection and an
 * expired session were the same sentence to the operator. They have opposite remedies —
 * one is "try again", the other is "sign in" — and a gate that cannot tell them apart
 * sends people to re-enter a password that was never the problem.
 */
export function isUnreachable(error: unknown): boolean {
  return error instanceof ApiProblem && error.status === 0;
}

/**
 * This session is gone and no retry brings it back.
 *
 * The ONE condition that may clear local session state. Everything else — a wrong
 * password, a wrong code, a rate limit, a network failure — leaves the session alone.
 *
 * **`invalid_credentials` is excluded, and that exclusion is the point** (§5.3): a
 * step-up prompt inside a live console answers 401 `invalid_credentials` on a typo, and
 * treating that as "your session ended" ejects an operator mid-task for pressing the
 * wrong key. `second_factor_required` is excluded for the mirror reason: it means the
 * session is alive and one door short, which is a NAVIGATION, not a logout.
 */
export function isSessionGone(error: unknown): boolean {
  return codeOf(error) === AUTHN_CODES.unauthorized;
}

/** The half-authenticated admin session: alive, and able to reach exactly one route. */
export function needsSecondFactor(error: unknown): boolean {
  return codeOf(error) === AUTHN_CODES.secondFactorRequired;
}

/** A 429 from either budget — the failure budget (`too_many_attempts`) or the middleware. */
export function isRateLimited(error: unknown): boolean {
  const code = codeOf(error);
  return code === AUTHN_CODES.tooManyAttempts || code === AUTHN_CODES.rateLimited;
}

/**
 * Fixed, code-keyed copy for the sign-in surfaces. See the file docstring for why fixed.
 *
 * `invalid_credentials` has ONE entry covering an unknown address, a wrong password and a
 * deactivated account, because the server answers all three identically and the UI must
 * not be the place the difference reappears. The sentence therefore says nothing about
 * whether the account exists — "check both" is honest for all three and actionable for
 * the only one a real user is in.
 */
const SIGN_IN_COPY: Record<string, string> = {
  [AUTHN_CODES.invalidCredentials]:
    "That email address and password did not match. Check both and try again.",
  [AUTHN_CODES.invalidSecondFactor]:
    "That code did not match. Check the latest email and try again, or send a new code.",
  [AUTHN_CODES.invalidCode]:
    "That code did not match. Check the latest email and try again, or send a new code.",
  [AUTHN_CODES.tooManyAttempts]:
    "Too many attempts. Wait a few minutes before trying again.",
  [AUTHN_CODES.rateLimited]: "Too many requests. Wait a moment and try again.",
  [AUTHN_CODES.disabled]:
    "Sign-in is switched off on this deployment. Contact whoever operates it.",
  [AUTHN_CODES.crossSiteRequest]:
    "This request was blocked because it did not come from a Calevate console. Open the console directly rather than through a link or an embedded frame.",
  [AUTHN_CODES.unauthorized]: "You are signed out. Sign in again to continue.",
  [AUTHN_CODES.secondFactorRequired]:
    "This sign-in still needs its emailed code.",
  [AUTHN_CODES.passwordLength]:
    "That password is not an accepted length. See the requirement under the field.",
  [AUTHN_CODES.invalidResetToken]:
    "This reset link cannot be used. Reset links work once and expire an hour after they are sent — request a new one.",
  [AUTHN_CODES.invalidBootstrapToken]:
    "This setup link cannot be used. Setup links work once and expire an hour after they are sent.",
  [AUTHN_CODES.alreadyBootstrapped]:
    "This account already has a password, so the setup link no longer opens anything. Sign in instead.",
  // D-185's refusal, and the one entry here whose job is to STOP a person retrying. An
  // account already exists on this address with a password somebody set, and the address
  // was never confirmed — so this invitation cannot be attached to it until the mailbox is
  // proved. The sentence has to send them to the OTP they already have rather than back to
  // the invite link, because re-opening the link produces this same refusal forever.
  [AUTHN_CODES.invitationAccountUnverified]:
    "There is already an account for this email address, and the address has not been confirmed. Sign in to that account, confirm the address from your account settings, then open this invitation again.",
  [AUTHN_CODES.invitationInvalid]:
    "This invitation cannot be used. Invitations work once and expire 72 hours after they are created — ask whoever invited you for a fresh link.",
  // NOT the server's `detail`, which prints the two curl calls that clear it — correct for
  // an operator reading a log, wrong on a screen where the button is what does it. The
  // sentence says the session is intact, because the failure mode this copy exists to
  // prevent is an operator reading a step-up prompt as a logout and abandoning the action.
  [AUTHN_CODES.reauthenticationRequired]:
    "This action needs you to confirm it is still you. Your session is fine — send yourself a code and enter it, then try the action again.",
};

/**
 * What to show a person for a refusal on an authentication surface.
 *
 * `null` means "this is not one of ours" — the caller falls through to `ProblemNotice`,
 * which is the app's one renderer for an unrecognised failure and already says nothing it
 * cannot support. Returning a generic string here instead would turn every unknown
 * failure into a confident claim about the credential, which is the §5.7 defect 9
 * mistake pointed at a form rather than at a gate.
 */
export function signInMessage(error: unknown): string | null {
  if (isUnreachable(error)) {
    return "We could not reach Calevate. Check your connection and try again — nothing was submitted.";
  }
  // `lookup`, not `SIGN_IN_COPY[code]`: the key is a WIRE STRING the server chose, and a
  // bare index walks the prototype chain — a refusal carrying `code: "constructor"` would
  // resolve to the `Object` function and be rendered into the page. `src/lib/lookup.ts` is
  // this repo's one answer to that, and `tests/wireLookupGuard.test.ts` enforces it.
  // `?? null` rather than a default sentence, for the reason above.
  return lookup(SIGN_IN_COPY, codeOf(error)) ?? null;
}
