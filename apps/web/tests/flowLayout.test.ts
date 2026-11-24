import { describe, expect, it } from "vitest";

import { OPENING_KEY, layoutFlow, type Box, type FlowLayout, type Point } from "@/app/c/[slug]/campaigns/flowLayout";
import { placed } from "@/app/c/[slug]/campaigns/scenarioModel";
import { CALL_BACK, END, SPECIAL_TARGETS, sectionsOf } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { EMPTY_SCRIPT, type ConversationStage } from "@/lib/api/script";

/** How the call-flow canvas routes links: none behind a card, every one from its own source. */

const stage = (over: Partial<ConversationStage>): ConversationStage => ({
  id: "a",
  name: "A",
  mode: "guide",
  instruction: "",
  sounds_like: "",
  branches: [],
  otherwise: "",
  collect: [],
  procedure: [],
  position: null,
  step: 1,
  scripts: {},
  qa: [],
  coaching: [],
  ...over,
});

// The shape of the Rytu Khata flow the founder reported: 1.1 goes on to 2.1 and skips to
// 3.1, 2.1 has no next, and 3.1 loops back to 1.1.
const RYTU = [
  stage({
    id: "install",
    name: "Install app",
    step: 1,
    branches: [
      { when: "Android installation", target: "android" },
      { when: "Setup farms", target: "farms" },
    ],
  }),
  stage({ id: "android", name: "Android installation", step: 2 }),
  stage({ id: "farms", name: "Setup farms", step: 3, branches: [{ when: "Not installed yet", target: "install" }] }),
];

const lay = (stages: ConversationStage[], opening = true) =>
  layoutFlow(placed(sectionsOf({ ...EMPTY_SCRIPT, stages })), SPECIAL_TARGETS, opening ? { notNow: CALL_BACK } : null);

/** Strictly inside: a link may touch the edge it enters or leaves. */
const inside = (p: Point, b: Box) => p.x > b.x + 1 && p.x < b.x + b.w - 1 && p.y > b.y + 1 && p.y < b.y + b.h - 1;

const cards = (l: FlowLayout): [string, Box][] => [
  ...l.boxes.entries(),
  ...(l.opening ? ([[OPENING_KEY, l.opening]] as [string, Box][]) : []),
  ...(l.notNow ? ([["not-now", l.notNow.box]] as [string, Box][]) : []),
];

const linkOf = (l: FlowLayout, from: string, to: string) => {
  const found = l.links.find((k) => k.from === from && k.to === to);
  if (!found) throw new Error(`no link ${from} -> ${to}`);
  return found;
};

describe("call flow routing", () => {
  it("draws a loop back over the cards, never behind one", () => {
    const l = lay(RYTU);
    const back = linkOf(l, "farms", "install");
    expect(back.kind).toBe("back");
    for (const [id, b] of cards(l)) {
      expect(back.samples.filter((p) => inside(p, b)), `back link enters ${id}`).toEqual([]);
    }
    // It rises above the cards and comes down into the left edge of 1.1, not in from the
    // canvas's edge.
    const target = l.boxes.get("install") as Box;
    expect(Math.min(...back.samples.map((p) => p.y))).toBeLessThan(l.cardTop);
    expect(Math.min(...back.samples.map((p) => p.x))).toBeGreaterThan(target.x - 88);
    expect(back.end.x).toBe(target.x);
    expect(back.end.y).toBeGreaterThan(target.y);
    expect(back.end.y).toBeLessThan(target.y + target.h);
    // It meets 1.1 at its own point, not on the opening's arrowhead.
    expect(back.end).not.toEqual(linkOf(l, OPENING_KEY, "install").end);
    const from = l.boxes.get("farms") as Box;
    expect(back.samples[0]).toEqual({ x: from.x + from.w, y: from.y + from.h / 2 });
  });

  it("runs a link that skips a step between the rows, round the middle card", () => {
    const l = lay(RYTU);
    const skip = linkOf(l, "install", "farms");
    expect(skip.kind).toBe("skip");
    const middle = l.boxes.get("android") as Box;
    expect(skip.samples.filter((p) => inside(p, middle))).toEqual([]);
    for (const [id, b] of cards(l)) {
      expect(skip.samples.filter((p) => inside(p, b)), `skip link enters ${id}`).toEqual([]);
    }
  });

  it("never starts a line beside a box that has no next", () => {
    const l = lay(RYTU);
    const quiet = l.boxes.get("android") as Box;
    const dot = { x: quiet.x + quiet.w, y: quiet.y + quiet.h / 2 };
    for (const link of l.links) {
      const near = link.samples.filter((p) => Math.hypot(p.x - dot.x, p.y - dot.y) < 16);
      expect(near, `${link.key} passes 2.1's dot`).toEqual([]);
    }
  });

  it("keeps every link out of every card and off every other link", () => {
    const stages = [
      ...RYTU.slice(0, 2),
      stage({ id: "android2", name: "iPhone", step: 2, branches: [{ when: "Done", target: "install" }] }),
      stage({
        id: "farms",
        name: "Setup farms",
        step: 3,
        branches: [
          { when: "Not installed yet", target: "install" },
          { when: "The call is done", target: END },
        ],
      }),
      stage({ id: "farms2", name: "Crops", step: 3, branches: [{ when: "Forgot", target: "android" }] }),
    ];
    stages[0] = { ...stages[0], branches: [...(stages[0].branches ?? []), { when: "Busy", target: END }] };
    const l = lay(stages);
    for (const link of l.links)
      for (const [id, b] of cards(l))
        expect(link.samples.filter((p) => inside(p, b)), `${link.key} enters ${id}`).toEqual([]);
    // Two links may cross; they never run along each other, except where links of one source
    // fan out of its one dot, or links into one card meet at its edge.
    const orthogonal = l.links.filter((k) => k.kind === "back" || k.kind === "skip");
    for (const a of orthogonal)
      for (const b of l.links) {
        if (a === b) continue;
        const start = a.samples[0];
        const fanning = (p: Point) =>
          (a.from === b.from && Math.hypot(p.x - start.x, p.y - start.y) <= 48) ||
          (a.to === b.to && Math.hypot(p.x - a.end.x, p.y - a.end.y) <= 48);
        const shared = a.samples.filter(
          (p) => !fanning(p) && b.samples.some((q) => Math.hypot(p.x - q.x, p.y - q.y) < 1.5),
        );
        expect(shared.length, `${a.key} runs along ${b.key}`).toBeLessThan(6);
      }
  });

  it("starts the flow at the opening, linked into every step-1 scenario", () => {
    const stages = [stage({ id: "one", step: 1 }), stage({ id: "two", step: 1 }), stage({ id: "three", step: 2 })];
    const l = lay(stages);
    expect(l.opening).not.toBeNull();
    const fromOpening = l.links.filter((k) => k.from === OPENING_KEY && k.kind !== "not-now").map((k) => k.to);
    expect(fromOpening).toEqual(["one", "two"]);
    const opening = l.opening as Box;
    expect(opening.x + opening.w).toBeLessThan((l.boxes.get("one") as Box).x);
    expect(l.notNow?.target).toBe(CALL_BACK);
    expect(lay(stages, false).opening).toBeNull();
  });
});
