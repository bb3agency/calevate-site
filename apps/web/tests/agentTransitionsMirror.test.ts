import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * `MOVES_BY_STATUS` in `src/lib/agentState.ts` is a MIRROR of the server's lifecycle
 * table. This is the check that stops it going stale silently.
 *
 * ## The defect this exists for
 *
 * `agentState.ts` decides which lifecycle buttons an agent's screen offers, and it says
 * plainly that it is a second copy of `apps/api/agents/lifecycle.py`. The copy is accepted
 * there for a stated reason — the alternative is a round trip per agent to be told what may
 * be pressed — and CLAUDE.md's one-way-per-problem rule then asks for the thing that makes
 * a copy safe: something that fails when the two stop agreeing.
 *
 * Both directions of the drift are real and neither announces itself:
 *
 * - **An edge ADDED on the server and not here** is a move the API will make and the
 *   screen never offers. The client cannot do it and there is nothing on the page to say
 *   why. `archived -> live` would be the worst version: an owner who could never bring an
 *   agent back without ringing us.
 * - **An edge REMOVED on the server and left here** is a button that can only ever be
 *   refused — which this repo's own rule ("a button that would 403 is worse than no button
 *   at all") calls out as the worse of the two.
 *
 * Neither is a type error, neither fails a test, and both survive a review of the diff
 * that caused them, because the diff is in a `.py` file and the defect is in a `.ts` one.
 *
 * ## Why it compares against `AGENT_MOVERS` and not `AGENT_TRANSITIONS`
 *
 * They answer different questions, and only one of them is the client's. `AGENT_TRANSITIONS`
 * says which EDGES are legal; `AGENT_MOVERS` says which MOVER owns each edge — and the two
 * stop being interchangeable exactly where this screen needs them to be, because
 * `deactivate` and `restore` both end at `paused`. Deriving "which button" from the target
 * state would offer `restore` on a live agent, which is the bug the server's own
 * `_assert_movers_partition_the_table` was added to prevent one layer down. So the client
 * table is checked against the mover table, which is the same fact in the same shape.
 *
 * `AGENT_MOVERS` is itself held to `AGENT_TRANSITIONS` at import time on the server, so
 * this test inherits that: a mover table that has drifted from the transition table cannot
 * be the thing this file agrees with, because the API refuses to start.
 *
 * ## Why it reads Python, and why that is not a second hand-written copy
 *
 * There is no generated artefact to key against: `AgentOut` carries no allowed-moves field
 * and `status` is a bare `str` in `openapi.json`, so the generated client has nothing to
 * check this against. `campaignBlockerCopy.test.ts` is the precedent, argues the same trade
 * at length, and names the same escape: the day the API returns the allowed moves on
 * `AgentOut`, `MOVES_BY_STATUS` and this file both delete and `tsc` does the work.
 *
 * The expected table here is DERIVED from the server's source rather than typed out — a
 * third hand-written copy would be a test that agrees with itself.
 *
 * ## Why in the frontend suite
 *
 * The house pattern for executable governance is `make guardrails`, and this fact is a
 * frontend one: whether a table in a `.ts` file still matches a vocabulary. The person most
 * likely to break it from THIS side is the person running `pnpm -C apps/web test`. The
 * person who breaks it from the server side is caught by the same run in CI.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = resolve(WEB_ROOT, "../..");
const LIFECYCLE_PY = resolve(REPO_ROOT, "apps/api/agents/lifecycle.py");
const AGENT_STATE_TS = resolve(WEB_ROOT, "src/lib/agentState.ts");

/**
 * One `AGENT_MOVERS` entry: `"archive": (frozenset({"draft", "live"}), "archived"),`
 *
 * A regex over one literal rather than a Python parse, for `campaignBlockerCopy.test.ts`'s
 * reason: the alternative is a Python runtime in the frontend gate. It is deliberately
 * ANCHORED to the `AGENT_MOVERS = {` block below, so a `frozenset` literal elsewhere in the
 * module cannot be mistaken for a mover — and the premise test fails loudly if the block
 * stops being found at all, which is the failure mode a scan like this actually has.
 */
const MOVER_ENTRY = /"([a-z_]+)":\s*\(\s*frozenset\(\{([^}]*)\}\)\s*,\s*"([a-z_]+)"\s*\)/g;

/** `{ status: [the movers that accept it] }`, read off the server's own mover table. */
function serverMovesByStatus(): Record<string, string[]> {
  const source = readFileSync(LIFECYCLE_PY, "utf8");
  // The ASSIGNMENT at column zero, never the first mention of the name: the module
  // docstring names `AGENT_MOVERS` sixty lines above the table, and anchoring on the name
  // sliced a block of prose that matched nothing — which read exactly like a table with
  // no entries. Found by this file's own premise test, which is what it is for.
  const declaration = /^AGENT_MOVERS\b[^=\n]*=\s*\{/m.exec(source);
  expect(declaration, `AGENT_MOVERS is gone from ${LIFECYCLE_PY} — has the table been renamed?`)
    .not.toBeNull();
  const open = declaration!.index + declaration![0].length;
  const close = source.indexOf("\n}", open);
  expect(close, "AGENT_MOVERS is no longer a brace-delimited literal").toBeGreaterThan(open);
  const block = source.slice(open, close);

  const moves: Record<string, string[]> = {};
  for (const [, mover, sources] of block.matchAll(MOVER_ENTRY)) {
    for (const quoted of sources.split(",")) {
      const status = quoted.trim().replace(/^"|"$/g, "");
      if (!status) continue;
      (moves[status] ??= []).push(mover);
    }
  }
  for (const list of Object.values(moves)) list.sort();
  return moves;
}

/**
 * `MOVES_BY_STATUS` from `agentState.ts`, read off the AST.
 *
 * Not an import: the constant is module-private and exporting it to suit a test would put
 * a second name on the module's surface. Computed keys are resolved through the file's own
 * string constants (`[ARCHIVED_STATUS]: [...]`), because that indirection is the point of
 * `ARCHIVED_STATUS` — the status is named once — and a reader that could not follow it
 * would report the archive row as missing.
 */
function clientMovesByStatus(): Record<string, string[]> {
  const file = ts.createSourceFile(
    AGENT_STATE_TS,
    readFileSync(AGENT_STATE_TS, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  );

  /** Top-level `const X = "literal"` in this file, for resolving a computed key. */
  const constants = new Map<string, string>();
  const collect = (node: ts.Node): void => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer &&
      ts.isStringLiteral(node.initializer)
    ) {
      constants.set(node.name.text, node.initializer.text);
    }
    ts.forEachChild(node, collect);
  };
  collect(file);

  const keyOf = (name: ts.PropertyName): string | undefined => {
    if (ts.isIdentifier(name)) return name.text;
    if (ts.isStringLiteral(name)) return name.text;
    if (ts.isComputedPropertyName(name) && ts.isIdentifier(name.expression)) {
      return constants.get(name.expression.text);
    }
    return undefined;
  };

  let table: Record<string, string[]> | null = null;
  const visit = (node: ts.Node): void => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.name.text === "MOVES_BY_STATUS" &&
      node.initializer &&
      ts.isObjectLiteralExpression(node.initializer)
    ) {
      const read: Record<string, string[]> = {};
      for (const property of node.initializer.properties) {
        if (!ts.isPropertyAssignment(property)) continue;
        const key = keyOf(property.name);
        if (key === undefined) continue;
        if (!ts.isArrayLiteralExpression(property.initializer)) continue;
        read[key] = property.initializer.elements
          .filter(ts.isStringLiteral)
          .map((element) => element.text)
          .sort();
      }
      table = read;
    }
    ts.forEachChild(node, visit);
  };
  visit(file);

  expect(table, "MOVES_BY_STATUS is not a top-level object literal in agentState.ts any more")
    .not.toBeNull();
  return table!;
}

describe("the client's lifecycle table mirrors the server's", () => {
  it("reads a plausible mover table out of the API", () => {
    // The premise, first and alone. Every assertion below is worthless if this scan has
    // silently stopped matching — a renamed constant, a reformatted literal, a moved
    // module — and a scan that finds nothing would otherwise fail the comparison with a
    // message about the frontend rather than about itself.
    const server = serverMovesByStatus();
    expect(
      Object.keys(server).sort(),
      "the mover scan did not find the four agent statuses — has lifecycle.py moved?",
    ).toEqual(["archived", "draft", "live", "paused"]);
    // Two controls: the edge that must exist, and the one whose absence is the point.
    expect(server.archived, "restore is the archive's only way out").toContain("restore");
    expect(server.archived, "an archived agent must not be switchable straight on").not.toContain(
      "activate",
    );
  });

  it("offers exactly the moves the API will make, from every status", () => {
    expect(
      clientMovesByStatus(),
      "src/lib/agentState.ts::MOVES_BY_STATUS no longer matches " +
        "apps/api/agents/lifecycle.py::AGENT_MOVERS. A move the server accepts and this " +
        "table omits is a control the client cannot reach and nothing on the screen " +
        "explains; a move this table offers and the server has dropped is a button that " +
        "can only ever be refused. Copy the server's edges into MOVES_BY_STATUS — and if " +
        "the API has started returning the allowed moves on AgentOut, delete both the " +
        "table and this file and read that instead.",
    ).toEqual(serverMovesByStatus());
  });
});
