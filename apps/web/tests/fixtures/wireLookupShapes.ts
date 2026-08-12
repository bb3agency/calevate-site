/**
 * The banned shapes, and their safe look-alikes, written out once so the guards can be
 * pointed at something that MUST fail.
 *
 * A guard nobody has watched fail is a guard nobody knows is wired up. Both instruments
 * in tests/wireLookupGuard.test.ts read this file: the ESLint rule must flag exactly the
 * `BANNED_IN` line, the type-aware scan must flag exactly the `BANNED_READ` line, and
 * NEITHER may say anything about the four safe shapes below — which are not invented for
 * the test, they are transcriptions of real sites the sweep deliberately left alone
 * (`counts[kind]` in attention/page.tsx, `KYC_STATUS_COPY[status]` in verification/page.tsx,
 * `values[field.key]` in lib/api/messagingConsent.ts).
 *
 * This file is deliberately NOT fixed. It is excluded from `pnpm lint` in
 * eslint.config.mjs and re-linted explicitly by the test with `ignore: false`; it
 * type-checks cleanly, which is the whole point — `tsc` has no objection to either
 * banned line, and that is why these guards exist at all.
 */

/** A copy table keyed by a WIRE STRING — the shape `HOLD_RULES` and `LEAD_STATUS_STYLES` have. */
const WIRE_KEYED: Record<string, string> = { queued: "grey", won: "green" };

/** A copy table keyed by a GENERATED UNION — the shape `KYC_STATUS_COPY` has. */
type Verdict = "pending" | "verified";
const UNION_KEYED: Record<Verdict, string> = { pending: "amber", verified: "green" };

// ─── BANNED ──────────────────────────────────────────────────────────────────────────

/**
 * BANNED_IN — the guard half. `isKnownKycStatus`, `isKnownSource` and `holdRule` were all
 * this line. `"constructor"` answers true and the caller reads a property off `Object`.
 */
export function bannedIn(wireValue: string): boolean {
  return wireValue in WIRE_KEYED;
}

/**
 * BANNED_READ — the read half. `styles[value]` in StatusBadge, which rendered
 * `function Object() { [native code] }` into a `className`. `??` does not rescue it:
 * the `Object` function is neither `null` nor `undefined`.
 */
export function bannedRead(wireValue: string): string {
  return WIRE_KEYED[wireValue] ?? "slate";
}

/**
 * BANNED_ALIAS — the same read, one local binding away from the table. This is the exact
 * shape `StatusBadge` had (`const styles = kind === "lead" ? A : B; styles[value]`), and
 * a scan that only asks "is the table module-scope?" waves it through.
 */
export function bannedAliasedRead(wireValue: string, other: Record<string, string>): string {
  const styles = wireValue.length > 3 ? WIRE_KEYED : other;
  return styles[wireValue] ?? "slate";
}

// ─── SAFE — the guards must stay silent on every one of these ────────────────────────

/** TypeScript's narrowing idiom. The key is a literal the AUTHOR wrote; it cannot be a wire value. */
export function safeLiteralIn(value: object): boolean {
  return "phone" in value;
}

/** A union-keyed read. `tsc` rejects a plain `string` here, so the key cannot be `constructor`. */
export function safeUnionRead(status: Verdict): string {
  return UNION_KEYED[status];
}

/** A key that came from `Object.keys` of our own table — the `counts[kind]` shape. */
export function safeOwnKeysRead(counts: Record<string, number>): number {
  return (Object.keys(UNION_KEYED) as Verdict[]).reduce((n, kind) => n + (counts[kind] ?? 0), 0);
}

/** A LOCAL object the caller built, indexed by a dynamic key — the `values[field.key]` shape. */
export function safeLocalRead(field: { key: string }): string | undefined {
  const values: Record<string, string> = { consent_text: "yes" };
  return values[field.key];
}
