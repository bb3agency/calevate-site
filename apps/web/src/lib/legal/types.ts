/**
 * The shape of a public legal document, and the ONE place its text lives.
 *
 * ## Why a typed content module rather than MDX or a markdown file in `docs/`
 *
 * These documents have to exist in exactly one place. The obvious wrong shape — prose in
 * `docs/legal/*.md`, pasted into a React component — is two copies of a legally operative
 * text that will disagree the first time one of them is edited, which is the defect
 * CLAUDE.md's "one way per problem" exists to prevent. Three mechanisms were weighed:
 *
 * - **MDX** (`@next/mdx`, `remark`, `rehype`) — the conventional answer, and it costs
 *   four new packages plus a `next.config.ts` change for content that is structurally
 *   simple (headings, paragraphs, lists, three tables). Hard rule 9 governs exactly this
 *   trade, and this repo already declined `@vitejs/plugin-react` and
 *   `@testing-library/jest-dom` on the same grounds.
 * - **Markdown in `docs/legal/`, read at build time** — keeps the text where a lawyer
 *   would look for it, and needs a markdown parser (a dependency) plus a filesystem read
 *   that reaches outside `apps/web`. It also makes the text untypeable: nothing could
 *   assert that every document carries a grievance contact.
 * - **A typed content module** — taken. Zero new dependencies, the structure is checked
 *   by `tsc`, one renderer means one heading hierarchy and one set of anchors for all
 *   eight documents, and the rules that matter legally (every placeholder is declared,
 *   the pending-review banner is present, no document is missing its contact section)
 *   are assertable in `tests/legal.test.tsx` rather than reviewed by eye.
 *
 * `docs/legal/README.md` points here. It deliberately contains no prose from these
 * documents.
 *
 * ## The block vocabulary is deliberately small
 *
 * Five block kinds, no inline markup, no HTML strings. A legal document that can express
 * arbitrary markup is a document whose accessibility and dark-mode behaviour is decided
 * per paragraph by whoever wrote it. The one piece of inline structure that is genuinely
 * needed — a `{{PLACEHOLDER}}` the founder must fill — is a token in plain text that the
 * renderer finds and marks up itself, so it looks the same in all eight documents and a
 * test can enumerate every one of them.
 */

/** A single addressable unit of prose inside a section. */
export type LegalBlock =
  | { readonly kind: "para"; readonly text: string }
  | { readonly kind: "list"; readonly ordered?: boolean; readonly items: readonly string[] }
  | {
      readonly kind: "definitions";
      readonly items: readonly { readonly term: string; readonly detail: string }[];
    }
  | {
      readonly kind: "table";
      /** Names the table for a screen reader and for a reader skimming the page. */
      readonly caption: string;
      readonly columns: readonly string[];
      readonly rows: readonly (readonly string[])[];
    }
  | {
      readonly kind: "callout";
      /**
       * `note` is context. `warning` is a statement of a limit or an unresolved
       * question — the places where an honest document declines to claim something.
       */
      readonly tone: "note" | "warning";
      readonly title: string;
      readonly text: string;
    };

/** A `<h3>`-level division of a section. */
export interface LegalSubsection {
  /** URL fragment, unique within the document. Stable: it is a citable anchor. */
  readonly id: string;
  readonly heading: string;
  readonly blocks: readonly LegalBlock[];
}

/** A `<h2>`-level division of a document. Numbered for citation ("Privacy §7.2"). */
export interface LegalSection {
  readonly id: string;
  readonly heading: string;
  readonly blocks?: readonly LegalBlock[];
  readonly subsections?: readonly LegalSubsection[];
}

/** One published document. */
export interface LegalDocument {
  /** The URL segment under `/legal/`. */
  readonly slug: string;
  /** `<h1>` and the `<title>`. */
  readonly title: string;
  /** How the document is listed on `/legal` and in the cross-links. */
  readonly shortTitle: string;
  /** One sentence: what this document is for and who it binds. */
  readonly summary: string;
  /**
   * Who the document speaks to. Rendered under the title, because the single most
   * common mistake a reader makes on a page like this is assuming it is about them.
   */
  readonly appliesTo: string;
  readonly sections: readonly LegalSection[];
}
