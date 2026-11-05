import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PromoWarning } from "@/app/c/[slug]/agents/[agentId]/script/PromoWarning";
import type { Session } from "@/lib/api/client";

/**
 * The offer check names the languages it could not read (`PromoReportOut.not_checked_in`),
 * so a script it could not read is never shown as checked.
 */

let report: unknown = null;

vi.mock("@/lib/api/compliancePack", () => ({
  useAgentPromoCheck: () => ({ data: report ? { report } : undefined }),
}));
vi.mock("@/components/copilot/AskAssistant", () => ({
  AskAssistant: ({ label }: { label: string }) => <button type="button">{label}</button>,
}));

const SESSION = {} as Session;

describe("PromoWarning", () => {
  it("names the languages the check could not read", () => {
    report = {
      verdict: "check",
      blocks_launch: false,
      findings: [],
      truncated: false,
      fix: "",
      not_checked_in: ["Tamil", "Kannada"],
    };
    render(<PromoWarning session={SESSION} agentId="a1" agentName="Asha" />);
    expect(screen.getByText("Not checked in Tamil, Kannada")).toBeTruthy();
    expect(screen.getByText("Read these lines yourself")).toBeTruthy();
  });

  it("says nothing about languages when every line was read", () => {
    report = {
      verdict: "check",
      blocks_launch: false,
      findings: [{ where: "Opening line", phrase: "free", quote: "free parking", kind: "x", why: "" }],
      truncated: false,
      fix: "",
      not_checked_in: [],
    };
    render(<PromoWarning session={SESSION} agentId="a1" agentName="Asha" />);
    expect(screen.queryByText(/Not checked in/)).toBeNull();
    expect(screen.getByText("Check these lines")).toBeTruthy();
  });
});
