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
 * NIST SP 800-63B-4 §3.1.1.2 is where the shape comes from — a length floor and no
 * composition rules, because forced character classes push people to predictable
 * substitutions. The API's own refusal sentence says the same ("There are no other rules
 * — no required …"), so the two halves tell one story.
 *
 * ## THE FLOOR IS PER REALM, AND THAT IS THE SAME DEFECT ONE LEVEL UP
 *
 * §3.1.1.2 requires 15 characters when the password is "used as a single-factor
 * authentication mechanism" and permits fewer only for a password "only used as part of
 * multi-factor authentication processes". The client realm has no second factor and the
 * admin realm does (D-170), so the two realms have DIFFERENT floors —
 * `apps/api/authn/policy.py::MIN_CHARS_BY_REALM` is the API's single copy of that fact.
 *
 * A single client-side `MIN_PASSWORD_CHARS = 12` shown on a client-realm form is
 * precisely the defect this file was written about, one level up from the truncation
 * case: a validator advertising a bound looser than the one the server enforces, so the
 * person types twelve characters, is told it is fine, submits, and is refused. So the
 * bound here takes a realm, and `tests/authnSourceGuards.test.ts` reads the whole table
 * back out of `policy.py` rather than one number out of `hashing.py`.
 *
 * `MIN_PASSWORD_CHARS` remains exported as the ABSOLUTE floor — the smallest value any
 * realm allows, and the only honest bound for a form that does not know its realm. No
 * form is in that position today; it exists so that a future one cannot silently pick
 * the client's 15 for an admin or the admin's 12 for a client.
 */

/** The realms the API authenticates in — `apps/api/authn/models.py::AUTHN_REALMS`. */
export type AuthnRealm = "client" | "admin";

/**
 * Each realm's minimum, mirrored from `apps/api/authn/policy.py::MIN_CHARS_BY_REALM`.
 *
 * `client` is 15 because a client password is the whole of the authentication;
 * `admin` is 12 because an admin password is one factor of two (the emailed OTP is the
 * other) and NIST permits as few as 8 in that case — 12 is what those accounts have.
 */
export const MIN_PASSWORD_CHARS_BY_REALM: Record<AuthnRealm, number> = {
  client: 15,
  admin: 12,
};

/** The smallest floor any realm imposes. See the note above on why this is not the one
 * to show on a form that knows which realm it is in. */
export const MIN_PASSWORD_CHARS = Math.min(...Object.values(MIN_PASSWORD_CHARS_BY_REALM));

/** Argon2id has no truncation point; this is the API's declared ceiling, not a hasher's. */
export const MAX_PASSWORD_CHARS = 128;

/** The one sentence shown under a password field, so the forms cannot drift.
 *
 * "Three or four unrelated words" rather than a bare character count: §3.1.1.2 requires
 * that verifiers "offer guidance to the subscriber to help the subscriber choose a strong
 * password", and a floor stated alone is the advice that produces `Password@12345`. */
export function passwordRule(realm: AuthnRealm): string {
  return `At least ${MIN_PASSWORD_CHARS_BY_REALM[realm]} characters — three or four unrelated words is the easiest way there. Length is the only rule: no required symbols, digits or capitals.`;
}

/**
 * Why this password cannot be submitted, or `null` if it can.
 *
 * Length only, and both ends of it — the floor is the REALM's (see above). The upper bound is a real refusal rather than a
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
export function passwordProblem(password: string, realm: AuthnRealm): string | null {
  const floor = MIN_PASSWORD_CHARS_BY_REALM[realm];
  if (password.length < floor) {
    return `Use at least ${floor} characters — this one has ${password.length}.`;
  }
  if (password.length > MAX_PASSWORD_CHARS) {
    return `Use at most ${MAX_PASSWORD_CHARS} characters — this one has ${password.length}.`;
  }
  return null;
}
