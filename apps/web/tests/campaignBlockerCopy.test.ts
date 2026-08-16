import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * `BLOCKER_COPY` is keyed by the compliance gate's own rule names. This is the check
 * that those keys still name something.
 *
 * ## What the defect actually is
 *
 * The launch panel renders `note?.text ?? blocker.reason`: the client-facing sentence
 * this build carries for a rule, falling back to the server's own words for a rule it
 * does not know. The fall-back is right and stays — a blocker nobody has written copy
 * for is still a blocker, and an unnamed one would read as "you cannot launch, and we
 * will not say why".
 *
 * What has no safety net is the KEY. Rename `pe_registration_not_active` on the server
 * and this build keeps its entry, silently stops matching, and shows the terse operator
 * sentence forever — with the owner badge, the "we chase this with the registrar" and the
 * "incoming calls are unaffected" all quietly gone. Nothing fails. Nobody notices until a
 * client rings to ask what they are supposed to do about a registration they cannot see.
 *
 * The page comment above `BLOCKER_COPY` argues why the fix is this rather than inverting
 * the precedence, and names the backend change that would replace this file with `tsc`.
 *
 * ## Why it reads Python, and why it reads it this way
 *
 * There is no other source of truth. `BlockerOut.rule` is a bare `str` in `openapi.json`,
 * so the generated client carries no union to key against — which is precisely the
 * backend change that would make this test unnecessary. `LIST_PROVENANCE_COPY`, sixty
 * lines below `BLOCKER_COPY` in the same file, IS keyed off a generated union
 * (`CampaignSummary["consent_provenance_blocker"]`) and needs no test at all; that
 * contrast is the argument, not a preference.
 *
 * The scan is a REGEX over the emitting call sites, not an import and not a parse. It
 * matches the four shapes the gate constructs a rule with — `LaunchBlocker("…"`,
 * `DispatchDecision(… rule="…"`, `return ("…", REASON)` from the tuple-returning
 * predicates, and a bare `rule="…"` — which between them cover every blocker the API can
 * emit. It over-matches rather than under-matches on purpose: a rule string this scan
 * invents cannot make a stale key look live unless the API also happens to contain that
 * exact literal, while a rule it MISSES would fail a key that is perfectly fine, and a
 * guard that cries wolf is a guard somebody deletes. The premise assertions below exist
 * so a scan that silently stops finding anything fails loudly instead of passing.
 *
 * ## Why here and not `scripts/check_*.py`
 *
 * The house pattern for executable governance is a checker in `make guardrails`, and the
 * fact under test is a frontend one: whether a table in a `.tsx` file still lines up with
 * a vocabulary. Both halves of the correspondence are read from source either way, so the
 * question is only which gate runs it — and `pnpm -C apps/web test` is the gate that runs
 * when somebody edits this table. Putting it in the backend gate would mean the person
 * most likely to break it is the person least likely to run it.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = resolve(WEB_ROOT, "../..");
const CAMPAIGNS_PAGE = resolve(WEB_ROOT, "src/app/c/[slug]/campaigns/page.tsx");

/** The two API packages a launch blocker can be constructed in. */
const RULE_SOURCES = ["apps/api/campaigns", "apps/api/compliance"];

/** Every shape `compliance` names a rule with. See the header on why this over-matches. */
const RULE_PATTERN =
  /(?:LaunchBlocker\(|DispatchDecision\(|return \(|rule=)\s*"([a-z0-9_]+)"/g;

function pythonFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) found.push(...pythonFiles(path));
    else if (entry.name.endsWith(".py")) found.push(path);
  }
  return found;
}

/** The rule names the compliance gate can put on the wire. */
function serverRuleVocabulary(): Set<string> {
  const rules = new Set<string>();
  for (const source of RULE_SOURCES) {
    for (const file of pythonFiles(resolve(REPO_ROOT, source))) {
      const text = readFileSync(file, "utf8");
      for (const match of text.matchAll(RULE_PATTERN)) rules.add(match[1]);
    }
  }
  return rules;
}

/**
 * The keys of a top-level `Record` literal in the campaigns page, read from the AST.
 *
 * Not an import: `BLOCKER_COPY` is private to a `page.tsx`, and Next's App Router
 * validates the exports of a page module — exporting a constant to make it testable
 * would change the shape of a route file to suit a test. Not a regex either, because
 * these entries span lines and hold `+`-joined prose with braces in it.
 */
function recordKeys(file: string, name: string): string[] {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );

  let keys: string[] | null = null;
  const visit = (node: ts.Node): void => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.name.text === name &&
      node.initializer &&
      ts.isObjectLiteralExpression(node.initializer)
    ) {
      keys = node.initializer.properties.flatMap((property) => {
        const key = property.name;
        if (!key) return [];
        if (ts.isIdentifier(key)) return [key.text];
        if (ts.isStringLiteral(key)) return [key.text];
        return [];
      });
    }
    ts.forEachChild(node, visit);
  };
  visit(source);

  expect(keys, `${name} is not a top-level object literal in ${file} any more`).not.toBeNull();
  return keys!;
}

describe("the launch panel's blocker copy is keyed to rules that still exist", () => {
  it("reads a plausible rule vocabulary out of the compliance gate", () => {
    // The premise, first and on its own. Every assertion below is worthless if this scan
    // has silently stopped matching — a moved package, a renamed constructor, a `.py`
    // tree that is not where this thinks it is — and a scan that finds nothing would
    // otherwise fail the NEXT test with a message about copy rather than about itself.
    const rules = serverRuleVocabulary();
    expect(rules.size, "the rule scan found almost nothing — has the API moved?").toBeGreaterThan(
      20,
    );
    // Three controls: one blocker from each of the modules this correspondence spans.
    for (const known of ["no_contacts", "pe_registration_missing", "consent_source_refused"]) {
      expect(rules, `the scan cannot see ${known}`).toContain(known);
    }
    // …and it is a scan, not a sponge: an invented rule must not appear to be live, or a
    // stale key would pass by accident and this whole file would prove nothing.
    expect(rules).not.toContain("pe_registration_not_active_v2");
  });

  it("has no entry naming a rule the API cannot emit", () => {
    const rules = serverRuleVocabulary();
    const keys = recordKeys(CAMPAIGNS_PAGE, "BLOCKER_COPY");
    expect(keys.length, "BLOCKER_COPY is empty — the AST read is looking at the wrong node")
      .toBeGreaterThan(10);

    expect(
      keys.filter((key) => !rules.has(key)),
      "these BLOCKER_COPY keys name no rule the compliance gate emits, so the client " +
        "copy for them is dead: the launch panel will fall through to the server's own " +
        "terse `reason` and the owner badge, the DLT explanation and the 'incoming calls " +
        "are unaffected' line all disappear with nothing failing. Rename the key to " +
        "match the rule, or delete the entry. (`apps/api/campaigns/service.py` and " +
        "`apps/api/compliance/` are where the names live.)",
    ).toEqual([]);
  });
});
