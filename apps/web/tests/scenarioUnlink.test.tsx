import { act, fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CampaignFlow } from "@/app/c/[slug]/campaigns/CampaignFlow";
import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { DEFAULT_LIMITS } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { ToastProvider } from "@/components/arc/toast";
import type { ActionFeedback } from "@/components/arc/feedback";
import type { ScriptRestore } from "@/lib/api/scriptVersions";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

import { expectNoA11yViolations } from "./a11y";
import { noReply, renderClientPage } from "./harness";

/** A link made on the call-flow canvas can be removed there too. */

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

const LINKED: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: "Hello.",
  stages: [
    stage({
      id: "a",
      name: "Android installation",
      step: 1,
      branches: [
        { when: "Setup farms", target: "b" },
        { when: "Done", target: "end" },
      ],
    }),
    stage({ id: "b", name: "Setup farms", step: 2 }),
  ],
};

const REMOVE_A_B = /Remove the link from 1\.1 Android installation to 2\.1 Setup farms/;

const targetsOf = (script: CallScript | undefined, id: string) =>
  script?.stages?.find((s) => s.id === id)?.branches?.map((b) => b.target);

const view = (
  opts: { wide?: boolean; readOnly?: boolean; onUndo?: () => void; script?: CallScript } = {},
) => {
  const onChange = vi.fn();
  const rendered = renderClientPage(
    <ToastProvider>
      <ScenarioFlow
        agent={null}
        hear={{ allowed: true, reason: null, unknown: false }}
        script={opts.script ?? LINKED}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={null}
        readOnly={opts.readOnly ?? false}
        wide={opts.wide ?? true}
        onSelect={() => {}}
        onChange={onChange}
        onUndo={opts.onUndo}
      />
    </ToastProvider>,
    {},
  );
  return { onChange, rendered };
};

const changed = (onChange: ReturnType<typeof vi.fn>) => {
  expect(onChange).toHaveBeenCalledTimes(1);
  const [next, discrete] = onChange.mock.calls[0] as [CallScript, boolean | undefined];
  expect(discrete).toBe(true);
  return next;
};

describe("unlinking on the canvas", () => {
  it("removes a link with its × and keeps the others", async () => {
    const onUndo = vi.fn();
    const { onChange } = view({ onUndo });
    const remove = await screen.findByRole("button", { name: REMOVE_A_B });
    fireEvent.click(remove);
    expect(targetsOf(changed(onChange), "a")).toEqual(["end"]);
    // Says what was unlinked, with the canvas's Undo beside it.
    expect(await screen.findByText("Unlinked 1.1 → 2.1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(onUndo).toHaveBeenCalledTimes(1);
  });

  it("draws the step-to-step link and puts the end of the call on 1.1 as a chip", async () => {
    const { container } = await view().rendered;
    await screen.findByRole("button", { name: /Scenario 1\.1/ });
    expect(container.querySelector('path[data-link="a-0"]')).not.toBeNull();
    expect(container.querySelector('path[data-link="a-1"]')).toBeNull();
    expect(container.querySelector('[data-unlink="a-1"]')).toBeNull();
    const chip = container.querySelector<HTMLElement>('[data-scenario="a"] [data-exit="end"]');
    expect(chip?.textContent).toContain("Done");
    expect(chip?.textContent).toContain("End the call");
    // No end point stands on the canvas as a box of its own.
    expect(screen.queryByText("End the call", { selector: "span.border-dashed" })).toBeNull();
  });

  it("removes a way out to an end point with its chip's ×", async () => {
    const { onChange } = view();
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove the link from 1.1 Android installation to End the call" }),
    );
    expect(targetsOf(changed(onChange), "a")).toEqual(["b"]);
  });

  it("chooses a link with a click and removes it with Delete", async () => {
    const { onChange, rendered } = view();
    const { container } = await rendered;
    const hit = container.querySelector('path[data-link-hit="a-0"]') as SVGPathElement;
    expect(hit).not.toBeNull();
    fireEvent.click(hit);
    const remove = container.querySelector('button[data-unlink="a-0"]') as HTMLButtonElement;
    expect(remove.dataset.shown).toBe("true");
    expect(document.activeElement).toBe(remove);
    fireEvent.keyDown(remove, { key: "Delete" });
    expect(targetsOf(changed(onChange), "a")).toEqual(["end"]);
  });

  it("lets Escape put a chosen link down without removing it", async () => {
    const { onChange, rendered } = view();
    const { container } = await rendered;
    fireEvent.click(container.querySelector('path[data-link-hit="a-0"]') as SVGPathElement);
    const remove = container.querySelector('button[data-unlink="a-0"]') as HTMLButtonElement;
    fireEvent.keyDown(remove, { key: "Escape" });
    expect(remove.dataset.shown).toBe("false");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("offers an unlink for each next link in the box's menu", async () => {
    const { onChange } = view();
    fireEvent.click(await screen.findByRole("button", { name: "More for scenario 1.1" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Unlink from End the call" })).toBeTruthy();
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Unlink from 2.1 Setup farms" }));
    expect(targetsOf(changed(onChange), "a")).toEqual(["end"]);
  });

  it("shows no remove control to a person who cannot change the flow", async () => {
    const { rendered } = view({ readOnly: true });
    const { container } = await rendered;
    await screen.findByRole("button", { name: /Scenario 1\.1/ });
    expect(container.querySelector("[data-unlink]")).toBeNull();
    expect(container.querySelector("[data-link-hit]")).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove the link/ })).toBeNull();
    // The links are still drawn.
    expect(container.querySelector('path[data-link="a-0"]')).not.toBeNull();
  });

  it("removes a link from its chip when the steps are stacked", async () => {
    const { onChange } = view({ wide: false });
    const remove = await screen.findByRole("button", { name: /Remove the link from 1\.1 Android installation to End the call/ });
    fireEvent.click(remove);
    expect(targetsOf(changed(onChange), "a")).toEqual(["b"]);
  });

  it("keeps the stacked chips but no remove buttons when read only", async () => {
    const { rendered } = view({ wide: false, readOnly: true });
    const { container } = await rendered;
    await screen.findByText("Step 1");
    expect(container.querySelectorAll("[data-next-chip]")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /Remove the link/ })).toBeNull();
  });

  it("passes axe with the link controls on the canvas and in the chips", async () => {
    const wide = await view().rendered;
    fireEvent.click(wide.container.querySelector('path[data-link-hit="a-0"]') as SVGPathElement);
    await expectNoA11yViolations(wide.container, "call flow with link controls");
    wide.unmount();
    const narrow = await view({ wide: false }).rendered;
    await screen.findByText("Step 1");
    await expectNoA11yViolations(narrow.container, "stacked call flow with next chips");
  });
});

describe("undo after an unlink", () => {
  it("the canvas's Undo puts the link back", async () => {
    const restore: ActionFeedback<ScriptRestore> = { status: "idle", run: () => {}, error: null, reset: () => {} };
    await renderClientPage(
      <ToastProvider>
        <CampaignFlow
          agentId="agent-1"
          script={LINKED}
          canWrite
          saving={false}
          onSave={() => {}}
          mapping={false}
          languages={["te-IN"]}
          campaignId="campaign-1"
          versions={undefined}
          restore={restore}
          onRestore={async () => {}}
        />
      </ToastProvider>,
      // Neither answer changes what the flow draws: the script's limits default, and
      // hearing a line is not under test.
      { "/v1/agents/agent-1/script": noReply(), "/v1/me": noReply() },
    );
    const chipsOf = () =>
      Array.from(document.querySelectorAll<HTMLElement>("[data-next-chip]")).map((c) => c.dataset.nextChip);
    expect(chipsOf()).toEqual(["b", "end"]);
    fireEvent.click(await screen.findByRole("button", { name: REMOVE_A_B }));
    expect(chipsOf()).toEqual(["end"]);
    // The toast's Undo is the toolbar's step back: the removal alone.
    const toast = within(await screen.findByRole("region", { name: "Notifications" }));
    expect(toast.getByText("Unlinked 1.1 → 2.1")).toBeTruthy();
    await act(async () => {
      fireEvent.click(toast.getByRole("button", { name: "Undo" }));
    });
    expect(chipsOf()).toEqual(["b", "end"]);
    // And Redo takes it out again, through the toolbar.
    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    expect(chipsOf()).toEqual(["end"]);
  });
});
