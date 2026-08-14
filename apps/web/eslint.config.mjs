import { dirname } from "path";
import { fileURLToPath } from "url";

import { FlatCompat } from "@eslint/eslintrc";

/**
 * `eslint-config-next@15` still ships eslintrc-shaped configs (`module.exports =
 * { extends: [...] }`), not flat-config arrays. Importing them directly into a flat
 * config throws "nextVitals is not iterable" — which it had been doing, so `pnpm lint`
 * has never actually linted anything. FlatCompat is the bridge Next's own scaffold
 * uses; drop it when eslint-config-next ships flat config natively.
 */
const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

/**
 * The `in`-on-a-wire-string ban — half of the executable guard against the defect class
 * `src/lib/lookup.ts` documents.
 *
 * Three live crashes came out of one shape: `value in TABLE`, where `value` is a string
 * the SERVER chose. `in` walks the prototype chain, so `"constructor" in TABLE` answers
 * true, the caller reads a property off the `Object` function, and the screen goes blank
 * mid-render. The fix (`lookup`/`hasKey`, on `Object.hasOwn`) is in place everywhere and
 * nothing stopped the next author from writing the old shape again — D-29's point being
 * that a rule resting on human vigilance is violated exactly when the codebase grows
 * fastest. This is that rule, made executable.
 *
 * ## Why the selector keys on the LEFT operand, not on the table
 *
 * The tempting selector is "`in` against one of our copy tables", and esquery cannot
 * express it: selectors match one node, and the table's declaration is somewhere else
 * in the file, or in another module (`HOLD_RULES` is imported). What CAN be said in a
 * selector is the thing that actually separates the bug from the idiom:
 *
 *  - `value in TABLE` — a DYNAMIC key. Unsafe against ANY object literal, whoever built
 *    it, because the key may name an inherited member. There is no correct use of this
 *    form: when the key is dynamic, `Object.hasOwn` (or `hasKey`) is always the answer.
 *  - `"phone" in item` — a STRING LITERAL key. TypeScript's discriminated-union
 *    narrowing idiom, and safe: the author wrote the key, so it cannot be `constructor`
 *    unless they typed `constructor`.
 *
 * So the ban is on `in` with a non-literal left operand, and the narrowing idiom stays
 * legal. That is why this fires on zero existing sites while still catching all three of
 * the original bugs — verified in tests/wireLookupGuard.test.ts, which reintroduces them.
 *
 * `for (const k in obj)` is a `ForInStatement`, a different node, and is untouched.
 *
 * The other half of the defect — `TABLE[value]`, which is a READ rather than a guard —
 * is NOT here. Telling `HOLD_RULES[rule]` (unsafe: string-keyed) from
 * `KYC_STATUS_COPY[status]` (safe: the key is a generated union, and `tsc` rejects a
 * plain string there) requires TYPE information, which this config deliberately does not
 * load — `next/typescript` runs typescript-eslint without a type-aware project service,
 * and turning one on to carry a single rule costs every `pnpm lint` a full program
 * build. Without types the only selector available is "computed read off a table-shaped
 * name", which fires on ~35 sites the sweep correctly left alone; a rule that cries wolf
 * gets `eslint-disable`d, and then it protects nothing. That half is enforced instead by
 * tests/wireLookupGuard.test.ts, which builds the real `tsc` program once and asks the
 * checker directly. Selector docs: https://eslint.org/docs/latest/rules/no-restricted-syntax
 */
const NO_DYNAMIC_IN = {
  selector: 'BinaryExpression[operator="in"]:not([left.type="Literal"])',
  message:
    "`in` walks the prototype chain, so a wire value of `constructor` reports as present " +
    "and the read yields the `Object` function. Use `hasKey(TABLE, value)` to narrow, or " +
    "`lookup(TABLE, value)` to read (src/lib/lookup.ts). `in` with a literal key — " +
    'TypeScript\'s `"field" in obj` narrowing — is still allowed.',
};

const eslintConfig = [
  {
    ignores: [
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      // Deliberately contains the shapes banned below, so that a test can watch the ban
      // fire. `pnpm lint` must stay green, so the fixture is skipped here and linted
      // explicitly by tests/wireLookupGuard.test.ts with the API's `ignore: false`.
      "tests/fixtures/**",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript", "plugin:jsx-a11y/recommended"),
  {
    /**
     * The STATIC half of the accessibility gate; `tests/a11y.test.tsx` is the runtime half.
     *
     * Not a second way of doing one thing — the two see different defects, the way
     * `no-restricted-syntax` and `tests/wireLookupGuard.test.ts` split the `in`/lookup
     * rule above. axe walks a RENDERED tree, so it can only judge what the accessibility
     * tree ended up looking like; it cannot see that a `<div onClick>` is a control at
     * all, because a div with a click handler renders as a div. jsx-a11y reads the JSX
     * and catches exactly that class at author time: interactive handlers on static
     * elements, a positive `tabIndex`, an `<a>` with no `href`, invalid ARIA before it
     * ever renders.
     *
     * `eslint-plugin-jsx-a11y` costs NO new dependency: `eslint-config-next` already
     * ships it, and `next/core-web-vitals` already enables six of its rules — so this
     * turns on the rest of a plugin that was being paid for and half-used.
     *
     * It fires on ZERO existing sites bar the two configured below, which is the
     * evidence that the 26 files reaching for `aria-*`/`role=` were doing real work.
     */
    files: ["src/**/*.tsx"],
    rules: {
      // Default `depth: 2`. Our radio rows are `<label><input><span><span>text`, so the
      // label's text sits one level deeper than the rule looks and it reports a label
      // with no accessible text — which is false: the control is implicitly associated by
      // wrapping, and axe computes the name correctly (tests/a11y.test.tsx scans this
      // screen). Raising the depth fixes the rule's reach rather than silencing it.
      "jsx-a11y/label-has-associated-control": ["error", { depth: 3 }],
    },
  },
  {
    // Application AND tests: a test that reaches for `in` on a wire value is asserting
    // the wrong thing, and tests/harness.tsx already routes its own table lookups
    // through `Object.hasOwn` for exactly this reason.
    files: ["src/**/*.{ts,tsx}", "tests/**/*.{ts,tsx}"],
    rules: { "no-restricted-syntax": ["error", NO_DYNAMIC_IN] },
  },
];

export default eslintConfig;
