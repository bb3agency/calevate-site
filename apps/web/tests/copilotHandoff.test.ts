import { describe, expect, it } from "vitest";

import { PRACTICE_CALLERS_ANCHOR, handoffFor } from "@/lib/copilot/handoff";

describe("where a confirmed Pip action's result waits", () => {
  it("takes suggested fixes to the agent's Practice callers card", () => {
    expect(handoffFor("agent_tests_fix", "acme", "agent-1")).toEqual({
      label: "Go to the fixes",
      path: `/c/acme/agents/agent-1?section=training#${PRACTICE_CALLERS_ANCHOR}`,
    });
  });

  it("takes a script suggestion to the Script tab", () => {
    expect(handoffFor("agent_script_suggest", "acme", "agent-1")?.path).toBe("/c/acme/agents/agent-1?section=script");
  });

  it("offers no link for an action whose result is already on screen", () => {
    expect(handoffFor("lead_set_status", "acme", "lead-1")).toBeNull();
    expect(handoffFor("agent_tests_fix", "acme", "")).toBeNull();
  });
});
