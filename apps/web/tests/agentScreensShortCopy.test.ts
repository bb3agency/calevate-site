import { readFileSync } from "node:fs";
import { join } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { JOBS } from "@/app/c/[slug]/agents/actions/jobs";

import { WEB_ROOT } from "./copyScan";

/**
 * BUTTONS, NOT PARAGRAPHS — on the agent list, one agent's tabs (all but Training) and the
 * script editor, no line a person reads by default runs past about one phone line.
 *
 * The readers are small-business owners and staff, often on a phone and often reading
 * English as a second language. A line longer than {@link MAX} characters wraps to three or
 * four lines at 375px, which is where they stop reading. Longer reasoning still has a home:
 * behind a tap (an ⓘ, a "How it works", a disclosure), which this guard deliberately skips.
 *
 * What counts as "read by default": JSX text and every string literal that reads as prose
 * (three or more words), wherever it is, minus:
 *  - the inside of an `InfoTip`, `Disclosure`, `HowItWorks` or `<details>`, and an `info`
 *    prop or property — those are opened by a tap;
 *  - `title` and `aria-*` attributes — a hover tooltip or a screen-reader name;
 *  - what the screen tells the assistant (`useCopilotSurface`, `CopilotSurfaceScope`), which
 *    no person sees;
 *  - class lists.
 * Words that come from the server (headlines, reasons) are not in the source and are not
 * judged here.
 */
const MAX = 60;

const ROOT = "src/app/c/[slug]/agents";

/** The files this pass rewrote, so a new long line in them fails here. */
const FILES = [
  "page.tsx",
  "Roster.tsx",
  "LaneGuide.tsx",
  "AgentBadge.tsx",
  "AgentReadiness.tsx",
  "AgentLifecycle.tsx",
  "AgentIdentity.tsx",
  "AgentModel.tsx",
  "[agentId]/AgentWorkspace.tsx",
  "[agentId]/sections/agentHeader.tsx",
  "[agentId]/sections/overview.tsx",
  "[agentId]/sections/settingsTab.tsx",
  "[agentId]/sections/deliverySections.tsx",
  "panels/publishing.tsx",
  "panels/openingNotices.tsx",
  "panels/delivery.tsx",
  "panels/voiceTuning.tsx",
  "panels/callHandling.tsx",
  "panels/callerContinuity.tsx",
  "panels/callerScreen.tsx",
  "panels/handover.tsx",
  "panels/teamAlerts.tsx",
  "panels/extraction.tsx",
  "panels/extractionRow.tsx",
  "actions/Actions.tsx",
  "actions/ToolRow.tsx",
  "actions/ToolDetail.tsx",
  "actions/BookingJob.tsx",
  "[agentId]/script/ScriptBuilder.tsx",
  "[agentId]/script/ScriptSections.tsx",
  "[agentId]/script/SectionEditor.tsx",
  "[agentId]/script/HandWritten.tsx",
  "[agentId]/script/PipAsk.tsx",
  "[agentId]/script/PipProposal.tsx",
  "[agentId]/script/ProposalReview.tsx",
  "[agentId]/script/ScriptHistory.tsx",
  "[agentId]/script/PutLive.tsx",
  "[agentId]/script/ScriptToolbar.tsx",
  "[agentId]/script/SmallSteps.tsx",
  "[agentId]/script/TaughtRules.tsx",
] as const;

/** Elements whose children are shown only after a tap. */
const BEHIND_A_TAP = new Set(["InfoTip", "Disclosure", "HowItWorks", "details", "Popover"]);
/** Attributes and properties nobody reads by default. */
const UNREAD_ATTRS = /^(info|title|aria-[a-z]+|className|href|id|key|prompt|data-[a-z-]+)$/;
const UNREAD_PROPS = new Set(["info", "facts", "prompt", "why"]);
/** Calls and elements that speak to the assistant, not to a person. */
const ASSISTANT_ONLY = new Set(["useCopilotSurface", "CopilotSurfaceScope"]);
/** Constants that are a request sent to the assistant, never shown. */
const UNREAD_CONSTS = /_REQUEST$/;
/** Components that render only inside a disclosure their caller draws. */
const RENDERED_BEHIND_A_TAP = new Set(["NoticeDetails"]);

/** What a JSX entity reads as, so `can&apos;t` counts as five characters, not ten. */
function decoded(text: string): string {
  return text
    .replace(/&(apos|rsquo|lsquo);/g, "'")
    .replace(/&(quot|ldquo|rdquo);/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/&nbsp;/g, " ");
}

function tagName(node: ts.JsxOpeningLikeElement): string {
  return node.tagName.getText();
}

function unread(node: ts.Node): boolean {
  for (let up: ts.Node | undefined = node.parent; up; up = up.parent) {
    if (ts.isJsxElement(up) && BEHIND_A_TAP.has(tagName(up.openingElement))) {
      // The element's own props (a Disclosure's title) are on screen; its children are not.
      const inChildren = node.pos >= up.openingElement.end && node.end <= up.closingElement.pos;
      if (inChildren) return true;
    }
    if (ts.isJsxSelfClosingElement(up) && (tagName(up) === "HowItWorks" || tagName(up) === "InfoTip")) return true;
    if ((ts.isJsxElement(up) || ts.isJsxSelfClosingElement(up)) && ASSISTANT_ONLY.has(tagName(ts.isJsxElement(up) ? up.openingElement : up))) {
      return true;
    }
    if (ts.isJsxAttribute(up) && UNREAD_ATTRS.test(up.name.getText())) return true;
    if (ts.isPropertyAssignment(up) && ts.isIdentifier(up.name) && UNREAD_PROPS.has(up.name.text)) return true;
    if (ts.isCallExpression(up) && ASSISTANT_ONLY.has(up.expression.getText())) return true;
    if (ts.isVariableDeclaration(up) && ts.isIdentifier(up.name) && UNREAD_CONSTS.test(up.name.text)) return true;
    if (ts.isFunctionDeclaration(up) && up.name && RENDERED_BEHIND_A_TAP.has(up.name.text)) return true;
    if (ts.isImportDeclaration(up) || ts.isThrowStatement(up)) return true;
  }
  return false;
}

function readsAsProse(text: string): boolean {
  return text.trim().split(/\s+/).filter((word) => /[A-Za-z]/.test(word)).length >= 3;
}

/** A Tailwind class list: lower-case tokens, most of them with `-`, `:` or `[`. */
function classLike(text: string): boolean {
  const tokens = text.trim().split(/\s+/);
  if (tokens.some((token) => !/^[!-]?[a-z0-9@[(]/.test(token))) return false;
  return tokens.filter((token) => /[-:[/]/.test(token)).length * 2 >= tokens.length;
}

interface Line {
  where: string;
  text: string;
}

function longLines(relative: string): Line[] {
  const file = join(WEB_ROOT, ROOT, relative);
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const out: Line[] = [];
  const visit = (node: ts.Node): void => {
    let text: string | null = null;
    if (ts.isJsxText(node)) text = node.text;
    else if (
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node)
    ) {
      text = (node as ts.LiteralLikeNode).text;
    }
    if (text !== null) {
      const shown = decoded(text).replace(/\s+/g, " ").trim();
      if (shown.length > MAX && readsAsProse(shown) && !classLike(shown) && !unread(node)) {
        const line = source.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        out.push({ where: `${relative}:${line}`, text: shown });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

describe("agent screens speak in short lines", () => {
  it.each(FILES)("%s has no default line longer than one phone line", (relative) => {
    const found = longLines(relative).map((line) => `${line.where} (${line.text.length}): ${line.text}`);
    expect(found, `Shorten these, or move the reasoning behind a tap (InfoTip / HowItWorks):\n${found.join("\n")}`).toEqual([]);
  });

  it("keeps each job card on the Actions tab to a short title and line", () => {
    // `jobs.ts` also holds what the agent is told (default instructions, tool descriptions),
    // which no person reads on a card, so the cards are checked from the data itself.
    for (const job of JOBS) {
      expect(job.title.length, job.title).toBeLessThanOrEqual(MAX);
      expect(job.line.length, job.line).toBeLessThanOrEqual(MAX);
    }
  });

  it("catches a long line it is shown, so it is not passing by reading nothing", () => {
    // The walk must see JSX text in a real component: parse a known-long sentence through the
    // same predicates the files above go through.
    const sample = "This sentence is deliberately much longer than one line on a small phone screen.";
    expect(sample.length).toBeGreaterThan(MAX);
    expect(readsAsProse(sample)).toBe(true);
    expect(classLike(sample)).toBe(false);
    expect(classLike("flex flex-wrap items-center gap-x-2 gap-y-1 text-body font-medium text-ink")).toBe(true);
  });
});
