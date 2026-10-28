import { readFileSync } from "node:fs";
import { join } from "node:path";

import ts from "typescript";

import { WEB_ROOT, copyIn, tsSources, type CopyScanOptions, type CopyString } from "./copyScan";

/**
 * BUTTONS, NOT PARAGRAPHS — the one rule every "short default copy" guard applies.
 *
 * Our clients are small-business owners, often on a 375px phone, often reading English as
 * a second language. About 60 characters (8 words) is one line there; a longer line of
 * default copy wraps to three or four, which is where they stop reading. A longer reason
 * belongs behind a tap (`Why`, an ⓘ, a disclosure), so the guards measure only what is
 * shown without one.
 *
 * Each area guard names its own roots and its own idea of "behind a tap" ({@link Hidden}),
 * so folding them onto this module weakens none of them: what was hidden for one area is
 * not silently hidden for another. The walk itself is `copyScan`'s, so a comment, a class
 * list or a wire value is never measured.
 */
export const SHORT_LINE = 60;

/** Where a file's copy is shown only after a tap, or never to a person. */
export interface Hidden {
  /** Elements whose CHILDREN open on a tap; their own props (a disclosure's title) count. */
  readonly elements?: ReadonlySet<string>;
  /** Self-closing elements whose props are all behind a tap (`<HowItWorks … />`). */
  readonly closedElements?: ReadonlySet<string>;
  /** JSX attributes that are a tooltip, a screen-reader name or a tap's contents. */
  readonly attrs?: RegExp;
  /** Object properties that are a tap's contents or never shown. */
  readonly props?: ReadonlySet<string>;
  /** Calls that speak to the assistant, not a person (`useCopilotSurface`). */
  readonly calls?: ReadonlySet<string>;
  /** Components, by function name, that only ever render behind a tap. */
  readonly functions?: ReadonlySet<string>;
  /** Constants, by name, that are never shown by default. */
  readonly constants?: RegExp;
}

/** What a JSX entity reads as, so `can&apos;t` counts as five characters, not ten. */
export function decoded(text: string): string {
  return text
    .replace(/&(apos|rsquo|lsquo);/g, "'")
    .replace(/&(quot|ldquo|rdquo);/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/&nbsp;/g, " ");
}

/** A string as a reader meets it: entities decoded, whitespace collapsed. */
export function shown(text: string): string {
  return decoded(text).replace(/\s+/g, " ").trim();
}

/**
 * A Tailwind class list the wide walk picked up (a `className` ternary is not followed by
 * its attribute filter): lower-case tokens, at least half with a `-`, `:`, `[` or `/`.
 */
export function isClassList(text: string): boolean {
  const tokens = text.trim().split(/\s+/);
  if (tokens.some((token) => !/^[!-]?[a-z0-9@[(]/.test(token))) return false;
  if (tokens.some((token) => !/^[a-z0-9:\-[\]/.()&*>%#=_!@,'"+]+$/.test(token))) return false;
  return tokens.filter((token) => /[-:[/]/.test(token)).length * 2 >= tokens.length;
}

type Range = readonly [number, number];

/** The character ranges of one file a person does not see by default. */
function hiddenRanges(file: string, hidden: Hidden): Range[] {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const ranges: Range[] = [];
  const whole = (node: ts.Node) => ranges.push([node.getStart(), node.getEnd()]);
  const visit = (node: ts.Node): void => {
    if (ts.isJsxElement(node)) {
      const tag = node.openingElement.tagName.getText();
      if (hidden.elements?.has(tag)) ranges.push([node.openingElement.end, node.closingElement.pos]);
      if (hidden.calls?.has(tag)) whole(node);
    }
    if (ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText();
      if (hidden.closedElements?.has(tag) || hidden.calls?.has(tag)) whole(node);
    }
    if (ts.isJsxAttribute(node) && hidden.attrs?.test(node.name.getText())) whole(node);
    // A property, or a destructured prop's default (`why = "…"`), is the same copy either way.
    if (
      (ts.isPropertyAssignment(node) || ts.isBindingElement(node)) &&
      (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) &&
      hidden.props?.has(node.name.text)
    ) {
      whole(node);
    }
    if (ts.isCallExpression(node) && hidden.calls?.has(node.expression.getText())) whole(node);
    if (ts.isFunctionDeclaration(node) && node.name && hidden.functions?.has(node.name.text)) whole(node);
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && hidden.constants?.test(node.name.text)) {
      whole(node);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return ranges;
}

/** Every string one file shows by default, as a reader meets it. */
export function defaultCopyIn(
  file: string,
  hidden: Hidden = {},
  options: CopyScanOptions = { wide: true, chains: true },
): CopyString[] {
  const ranges = hiddenRanges(file, hidden);
  return copyIn(file, options)
    .filter((copy) => !ranges.some(([from, to]) => copy.start >= from && copy.start < to))
    .map((copy) => ({ ...copy, text: shown(copy.text) }))
    .filter((copy) => copy.text.length > 0 && !isClassList(copy.text));
}

/** Every default string under a set of roots (directories or files under `apps/web`). */
export function defaultCopyUnder(
  roots: readonly string[],
  hidden: Hidden = {},
  options?: CopyScanOptions,
  skip: readonly string[] = [],
): CopyString[] {
  return roots.flatMap((root) =>
    tsSources(join(WEB_ROOT, root))
      .flatMap((file) => defaultCopyIn(file, hidden, options))
      .filter((copy) => !skip.some((prefix) => copy.file.startsWith(prefix))),
  );
}

/** The default lines longer than {@link SHORT_LINE}, as `file:line (length) text`. */
export function longLines(copy: readonly CopyString[], kept: (text: string) => boolean = () => false): string[] {
  return copy
    .filter((c) => c.text.length > SHORT_LINE && !kept(c.text))
    .map((c) => `${c.file}:${c.line} (${c.text.length}) ${c.text}`);
}
