import Link from "next/link";
import type { ReactNode } from "react";

import { CopyLinkButton } from "@/components/legal/copyLink";
import { LegalContents } from "@/components/legal/contents";
import { BackToTop, PrintButton } from "@/components/legal/readerControls";
import { MarketingPage, PILL_LINK, SHELL } from "@/components/marketing/pageShell";
import { ScrollRegion } from "@/components/ui";

import { LEGAL_DOCUMENTS } from "./index";
import {
  CHROME_TOKENS,
  PENDING_LEGAL_REVIEW,
  PENDING_LEGAL_REVIEW_MARKER,
  PLACEHOLDER_PATTERN,
  assertLegalSetPublishable,
  resolvePlaceholders,
} from "./placeholders";
import type { LegalBlock, LegalDocument, LegalSection } from "./types";
import { documentVersionLabel } from "./versions";

/**
 * ONE renderer for all eight documents.
 *
 * The alternative — a page component per document — is how heading hierarchies drift,
 * how one page ends up with a table that overflows at 320px while the others do not, and
 * how the pending-review banner gets forgotten on the ninth document. Everything about
 * how a legal page looks and announces itself is decided here, once, and
 * `tests/legal.test.tsx` scans all eight through axe rather than one representative.
 *
 * PRESENTATION ONLY. The words live in the document modules and are hash-guarded
 * (`tests/legalContentHash.test.ts`); nothing here may add, drop, reorder or rephrase
 * one of them. `tests/legalReader.test.tsx` checks that every string `textOf` reaches is
 * rendered, in order.
 *
 * ## Accessibility decisions worth stating
 *
 * - **Heading levels are structural, not visual.** `h1` is the document, `h2` is a
 *   numbered section, `h3` is a subsection. Nothing skips a level, and size is a class
 *   rather than a tag.
 * - **The table of contents is ONE `nav` with a name**, a sticky rail on a wide screen
 *   and a collapsed disclosure on a phone (`components/legal/contents.tsx`). These
 *   documents are long; a reader who cannot jump to clause 14 has to read to it. The
 *   entry for the clause being read carries `aria-current="location"`.
 * - **Every heading has a copy-link control beside it**, not inside it, so the heading's
 *   accessible name stays the heading.
 * - **Wide tables scroll inside their own focusable region.** A `div` with
 *   `overflow-x: auto` that is not keyboard focusable is content a keyboard user cannot
 *   reach — axe's `scrollable-region-focusable` is exactly this — so the wrapper takes
 *   `tabIndex={0}` and is named from the table's own caption.
 * - **Callout tone is never carried by colour alone.** Each one prints its kind in words
 *   ("Note", "Important") above the title, because colour is invisible to a screen reader
 *   and unreliable for a reader with low vision on a cheap phone in daylight — which is
 *   the reader this whole product is built for.
 */

/**
 * Renders `{{TOKEN}}` runs as visible marks and everything else as plain text.
 *
 * A token whose fact has been DECIDED is substituted first and never reaches the marking
 * pass, so it renders as ordinary prose. That is the half that was missing: the hosting
 * location was decided at D-180 and went on rendering as a raw `{{…}}` on two
 * client-facing pages, because the only path from a decision to the prose was somebody
 * remembering to edit each document. Substitution happens HERE rather than in the
 * document modules so the token stays in the source, where `textOf` can still audit that
 * every token is declared and every declaration is used.
 */
function withPlaceholders(source: string): ReactNode[] {
  const text = resolvePlaceholders(source);
  const out: ReactNode[] = [];
  let cursor = 0;
  // A fresh regex per call: `PLACEHOLDER_PATTERN` is global and therefore stateful, and
  // sharing `lastIndex` across renders would drop matches on every second paragraph.
  const pattern = new RegExp(PLACEHOLDER_PATTERN.source, "g");
  for (const match of text.matchAll(pattern)) {
    const at = match.index;
    if (at > cursor) out.push(text.slice(cursor, at));
    out.push(
      <mark
        key={`${at}-${match[0]}`}
        className="rounded-sm bg-amber-200/70 px-1 font-mono text-[0.9em] text-ink dark:bg-amber-400/25"
      >
        {match[0]}
      </mark>,
    );
    cursor = at + match[0].length;
  }
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}

function Prose({ text }: { text: string }) {
  return <>{withPlaceholders(text)}</>;
}

/**
 * The reading measure for running prose, independent of the container's width.
 *
 * `ch` rather than `rem`: the constraint is a COUNT OF CHARACTERS — the eye loses the
 * start of the next line somewhere past 75 — and `ch` is the unit that keeps that true
 * when the font or the root size changes. A `rem` cap re-breaks at every type change and
 * has to be re-guessed each time.
 */
const PROSE_MEASURE = "max-w-[68ch]";

/** Running prose: 16px on a phone, 17px from `sm`, at a reading line height. */
const BODY = `text-base leading-7 text-ink-muted sm:text-[17px] sm:leading-[1.8] print:text-black ${PROSE_MEASURE}`;

/**
 * Tables reflow into one block per row, each cell under its column's name, where the
 * columns would otherwise be too narrow to read.
 *
 * A clause-length cell in a 120px column is a ribbon of three-word lines, and a sideways
 * scroll on a phone hides the very columns a reader came for. Below `md` every table
 * reflows; a table of four or more columns (the cookie and sub-processor lists) reflows
 * at every width, because even the widest reading column left one of their columns
 * under 140px of paragraph text.
 * The column name comes from `data-label` through a pseudo-element, so the words in the
 * DOM are still each cell's text once. Each set is written out whole, padding included,
 * because Tailwind only generates class names it can read in the source and two
 * unprefixed utilities for one property resolve by stylesheet order, not class order.
 */
const WIDE_TABLE_COLUMNS = 4;

const REFLOW_BELOW_MD = {
  table: "max-md:block md:min-w-[36rem] max-md:[&_caption]:block",
  head: "max-md:sr-only",
  body: "max-md:block",
  row: "max-md:block max-md:py-2 max-md:first:border-t",
  cell:
    "px-3 py-3 max-md:block max-md:px-0 max-md:py-1.5 max-md:first:pt-2 max-md:first:text-base " +
    "max-md:before:mb-0.5 max-md:before:block max-md:before:text-[13px] max-md:before:font-medium " +
    "max-md:before:text-ink-faint max-md:before:content-[attr(data-label)] max-md:first:before:hidden",
} as const;

const REFLOW_ALWAYS = {
  table: "block [&_caption]:block",
  head: "sr-only",
  body: "block",
  row: "block py-3 first:border-t sm:grid sm:grid-cols-2 sm:gap-x-8 sm:py-4",
  cell:
    "block py-1.5 first:pt-2 first:text-base sm:first:col-span-2 sm:first:text-[17px] " +
    "before:mb-0.5 before:block before:text-[13px] before:font-medium before:text-ink-faint " +
    "before:content-[attr(data-label)] first:before:hidden",
} as const;

function Block({ block }: { block: LegalBlock }) {
  switch (block.kind) {
    case "para":
      return (
        <p className={`mt-4 ${BODY}`}>
          <Prose text={block.text} />
        </p>
      );

    case "list": {
      const className =
        `mt-4 space-y-2.5 pl-6 marker:text-ink-faint ${BODY} ` +
        (block.ordered ? "list-decimal" : "list-disc");
      const items = block.items.map((item) => (
        <li key={item.slice(0, 60)} className="pl-1.5">
          <Prose text={item} />
        </li>
      ));
      return block.ordered ? (
        <ol className={className}>{items}</ol>
      ) : (
        <ul className={className}>{items}</ul>
      );
    }

    case "definitions":
      // A hairline-separated glossary rather than a boxed card per term: a column of
      // identical boxes reads as a feature grid, and these are clauses.
      return (
        <dl className={`mt-5 divide-y divide-line border-y border-line ${PROSE_MEASURE}`}>
          {block.items.map((item) => (
            <div key={item.term} className="py-4">
              <dt className="text-base font-semibold text-ink sm:text-[17px]">
                <Prose text={item.term} />
              </dt>
              <dd className="mt-1 text-base leading-7 text-ink-muted sm:text-[17px] sm:leading-[1.8] print:text-black">
                <Prose text={item.detail} />
              </dd>
            </div>
          ))}
        </dl>
      );

    case "table": {
      const reflow = block.columns.length >= WIDE_TABLE_COLUMNS ? REFLOW_ALWAYS : REFLOW_BELOW_MD;
      return (
        // Focusable, and named from the caption — a scroll container a keyboard cannot
        // reach is content a keyboard cannot read. `ScrollRegion` carries that shape for
        // every scroll container in the product, and the table stays its DIRECT child,
        // which `tests/legal.test.tsx` checks.
        //
        // The explicit table roles are not redundant: a block-reflowed table loses its
        // table semantics in the accessibility tree, and the roles put them back
        // (adrianroselli.com/2018/02/tables-css-display-properties-and-aria.html).
        <ScrollRegion label={block.caption} className="mt-6">
          <table role="table" className={`w-full border-collapse text-left text-sm sm:text-[15px] ${reflow.table}`}>
            <caption className="pb-3 text-left text-sm font-semibold text-ink sm:text-[15px]">
              {block.caption}
            </caption>
            {/* eslint-disable-next-line jsx-a11y/no-redundant-roles -- the reflow removes it */}
            <thead role="rowgroup" className={reflow.head}>
              <tr role="row" className="border-y border-line bg-surface">
                {block.columns.map((column) => (
                  <th
                    key={column}
                    role="columnheader"
                    scope="col"
                    className="px-3 py-2.5 align-top font-semibold text-ink"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            {/* eslint-disable-next-line jsx-a11y/no-redundant-roles -- the reflow removes it */}
            <tbody role="rowgroup" className={reflow.body}>
              {block.rows.map((row) => (
                <tr key={row.join("|").slice(0, 80)} role="row" className={`border-b border-line align-top ${reflow.row}`}>
                  {row.map((cell, index) => (
                    <td
                      key={`${index}-${cell.slice(0, 40)}`}
                      // The plugin reads `td` as a grid cell, which is interactive; in a
                      // static table it is not, and `cell` is its role.
                      // eslint-disable-next-line jsx-a11y/no-interactive-element-to-noninteractive-role
                      role="cell"
                      data-label={block.columns[index]}
                      className={`leading-6 text-ink-muted first:font-medium first:text-ink print:text-black ${reflow.cell}`}
                    >
                      <Prose text={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      );
    }

    case "callout": {
      const warning = block.tone === "warning";
      return (
        <aside
          className={
            `mt-6 rounded-2xl border p-5 sm:p-6 print:border-black/40 ${PROSE_MEASURE} ` +
            (warning
              ? "border-amber-500/40 bg-amber-50/70 dark:bg-amber-400/10"
              : "border-brand/25 bg-brand-soft/50 dark:bg-brand/10")
          }
        >
          {/* The tone in words. Colour is not a signal a screen reader can use, and it is
              not a reliable one on a cheap screen in daylight.

              `text-ink-muted`, not `text-ink-faint`: this label is on a TINTED ground,
              where the faint ink measures below 4.5:1 — and a label whose whole job is to
              carry the meaning colour cannot is the last text that should be dimmest. */}
          <p className="flex items-center gap-2 text-sm font-semibold text-ink-muted">
            <span
              aria-hidden
              className={`h-2 w-2 rounded-full ${warning ? "bg-amber-500" : "bg-brand"}`}
            />
            {warning ? "Important" : "Note"}
          </p>
          <p className="mt-2 text-base font-semibold text-ink sm:text-[17px]">
            <Prose text={block.title} />
          </p>
          <p className="mt-1.5 text-base leading-7 text-ink-muted sm:text-[17px] sm:leading-[1.8] print:text-black">
            <Prose text={block.text} />
          </p>
        </aside>
      );
    }

    default: {
      // Adding a block kind means adding it here AND in `blockText` (index.ts), or the
      // placeholder audit stops reading it. `never` makes that a compile error.
      const unreachable: never = block;
      return unreachable;
    }
  }
}

/**
 * A section, its subsections, and a copy-link control beside each heading.
 *
 * `scroll-mt-*` sits on the element that carries the `id`, because that is the element a
 * fragment scrolls to, and it has to clear the sticky site header.
 */
function Section({ section }: { section: LegalSection }) {
  return (
    <section
      aria-labelledby={section.id}
      className="mt-12 border-t border-line pt-10 first:mt-0 first:border-t-0 first:pt-0 sm:mt-14"
    >
      <div className="group/heading flex items-start gap-2">
        <h2
          id={section.id}
          className="scroll-mt-24 text-[1.375rem] leading-snug font-semibold tracking-tight text-balance text-ink sm:text-[1.625rem] print:break-after-avoid"
        >
          {section.heading}
        </h2>
        <CopyLinkButton id={section.id} heading={section.heading} />
      </div>
      {(section.blocks ?? []).map((block, index) => (
        <Block key={`${section.id}-b${index}`} block={block} />
      ))}
      {(section.subsections ?? []).map((sub) => (
        <div key={sub.id} id={sub.id} className="mt-9 scroll-mt-24">
          <div className="group/heading flex items-start gap-2">
            <h3 className="text-lg leading-snug font-semibold text-balance text-ink sm:text-xl print:break-after-avoid">
              {sub.heading}
            </h3>
            <CopyLinkButton id={sub.id} heading={sub.heading} />
          </div>
          {sub.blocks.map((block, index) => (
            <Block key={`${sub.id}-b${index}`} block={block} />
          ))}
        </div>
      ))}
    </section>
  );
}

/**
 * The contents. The links are rendered HERE, on the server, and handed to
 * `LegalContents`, which adds the phone disclosure and the scroll spy around them.
 *
 * `aria-[current=location]` is the state the scroll spy sets, and `data-active` on a
 * section's row keeps the section's own entry dark while one of its subsections is the
 * current one. Each anchor carries
 * `inline-block py-1` so its target is taller than its line box (WCAG 2.5.8 — measured by
 * `tests/responsive.test.ts`), and `touch:py-2` takes it further on a phone.
 */
function TableOfContents({ doc }: { doc: LegalDocument }) {
  return (
    <LegalContents count={doc.sections.length}>
      <ol className="space-y-0.5 border-l border-line text-sm">
        {doc.sections.map((section) => (
          <li key={section.id} data-toc-section className="group/toc">
            <a
              href={`#${section.id}`}
              className="-ml-px inline-block border-l-2 border-transparent py-1 pr-1 pl-3.5 leading-snug text-ink-muted transition-colors duration-(--duration-fast) ease-out hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong group-data-active/toc:text-ink aria-[current=location]:border-brand-strong aria-[current=location]:font-medium aria-[current=location]:text-ink touch:py-2"
            >
              {section.heading}
            </a>
            {section.subsections && section.subsections.length > 0 && (
              <ul className="mb-1 space-y-0.5">
                {section.subsections.map((sub) => (
                  <li key={sub.id}>
                    <a
                      href={`#${sub.id}`}
                      className="-ml-px inline-block border-l-2 border-transparent py-1 pr-1 pl-7 text-[13px] leading-snug text-ink-muted transition-colors duration-(--duration-fast) ease-out hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong aria-[current=location]:border-brand-strong aria-[current=location]:text-ink touch:py-2"
                    >
                      {sub.heading}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </LegalContents>
  );
}

/**
 * The draft banner. INERT since the set was published on 2 September 2026 — it renders
 * nothing while `PENDING_LEGAL_REVIEW` is false.
 *
 * Kept rather than deleted, and the wording kept with it: a document set can go back into
 * draft (a rewrite waiting on counsel, a new document added before it is settled), and the
 * banner is the thing that must exist before that is possible without somebody inventing
 * new words for it under time pressure. `tests/legal.test.tsx` asserts it is absent from
 * every document today.
 */
export function PendingReviewBanner() {
  if (!PENDING_LEGAL_REVIEW) return null;
  return (
    <aside className="rounded-card border-2 border-dashed border-amber-500 bg-amber-50/70 p-4 dark:bg-amber-400/10">
      {/* `text-ink-muted` on a tinted ground — see the tone label above. */}
      <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
        Draft — not yet in force
      </p>
      <p className="mt-1 text-[15px] font-semibold text-ink">
        {PENDING_LEGAL_REVIEW_MARKER}
      </p>
      <p className="mt-1 text-[15px] leading-7 text-ink-muted">
        These documents were drafted against what the Calevate codebase actually
        does and against Indian law as researched, and they have not been
        reviewed by a lawyer qualified in India. Highlighted tokens are facts
        about the business that have not been decided or established yet. Do not
        rely on this page, and do not present it to a client, a regulator or a
        payment gateway until an advocate has reviewed it and this banner has
        been deliberately removed.
      </p>
    </aside>
  );
}

/** A masthead label: sentence case and small, not a tracked capital eyebrow. */
const META_TERM = "text-sm font-medium text-ink-faint";

/**
 * Hides the shared site header and footer when printing, from inside this page.
 *
 * A `:has()` rule keyed on this page's own wrapper rather than an edit to the shell: the
 * shell is shared by every public page and a printed policy wants the document, not the
 * website around it. Exported for the index page, which prints the same way.
 */
export const PRINT_WITHOUT_CHROME =
  "print:[:root:has(&)_[data-marketing-root]>header]:hidden print:[:root:has(&)_[data-marketing-root]>footer]:hidden";

/** The full page for one document: banner, masthead, contents, body, cross-links. */
export function LegalDocumentPage({ doc }: { doc: LegalDocument }) {
  // The set is published, so every fact in it must carry a value: a blank would render as
  // a literal `{{TOKEN}}` on a page a regulator or a payment gateway reads. Throwing here
  // fails the render — and therefore the build and the suite — long before a reader could
  // see it, which is what makes adding a ninth document with a new blank safe.
  assertLegalSetPublishable();
  const others = LEGAL_DOCUMENTS.filter((other) => other.slug !== doc.slug);
  return (
    // The real site header, not a second one (founder, 9 Sep 2026): a legal document is a
    // public page like any other and gets the public chrome. `MarketingPage` supplies the
    // header, the one `<main>` landmark and the footer, so everything below is a `div`.
    <MarketingPage>
      <div className={PRINT_WITHOUT_CHROME}>
        <div id="top" className="scroll-mt-16 border-b border-line">
          <div className={`${SHELL} pt-8 pb-10 sm:pt-12 sm:pb-14 print:pt-0`}>
            <PendingReviewBanner />

            <nav aria-label="Breadcrumb" className="print:hidden">
              <ol className="flex items-center gap-2 text-sm text-ink-muted">
                <li>
                  <Link
                    href="/legal"
                    className="inline-block rounded-sm py-1 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong touch:py-2.5"
                  >
                    Legal
                  </Link>
                </li>
                <li aria-hidden className="text-ink-faint">
                  /
                </li>
                <li>
                  <span aria-current="page" className="text-ink">
                    {doc.shortTitle}
                  </span>
                </li>
              </ol>
            </nav>

            <h1 className="mt-5 max-w-4xl text-[2.25rem] leading-[1.08] font-semibold tracking-tight text-balance text-ink sm:mt-6 sm:text-5xl sm:leading-[1.05]">
              {doc.title}
            </h1>
            <p className="mt-5 max-w-[68ch] text-lg text-pretty text-ink-muted sm:text-xl print:text-black">
              {doc.summary}
            </p>

            {/* What a reader checks before reading a word: who it binds, since when, and
                which revision. One hairline row rather than three boxes, so it reads as
                the document's masthead and not as a feature grid. */}
            <div className="mt-8 flex flex-col gap-6 border-t border-line pt-6 sm:mt-10 lg:flex-row lg:items-end lg:justify-between">
              <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:gap-x-10">
                <div className="col-span-2 max-w-[52ch] sm:col-span-1">
                  <dt className={META_TERM}>Who it applies to</dt>
                  <dd className="mt-1 text-base leading-7 text-ink">{doc.appliesTo}</dd>
                </div>
                <div>
                  <dt className={META_TERM}>In force from</dt>
                  <dd className="mt-1 text-base leading-7 font-medium whitespace-nowrap text-ink">
                    {/* The shell's own placeholder — declared in CHROME_TOKENS so the audit
                        in tests/legal.test.tsx counts it as used rather than as a dead entry. */}
                    <Prose text={CHROME_TOKENS.join(" ")} />
                  </dd>
                </div>
                {/* THE VERSION IS ON THE PAGE BECAUSE IT IS ON THE CONTRACT. A client's owner
                    accepts this document by version, and `apps/api/legal/` records that
                    version in an append-only ledger; a reader who cannot see which version
                    they are reading cannot tell whether it is the one they agreed to. The
                    string comes from `versions.ts`, which the docs-drift guard holds equal
                    to the API's catalogue — so this cell can never show a version the
                    ledger does not use. */}
                <div>
                  <dt className={META_TERM}>Version</dt>
                  <dd className="mt-1 text-base leading-7 font-medium text-ink tabular-nums">
                    {documentVersionLabel(doc.slug) ?? "Unversioned"}
                  </dd>
                </div>
              </dl>
              <div className="shrink-0 print:hidden">
                <PrintButton className={PILL_LINK} />
              </div>
            </div>
          </div>
        </div>

        {/* THE SHELL WIDENS; THE READING MEASURE DOES NOT. The page uses the site's shell so
            it lines up with the header, and the room beside the text goes to the contents
            rail. Prose keeps `PROSE_MEASURE` (~68ch): past roughly 75 characters a reader
            loses the return sweep, and on these pages a missed line is a missed clause.

            A flex row with a fixed-width rail rather than an arbitrary grid template
            (`grid-cols-[15rem_minmax(0,1fr)]`): that template is a single bespoke class,
            and without it the grid falls back to one column while the rail's own `lg:`
            styles still apply, so the whole contents list spreads across the page above
            the text. Stock width and flex utilities carry no such single point of failure. `min-w-0` on the text column lets a wide
            table scroll inside its region instead of widening the column. */}
        <div
          className={`${SHELL} flex flex-col gap-8 py-10 sm:py-14 lg:flex-row lg:items-start lg:gap-14 xl:gap-20 print:block print:py-6`}
        >
          <div className="lg:sticky lg:top-24 lg:w-60 lg:shrink-0 xl:w-68 print:hidden">
            <TableOfContents doc={doc} />
          </div>

          <div className="min-w-0 flex-1">
            {doc.sections.map((section) => (
              <Section key={section.id} section={section} />
            ))}

            <nav
              aria-label="Other legal documents"
              className="mt-16 border-t border-line pt-8 print:hidden"
            >
              <h2 className="text-lg font-semibold text-ink">Other legal documents</h2>
              <ul className="mt-4 grid gap-x-8 gap-y-1 text-[15px] sm:grid-cols-2 xl:grid-cols-3">
                {others.map((other) => (
                  <li key={other.slug}>
                    <Link
                      href={`/legal/${other.slug}`}
                      className="inline-block py-1 text-ink underline decoration-line underline-offset-4 hover:decoration-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong touch:py-2.5"
                    >
                      {other.shortTitle}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </div>
        </div>

        <BackToTop />
      </div>
    </MarketingPage>
  );
}
