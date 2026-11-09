import { describe, expect, it } from "vitest";

import { warningRows } from "@/app/c/[slug]/agents/[agentId]/script/PutLive";

const REACH =
  "asks how the caller uses or likes it, and the call can reach it before step 9 helps them set it up, when they cannot answer it; ask it only on the way for callers who already had it, and after setting it up show them the first thing to do.";
const SAME = "says nearly what the opening line says; explain each thing in one step, and have this step move the call on (answer what they asked, or the next thing to do).";

describe("the put-live warnings read as rows", () => {
  it("groups one problem several steps share, and puts what to do under it", () => {
    const rows = warningRows([`Step 7: ${REACH}`, `Step 8: ${REACH}`, `Step 1: ${SAME}`]);
    expect(rows).toHaveLength(2);
    expect(rows[0].where).toBe("Steps 7 and 8");
    expect(rows[0].problem).toBe(
      "asks how the caller uses or likes it, and the call can reach it before step 9 helps them set it up, when they cannot answer it",
    );
    expect(rows[0].advice.startsWith("Ask it only on the way")).toBe(true);
    expect(rows[1]).toMatchObject({ where: "Step 1", problem: "says nearly what the opening line says" });
  });

  it("keeps a warning with no place or no advice whole", () => {
    expect(warningRows(["Too long for one breath."])).toEqual([
      { where: "", problem: "Too long for one breath.", advice: "" },
    ]);
  });
});
