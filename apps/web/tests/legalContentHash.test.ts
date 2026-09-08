import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { LEGAL_DOCUMENTS, blocksOf, textOf, type LegalDocument } from "@/lib/legal";
import { resolvePlaceholders } from "@/lib/legal/placeholders";
import { LEGAL_VERSIONS, type LegalRevision } from "@/lib/legal/versions";

/**
 * THE WORDS UNDER A REVISION MAY NOT MOVE WITHOUT THE REVISION MOVING.
 *
 * ## The gap this closes, in the words of the check that admitted it
 *
 * `scripts/check_docs_drift.py` §4d compares `apps/api/legal/catalogue.py` against
 * `apps/web/src/lib/legal/versions.ts` and says of itself: *"IT COMPARES IDENTITY, NOT
 * TEXT … a lawyer editing a clause in `terms.ts` without appending a revision produces an
 * acceptance row naming a version whose words have changed, and no check here sees it."*
 *
 * That is not a tidiness problem. `apps/api/legal/` writes an acceptance into an
 * append-only ledger naming a document and a version, four outbound gates read it, and a
 * DPDP/contract record that says "this client accepted Terms revision 6" is worth what it
 * says only while revision 6 still means what it meant on the day they clicked. Rewrite a
 * clause in place and every stored acceptance silently re-points at words nobody agreed
 * to. Until this file existed, exactly ONE clause was protected — the credit-lot promise
 * in Terms §6.1, pinned verbatim by two tests in `tests/legal.test.tsx` — and the other
 * eight documents were unguarded prose.
 *
 * ## What is hashed: THE OPERATIVE TEXT, defined exactly
 *
 * A document's operative text is **every string a reader of `/legal/<slug>` is shown, in
 * document order, one per line, with `{{PLACEHOLDER}}` tokens resolved to their values**:
 *
 *     canonical(doc) = resolvePlaceholders(textOf(doc))
 *     contentHash(doc) = "sha256:" + sha256(canonical(doc) as UTF-8) in lowercase hex
 *
 * `textOf` is `src/lib/legal/index.ts`'s existing walk and is reused rather than
 * re-implemented — a second definition of "the words of this document" is the drift this
 * repo's "one way per problem" rule exists to refuse, and `textOf`'s `never` check makes
 * TypeScript fail the build if a new block kind is added without extending it. It reaches
 * the title, the summary, the `appliesTo` line, every section and subsection heading, and
 * every paragraph, list item, definition term and detail, table caption, column heading
 * and cell, and callout title and body.
 *
 * What it therefore does NOT reach, each deliberately:
 *
 *  - **imports, comments and TypeScript formatting.** The drift check predicted the
 *    failure of the obvious approach — *"hashing the file, say — would fire on a comment
 *    change and be switched off within a week"* — and these documents carry more comment
 *    than prose. A hash over the file would go off on every docstring edit, which is how
 *    a guard gets deleted.
 *  - **`id` anchors and the `slug`.** They are addresses, not words. Renaming an anchor
 *    breaks a link, which is a different defect with a different guard in
 *    `tests/legal.test.tsx`.
 *  - **`shortTitle` and the block kinds themselves.** Presentation.
 *  - **the revision table.** `versions.ts` is a different module and is where the hash is
 *    RECORDED; hashing it would make every hash a checksum of itself.
 *
 * PLACEHOLDERS ARE RESOLVED, and that is the one non-obvious half. A token is a fact the
 * repository does not know (`{{REGISTERED_ADDRESS}}`), and its VALUE is what the client
 * reads. The repository already treats a change to one as operative: revision 5 of the
 * Privacy Policy, the Terms and the DPA exists solely because the published principal
 * place of business was reduced to a city. Hashing the raw token would have been blind to
 * the very change the revision log records.
 *
 * A reader can verify a hash by hand: print `resolvePlaceholders(textOf(doc))` and run it
 * through `sha256sum`. `pnpm -C apps/web legal:hashes` does exactly that and prints the
 * table (see below).
 *
 * ## Where the hash lives, and which side is authoritative
 *
 * The hash sits on the revision it describes, in `versions.ts`:
 *
 *     { revision: "6", material: true, contentHash: "sha256:…" }
 *
 * beside the revision rather than in a parallel table, so bumping a revision and
 * recording what it says are ONE edit in ONE place. Revisions authored before this guard
 * existed carry no hash: their text is not in the tree and cannot be recovered, and
 * inventing one would be a fact asserted from nothing (hard rule 11). Every revision
 * authored from now on carries one, so the history heals itself at the first bump.
 *
 * **The TypeScript side is authoritative for the hash, and only for the hash.**
 * `apps/api/legal/catalogue.py` remains authoritative for a document's IDENTITY — slug,
 * revision, `material`, effective date — because that is what an acceptance row is
 * compared against on a machine that never runs Node. But the PROSE exists only in
 * TypeScript, so a hash of it can only be computed where the prose is; a copy in Python
 * would be a number that side could never recompute or contradict, which is precisely the
 * laundering hard rule 11 forbids. `check_docs_drift` therefore asserts only what Python
 * can honestly assert — that the current revision of every document HAS a hash — and this
 * file asserts what the hash is.
 *
 * ## What this guard cannot do, said plainly
 *
 * It cannot stop someone editing a clause and pasting the new hash onto the unchanged
 * revision. Nothing in a single working tree can: there is no earlier copy of the text to
 * compare against. What it does is convert an INVISIBLE act into a VISIBLE one — a
 * `contentHash` changing under a revision number that did not is a two-line diff in a
 * file whose only subject is versions, and it is the diff a reviewer is looking for. The
 * check that follows the words is the human one; this makes it possible to do.
 *
 * ## It cannot manufacture its own evidence
 *
 * `scripts/check_drill_freshness.py` is the standard here: it is structurally incapable
 * of producing the artefact it validates, and it audits its own source to prove it. The
 * same property is what makes a content hash mean anything — a guard that could write the
 * hash it checks would be checking its own output, and every run would be green by
 * construction. So nothing here writes: `versions.ts` is edited by a person, the
 * regeneration command PRINTS and never patches, and `cannotWrite` below reads this
 * file's own source on every run and fails if a writer or a subprocess appears in it.
 *
 * ## Regenerating a hash is a named act
 *
 *     pnpm -C apps/web legal:hashes
 *
 * It prints one line per document: the slug, the revision it is recording against, and
 * the hash its current text has. It writes nothing. You paste the value beside the
 * revision you just appended — so making this gate green costs a revision entry, in both
 * mirrors, with `material` decided, rather than a reflex edit.
 */

/** The algorithm, spelled once. It is part of the stored value so a change is visible. */
const HASH_PREFIX = "sha256:";

/** Every string a reader is shown, in document order, placeholders resolved. */
export function canonicalText(doc: LegalDocument): string {
  return resolvePlaceholders(textOf(doc));
}

/** The operative-text hash of one document, in the spelling `versions.ts` stores. */
export function contentHash(doc: LegalDocument): string {
  return HASH_PREFIX + createHash("sha256").update(canonicalText(doc), "utf8").digest("hex");
}

/** The mirror entry for a document, or a failure the caller can read. */
function revisionsOf(doc: LegalDocument): readonly LegalRevision[] {
  const entry = LEGAL_VERSIONS[doc.slug];
  expect(entry, `apps/web/src/lib/legal/versions.ts carries no ${doc.slug} entry`).toBeDefined();
  return entry!.revisions;
}

function current(doc: LegalDocument): LegalRevision {
  const revisions = revisionsOf(doc);
  expect(revisions.length, `${doc.slug} has no revisions`).toBeGreaterThan(0);
  return revisions[revisions.length - 1];
}

/** How a person is told to fix a document whose words moved. Written for a lawyer. */
function bumpInstructions(doc: LegalDocument, revision: string): string {
  return (
    `The fix is a new revision, not a new hash. Append one to LEGAL_VERSIONS["${doc.slug}"]` +
    ".revisions in apps/web/src/lib/legal/versions.ts AND to the matching document in " +
    "apps/api/legal/catalogue.py, decide `material` honestly (does somebody who accepted " +
    `revision ${revision} have to accept again?), and put the printed hash on the NEW ` +
    "entry. Run `pnpm -C apps/web legal:hashes` to print it. Do not change the hash on " +
    `revision ${revision}: it is the record of the words that were accepted under it.`
  );
}

describe("legal documents: the words under a revision", () => {
  /**
   * THE PREMISE CHECK, and it is not decoration.
   *
   * Everything below is a hash of whatever `textOf` returns. If `textOf` ever stopped
   * reaching a block kind — a plausible edit, since its stated job today is the
   * placeholder audit — the hashes would still match each other and this whole file would
   * pass while guarding less than it claims. So the walk is verified against the
   * documents' own structure: for every block kind that appears anywhere in the published
   * set, a real string taken from a real block of that kind must be present in the
   * canonical text — resolved the same way the canonical text resolves it, because a
   * sample block may itself carry a `{{PLACEHOLDER}}`. No literal is typed here; the
   * sample is derived from the tree, so a document that stops using a kind cannot break
   * this and a walk that stops reading one cannot pass it.
   */
  it("hashes every kind of prose these documents contain", () => {
    const samples = new Map<string, { slug: string; text: string }>();
    for (const doc of LEGAL_DOCUMENTS) {
      for (const block of blocksOf(doc)) {
        if (samples.has(block.kind)) continue;
        const sample =
          block.kind === "para"
            ? block.text
            : block.kind === "list"
              ? block.items[0]
              : block.kind === "definitions"
                ? block.items[0]?.detail
                : block.kind === "table"
                  ? (block.rows[0] ?? [])[0]
                  : block.text;
        if (sample) samples.set(block.kind, { slug: doc.slug, text: sample });
      }
    }
    expect(samples.size, "the published set has fewer block kinds than the type allows").toBe(5);
    for (const [kind, sample] of samples) {
      expect(
        canonicalText(LEGAL_DOCUMENTS.find((doc) => doc.slug === sample.slug)!),
        `the operative text of /legal/${sample.slug} does not include its ${kind} blocks — ` +
          "`textOf` has stopped reading a kind of prose, and every hash below is now a " +
          "hash of less than the document",
      ).toContain(resolvePlaceholders(sample.text));
    }
  });

  /** Direction one: the words moved and the revision did not. */
  it("records the current words of every document under its current revision", () => {
    for (const doc of LEGAL_DOCUMENTS) {
      const revision = current(doc);
      const computed = contentHash(doc);
      expect(
        revision.contentHash,
        `/legal/${doc.slug} revision ${revision.revision} carries no contentHash. Every ` +
          "revision authored from now on records the words it publishes: " +
          `${computed}. ` +
          bumpInstructions(doc, revision.revision),
      ).toBeDefined();
      expect(
        revision.contentHash,
        `THE WORDS OF /legal/${doc.slug} HAVE CHANGED AND ITS REVISION HAS NOT. Revision ` +
          `${revision.revision} records the text as ${revision.contentHash}; the document ` +
          `in apps/web/src/lib/legal/ now reads as ${computed}. Every client who accepted ` +
          `revision ${revision.revision} accepted the earlier words, and the acceptance ` +
          "ledger still points at this revision. " +
          bumpInstructions(doc, revision.revision),
      ).toBe(computed);
    }
  });

  /**
   * Direction two: a revision was bumped and the words did not move.
   *
   * A different mistake with a different cost. A revision re-asks every client to accept
   * a document — a blocking one stops them dialling until they do — so a bump that
   * changes nothing spends a client's attention on nothing, and a set of documents that
   * asks for acceptance it does not need is how people learn to click through the ones
   * that matter.
   */
  it("never publishes a revision whose words are identical to the one before it", () => {
    for (const doc of LEGAL_DOCUMENTS) {
      const revisions = revisionsOf(doc);
      for (let i = 1; i < revisions.length; i += 1) {
        const previous = revisions[i - 1];
        const revision = revisions[i];
        if (!previous.contentHash || !revision.contentHash) continue;
        expect(
          revision.contentHash === previous.contentHash,
          `/legal/${doc.slug} revision ${revision.revision} records exactly the same words ` +
            `as revision ${previous.revision} (${revision.contentHash}). A revision asks ` +
            "every client to accept the document again, so one that changes no word costs " +
            "them a decision and teaches them to click through the next one. If the bump " +
            "was a mistake, delete the entry here and in apps/api/legal/catalogue.py. If " +
            "the words really did change, the hash is stale — print the current one with " +
            "`pnpm -C apps/web legal:hashes`.",
        ).toBe(false);
      }
    }
  });

  /** Nothing may carry a hash in a shape this guard does not compute. */
  it("stores hashes in one spelling", () => {
    for (const doc of LEGAL_DOCUMENTS) {
      for (const revision of revisionsOf(doc)) {
        if (revision.contentHash === undefined) continue;
        expect(
          revision.contentHash,
          `/legal/${doc.slug} revision ${revision.revision} has a contentHash that is not ` +
            "a lowercase sha256 digest with its algorithm named",
        ).toMatch(/^sha256:[0-9a-f]{64}$/);
      }
    }
  });

  /**
   * THE REPORT, which is also the command.
   *
   * `pnpm -C apps/web legal:hashes` runs this file; these lines are what it prints. They
   * are produced by an assertion rather than by a bare `console.log` so the printer
   * cannot outlive the thing it describes.
   */
  it("prints the operative-text hash of every published document", () => {
    const rows = LEGAL_DOCUMENTS.map((doc) => {
      const revision = current(doc);
      const computed = contentHash(doc);
      const state = revision.contentHash === computed ? "current" : "DOES NOT MATCH versions.ts";
      return `  ${doc.slug.padEnd(16)} revision ${revision.revision.padEnd(3)} ${computed}  ${state}`;
    });
    // This test IS the report `pnpm -C apps/web legal:hashes` runs; see the header.
    console.log(
      ["operative-text hashes (paste beside the revision you appended):", ...rows].join("\n"),
    );
    expect(rows.length).toBe(LEGAL_DOCUMENTS.length);
  });

  /**
   * THE SELF-AUDIT — `scripts/check_drill_freshness.py`'s property, in TypeScript.
   *
   * A guard that can write the evidence it checks is green by construction. This one
   * reads its own source and fails if anything that could create, patch or shell out to
   * something that patches appears in it. `node:fs` is imported for THIS test and for
   * nothing else, and `readFileSync` is the only member of it named anywhere here.
   */
  it("cannot write the hashes it checks", () => {
    const source = readFileSync(fileURLToPath(import.meta.url), "utf8");
    const writers = [
      "writeFileSync",
      "appendFileSync",
      "createWriteStream",
      "promises.writeFile",
      "child_process",
      "execSync",
      "spawnSync",
      "rmSync",
      "unlinkSync",
    ];
    for (const writer of writers) {
      expect(
        source.includes(`${writer}(`) || source.includes(`${writer}.`),
        `this guard calls ${writer}. A check that can produce the record it validates ` +
          "validates its own output; the hashes are written by a person, in a diff.",
      ).toBe(false);
    }
  });
});
