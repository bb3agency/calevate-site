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
 * ## ⚠ THIS GUARD WAS AIMED AT A PRODUCT THAT NO LONGER EXISTS (re-aimed 15 Sep 2026)
 *
 * Every ground it cited had flipped, and the guard went on failing builds for sentences
 * that had become TRUE. What it said, and what the tree says now — each re-read at source
 * this session rather than carried forward:
 *
 * - "`apps/api/engine/bolna.py:2484` — `BOLNA_CAPABILITIES.knowledge_base = False`" —
 *   it is `True` (`apps/api/engine/bolna.py:3636`).
 * - "`attach_kb` RAISES" — it does not. D-488 built the real one
 *   (`apps/api/engine/bolna.py:5420`): the approved document is uploaded, waited for, and
 *   the agent's `vector_ids` are PATCHed to reference it. `kb/service.publish_source`
 *   calls it behind `require_capability("knowledge_base")` (`kb/service.py:1643,1731`), so
 *   a published source really is in the engine's own store.
 * - "the vector store is explicitly NOT ours" — D-502 reversed D-28; `pgvector` is an
 *   extension in the Postgres this repo already runs.
 * - "This console has no file input at all: `grep 'type=\"file\"' apps/web/src` is empty" —
 *   it is not. `POST /v1/kb/uploads` ships (`apps/api/kb/routes.py:231`), the conversion
 *   seam is real (`calevate_shared.document_ingest.CONVERTIBLE_KINDS` = docx, txt, csv,
 *   xlsx, image, with PDF passing through as the document itself), and the control is
 *   `apps/web/src/app/c/[slug]/knowledge/AddDocument.tsx:133`.
 * - "in-call retrieval is T0 and nothing else (`docs/TRD.md:948`)" — that sentence is at
 *   `docs/TRD.md:802` and is now the stale half of a conflict this file does not get to
 *   resolve: `docs/` is authoritative, and it still describes the engine KB as unbuilt
 *   while the code above ships it. FLAGGED, not silently picked. On the engine we are
 *   migrating to the claim is false twice over — `PIPECAT_CAPABILITIES.knowledge_base` is
 *   `True` (`apps/api/engine/pipecat.py:229`) and the worker registers an in-process pack
 *   search as a CALL TOOL (`docs/PIPECAT-MIGRATION.md` §6 step 11, §8.1).
 *
 * `POST /v1/kb/sources` is the one ground that held: it still takes TEXT only
 * (`apps/api/kb/service.py:77`, `SUPPORTED_SUBMISSION_KINDS = {"text"}`). That governs the
 * PASTE box and not the screen, because a file and a link come in through the uploads
 * endpoint instead.
 *
 * ## What it guards NOW
 *
 * Retrieval is no longer the thing the product cannot do, so a ban on the word is a ban on
 * the truth. Three constraints survive, and the patterns below are cut to them:
 *
 * 1. **We do not train on, fine-tune on, or learn from a client's material**, and no agent
 *    answers an arbitrary question. Unchanged, and the one shape carried over untouched.
 * 2. **Nothing a client submits reaches a caller until it has been approved AND
 *    published.** Ingest is asynchronous (`kb/uploads.py` — `UPLOAD_RECEIVED`,
 *    `UPLOAD_CONVERTING`, "a per-item status a client can read while the engine indexes
 *    asynchronously"), approval is a human step (FLOWS §7, `kb/service.approve_source`),
 *    and `approved` is still not `live` — the two-step ladder `SubmittedList.tsx` exists
 *    for. Copy that couples adding knowledge to an immediacy word promises a state the
 *    product does not have.
 * 3. **We read what a client GIVES us, never their systems.** There is no connector that
 *    reads a client's website, drive, inbox or CRM for answers: a link is fetched once at
 *    submission through `integrations/egress_guard.assert_public_http_url` and re-fetched
 *    only by the change sweep, and everything else arrives as bytes a person uploaded.
 *
 * ## Why a source scan and not only a render assertion
 *
 * `publicLanding.test.tsx` and `knowledgeApproval.test.tsx` pin the rendered sentences on
 * the two screens that carry the claim, and those are the stronger assertions where they
 * apply. But a good deal of the copy that promises things is never in either render tree:
 * a `useCopilotSurface` field's `help` (the assist panel's own words), a `placeholder` an
 * operator copies into a message to a client, a `NoticeBox` behind a state no fixture
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
 * inconveniences, and then nothing guards the real claim. So "upload" is not banned at all
 * any more — a client really can upload a price list and the agent really does answer from
 * it — and the retrieval verbs are legal. What is banned is the IMMEDIACY beside them and
 * the SYSTEM beside them, each bounded by `[^.]{0,N}` so it cannot span a sentence
 * boundary and weld two innocent phrases into a false hit.
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
    // WAS `upload-it-and-the-agent-will-know` AND `knowledge-you-uploaded`, both of which
    // banned a thing the product now does (D-534 shipped the uploads door). What it could
    // never do is make it live without a person: `publish_source` runs after approval, and
    // conversion and indexing are asynchronous before that.
    name: "live-the-moment-you-add-it",
    pattern:
      /\b(upload\w*|add\w*|paste\w*|submit\w*|send\w*)\b[^.]{0,60}\b(knowledge|price list|rate card|brochure|catalogue|menu|faq|document|documents)\b[^.]{0,60}\b(immediately|instantly|right away|straight away|at once|within seconds|in seconds)\b/i,
    why: "knowledge is converted, then approved by a person, then published before any caller hears it (apps/api/kb/uploads.py, apps/api/kb/service.py::approve_source, FLOWS §7); `approved` is not `live`",
    fires: "Upload your price list and the agent answers from it immediately.",
    quietOn:
      "Your prices and timings are built into the agent before it takes a call, so the answer comes back straight away.",
  },
  {
    // WAS `searches-your-documents`, which banned the retrieval verb outright. The verb is
    // honest now; what is not is the OBJECT. Nothing reads a client's own systems.
    name: "reads-your-systems",
    pattern:
      /\b(read\w*|search\w*|scan\w*|look\w* up|crawl\w*|index\w*)\b[^.]{0,40}\byour\b[^.]{0,30}\b(website|site|drive|dropbox|inbox|mailbox|email|crm|database|server|systems?|files? on)\b/i,
    why: "there is no connector that reads a client's own systems: a link is fetched once at submission through integrations/egress_guard.assert_public_http_url, and everything else is bytes a person uploaded",
    fires: "The agent searches your website and your CRM for the answer.",
    // The legal set's own sentence about lead DELIVERY, which is the direction that is
    // real: we push finished leads OUT to a client's system on their instruction. That is
    // why `connect` and `sync` are not in the verb list — they are the delivery verbs, and
    // banning them fired on `src/lib/legal/terms.ts` §3, an operative clause in a published
    // document that is accurate.
    quietOn:
      "delivers them to your dashboard and, if you connect one, to your own system.",
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
 * ⚠ **EMPTY SINCE THE 15 SEP 2026 RE-AIM, AND THAT IS A MEASUREMENT RATHER THAN A CLAIM OF
 * VIRTUE.** It held eight entries, and every one of them was a legal-set clause using
 * "upload" in its ordinary sense — content a client puts into the service — which the two
 * retired `upload*` patterns fired on. Those patterns are gone because the product now
 * does the thing they banned, so the sentences they excused no longer trip anything and an
 * allowlist repeating them would excuse nothing. The mechanism stays wired: the scan below
 * consults it on every hit, so the next honest sentence that trips a pattern is one entry
 * away from being recorded WITH ITS REASON rather than being fixed by widening a regex.
 *
 * The judgement that put the legal set here in the first place still stands and is worth
 * inheriting: correcting a word in a published document's operative text means a new
 * revision in this mirror AND in `apps/api/legal/catalogue.py`, with the drift check across
 * both. That belongs to whoever owns the legal surface, not to a copy sweep.
 */
const ALLOWED: readonly { readonly text: string; readonly why: string }[] = [];

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
