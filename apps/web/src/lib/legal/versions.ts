/**
 * The VERSION of each published document — the browser's copy of a fact the server owns.
 *
 * ## Why this file exists rather than a `version` field on `LegalDocument`
 *
 * A version here is not decoration: `apps/api/legal/` records it in an append-only
 * ledger every time an owner accepts a document, and every outbound gate compares a
 * stored row against the current one to decide whether the account may dial. So the
 * SOURCE OF TRUTH is `apps/api/legal/catalogue.py` — it is read by Postgres-side code on
 * a machine that never runs Node — and this module is the mirror the browser needs.
 * `scripts/check_docs_drift.py` fails CI when the two disagree, which is the same
 * mechanism §4b uses for the TTS rate card and for the same reason: a mirror nothing
 * checks is a mirror that is wrong the first time one side moves.
 *
 * It is a separate module rather than three more fields on `LegalDocument` so the drift
 * check has one small file to parse instead of eight prose modules, and so that editing a
 * document's TEXT and editing its VERSION are visibly different acts in a diff.
 *
 * ## The version carries the review state
 *
 * While `PENDING_LEGAL_REVIEW` (in `placeholders.ts`) stood, every document's current
 * version was `<revision>+pre-review`. It was turned off on 2 September 2026 when the set
 * was published, so every version changed, every acceptance recorded against a
 * `+pre-review` version stopped being current, and the server asked every client to
 * accept again. Nothing special-cased the flip — it falls out of the version string — but
 * it did need the same edit on both sides of the mirror, and the drift check names the
 * side that was missed.
 *
 * ## Adding a revision
 *
 * An edit to a document's OPERATIVE TEXT is a new entry in that document's `revisions`,
 * here AND in `catalogue.py`. `material: true` when somebody who accepted the previous
 * revision must accept again; `material: false` for a correction that changes nothing
 * anybody agreed to. The API decides what each flag DOES; this file only has to say the
 * same thing the API says.
 */

import { lookup } from "@/lib/lookup";

import { PENDING_LEGAL_REVIEW } from "./placeholders";

/** The suffix a version carries while the documents are still pre-legal-review. */
export const PRE_REVIEW_SUFFIX = "+pre-review";

/** One authored revision. `material` describes the STEP INTO it, not the document. */
export interface LegalRevision {
  readonly revision: string;
  readonly material: boolean;
}

/** What the mirror holds for one document. */
export interface LegalVersionEntry {
  /** Mirrors the document's own `shortTitle`, and the API's `LegalDocumentSpec.title`. */
  readonly title: string;
  /** Does an unaccepted copy of this document stop the account operating? */
  readonly blocking: boolean;
  /** Oldest first; the last entry is current. */
  readonly revisions: readonly LegalRevision[];
  /**
   * The date the document starts binding, ISO-8601, or null while it has none.
   *
   * 2 September 2026 everywhere: the day the set was published. The prose spelling of
   * the same day is the `{{EFFECTIVE_DATE}}` placeholder, which the page header renders
   * under "In force from"; this is the machine form, and `catalogue.py` carries the same
   * string or CI says so.
   */
  readonly effectiveDate: string | null;
}

export const LEGAL_VERSIONS: Readonly<Record<string, LegalVersionEntry>> = {
  privacy: {
    title: "Privacy Policy",
    blocking: true,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: true },
      { revision: "3", material: true },
      { revision: "4", material: false },
    ],
    effectiveDate: "2026-09-02",
  },
  terms: {
    title: "Terms of Service",
    blocking: true,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: true },
      { revision: "3", material: true },
      { revision: "4", material: false },
    ],
    effectiveDate: "2026-09-02",
  },
  "acceptable-use": {
    title: "Acceptable Use",
    blocking: true,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: false },
    ],
    effectiveDate: "2026-09-02",
  },
  dpa: {
    title: "Data Processing Addendum",
    blocking: true,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: true },
      { revision: "3", material: true },
      { revision: "4", material: false },
    ],
    effectiveDate: "2026-09-02",
  },
  subprocessors: {
    title: "Sub-processors",
    blocking: false,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: true },
      { revision: "3", material: true },
    ],
    effectiveDate: "2026-09-02",
  },
  refunds: {
    title: "Refunds & Cancellation",
    blocking: false,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: false },
    ],
    effectiveDate: "2026-09-02",
  },
  grievance: {
    title: "Grievance Redressal",
    blocking: false,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: false },
    ],
    effectiveDate: "2026-09-02",
  },
  cookies: {
    title: "Cookies & Tracking",
    blocking: false,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: false },
    ],
    effectiveDate: "2026-09-02",
  },
};

/**
 * The version string a reader of `/legal/<slug>` is looking at, or null for a slug the
 * mirror does not carry.
 *
 * `lookup` rather than an index, for the reason `legalDocument` gives: the argument comes
 * off a URL, and a keyed read with such a value is the prototype hazard `lib/lookup.ts`
 * exists to refuse.
 */
export function documentVersion(slug: string): string | null {
  const entry = lookup(LEGAL_VERSIONS, slug);
  if (entry === undefined || entry.revisions.length === 0) return null;
  const revision = entry.revisions[entry.revisions.length - 1].revision;
  return PENDING_LEGAL_REVIEW ? `${revision}${PRE_REVIEW_SUFFIX}` : revision;
}

/** How the version is shown to a reader — the string, plus what the suffix means. */
export function documentVersionLabel(slug: string): string | null {
  const version = documentVersion(slug);
  if (version === null) return null;
  return PENDING_LEGAL_REVIEW ? `${version} (draft, not yet reviewed)` : version;
}
