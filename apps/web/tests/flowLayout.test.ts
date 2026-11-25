import { describe, expect, it } from "vitest";

import { BOX_H, OPENING_KEY, layoutFlow, thenOf, type Box, type FlowLayout, type Point } from "@/app/c/[slug]/campaigns/flowLayout";
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
    expect(back.samples[0]).toEqual({ x: from.x + from.w, y: from.y + BOX_H / 2 });
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

  it("never starts a line beside a box but its own", () => {
    const l = lay(RYTU);
    const quiet = l.boxes.get("android") as Box;
    const dot = { x: quiet.x + quiet.w, y: quiet.y + quiet.h / 2 };
    // 2.1's only line is its own way on to step 3; no other link surfaces at its dot.
    for (const link of l.links.filter((k) => k.from !== "android")) {
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
    const fromOpening = l.links.filter((k) => k.from === OPENING_KEY).map((k) => k.to);
    expect(fromOpening).toEqual(["one", "two"]);
    const opening = l.opening as Box;
    expect(opening.x + opening.w).toBeLessThan((l.boxes.get("one") as Box).x);
    expect(lay(stages, false).opening).toBeNull();
  });
});

describe("ways out to an end point", () => {
  // The founder's eight-step flow had a call back or an end on most scenarios, each drawn as a
  // line across every step to a column of end nodes.
  const ENDED = [
    stage({
      id: "intro",
      step: 1,
      branches: [
        { when: "Busy", target: CALL_BACK },
        { when: "Not interested", target: END },
        { when: "Ready", target: "login" },
      ],
    }),
    stage({ id: "login", step: 2, branches: [{ when: "Busy", target: CALL_BACK }] }),
    stage({ id: "lang", step: 3, otherwise: "lang", branches: [{ when: "Asks again", target: "lang" }] }),
    stage({ id: "close", step: 4, otherwise: END }),
  ];

  it("draws no line to an end point and puts each on its scenario as a chip", () => {
    const l = lay(ENDED);
    for (const end of SPECIAL_TARGETS) {
      expect(l.links.filter((k) => k.to === end)).toEqual([]);
      expect(l.boxes.has(end)).toBe(false);
    }
    expect(l.exits.get("intro")).toEqual([
      { key: "intro-0", target: CALL_BACK, when: "Busy", via: "branch" },
      { key: "intro-1", target: END, when: "Not interested", via: "branch" },
    ]);
    expect(l.exits.get("close")).toEqual([{ key: "close-otherwise", target: END, when: "", via: "otherwise" }]);
    // The step-to-step branch is still a line, under the same key as before.
    expect(linkOf(l, "intro", "login").key).toBe("intro-2");
  });

  it("draws no loop for a scenario that stays where it is", () => {
    const l = lay(ENDED);
    expect(l.links.filter((k) => k.from === "lang" && k.to === "lang")).toEqual([]);
    // A branch back into itself is a chip; the Otherwise is the card's own Then line.
    expect(l.exits.get("lang")?.map((x) => x.key)).toEqual(["lang-0"]);
    const items = placed(sectionsOf({ ...EMPTY_SCRIPT, stages: ENDED }));
    expect(thenOf(items[2], 4)).toEqual({ kind: "stay" });
  });

  it("makes a row as tall as its card with the most chips", () => {
    const l = lay(ENDED);
    const intro = l.boxes.get("intro") as Box;
    const login = l.boxes.get("login") as Box;
    expect(intro.h).toBeGreaterThan(112);
    // Row 1 lines up across the columns, whatever each card holds.
    expect(login.h).toBe(intro.h);
    expect(login.y).toBe(intro.y);
    for (const link of l.links)
      for (const [id, b] of cards(l))
        expect(link.samples.filter((p) => inside(p, b)), `${link.key} enters ${id}`).toEqual([]);
  });
});

describe("the call's own order", () => {
  // The founder's flow after a Pip rewrite: no scenario had a next, and none looked connected.
  const LOOSE = [
    stage({ id: "login", name: "Login", step: 1 }),
    stage({ id: "farms", name: "Add farms", step: 2 }),
    stage({ id: "farms2", name: "No farm yet", step: 2 }),
    stage({ id: "expenses", name: "Enter expenses", step: 3 }),
  ];
  const implicit = (l: FlowLayout) => l.links.filter((k) => k.via === "then");

  it("goes on to every scenario of the next step from a scenario with no Otherwise", () => {
    const l = lay(LOOSE);
    expect(implicit(l).map((k) => `${k.from}>${k.to}`)).toEqual([
      "login>farms",
      "login>farms2",
      "farms>expenses",
      "farms2>expenses",
    ]);
    for (const link of implicit(l)) {
      expect(link.kind).toBe("next");
      for (const [id, b] of cards(l))
        expect(link.samples.filter((p) => inside(p, b)), `${link.key} enters ${id}`).toEqual([]);
    }
    // The last step goes on to nothing drawn: the call ends there.
    expect(l.links.filter((k) => k.from === "expenses")).toEqual([]);
  });

  it("gives way to an Otherwise, which is drawn as the way it goes", () => {
    const stages = [{ ...LOOSE[0], otherwise: "farms2" }, ...LOOSE.slice(1)];
    const l = lay(stages);
    expect(implicit(l).filter((k) => k.from === "login")).toEqual([]);
    const otherwise = linkOf(l, "login", "farms2");
    expect(otherwise.via).toBe("otherwise");
    // An Otherwise to an end point is a chip on its scenario, and still stops the call's order.
    const ended = lay([{ ...LOOSE[0], otherwise: END }, ...LOOSE.slice(1)]);
    expect(ended.links.filter((k) => k.from === "login")).toEqual([]);
    expect(ended.exits.get("login")?.map((x) => x.via)).toEqual(["otherwise"]);
  });

  it("never doubles a link the scenario already has, nor the opening's", () => {
    const stages = [{ ...LOOSE[0], branches: [{ when: "Add farms", target: "farms" }] }, ...LOOSE.slice(1)];
    const l = lay(stages);
    const pairs = l.links.map((k) => `${k.from}>${k.to}`);
    expect(new Set(pairs).size).toBe(pairs.length);
    expect(linkOf(l, "login", "farms").via).toBe("branch");
    expect(linkOf(l, "login", "farms2").via).toBe("then");
    expect(linkOf(l, OPENING_KEY, "login").via).toBe("opening");
    expect(implicit(l).some((k) => k.from === OPENING_KEY || k.to === "login")).toBe(false);
  });

  it("names where each scenario goes when no way out applies", () => {
    const items = placed(sectionsOf({ ...EMPTY_SCRIPT, stages: [{ ...LOOSE[0], otherwise: END }, ...LOOSE.slice(1)] }));
    expect(items.map((p) => thenOf(p, 3))).toEqual([
      { kind: "otherwise", target: END },
      { kind: "step", step: 3 },
      { kind: "step", step: 3 },
      { kind: "end" },
    ]);
  });
});
