import { describe, expect, it } from "vitest";

import { leadVarOptions } from "@/app/c/[slug]/agents/actions/params";

describe("'From the lead' options for an action parameter", () => {
  it("marks a stored binding stale only when the agent's captured details were read", () => {
    const read = leadVarOptions([{ key: "budget", label: "Budget" }], "field:area");
    expect(read.find((o) => o.value === "field:area")?.label).toBe("area (no longer captured)");
    expect(read.find((o) => o.value === "field:budget")?.label).toBe("Budget");
  });

  it("lists a stored binding by its key, with no claim, while the agent is unread", () => {
    const unread = leadVarOptions(null, "field:area");
    expect(unread.find((o) => o.value === "field:area")?.label).toBe("area");
  });
});
