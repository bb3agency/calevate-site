/**
 * The shape of an emailed code, as the server issues it.
 *
 * Both numbers are the server's and are pinned to it by `tests/authnSourceGuards.test.ts`:
 * `OTP_DIGITS` in `apps/api/authn/codes.py` and `OTP_RESEND_COOLDOWN` in
 * `apps/api/authn/otp.py`. The cooldown is shown as a countdown; when the server refuses a
 * resend anyway (another tab, a clock that is off) its `Retry-After` replaces it.
 */

export const OTP_LENGTH = 6;

export const OTP_RESEND_COOLDOWN_MS = 60_000;
