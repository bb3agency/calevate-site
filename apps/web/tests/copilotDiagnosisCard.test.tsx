/**
 * Pip's troubleshoot card (D-935): the first problem open with its one button, the passed
 * checks folded away, an unknown never shown as a pass.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DiagnosisCard } from "../src/components/copilot/DiagnosisCard";
import type { CopilotDiagnosis } from "../src/lib/copilot/types";

const NO_NUMBER: CopilotDiagnosis = {
  family: "agent",
  subject: "Why Sindhu did not pick up",
  verdict: "No phone number is attached to Sindhu.",
  checks: [
    { key: "agent", label: "The agent is switched on", status: "ok", detail: "Sindhu is live." },
    { key: "credit", label: "There is credit to answer calls", status: "ok", detail: "There is credit." },
    {
      key: "number",
      label: "A number rings this agent",
      status: "problem",
      detail: "No phone number is attached to Sindhu.",
      fix: { label: "Attach a number", ask: "Attach a phone number to Sindhu" },
    },
    { key: "drift", label: "The agent on the phone matches what you saved", status: "unknown", detail: "Not checked yet." },
  ],
};

describe("the troubleshoot card", () => {
  it("leads with the first cause and asks Pip for its fix", () => {
    const onAsk = vi.fn();
    render(<DiagnosisCard diagnosis={NO_NUMBER} onAsk={onAsk} />);
    expect(screen.getByRole("region", { name: "Why Sindhu did not pick up" })).toBeTruthy();
    expect(screen.getByText("No phone number is attached to Sindhu.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Attach a number" }));
    expect(onAsk).toHaveBeenCalledWith("Attach a phone number to Sindhu");
  });

  it("folds the other checks and never shows an unknown as passed", () => {
    render(<DiagnosisCard diagnosis={NO_NUMBER} onAsk={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: /2 of 3 other checks passed/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Sindhu is live.")).toBeNull();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Sindhu is live.")).toBeTruthy();
    expect(screen.getByText("Not checked: Not checked yet.")).toBeTruthy();
  });

  it("disables the fix while Pip is answering", () => {
    render(<DiagnosisCard diagnosis={NO_NUMBER} onAsk={vi.fn()} asking />);
    expect(
      (screen.getByRole("button", { name: "Attach a number" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("opens a console screen through the panel's navigator", () => {
    const onNavigate = vi.fn();
    const diagnosis: CopilotDiagnosis = {
      ...NO_NUMBER,
      checks: [
        {
          key: "credit",
          label: "There is credit to answer calls",
          status: "problem",
          detail: "Your credit has run out, so agents stop answering.",
          fix: {
            label: "Add credit",
            screen: "Credits & billing",
            route: "/c/{slug}/billing",
            where: "Credits & billing, under Settings & account in the left sidebar",
          },
        },
      ],
    };
    render(<DiagnosisCard diagnosis={diagnosis} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole("button", { name: "Add credit" }));
    expect(onNavigate).toHaveBeenCalledWith({
      route: "/c/{slug}/billing",
      screen: "Credits & billing",
      where: "Credits & billing, under Settings & account in the left sidebar",
    });
  });

  it("says the next step in words where it cannot act (the admin console)", () => {
    render(<DiagnosisCard diagnosis={NO_NUMBER} />);
    expect(screen.queryByRole("button", { name: "Attach a number" })).toBeNull();
    expect(screen.getByText("Next step: Attach a phone number to Sindhu.")).toBeTruthy();
  });

  it("says everything checked out when nothing is wrong", () => {
    const fine: CopilotDiagnosis = {
      ...NO_NUMBER,
      verdict: "Everything we checked looks fine.",
      checks: NO_NUMBER.checks.filter((check) => check.status === "ok"),
    };
    render(<DiagnosisCard diagnosis={fine} />);
    expect(screen.getByText("Everything we checked looks fine.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /2 other checks passed/ })).toBeTruthy();
  });
});
