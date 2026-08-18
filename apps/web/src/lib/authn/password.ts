/**
 * The password bounds, mirrored from the hasher that enforces them (D-174).
 *
 * §5.7 defect 8 of `docs/evidence/raghava-platform-teardown.md`: the reference
 * implementation's client validator accepts 128 characters while its bcrypt hasher
 * silently truncates at 72 bytes, so it advertises a strength it does not store. **A
 * validator that is more permissive than the hasher is a security bug, not a cosmetic
 * mismatch** — every character past the truncation point is theatre.
 *
 * Ours does not truncate: `apps/api/authn/hashing.py` is Argon2id, and its own bound is
 * `MIN_PASSWORD_CHARS = 12` / `MAX_PASSWORD_CHARS = 128`, enforced twice on the way in
 * (Pydantic's `Field(min_length=…, max_length=…)` on every wire model, then
 * `_refuse_unusable` at the hash itself). So the honest client bound is the SAME two
 * numbers, and `tests/authnSourceGuards.test.ts` reads them back out of
 * `apps/api/authn/hashing.py` and fails if these drift from it. Pinning to the source
 * rather than to a comment is the whole lesson of the defect: the reference's 128 was
 * true when it was written.
 *
 * NIST SP 800-63B §3.1.1.2 is where the shape comes from — a length floor and no
 * composition rules, because forced character classes push people to predictable
 * substitutions. The API's own refusal sentence says the same ("There are no other rules
 * — no required …"), so the two halves tell one story.
 */

/** Argon2id has no truncation point; these are the API's declared bounds, not a hasher's. */
export const MIN_PASSWORD_CHARS = 12;
export const MAX_PASSWORD_CHARS = 128;

/** The one sentence shown under every password field, so the three forms cannot drift. */
export const PASSWORD_RULE = `At least ${MIN_PASSWORD_CHARS} characters. Length is the only rule — no required symbols, digits or capitals.`;

/**
 * Why this password cannot be submitted, or `null` if it can.
 *
 * Length only, and both ends of it. The upper bound is a real refusal rather than a
 * silent clamp: the API rejects an over-long body before it reaches the hash, on the
 * grounds that an unbounded password on an unauthenticated route is a free CPU sink, and
 * a client that quietly trimmed to fit would store a different password than the one the
 * person typed.
 *
 * **Counted in JavaScript string units deliberately, matching the server.** Pydantic's
 * `max_length` counts Python characters (code points) and `len()` in `_refuse_unusable`
 * does the same, while JavaScript's `.length` counts UTF-16 code units — so an emoji or
 * an astral-plane character counts twice here and once there. The difference can only
 * make this client STRICTER than the server, never looser, which is the safe direction
 * for a bound whose whole purpose is to not over-promise. The alternative,
 * `[...password].length`, would count code points and match exactly; it is not used
 * because a client that accepts a password the server will refuse is the failure this
 * file exists to prevent, and being one notch tight costs a user nothing they can see.
 */
export function passwordProblem(password: string): string | null {
  if (password.length < MIN_PASSWORD_CHARS) {
    return `Use at least ${MIN_PASSWORD_CHARS} characters — this one has ${password.length}.`;
  }
  if (password.length > MAX_PASSWORD_CHARS) {
    return `Use at most ${MAX_PASSWORD_CHARS} characters — this one has ${password.length}.`;
  }
  return null;
}
