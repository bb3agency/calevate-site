/**
 * Reading a WIRE STRING out of a copy table, exactly once, safely.
 *
 * Every screen in this app turns a server-supplied enum into words: a hold rule into a
 * remedy, a KYC status into a headline, a delivery status into a colour. All of them are
 * an object literal indexed by a string the server chose, and all of them were written
 * as `TABLE[value] ?? fallback` or `value in TABLE` — both of which read the PROTOTYPE
 * CHAIN, so a wire value of `constructor` resolves to the `Object` function instead of
 * missing. Three different failures came out of that one shape:
 *
 *  - `value in TABLE` answers TRUE, the caller reads `.label` off `Object`, and calling
 *    `.toLowerCase()` on the `undefined` throws DURING RENDER — a blank screen where a
 *    compliance verdict should be (`holdRule`, `isKnownKycStatus`, `isKnownSource`).
 *  - `TABLE[value] ?? fallback` never fires the fallback, because `Object` is neither
 *    `null` nor `undefined`. Where the result is interpolated into a `className` the
 *    page renders `function Object() { [native code] }` as a list of CSS classes.
 *  - `TABLE[value]?.field ?? fallback` happens to be correct, because the property
 *    access on the inherited function yields `undefined` and the `??` finally fires.
 *
 * That third case is why this module exists rather than a patch at each site. Some
 * lookups were right, some were wrong, and NOTHING IN THE SOURCE DISTINGUISHES THEM —
 * the difference is one `?.` several tokens away from the bug. A reviewer cannot audit
 * that, and the next copy table will be written in whichever style was copied. One
 * function, used everywhere, makes "is this lookup safe" a question about which function
 * was called rather than about operator precedence.
 *
 * ## Why the tables stay object literals
 *
 * The airtight fix for prototype-chain lookups is a `Map`, or `Object.create(null)`:
 * neither has a prototype to walk, so the class of bug cannot be written at all. Both
 * were rejected, and the reason is that these tables are not only read by key.
 * `Record<KycStatus, …>` over a GENERATED union is what makes `tsc` fail when the API
 * adds a status nobody wrote copy for — kyc.ts says so explicitly, and the admin form
 * builds its `<select>` from `Object.keys` of the same table. A `Map` literal loses the
 * exhaustiveness check (its constructor takes an array of pairs, and a missing pair is
 * not a type error), which trades a compile-time guarantee for a runtime one we can get
 * more cheaply here. `Object.create(null)` keeps the type but produces objects that
 * break `Object.prototype` expectations in ways the next reader will not predict.
 *
 * So: keep the literal, keep the exhaustiveness, and make the READ the narrow place.
 * `Object.hasOwn` is the guard — ES2022, and the reason it exists is precisely that
 * `hasOwnProperty` is itself shadowable
 * (developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Object/hasOwn).
 *
 * ## Why no fallback parameter
 *
 * `lookup` returns `undefined` and stops there, rather than taking a default. Fail
 * direction is a per-site decision in this codebase and deliberately NOT uniform: the
 * ops queue fails VISIBLE (an unnameable hold keeps its row), the client's campaign
 * hold fails CLOSED (an unnameable rule stays held), and a colour lookup falls back to
 * slate. Handing the fallback to this function would put all three behind one call and
 * invite the next author to think the choice had already been made. `?? …` at the call
 * site keeps each site's intent where the intent is.
 */

/**
 * The table's value for `key`, or `undefined` when the table does not OWN that key.
 *
 * `null`/`undefined` keys are absent rather than an error: most callers hold a nullable
 * column (`source: string | null`) and the alternative is a `&&` at every one of them.
 */
export function lookup<K extends string, V>(
  table: Record<K, V>,
  key: string | null | undefined,
): V | undefined {
  if (key === null || key === undefined) return undefined;
  return Object.hasOwn(table, key) ? (table as Record<string, V>)[key] : undefined;
}

/**
 * Narrow a wire string to one of the table's own keys.
 *
 * For the tables keyed by a GENERATED union, where the caller needs the narrowed type
 * rather than the value — an `<option value>` that must be a member the API's `Literal`
 * accepts. Where only the value is wanted, `lookup` says it in one call instead of two.
 */
export function hasKey<K extends string>(
  table: Record<K, unknown>,
  key: string | null | undefined,
): key is K {
  return key !== null && key !== undefined && Object.hasOwn(table, key);
}
