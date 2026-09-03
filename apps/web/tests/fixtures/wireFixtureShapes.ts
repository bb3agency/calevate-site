/**
 * Planted shapes for `wireFixtureGuard.test.ts` — banned assertions and the safe
 * look-alikes the guard must never touch.
 *
 * Every banned shape here is TRANSCRIBED from a site that was live in this tree before
 * the sweep that added the guard, so the instrument is proven against the code that
 * actually existed rather than against an invention. Each offending expression sits a
 * fixed distance below its `export function` signature; the guard locates them by marker
 * so these expectations survive edits above.
 *
 * `eslint.config.mjs` skips `tests/fixtures/**`, so the deliberately-wrong code here does
 * not have to be disabled line by line.
 */

import type { TenantSummary } from "@/lib/api/admin";
import { ApiProblem, type CallSummary, type Me } from "@/lib/api/client";

const ORG = { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" };

// ─── banned ──────────────────────────────────────────────────────────────────────────

/** The single assertion. `tenant()` in adminCommercials.test.tsx was exactly this. */
export function bannedSingleAssertion(): TenantSummary {
  return {
    id: "t1",
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  } as TenantSummary;
}

/**
 * The DOUBLE assertion, which is strictly worse: a single `as T` still rejects a literal
 * with no overlap at all, and `as unknown as T` rejects nothing whatsoever. 55 of the 106
 * sites the sweep removed were spelled this way.
 */
export function bannedDoubleAssertion(): Me {
  return {
    user_id: "u1",
    realm: "client",
    role: "owner",
    permissions: ["calls:read"],
    impersonating: false,
    organization: ORG,
  } as unknown as Me;
}

/** An ARRAY of wire objects — `MEMBERS` in leadsBulk.test.tsx. */
export function bannedArrayAssertion(): CallSummary[] {
  return [] as CallSummary[];
}

/**
 * An INDEXED ACCESS into a wire type, which is how a fixture claims the server's closed
 * union already contains a value it does not. `attention.test.tsx` said
 * `kind: "number_suspended" as AttentionItem["kind"]` while testing that the build had
 * never heard of that kind — an assertion asserting the opposite of the test's premise.
 */
export function bannedIndexedAccessAssertion(): CallSummary["status"] {
  return "abandoned" as CallSummary["status"];
}

/**
 * `Partial<T>` — the hole the first draft of the guard left open, and the one that was
 * hiding a real missing field.
 *
 * `Partial<Me>` is a MAPPED type. Its resolved type carries no symbol declared in
 * `schema.d.ts` (the mapped type is anonymous), `getTypeArguments` returns `[]` because a
 * mapped type is not a type REFERENCE, and its `aliasSymbol` is `Partial`, declared in
 * `lib.es5.d.ts`. So every test in this guard's first version passed while
 * `as unknown as Partial<CallDetail>` sat in `callDetail.test.tsx` — and behind one of
 * those three assertions, a transcript fixture was missing `TranscriptTurnOut.redacted`,
 * which the wire marks REQUIRED. Two spellings of one shape in one file, and
 * `pnpm typecheck` green over both.
 *
 * The fix is `aliasTypeArguments`, which is where a mapped type keeps what it was applied
 * TO. Every generic wrapper answers to it — `Partial`, `Readonly`, `Required`, `Pick`,
 * `Omit`, `Record<string, Me>` — so this closes the shape rather than the one instance.
 *
 * Why the assertion is never right here: a fixture builder already takes `Partial<T>`
 * (`function me(over: Partial<Me> = {})`), so the argument is checked by the parameter
 * and the assertion can only remove that check. The three live sites were the assertion
 * fighting the annotation, which is exactly what the 106 removed sites were.
 */
export function bannedPartialAssertion(): Partial<Me> {
  return { role: "staff", permissions: ["calls:read"] } as Partial<Me>;
}

// ─── safe ────────────────────────────────────────────────────────────────────────────

/**
 * The sanctioned spelling where there is no declaration to annotate — a value inside a
 * `Routes` map. `satisfies` demands every required field and rejects fields the server
 * cannot send, and unlike an annotation it leaves the value's own type alone.
 */
export const safeSatisfies = {
  "/v1/admin/tenants/t1": {
    id: "t1",
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  } satisfies TenantSummary,
};

/** The other sanctioned spelling: annotate the declaration and let it be checked. */
export function safeAnnotation(): TenantSummary {
  const tenant: TenantSummary = {
    id: "t1",
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  };
  return tenant;
}

/**
 * A payload that is deliberately OFF-CONTRACT, carried as `unknown`.
 *
 * This is the honest expression of "the server is newer than this build", and it is what
 * three tests were reaching for when they wrote an assertion instead. Nothing is asserted,
 * so nothing is claimed; the route map takes `unknown` and the screen has to cope.
 */
export const safeOffContractPayload: Record<string, unknown> = {
  kind: "number_suspended",
  title: "Your number was suspended",
};

/**
 * A DOM assertion. `screen.getByRole(...) as HTMLButtonElement` appears ~120 times in this
 * suite and is unavoidable: testing-library returns `HTMLElement` and `.disabled` lives on
 * the subtype. Nothing about it concerns the wire.
 */
export function safeDomAssertion(): boolean {
  const node = { disabled: true } as unknown as HTMLButtonElement;
  return node.disabled;
}

/**
 * A HAND-WRITTEN api type. `ApiProblem` is a class in `src/lib/api/client.ts`, not a
 * generated schema shape, and narrowing a caught `unknown` onto it is the normal spelling
 * (identityMirrorRetry.test.ts). The guard keys on `schema.d.ts` precisely so this stays
 * legal — a rule that fired here would be waived within a week.
 */
export function safeNonWireAssertion(failure: unknown): number {
  return (failure as ApiProblem).status;
}

/** `as const`, which narrows a literal rather than silencing a check. */
export function safeAsConst(): readonly string[] {
  return ["calls:read", "leads:read"] as const;
}
