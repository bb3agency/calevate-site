# docs/legal — the legal source of truth, the research behind it, and where the public documents live

## The source of truth: `LEGAL-OPS-PLAYBOOK.md`

`LEGAL-OPS-PLAYBOOK.md` is the **decision-complete** working playbook for every legality
Calevate faces — the founder's final scenario, dated 24 Aug 2026. Read it first for any
legal, tax, telecom, or data-protection question. Its headline decisions (the ones that
change how the code should behave):

- **India-only B2B. No foreign clients.** No FEMA / FIRC / LUT / IEC / SOFTEX / Stripe Atlas
  / US TCPA / EU workstream. Andhra Pradesh + Telangana at launch, Telugu-first.
- **Sole proprietor** (the founder). Calevate is a product/trade name, not a company.
- **Model B only** for phone numbers: the *client* owns and KYCs the connection on their own
  Exotel/Plivo/Vobiz account; Calevate is the **Telemarketer (TM)**, the client is the
  **Principal Entity (PE)**. Never resell numbers from a pool in Calevate's name (Model A).
- **No GST at launch** (below the ₹20 lakh services threshold; inter-state supply does not
  force it). Proforma / bill of supply, never a GST tax invoice, until a GSTIN exists.
- **Inbound reception can go live without DLT TM.** **Any outbound** (callback or campaign)
  is off until the TM-ID exists *and* that client's PE–TM chain is Active, on the right
  number series (140 for promotional; never 160-for-promo; never a raw mobile for a blast).
- Data protection stays on even India-only: transcripts still reach **US Azure OpenAI** on
  every turn, so never claim "data stays in India"; treat voice as sensitive/biometric until
  an advocate says otherwise; keep the CERT-In breach runbook.

**Precedence.** The playbook wins over the two research files below and over any stale
assumption elsewhere in `docs/` or the code; where it and `docs/` conflict, flag it, do not
silently pick (root `CLAUDE.md`). It is **not legal advice** — the unknowns it lists (§20)
go to a CA / telecom advocate before money moves or the first outbound call originates.

## The research behind it (background, cite with care)

- `phone-number-research.md` — the Model A vs Model B / DLT / number-series / concurrency
  research. Records *why* Model A is rejected.
- `comet-legal-research.md` — entity, GST/OIDAR/RCM, income tax, DLT/OSP, DPDP/SPDI, and the
  now-**parked** foreign-client material (US TCPA, FEMA/SOFTEX, export/LUT, multi-currency).

Both carry confidence labels (CONFIRMED / REPORTED / UNRESOLVED). Under hard rule 11, a
REPORTED or UNRESOLVED item is a question for a professional, never a fact to wire into money,
a client-facing claim, or a compliance gate.

## The obligation audit: `docs/LEGAL-SURFACE.md`

`docs/LEGAL-SURFACE.md` (top level) is the earlier audit that maps each legal obligation to
the code that creates it and lists the ten findings where we fall short. The playbook now
**decides** several of the founder-decisions that audit left open (entity, geography, Model B,
no-GST-at-launch), so read the playbook for the decision and LEGAL-SURFACE for the code map.

---

# Where the public legal *documents* live, and why not here

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
