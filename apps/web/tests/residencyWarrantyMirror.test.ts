import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { DPA } from "../src/lib/legal/dpa";

/**
 * THE DPA MAKES AN EXPRESS WARRANTY ABOUT A CODE MECHANISM, AND PROSE OUTLIVES MECHANISMS.
 *
 * Clause 9 warrants that our software cannot send a language-model request outside an
 * Indian region "without a change to our source code that declares a different residency
 * posture in a named constant — a change our build rejects until every other file agrees
 * with that declaration". That is a claim about three things existing: the declaration,
 * the guard that compares it against the tree, and the refusal to let any runtime control
 * move it.
 *
 * It has already been false once. The sentence previously said no such change could pass
 * the build at all, which was true while the region was welded into ~30 files agreeing
 * with each other — and stopped being true the moment the posture became a declared,
 * switchable constant. Nothing caught that: a contract sentence has no compiler. The two
 * lanes that touched the two halves reached opposite conclusions about whether it still
 * held, which is exactly what an unpinned claim produces.
 *
 * So the warranty is pinned to its mechanism the way `agentTransitionsMirror` pins the
 * client's transition table to the server's. This does not check that the mechanism is
 * CORRECT — `scripts/check_model_residency.py` and `tests/residency_posture_test.py` own
 * that — only that the thing the contract describes to a client is still there to describe.
 */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const CONTRACT = resolve(REPO_ROOT, "packages/shared/src/calevate_shared/engine.py");
const GUARD = resolve(REPO_ROOT, "scripts/check_model_residency.py");

function warrantyText(): string {
  const section = DPA.sections.find((s) => s.id === "transfers");
  expect(section, "the DPA no longer has a `transfers` section").toBeDefined();
  return JSON.stringify(section);
}

describe("the DPA's residency warranty and the mechanism it describes", () => {
  it("still describes a posture declared in a named constant that exists", () => {
    const text = warrantyText();
    expect(text).toContain("declares a different residency posture in a named constant");
    expect(
      readFileSync(CONTRACT, "utf8"),
      "the DPA warrants a posture declared in a named constant; the portability contract " +
        "declares none. Either the mechanism moved and the warranty is now false to a " +
        "client, or the constant was renamed and this test should follow it.",
    ).toMatch(/^DECLARED_POSTURE_NAME:\s*Final\s*=/m);
  });

  it("still describes a build that rejects a declaration the tree disagrees with", () => {
    expect(warrantyText()).toContain("rejects until every other file agrees");
    const guard = readFileSync(GUARD, "utf8");
    expect(
      guard,
      "the DPA warrants that our build rejects a posture declaration the rest of the " +
        "tree has not been moved to. The residency guard no longer reads the declaration, " +
        "so nothing compares the two and the warranty describes a check that is gone.",
    ).toContain("declared_posture_name");
  });

  it("still refuses to let anything but a commit move the posture", () => {
    const text = warrantyText();
    expect(text).toContain("no configuration setting may carry a region, an endpoint or a posture");
    expect(text).toContain("only a reviewed commit can");
    expect(
      readFileSync(GUARD, "utf8"),
      "the DPA warrants that no setting can carry a posture. The guard no longer refuses " +
        "that name fragment, so a `Settings.residency_posture` would now pass — which is " +
        "the console-editable posture D-95 §4 forbids.",
    ).toContain("posture");
  });
});
