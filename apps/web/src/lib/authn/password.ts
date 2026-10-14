/**
 * The password bounds, mirrored from the hasher that enforces them (D-174).
 *
 * §5.7 defect 8 of `docs/evidence/raghava-platform-teardown.md`: the reference
 * implementation's client validator accepts 128 characters while its bcrypt hasher
 * silently truncates at 72 bytes, so it advertises a strength it does not store. **A
 * validator that is more permissive than the hasher is a security bug, not a cosmetic
 * mismatch** — every character past the truncation point is theatre.
 *
 * Ours does not truncate: `apps/api/authn/hashing.py` is Argon2id, its absolute bound is
 * `MIN_PASSWORD_CHARS` / `MAX_PASSWORD_CHARS`, and `apps/api/authn/policy.py` holds each
 * realm's floor (`MIN_CHARS_BY_REALM`, read through `min_password_chars`). The numbers
 * here are the same ones, and `tests/authnSourceGuards.test.ts` reads them back out of
 * those two files and fails if they drift. A validator looser than the server tells a
 * person their password is fine and then the submit is refused.
 *
 * The floor is 8 characters on every realm (D-765, founder decision 13 Oct 2026). It is
 * still looked up per realm because the API keeps that seam.
 *
 * NIST SP 800-63B-4 §3.1.1.2 is where the shape comes from — a length floor and no
 * composition rules, because forced character classes push people to predictable
 * substitutions. The API's own refusal sentence says the same ("There are no other rules
 * — no required …"), so the two halves tell one story.
 */

/** The realms the API authenticates in — `apps/api/authn/models.py::AUTHN_REALMS`. */
export type AuthnRealm = "client" | "admin";

/** Each realm's minimum, mirrored from `apps/api/authn/policy.py::MIN_CHARS_BY_REALM`. */
export const MIN_PASSWORD_CHARS_BY_REALM: Record<AuthnRealm, number> = {
  client: 8,
  admin: 8,
};

/** The smallest floor any realm imposes — the hasher's absolute bound. A form that knows
 * its realm shows that realm's floor instead. */
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
