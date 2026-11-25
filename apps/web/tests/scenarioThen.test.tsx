import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { DEFAULT_LIMITS } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { ToastProvider } from "@/components/arc/toast";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

import { expectNoA11yViolations } from "./a11y";
import { renderClientPage } from "./harness";

/**
 * The call goes on to the next step by itself (founder, 25 Nov 2026: after a Pip rewrite every
 * scenario read "No next yet" with no arrows, though the call ran them in order).
 */

const stage = (over: Partial<ConversationStage>): ConversationStage => ({
  id: "a",
  name: "A",
  mode: "guide",
  instruction: "Do A.",
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

const RYTU: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: "Hello.",
  stages: [
    stage({ id: "login", name: "Login", step: 1, branches: [{ when: "They want a call back", target: "call_back" }] }),
    stage({ id: "farms", name: "Add Farms", step: 2 }),
    stage({ id: "expenses", name: "Enter Expenses", step: 3 }),
  ],
};

const view = (opts: { wide?: boolean; readOnly?: boolean; script?: CallScript } = {}) => {
  const onChange = vi.fn();
  const rendered = renderClientPage(
    <ToastProvider>
      <ScenarioFlow
        agent={null}
        hear={{ allowed: true, reason: null, unknown: false }}
        script={opts.script ?? RYTU}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={null}
        readOnly={opts.readOnly ?? false}
        wide={opts.wide ?? true}
        onSelect={() => {}}
        onChange={onChange}
      />
    </ToastProvider>,
    {},
  );
  return { onChange, rendered };
};

describe("the call's own order on the canvas", () => {
  it("draws a quiet link on to the next step, and none past an Otherwise", async () => {
    const { container } = await view().rendered;
    await screen.findByRole("button", { name: /Scenario 1\.1/ });
    const login = container.querySelector('path[data-link="login~then~farms"]');
    expect(login).not.toBeNull();
    expect(login?.getAttribute("data-via")).toBe("then");
    expect(login?.getAttribute("stroke-dasharray")).toBeTruthy();
    expect(container.querySelector('path[data-link="farms~then~expenses"]')).not.toBeNull();
    // The owner's way out to a call back is a chip on 1.1, never a line.
    expect(container.querySelector('path[data-link="login-0"]')).toBeNull();
    expect(container.querySelector('[data-scenario="login"] [data-exit="call_back"]')?.textContent).toContain(
      "Offer a call back",
    );

    const overridden = await view({
      script: { ...RYTU, stages: RYTU.stages?.map((s) => (s.id === "farms" ? { ...s, otherwise: "end" } : s)) },
    }).rendered;
    expect(overridden.container.querySelector('path[data-link="farms~then~expenses"]')).toBeNull();
    // An Otherwise to an end point is a chip on its card, not a line.
    expect(overridden.container.querySelector('path[data-link="farms-otherwise"]')).toBeNull();
    const chip = overridden.container.querySelector('[data-scenario="farms"] [data-exit="end"]');
    expect(chip?.textContent).toContain("Otherwise");
    expect(chip?.textContent).toContain("End the call");
  });

  it("says where each scenario goes on, and the last step ends the call", async () => {
    const { container } = await view().rendered;
    await screen.findByRole("button", { name: /Scenario 1\.1/ });
    const said = (id: string) => container.querySelector(`[data-then="${id}"]`)?.textContent ?? "";
    expect(said("login")).toContain("Then step 2");
    expect(said("farms")).toContain("Then step 3");
    expect(said("expenses")).toContain("Then end of call");
    expect(container.textContent).not.toContain("No next yet");
    expect(screen.getByRole("button", { name: /Scenario 3\.1: Enter Expenses\. Then end of call\./ })).toBeTruthy();
  });

  it("offers no remove control on the call's own order", async () => {
    const { container } = await view().rendered;
    await screen.findByRole("button", { name: /Scenario 1\.1/ });
    expect(container.querySelector('[data-link-hit="login~then~farms"]')).toBeNull();
    expect(container.querySelector('[data-unlink="login~then~farms"]')).toBeNull();
    // The owner's own way out keeps its ×, on its chip.
    expect(screen.getByRole("button", { name: "Remove the link from 1.1 Login to Offer a call back" })).toBeTruthy();
  });

  it("removes an Otherwise with its ×, and the call goes on to the next step again", async () => {
    const script = { ...RYTU, stages: RYTU.stages?.map((s) => (s.id === "farms" ? { ...s, otherwise: "end" } : s)) };
    const { onChange } = view({ script });
    fireEvent.click(await screen.findByRole("button", { name: /Remove the link from 2\.1 Add Farms to End the call/ }));
    const [next] = onChange.mock.calls[0] as [CallScript];
    expect(next.stages?.find((s) => s.id === "farms")?.otherwise).toBe("");
  });

  it("shows the same chip, marked automatic, when the steps are stacked", async () => {
    const { container } = await view({ wide: false }).rendered;
    await screen.findByText("Step 1");
    const chip = (id: string) => container.querySelector<HTMLElement>(`[data-then-chip="${id}"]`);
    expect(chip("login")?.textContent).toBe("Then step 2(automatic)");
    expect(chip("expenses")?.textContent).toBe("Then end of call(automatic)");
    expect(within(chip("login") as HTMLElement).queryByRole("button")).toBeNull();
  });

  it("passes axe on the canvas and stacked", async () => {
    const wide = await view().rendered;
    await screen.findByRole("button", { name: /Scenario 1\.1/ });
    await expectNoA11yViolations(wide.container, "call flow with the call's own order");
    wide.unmount();
    const narrow = await view({ wide: false }).rendered;
    await screen.findByText("Step 1");
    await expectNoA11yViolations(narrow.container, "stacked call flow with then chips");
  });
});
