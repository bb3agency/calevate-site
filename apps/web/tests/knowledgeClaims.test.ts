import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";

/**
 * THE KNOWLEDGE-BASE CLAIM, guarded across every surface at once — including the copy a
 * render test cannot reach.
 *
 * ## The fact this guard is aimed at
 *
 * **In-call retrieval is T0 and nothing else.** The facts a person approves are compiled
 * into the agent's own system prompt at publish time and travel with it; nothing is
 * looked up while a caller is on the line, and no document is read at any point. Verified
 * at source rather than recalled:
 *
 * - `docs/TRD.md:948` — "the honest statement of the shipped system is: in-call retrieval
 *   is T0 and nothing else".
 * - `apps/api/engine/bolna.py:2484` — `BOLNA_CAPABILITIES.knowledge_base = False`.
 * - `apps/api/engine/bolna.py:3536` — `attach_kb` RAISES: "The voice platform's knowledge
 *   base accepts documents, not text."
 * - `apps/api/kb/__init__.py` — the vector store is explicitly NOT ours; `kb_chunks` +
 *   pgvector are CONTINGENCY, and this module "never [stores] an embedding".
 * - `apps/api/kb/routes.py:44` — `POST /v1/kb/sources` declares `kind: "text" | "url" |
 *   "file"` and the service REFUSES the last two. Text is the only shape that works.
 * - `apps/api/agents/t0.py` — the compiler that splices approved knowledge into
 *   `[T0 FACTS]` / "Published knowledge:" at publish time. That is the whole mechanism.
 * - This console has no file input at all: `grep 'type="file"' apps/web/src` is empty.
 *
 * ## Why a source scan and not only a render assertion
 *
 * `publicLanding.test.tsx` and `knowledgeApproval.test.tsx` pin the rendered sentences on
 * the two screens that carry the claim, and those are the stronger assertions where they
 * apply. But a good deal of the copy that promises things is never in either render tree:
 * a `useCopilotSurface` field's `help` (the assist panel's own words — and that is exactly
 * where "It is split into chunks and retrieved during calls" was found), a `placeholder`
 * an operator copies into a message to a client, a `NoticeBox` behind a state no fixture
 * produces. A scan of the STRING LITERALS reaches all of it.
 *
 * Literals only, via the TypeScript parser — never a `grep` over the file text. Half the
 * corrected sites now carry a comment explaining what the sentence used to say, and a
 * text-level scan would fire on the explanation of the defect and force the next author to
 * delete the reasoning to make the guard pass.
 *
 * ## Why the patterns are narrow, and what that costs
 *
 * A ban wide enough to fire on an honest sentence gets deleted by the first person it
 * inconveniences, and then nothing guards the real claim. So:
 *
 * - "upload" is NOT banned on its own. It is honest about a client's own systems, about a
 *   campaign list, and about anything a human reads. It is banned within one sentence of
 *   the agent's KNOWLEDGE, which is the only place the product cannot honour it.
 * - The retrieval verbs are banned only when they are pointed at a CALL or at the client's
 *   own documents — "retrieved during calls", "searches your documents". "Preview",
 *   "submit" and "review" are the words this workflow is actually made of and stay legal.
 * - Every pattern is bounded by `[^.]{0,N}` so it cannot span a sentence boundary and
 *   weld two innocent phrases into a false hit.
 *
 * The cost is the allowlist below: a handful of real sentences that trip a pattern for a
 * reason, each with the reason written down. An empty allowlist would be a lie about how
 * clean the tree is.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = resolve(WEB_ROOT, "src");

/** One banned shape, its reason, and a sample it MUST fire on. */
interface BannedShape {
  readonly name: string;
  readonly pattern: RegExp;
  /** What a reader would wrongly conclude, for the failure message. */
  readonly why: string;
  /** Proof the detector works — asserted below, so a broken regex fails loudly. */
  readonly fires: string;
  /** Proof it is not over-broad: an honest sentence it must NOT flag. */
  readonly quietOn: string;
}

const BANNED: readonly BannedShape[] = [
  {
    name: "look-it-up-mid-call",
    pattern: /\b(retriev\w+|search\w+|looks? up|fetch\w+)\b[^.]{0,40}\b(during|mid|on)[- ]?(a )?calls?\b/i,
    why: "nothing is retrieved during a call — approved facts are already in the prompt (docs/TRD.md:948)",
    fires: "It is split into chunks and retrieved during calls.",
    quietOn: "It opens by saying it is an AI, and answers from what you approved.",
  },
  {
    name: "searches-your-documents",
    pattern:
      /\b(search\w*|looks? up|reads?|scans?|consults?)\b[^.]{0,40}\byour\b[^.]{0,30}\b(documents?|files?|pdfs?|knowledge base|material)\b/i,
    why: "there is no document store to search: the vector store is not ours and no embedding path exists (apps/api/kb/__init__.py)",
    fires: "The agent searches your documents for the answer.",
    quietOn: "Your account manager reviews everything you add before it goes live.",
  },
  {
    name: "upload-it-and-the-agent-will-know",
    pattern: /\bupload\w*\b[^.]{0,60}\b(knowledge|price list|rate card|brochure|catalogue|faq)\b/i,
    why: 'POST /v1/kb/sources takes text and refuses kind="file"/"url" (apps/api/kb/routes.py:44); this console has no file input at all',
    fires: "Upload your price list and the agent will answer from it.",
    quietOn: "Paste in a list. It works through it and retries the no-answers.",
  },
  {
    name: "knowledge-you-uploaded",
    pattern: /\bknowledge\b[^.]{0,60}\bupload\w*/i,
    why: "knowledge is written or pasted as text, never uploaded — the same missing control, said the other way round",
    fires: "The knowledge base you uploaded is answered from on every call.",
    quietOn: "Knowledge you submit is reviewed before it goes live.",
  },
  {
    name: "open-genre-ai-promise",
    pattern: /\btrained on your\b|\blearns your\b|\bknows everything\b|\banswers? any question\b/i,
    why: "we neither train nor fine-tune on a client's material, and no agent can answer any question",
    fires: "It is trained on your business and answers any question a caller has.",
    quietOn: "It answers what you have taught it, in the words you approved.",
  },
];

/**
 * Sentences that trip a pattern and are staying, each with the reason.
 *
 * Matched as EXACT strings against the offending literal's matched text, not by file or by
 * pattern name, so an allowlist entry cannot silently cover a second sentence that appears
 * later in the same file.
 *
 * The legal set is the whole of it, and the judgement is deliberate. Those documents use
 * "upload" in its ordinary sense — content a client puts into the service — in clauses
 * about ownership, warranty and erasure scope. That is loose rather than FALSE: a client
 * really does put knowledge content in, and it really is theirs. Correcting the word there
 * is an edit to a published document's operative text, which under
 * `src/lib/legal/versions.ts` means a new revision in this mirror AND in
 * `apps/api/legal/catalogue.py`, with the drift check across both. That belongs to whoever
 * owns the legal surface, with `docs/LEGAL-SURFACE.md`'s findings list in front of them —
 * not to a copy sweep. It is recorded here so the next reader inherits the decision rather
 * than the silence.
 */
const ALLOWED: readonly { readonly text: string; readonly why: string }[] = [
  {
    text: "knowledge content a client uploads",
    why: "legal set (privacy §11, subprocessors): 'upload' in its ordinary sense, in a retention/erasure clause. Not a retrieval claim.",
  },
  {
    text: "Knowledge content a client uploaded",
    why: "legal set (privacy §12, erasure scope): same word, same clause family.",
  },
  {
    text: "Knowledge content you uploaded",
    why: "legal set (DPA): same, addressed to the client.",
  },
  {
    text: "knowledge content, uploaded",
    why: "legal set (terms): an inventory of what a client puts in — knowledge content, uploaded lists, settings.",
  },
  {
    text: "knowledge content you uploaded",
    why: "legal set (terms, exit rights): what the client takes away with them.",
  },
  {
    text: "knowledge documents, extraction schemas and uploaded",
    why: "legal set (terms, client responsibilities): the client's own content, warranted by them.",
  },
  {
    text: "uploaded knowledge",
    why: "legal set (DPA, the retention correction): describes the same store as the row above it.",
  },
  {
    text: "Uploading anyone else's personal data into your agent's knowledge",
    why: "acceptable-use PROHIBITION. It bans a thing; it does not offer one, and it must keep covering pasted text.",
  },
];

/** Every `.ts`/`.tsx` under `src`, minus the generated wire client. */
function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      sourceFiles(path, out);
      continue;
    }
    if (!/\.tsx?$/.test(entry)) continue;
    // Generated from the OpenAPI document: not copy, and not ours to edit here.
    if (entry === "schema.d.ts") continue;
    out.push(path);
  }
  return out;
}

/** One string literal, with where it is. */
interface Literal {
  readonly file: string;
  readonly line: number;
  readonly text: string;
}

/** Is this a leaf that carries prose a reader will see? */
function isProse(node: ts.Node): node is ts.StringLiteralLike | ts.TemplateLiteralLikeNode | ts.JsxText {
  return (
    ts.isStringLiteral(node) ||
    ts.isNoSubstitutionTemplateLiteral(node) ||
    ts.isTemplateHead(node) ||
    ts.isTemplateMiddle(node) ||
    ts.isTemplateTail(node) ||
    ts.isJsxText(node)
  );
}

/**
 * Every unit of prose in a file, comments excluded — where a UNIT is one sentence as a
 * reader meets it, not one literal as the parser sees it.
 *
 * A `+` chain of string literals is the house way of writing a paragraph, so a chain is
 * collected WHOLE and its children are not visited again; everything else is a unit on its
 * own. Template `${…}` holes are dropped: a phrase split across an interpolation is not a
 * sentence anybody reads either.
 *
 * Literals rather than a `grep` over the file text, and that is load-bearing: half the
 * corrected sites now carry a comment quoting the sentence they replaced, and a text-level
 * scan would fire on the explanation and force the next author to delete the reasoning to
 * get the guard green.
 */
function literalsOf(file: string): Literal[] {
  const text = readFileSync(file, "utf8");
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const found: Literal[] = [];

  /** The concatenated prose of a `"a" + "b" + …` chain, or null if it is not one. */
  const chainText = (node: ts.Node): string | null => {
    if (isProse(node)) return node.text;
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const left = chainText(node.left);
      const right = chainText(node.right);
      return left !== null && right !== null ? left + right : null;
    }
    if (ts.isParenthesizedExpression(node)) return chainText(node.expression);
    return null;
  };

  const push = (node: ts.Node, prose: string): void => {
    found.push({
      file,
      line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
      text: prose,
    });
  };

  const visit = (node: ts.Node): void => {
    const chain = ts.isBinaryExpression(node) ? chainText(node) : null;
    if (chain !== null) {
      push(node, chain);
      return; // its literals are already accounted for, once, in order
    }
    if (isProse(node)) {
      push(node, node.text);
      return;
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

/**
 * The scanned corpus: one haystack per file, and a SEPARATOR that a pattern cannot cross.
 *
 * Two facts about how copy is written here pull in opposite directions. A paragraph is one
 * sentence spread over several literals — `"…the material you upload — your price list, " +
 * "your timings…"` — so a per-literal scan would miss any phrase that straddles the `+`
 * and this guard would be blind to most of the page it exists for. But two UNRELATED
 * literals sitting next to each other (a card's `label` and the `meaning` under it) are
 * not a sentence, and joining them plainly welded "Knowledge waiting on us" to "This
 * client uploaded…" into a hit that nobody had written.
 *
 * `literalsOf` already returns concatenation chains as ONE entry, so the first case is
 * covered before the join. The join between entries is therefore `" . "` — a sentence
 * terminator, which every pattern's `[^.]{0,N}` bound refuses to cross. Adjacency can no
 * longer manufacture a claim.
 */
const UNIT_SEPARATOR = " . ";

function haystacks(): { file: string; text: string; lines: Literal[] }[] {
  return sourceFiles(SRC).map((file) => {
    const lines = literalsOf(file);
    return { file, text: lines.map((l) => l.text).join(UNIT_SEPARATOR), lines };
  });
}

describe("the knowledge-base claim, across every client- and prospect-facing string", () => {
  it("has a corpus to scan at all", () => {
    // A scan that silently matched nothing would pass exactly like a clean tree — the
    // premise check `wireLookupGuard` and `surfaceStatesGuard` both carry, for the same
    // reason.
    const scanned = haystacks();
    expect(scanned.length).toBeGreaterThan(150);
    expect(scanned.some((h) => h.text.includes("What your agent knows"))).toBe(true);
  });

  it.each(BANNED.map((shape) => [shape.name, shape] as const))(
    "detects `%s` on a known-bad sentence and leaves an honest one alone",
    (_name, shape) => {
      // The detector proves itself before it is trusted. A regex edited into silence
      // would otherwise turn this whole file green.
      expect(shape.pattern.test(shape.fires)).toBe(true);
      expect(shape.pattern.test(shape.quietOn)).toBe(false);
    },
  );

  it("promises no document-backed or look-it-up-live knowledge anywhere in src", () => {
    const offences: string[] = [];
    for (const { file, text, lines } of haystacks()) {
      for (const shape of BANNED) {
        for (const match of text.matchAll(new RegExp(shape.pattern.source, "gi"))) {
          const hit = match[0];
          if (ALLOWED.some((entry) => hit.includes(entry.text) || entry.text.includes(hit))) {
            continue;
          }
          // Report the nearest literal so the failure names a line, not a file.
          const near = lines.find((l) => hit.includes(l.text.trim()) || l.text.includes(hit.slice(0, 24)));
          offences.push(
            `${relPosix(WEB_ROOT, file)}:${near?.line ?? "?"} — ${shape.name}: ${JSON.stringify(hit)}\n` +
              `    ${shape.why}`,
          );
        }
      }
    }
    expect(
      offences,
      "Client-facing copy promised knowledge the product does not have.\n" +
        "In-call retrieval is T0 and nothing else: the facts a person approves are compiled\n" +
        "into the agent's prompt at publish time. Say that instead — it is the faster\n" +
        "arrangement, not the poorer one — or, if the product has genuinely grown a\n" +
        "retrieval leg, move this guard in the same change and cite the code that ships it.\n\n" +
        offences.join("\n"),
    ).toEqual([]);
  });
});
