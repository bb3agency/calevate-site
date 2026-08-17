# docs/legal — where the public legal documents live, and why not here

**They are not in this directory, and that is the point.**

The eight published documents — Privacy Policy, Terms of Service, Acceptable Use Policy,
Data Processing Addendum, Sub-processor list, Refund & Cancellation Policy, Grievance
Redressal and the Cookie notice — have exactly **one** source of truth:

```
apps/web/src/lib/legal/          the documents, as typed content modules
  types.ts                       the block vocabulary, and why it is small
  placeholders.ts                every {{TOKEN}} the founder must fill, with its source
  index.ts                       the registry, slug resolution, prose extraction
  document.tsx                   the ONE renderer all eight pages go through
  privacy.ts terms.ts acceptableUse.ts dpa.ts
  subprocessors.ts refunds.ts grievance.ts cookies.ts

apps/web/src/app/legal/          the routes
  page.tsx                       the index at /legal
  [slug]/page.tsx                /legal/<slug>, statically generated for all eight

apps/web/tests/legal.test.tsx    the rules about them that a person cannot hold in their head
```

Writing the prose into a markdown file here and rendering a copy in React would be two
copies of a legally operative text, and the second one is where the drift starts
(CLAUDE.md: *"one way per problem, and migrate rather than accumulate"*). A privacy notice
that says one thing on the website and another in `docs/` is not a documentation problem, it
is a misrepresentation with a paper trail.

## Why a typed content module and not MDX

Three mechanisms were weighed; the reasoning is in the header of `types.ts`. In short: MDX
costs four dependencies and a `next.config.ts` change for content that is structurally
simple, and hard rule 9 governs exactly that trade. A markdown file read at build time needs
a parser and makes the content untypeable. The typed module costs nothing, is checked by
`tsc`, gives all eight documents one heading hierarchy and one set of anchors, and makes the
rules that matter legally assertable rather than reviewable by eye:

- every `{{TOKEN}}` used is declared, and every token declared is used;
- no GSTIN, CIN, PAN or PIN-coded address appears as a literal anywhere;
- no security certification is claimed, and no "data never leaves India" claim is made;
- the AI-disclosure paragraph describes a client-controlled setting with an unconditional
  truthful-answer floor, in identical words in both documents that carry it;
- the sub-processor register is the only copy of the vendor list — the DPA's Annex C links
  to it and names no vendor;
- the pending-review banner is on every page;
- every section anchor is unique and URL-safe, because clause references cite them;
- all eight documents pass axe, no heading level is skipped, and every wide table scrolls
  inside a focusable named region.

## What IS in this repository as prose

`docs/LEGAL-SURFACE.md` — the audit that produced the documents: every obligation found, the
instrument it comes from, the code that creates it, whether we satisfy it, and — the part
worth more than the policy pages — the ten findings where we do not, each naming what would
close it.

## Before publishing

`PENDING_LEGAL_REVIEW` in `placeholders.ts` is `true` and puts a visible draft banner on
every page. Turning it off is a publication decision that requires an Indian advocate's
review first; `tests/legal.test.tsx` fails if it is flipped without also deleting the
assertion that guards it, so it cannot happen as a side effect of another change.
