import { describe, expect, it } from "vitest";

import {
  addSection,
  connect,
  edgesOf,
  moveSection,
  removeSection,
  sectionDetail,
  sectionsOf,
  setPosition,
  updateSection,
  validate,
  chars,
  scriptAsText,
} from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { applyChanges, changeSummary, diffScripts } from "@/app/c/[slug]/agents/[agentId]/script/scriptDiff";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

/**
 * The flow canvas and the numbered list are two views of `script.stages`. These pin that
 * there is nothing else: order, branches and content come from one array, every edit is a
 * new array, and what the server would refuse is caught before an autosave sends it.
 */

function stage(id: string, name: string, extra: Partial<ConversationStage> = {}): ConversationStage {
  return { id, name, mode: "guide", instruction: `Do ${name}`, sounds_like: "", branches: [], otherwise: "", collect: [], position: null, ...extra };
}

function script(...stages: ConversationStage[]): CallScript {
  return { ...EMPTY_SCRIPT, stages };
}

const ids = (s: CallScript) => sectionsOf(s).map((x) => x.id);

describe("one model for the canvas and the list", () => {
  const base = script(stage("greet", "Greet"), stage("need", "Find the need"), stage("close", "Close"));

  it("numbers both views from the array order, so a reorder renumbers both", () => {
    const moved = moveSection(base, 2, 0);
    expect(ids(moved)).toEqual(["close", "greet", "need"]);
    // The canvas's implied "then" arrows follow the new order too.
    expect(edgesOf(sectionsOf(moved)).filter((e) => e.kind === "next")).toEqual([
      { from: "close", to: "greet", kind: "next", label: "Then" },
      { from: "greet", to: "need", kind: "next", label: "Then" },
    ]);
  });

  it("keeps a branch on the section it leaves through a reorder", () => {
    const branched = updateSection(base, "need", { branches: [{ when: "they say no", target: "close" }] });
    const moved = moveSection(branched, 1, 2);
    expect(sectionsOf(moved).find((s) => s.id === "need")?.branches).toEqual([{ when: "they say no", target: "close" }]);
    expect(edgesOf(sectionsOf(moved))).toContainEqual({ from: "need", to: "close", kind: "branch", label: "they say no", branch: 0 });
  });

  it("joins sections from the canvas: first as the way on, then as a branch to describe", () => {
    const first = connect(base, "greet", "close");
    expect(first.branch).toBeNull();
    expect(sectionsOf(first.script)[0].otherwise).toBe("close");
    const second = connect(first.script, "greet", "need");
    expect(second.branch).toBe(0);
    expect(sectionsOf(second.script)[0].branches).toEqual([{ when: "", target: "need" }]);
    // The empty condition is what the editor asks the owner to fill in before it saves.
    expect(validate(second.script).map((i) => i.field)).toContain("branch-0");
    expect(connect(second.script, "greet", "greet").script).toBe(second.script);
  });

  it("removes every way into a deleted section, so nothing points nowhere", () => {
    const wired = updateSection(updateSection(base, "greet", { otherwise: "close" }), "need", {
      branches: [{ when: "busy", target: "close" }, { when: "ready", target: "greet" }],
    });
    const after = removeSection(wired, "close");
    expect(ids(after)).toEqual(["greet", "need"]);
    expect(sectionsOf(after)[0].otherwise).toBe("");
    expect(sectionsOf(after)[1].branches).toEqual([{ when: "ready", target: "greet" }]);
    expect(validate(after)).toEqual([]);
  });

  it("stores a canvas move as a position and nothing else", () => {
    const moved = setPosition(base, "need", { x: 120.6, y: 40.2 });
    expect(sectionsOf(moved)[1].position).toEqual({ x: 121, y: 40 });
    expect(ids(moved)).toEqual(ids(base));
  });

  it("gives a new section an id the server accepts and a name nobody else has", () => {
    const one = addSection(script(stage("section-1", "Section 1")));
    expect(one.id).toMatch(/^[a-z0-9][a-z0-9_-]{0,39}$/);
    const names = sectionsOf(one.script).map((s) => s.name);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe("what the server would refuse, caught first", () => {
  it("names an unknown target, a duplicate name and an empty section", () => {
    const bad = script(
      stage("a", "Greet", { branches: [{ when: "x", target: "gone" }] }),
      stage("b", "greet"),
      stage("c", "", { instruction: "  " }),
    );
    const messages = validate(bad).map((i) => `${i.section}:${i.field}`);
    expect(messages).toContain("a:branch-0");
    expect(messages).toContain("b:name");
    expect(messages).toContain("c:name");
    expect(messages).toContain("c:instruction");
  });

  it("counts the instruction and the sounds-like line together, as the server does", () => {
    const s = stage("a", "A", { mode: "say", instruction: 'Hello  "friend"', sounds_like: "నమస్కారం" });
    expect(sectionDetail({ mode: s.mode!, instruction: s.instruction, sounds_like: s.sounds_like! })).toBe(
      "Say: \"Hello 'friend'\" It sounds like: \"నమస్కారం\"",
    );
    const long = script(stage("a", "A", { instruction: "x".repeat(590), sounds_like: "y".repeat(20) }));
    expect(validate(long).some((i) => i.field === "instruction" && i.message.includes("too long"))).toBe(true);
    expect(chars("👋")).toBe(1);
  });

  it("refuses more than twelve sections and more than six ways out", () => {
    const many = script(...Array.from({ length: 13 }, (_, i) => stage(`s${i}`, `S${i}`)));
    expect(validate(many).some((i) => i.field === "sections")).toBe(true);
    const branches = Array.from({ length: 7 }, (_, i) => ({ when: `w${i}`, target: "end" }));
    expect(validate(script(stage("a", "A", { branches }))).some((i) => i.field === "branches")).toBe(true);
  });

  it("does not check the sections of a hand-written script", () => {
    expect(validate({ ...EMPTY_SCRIPT, raw_override: "anything" })).toEqual([]);
  });
});

describe("AI proposals, kept part by part", () => {
  const current = script(stage("greet", "Greet"), stage("price", "Price"));

  it("lists each change and applies only the kept ones", () => {
    const proposal: CallScript = {
      ...current,
      opening_line: "Namaskaram",
      stages: [
        stage("greet", "Greet", { instruction: "Greet warmly" }),
        stage("new-1", "Delivery", { branches: [{ when: "far", target: "end" }] }),
      ],
    };
    const changes = diffScripts(current, proposal);
    expect(changes.map((c) => c.id).sort()).toEqual(["add:new-1", "change:greet", "part:opening_line", "remove:price"]);

    const kept = applyChanges(current, proposal, new Set(["change:greet", "add:new-1"]));
    expect(kept.opening_line).toBe("");
    expect(ids(kept)).toEqual(["greet", "new-1", "price"]);
    expect(sectionsOf(kept)[0].instruction).toBe("Greet warmly");
    expect(validate(kept)).toEqual([]);
  });

  it("drops a kept way out that points at a discarded addition", () => {
    const proposal = script(stage("greet", "Greet", { branches: [{ when: "ready", target: "pay" }] }), stage("price", "Price"), stage("pay", "Pay"));
    const kept = applyChanges(current, proposal, new Set(["change:greet"]));
    expect(sectionsOf(kept)[0].branches).toEqual([]);
  });

  it("matches a section by name when the AI gave it a new id", () => {
    const proposal = script(stage("x1", "Greet"), stage("x2", "Price", { instruction: "Say the price" }));
    expect(diffScripts(current, proposal).map((c) => c.id)).toEqual(["change:price"]);
  });

  it("writes the history note from what changed", () => {
    const draft = updateSection(current, "price", { instruction: "new" });
    expect(changeSummary(current, draft)).toBe('Changed "Price"');
    expect(changeSummary(current, moveSection(current, 0, 1))).toBe("Changed the order of the sections");
  });

  it("copies sections into text when the owner switches to writing by hand", () => {
    const wired = updateSection(current, "greet", { branches: [{ when: "angry", target: "hand_over" }] });
    const text = scriptAsText(wired);
    expect(text).toContain("1. Greet: Do Greet");
    expect(text).toContain("When angry: hand the caller to a person.");
  });
});
