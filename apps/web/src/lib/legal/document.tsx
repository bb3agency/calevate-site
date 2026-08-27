import Link from "next/link";
import type { ReactNode } from "react";

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
 * ## Accessibility decisions worth stating
 *
 * - **Heading levels are structural, not visual.** `h1` is the document, `h2` is a
 *   numbered section, `h3` is a subsection. Nothing skips a level, and size is a class
 *   rather than a tag.
 * - **The table of contents is a `nav` with a name.** These documents are long; a
 *   screen-reader or keyboard user who cannot jump to clause 14 has to read to it.
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

function Block({ block }: { block: LegalBlock }) {
  switch (block.kind) {
    case "para":
      return (
        <p className={`mt-4 text-[15px] leading-7 text-ink-muted ${PROSE_MEASURE}`}>
          <Prose text={block.text} />
        </p>
      );

    case "list": {
      const className =
        `mt-4 space-y-2 pl-5 text-[15px] leading-7 text-ink-muted ${PROSE_MEASURE} ` +
        (block.ordered ? "list-decimal" : "list-disc");
      const items = block.items.map((item) => (
        <li key={item.slice(0, 60)} className="pl-1">
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
      return (
        <dl className="mt-4 space-y-4">
          {block.items.map((item) => (
            <div
              key={item.term}
              className="rounded-card border border-line bg-surface p-4"
            >
              <dt className="text-[15px] font-semibold text-ink">
                <Prose text={item.term} />
              </dt>
              <dd className="mt-1 text-[15px] leading-7 text-ink-muted">
                <Prose text={item.detail} />
              </dd>
            </div>
          ))}
        </dl>
      );

    case "table":
      return (
        // Focusable, and named from the caption — a scroll container a keyboard cannot
        // reach is content a keyboard cannot read. This used to be the ONE place in the
        // product that got that right, arguing the case inline; the argument (and the
        // lint waiver) now live in `ScrollRegion`, which the other seventeen containers
        // were moved onto in the same change. This site moved too rather than keeping a
        // second copy of the shape.
        <ScrollRegion label={block.caption} className="mt-4 -mx-4 px-4 sm:mx-0 sm:px-0">
          <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
            <caption className="pb-3 text-left text-sm font-semibold text-ink">
              {block.caption}
            </caption>
            <thead>
              <tr className="border-b border-line">
                {block.columns.map((column) => (
                  <th
                    key={column}
                    scope="col"
                    className="py-2 pr-4 align-top font-semibold text-ink"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row) => (
                <tr key={row.join("|").slice(0, 80)} className="border-b border-line align-top">
                  {row.map((cell, index) => (
                    <td
                      key={`${index}-${cell.slice(0, 40)}`}
                      className="py-3 pr-4 leading-6 text-ink-muted"
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

    case "callout": {
      const warning = block.tone === "warning";
      return (
        <aside
          className={
            "mt-5 rounded-card border-l-4 p-4 " +
            (warning
              ? "border-l-amber-500 border-y border-r border-line bg-amber-50/60 dark:bg-amber-400/10"
              : "border-l-brand border-y border-r border-line bg-brand-soft/60 dark:bg-brand/10")
          }
        >
          {/* The tone in words. Colour is not a signal a screen reader can use, and it is
              not a reliable one on a cheap screen in daylight.

              `text-ink-muted`, not `text-ink-faint`: this label is on a TINTED ground
              (`bg-amber-50/60` / `bg-brand-soft/60`), where the faint ink measures below
              4.5:1 even after the palette was raised — axe in a real browser was still
              reporting it here when every other document had gone clean. And a label
              whose whole job is to carry the meaning that colour cannot is the last text
              on the page that should be the dimmest. */}
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            {warning ? "Important" : "Note"}
          </p>
          <p className="mt-1 text-[15px] font-semibold text-ink">
            <Prose text={block.title} />
          </p>
          <p className="mt-1 text-[15px] leading-7 text-ink-muted">
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

function Section({ section }: { section: LegalSection }) {
  return (
    <section aria-labelledby={section.id} className="mt-12 scroll-mt-20 first:mt-8">
      <h2 id={section.id} className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">
        {section.heading}
      </h2>
      {(section.blocks ?? []).map((block, index) => (
        <Block key={`${section.id}-b${index}`} block={block} />
      ))}
      {(section.subsections ?? []).map((sub) => (
        <div key={sub.id} id={sub.id} className="mt-8 scroll-mt-20">
          <h3 className="text-[17px] font-semibold text-ink">{sub.heading}</h3>
          {sub.blocks.map((block, index) => (
            <Block key={`${sub.id}-b${index}`} block={block} />
          ))}
        </div>
      ))}
    </section>
  );
}

function TableOfContents({ doc }: { doc: LegalDocument }) {
  return (
    <nav
      aria-label="On this page"
      className="mt-8 rounded-card border border-line bg-surface p-5"
    >
      <h2 className="text-[13px] font-semibold uppercase tracking-wider text-ink-faint">
        On this page
      </h2>
      <ol className="mt-3 space-y-2 text-sm">
        {doc.sections.map((section) => (
          <li key={section.id}>
            <a
              href={`#${section.id}`}
              className="inline-block py-1 text-ink underline decoration-line underline-offset-4 hover:decoration-brand"
            >
              {section.heading}
            </a>
            {section.subsections && section.subsections.length > 0 && (
              <ul className="mt-1.5 space-y-1.5 pl-4 text-ink-muted">
                {section.subsections.map((sub) => (
                  <li key={sub.id}>
                    <a
                      href={`#${sub.id}`}
                      className="inline-block py-1 underline decoration-line underline-offset-4 hover:decoration-brand"
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
    </nav>
  );
}

/** The banner that must be deliberately removed before publication. */
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
        These documents were drafted against what the Calevate codebase actually does and
        against Indian law as researched, and they have not been reviewed by a lawyer
        qualified in India. Highlighted tokens are facts about the business that have not
        been decided or established yet. Do not rely on this page, and do not present it
        to a client, a regulator or a payment gateway until an advocate has reviewed it
        and this banner has been deliberately removed.
      </p>
    </aside>
  );
}

/** The full page for one document: banner, title, contents, body, cross-links. */
export function LegalDocumentPage({ doc }: { doc: LegalDocument }) {
  // Publishing (deleting the pending-review banner) with facts still blank would put
  // `{{GSTIN}}` in front of a regulator. Throwing here fails the render — and therefore
  // the build and the suite — long before a reader could see it.
  assertLegalSetPublishable();
  const others = LEGAL_DOCUMENTS.filter((other) => other.slug !== doc.slug);
  return (
    <div className="bg-app">
      <header className="border-b border-line bg-surface/85">
        <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 lg:max-w-5xl xl:max-w-6xl 2xl:max-w-[88rem] flex items-center justify-between gap-4 py-4">
          <Link href="/" className="text-sm font-semibold text-ink">
            Calevate
          </Link>
          <Link
            href="/legal"
            className="text-sm text-ink-muted underline decoration-line underline-offset-4 hover:decoration-brand"
          >
            All legal documents
          </Link>
        </div>
      </header>

      {/* THE SHELL WIDENS; THE READING MEASURE DOES NOT. `max-w-3xl` everywhere left a
          768px column centred in a 2000px window with 600px of nothing on each side —
          on the one set of pages a reader is most likely to open maximised, because
          they are reading rather than filling something in.

          The fix is NOT to let the prose run the full width. A line of body text past
          roughly 75 characters costs the reader the return sweep, and these are the
          documents where a missed line is a missed clause. So the SHELL takes the
          screen and each paragraph keeps `PROSE_MEASURE` (~68ch); what actually uses
          the new room is the metadata row, the tables and the cross-links — the
          elements that were being squeezed, not the ones that were comfortable. */}
      <main className="mx-auto w-full max-w-3xl px-4 sm:px-6 lg:max-w-5xl xl:max-w-6xl 2xl:max-w-[88rem] py-10">
        <PendingReviewBanner />

        <h1 className="mt-8 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          {doc.title}
        </h1>
        <p className={`mt-3 text-[15px] leading-7 text-ink-muted ${PROSE_MEASURE}`}>{doc.summary}</p>

        <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-3">
          <div className="rounded-card border border-line bg-surface p-4">
            <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
              Who it applies to
            </dt>
            <dd className="mt-1 leading-6 text-ink-muted">{doc.appliesTo}</dd>
          </div>
          <div className="rounded-card border border-line bg-surface p-4">
            <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
              In force from
            </dt>
            <dd className="mt-1 leading-6 text-ink-muted">
              {/* The shell's own placeholder — declared in CHROME_TOKENS so the audit in
                  tests/legal.test.tsx counts it as used rather than as a dead entry. */}
              <Prose text={CHROME_TOKENS.join(" ")} />
            </dd>
          </div>
          {/* THE VERSION IS ON THE PAGE BECAUSE IT IS ON THE CONTRACT. A client's owner
              accepts this document by version, and `apps/api/legal/` records that version
              in an append-only ledger; a reader who cannot see which version they are
              reading cannot tell whether it is the one they agreed to. The string comes
              from `versions.ts`, which the docs-drift guard holds equal to the API's
              catalogue — so this cell can never show a version the ledger does not use. */}
          <div className="rounded-card border border-line bg-surface p-4">
            <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
              Version
            </dt>
            <dd className="mt-1 leading-6 text-ink-muted">
              {documentVersionLabel(doc.slug) ?? "Unversioned"}
            </dd>
          </div>
        </dl>

        <TableOfContents doc={doc} />

        {doc.sections.map((section) => (
          <Section key={section.id} section={section} />
        ))}

        <nav aria-label="Other legal documents" className="mt-14 border-t border-line pt-6">
          <h2 className="text-[13px] font-semibold uppercase tracking-wider text-ink-faint">
            Other legal documents
          </h2>
          <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            {others.map((other) => (
              <li key={other.slug}>
                <Link
                  href={`/legal/${other.slug}`}
                  className="inline-block py-1 text-ink underline decoration-line underline-offset-4 hover:decoration-brand"
                >
                  {other.shortTitle}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </main>

      <footer className="border-t border-line px-4 py-8 sm:px-6">
        <p className="mx-auto w-full max-w-3xl px-4 sm:px-6 lg:max-w-5xl xl:max-w-6xl 2xl:max-w-[88rem] text-xs text-ink-faint">
          Calevate — AI phone agents for Indian businesses.
        </p>
      </footer>
    </div>
  );
}
