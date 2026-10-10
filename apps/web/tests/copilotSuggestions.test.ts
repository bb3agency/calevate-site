import { describe, expect, it } from "vitest";

import { suggestedQuestions } from "@/lib/copilot/suggestions";

/**
 * The assistant's empty panel offers questions worth asking ON THIS SCREEN (REDESIGN-2).
 * Routes arrive either as a declared pattern or as the fallback's masked path, so both
 * spellings must pick the same screen.
 */
describe("suggested questions", () => {
  it("picks the screen from either route spelling", () => {
    expect(suggestedQuestions("/c/{slug}/calls")).toEqual(suggestedQuestions("/c/:hidden/calls"));
    expect(suggestedQuestions("/c/{slug}/calls/{callId}")).not.toEqual(suggestedQuestions("/c/{slug}/calls"));
    expect(suggestedQuestions("/c/{slug}")).toContain("What needs me today?");
  });

  it("offers three or four plain questions everywhere, with no glyphs", () => {
    for (const route of ["/c/x", "/c/x/leads", "/c/x/leads/1", "/c/x/agents/1", "/c/x/billing", "/c/x/settings/team", "/admin"]) {
      const questions = suggestedQuestions(route);
      expect(questions.length).toBeGreaterThanOrEqual(3);
      expect(questions.length).toBeLessThanOrEqual(4);
      for (const q of questions) expect(q).toMatch(/^[A-Z][^\p{Extended_Pictographic}]*$/u);
    }
  });

  it("falls back for a screen it does not know and for the admin realm", () => {
    expect(suggestedQuestions("/admin/tenants")).toEqual(suggestedQuestions("/c/x/nowhere"));
  });
});
