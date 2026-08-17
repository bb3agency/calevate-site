import { ACCEPTABLE_USE } from "./acceptableUse";
import { COOKIE_NOTICE } from "./cookies";
import { DPA } from "./dpa";
import { GRIEVANCE } from "./grievance";
import { PRIVACY_POLICY } from "./privacy";
import { REFUND_POLICY } from "./refunds";
import { SUBPROCESSORS } from "./subprocessors";
import { TERMS_OF_SERVICE } from "./terms";
import type { LegalBlock, LegalDocument } from "./types";

export type { LegalBlock, LegalDocument, LegalSection, LegalSubsection } from "./types";
export {
  PENDING_LEGAL_REVIEW,
  PENDING_LEGAL_REVIEW_MARKER,
  PLACEHOLDERS,
  PLACEHOLDER_PATTERN,
  placeholdersIn,
} from "./placeholders";

/**
 * Every published legal document, in the order they are listed on `/legal`.
 *
 * The order is not alphabetical and is not arbitrary: a reader arriving cold needs the
 * privacy notice first, then the two agreements that bind them, then the operational
 * documents they will look up when something specific happens. `slug` is the URL segment
 * and is stable — these pages get linked from contracts and from a payment gateway's
 * merchant record, so a slug is a promise.
 */
export const LEGAL_DOCUMENTS: readonly LegalDocument[] = [
  PRIVACY_POLICY,
  TERMS_OF_SERVICE,
  ACCEPTABLE_USE,
  DPA,
  SUBPROCESSORS,
  REFUND_POLICY,
  GRIEVANCE,
  COOKIE_NOTICE,
];

/**
 * Resolve a URL segment to a document.
 *
 * A linear scan rather than an object keyed by slug, deliberately: a keyed record read
 * with a value that came off the URL is exactly the prototype-chain hazard
 * `src/lib/lookup.ts` documents and the ESLint config bans — `"constructor"` would
 * resolve to the `Object` function. Eight documents make the scan free, and the shape
 * cannot be wrong.
 */
export function legalDocument(slug: string): LegalDocument | undefined {
  return LEGAL_DOCUMENTS.find((doc) => doc.slug === slug);
}

/** Every block in a document, flattened — sections first, then their subsections. */
export function blocksOf(doc: LegalDocument): LegalBlock[] {
  return doc.sections.flatMap((section) => [
    ...(section.blocks ?? []),
    ...(section.subsections ?? []).flatMap((sub) => sub.blocks),
  ]);
}

/**
 * All the prose in a document as one string — headings, paragraphs, list items, table
 * cells, definitions and callouts.
 *
 * Used by the placeholder audit in `tests/legal.test.tsx`. It has to reach EVERY string,
 * because a placeholder hiding in a table cell that the audit does not read is a fact the
 * founder is never told to fill in — so this walks the union exhaustively and TypeScript's
 * `never` check at the end fails the build if a new block kind is added without extending
 * it.
 */
export function textOf(doc: LegalDocument): string {
  const parts: string[] = [doc.title, doc.summary, doc.appliesTo];
  for (const section of doc.sections) {
    parts.push(section.heading);
    for (const block of section.blocks ?? []) parts.push(blockText(block));
    for (const sub of section.subsections ?? []) {
      parts.push(sub.heading);
      for (const block of sub.blocks) parts.push(blockText(block));
    }
  }
  return parts.join("\n");
}

function blockText(block: LegalBlock): string {
  switch (block.kind) {
    case "para":
      return block.text;
    case "list":
      return block.items.join("\n");
    case "definitions":
      return block.items.map((item) => `${item.term}\n${item.detail}`).join("\n");
    case "table":
      return [block.caption, ...block.columns, ...block.rows.flat()].join("\n");
    case "callout":
      return `${block.title}\n${block.text}`;
    default: {
      // A new block kind must be handled here as well as in the renderer, or the
      // placeholder audit silently stops reading it.
      const unreachable: never = block;
      return unreachable;
    }
  }
}
