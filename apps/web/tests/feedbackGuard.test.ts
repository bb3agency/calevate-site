import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";
import { FEEDBACK_BASELINE } from "./fixtures/feedbackBaseline";

/**
 * EVERY ACTION A SCREEN STARTS GIVES FEEDBACK (founder, 24 Oct 2026; docs/design/KIT.md,
 * "The feedback standard").
 *
 * The rule, as the AST sees it: wherever a screen or component (`src/app`, `src/components`)
 * creates a mutation — a call to `useMutation(...)` or to any hook that returns one — it
 * assigns the result to a name, and that name is passed to `useActionFeedback(...)` in the
 * same file. `useActionFeedback` is what puts pending / success / error on the button and
 * the failure in the toast stack, so a mutation that never reaches it is an action whose
 * outcome nobody is told.
 *
 * Which hooks return a mutation is DERIVED, not listed: every function named `use*` in
 * `src/` whose body returns `useMutation(...)` or another such hook, iterated until nothing
 * new is found. A hand-kept list is the thing that silently stops covering the next hook.
 *
 * A hook that only wraps and returns a mutation (`return useSaveThing(session)`) is a
 * definition, not a use, and is not checked; its callers are.
 *
 * `FEEDBACK_BASELINE` holds the call sites that predate the standard, as `file::name`. It
 * is a ratchet: a new site not on it fails, and a site on it that now complies (or is gone)
 * also fails until its entry is removed — so the list only shrinks.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(WEB_ROOT, "src");
const SCREEN_ROOTS = ["src/app/", "src/components/"];

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...sourceFiles(path));
    else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts")) found.push(path);
  }
  return found;
}

function parse(path: string): ts.SourceFile {
  return ts.createSourceFile(
    path,
    readFileSync(path, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

const FILES = sourceFiles(SRC).map((path) => ({ rel: relPosix(WEB_ROOT, path), file: parse(path) }));

function calleeName(call: ts.CallExpression): string | null {
  const callee = call.expression;
  if (ts.isIdentifier(callee)) return callee.text;
  if (ts.isPropertyAccessExpression(callee)) return callee.name.text;
  return null;
}

/** The function a node sits in, when that function is a named `use*` hook. */
function enclosingHookName(node: ts.Node): string | null {
  for (let at: ts.Node | undefined = node.parent; at; at = at.parent) {
    if (ts.isFunctionDeclaration(at) && at.name) return /^use[A-Z]/.test(at.name.text) ? at.name.text : null;
    if ((ts.isArrowFunction(at) || ts.isFunctionExpression(at)) && ts.isVariableDeclaration(at.parent)) {
      const name = at.parent.name;
      return ts.isIdentifier(name) && /^use[A-Z]/.test(name.text) ? name.text : null;
    }
    if (ts.isFunctionLike(at)) return null;
  }
  return null;
}

/** Is this call the value a hook returns (directly, or as an arrow body)? */
function isReturned(call: ts.CallExpression): boolean {
  let node: ts.Node = call;
  while (ts.isParenthesizedExpression(node.parent) || ts.isAsExpression(node.parent)) node = node.parent;
  return ts.isReturnStatement(node.parent) || ts.isArrowFunction(node.parent);
}

/** Calls to `useMutation` or a known mutation hook, anywhere in a file. */
function mutationCalls(file: ts.SourceFile, hooks: Set<string>): ts.CallExpression[] {
  const calls: ts.CallExpression[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node)) {
      const name = calleeName(node);
      if (name !== null && hooks.has(name)) calls.push(node);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return calls;
}

/** Every hook that returns a mutation, to a fixed point. */
function mutationHooks(): Set<string> {
  const hooks = new Set(["useMutation"]);
  for (let grew = true; grew; ) {
    grew = false;
    for (const { file } of FILES) {
      for (const call of mutationCalls(file, hooks)) {
        if (!isReturned(call)) continue;
        const owner = enclosingHookName(call);
        if (owner && !hooks.has(owner)) {
          hooks.add(owner);
          grew = true;
        }
      }
    }
  }
  return hooks;
}

/** Names passed as the first argument of `useActionFeedback(...)` in a file. */
function namesGivenFeedback(file: ts.SourceFile): Set<string> {
  const names = new Set<string>();
  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node) && calleeName(node) === "useActionFeedback") {
      const first = node.arguments[0];
      if (first && ts.isIdentifier(first)) names.add(first.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return names;
}

const HOOKS = mutationHooks();

/** `file::name` for every screen mutation that never reaches `useActionFeedback`. */
function violations(): string[] {
  const found: string[] = [];
  for (const { rel, file } of FILES) {
    if (!SCREEN_ROOTS.some((root) => rel.startsWith(root))) continue;
    const given = namesGivenFeedback(file);
    for (const call of mutationCalls(file, HOOKS)) {
      if (isReturned(call) && enclosingHookName(call)) continue;
      const declaration = call.parent;
      if (ts.isVariableDeclaration(declaration) && ts.isIdentifier(declaration.name)) {
        if (!given.has(declaration.name.text)) found.push(`${rel}::${declaration.name.text}`);
      } else {
        found.push(`${rel}::<unnamed ${calleeName(call)}>`);
      }
    }
  }
  return [...new Set(found)].sort();
}

describe("every mutation a screen starts gives feedback", () => {
  const found = violations();

  it("reads a real tree and finds the mutation hooks it claims to", () => {
    expect(FILES.length).toBeGreaterThan(300);
    // Hooks the API modules export and screens call; if these stop being found the scan
    // has stopped matching, which would look exactly like a clean tree.
    expect(HOOKS.has("useCreateCredential")).toBe(true);
    expect(HOOKS.size).toBeGreaterThan(100);
  });

  it("has no new mutation without useActionFeedback", () => {
    const baseline = new Set(FEEDBACK_BASELINE);
    const fresh = found.filter((site) => !baseline.has(site));
    expect(
      fresh,
      `assign the mutation to a name and pass it to useActionFeedback (docs/design/KIT.md):\n${fresh.join("\n")}`,
    ).toEqual([]);
  });

  it("keeps the baseline a ratchet: entries that now comply or are gone come off", () => {
    const now = new Set(found);
    const stale = FEEDBACK_BASELINE.filter((site) => !now.has(site));
    expect(
      stale,
      `these now give feedback (or no longer exist); remove them from tests/fixtures/feedbackBaseline.ts:\n${stale.join("\n")}`,
    ).toEqual([]);
  });

  it("would catch a mutation that skips the standard", () => {
    const sample = ts.createSourceFile(
      "sample.tsx",
      "function Screen(){ const save = useMutation({}); const done = useMutation({}); useActionFeedback(done, {errorTitle: 'x'}); }",
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    );
    const given = namesGivenFeedback(sample);
    const named = mutationCalls(sample, new Set(["useMutation"])).map((c) =>
      ts.isVariableDeclaration(c.parent) && ts.isIdentifier(c.parent.name) ? c.parent.name.text : "?",
    );
    expect(named.filter((n) => !given.has(n))).toEqual(["save"]);
  });
});
