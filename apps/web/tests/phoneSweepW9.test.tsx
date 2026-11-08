import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InlineEdit } from "@/components/arc/inline-edit";
import { Tabs } from "@/components/interior/tabs";
import { WizardSteps } from "@/components/interior/wizard-steps";

/**
 * Client screens swept on a phone (375 and 320 px, touch). jsdom has no layout, so these pin
 * the classes that give the measured result in a real browser.
 */

const classes = (el: Element): string[] => (el.getAttribute("class") ?? "").split(/\s+/);

describe("client screens on a phone", () => {
  it("a wrapping inline name shows the whole name rather than cutting it", () => {
    const name = "Site-visit reminders for past enquiries";
    render(<InlineEdit value={name} label="Campaign name" wrap onSave={() => {}} />);
    const text = screen.getByText(name);
    expect(classes(text)).not.toContain("truncate");
  });

  it("the campaign page title wraps its name", () => {
    const source = readFileSync(
      join(process.cwd(), "src/app/c/[slug]/campaigns/CampaignScreen.tsx"),
      "utf8",
    );
    const edit = /<InlineEdit[\s\S]*?\/>/.exec(source)?.[0] ?? "";
    expect(edit).toMatch(/label="Campaign name"/);
    expect(edit).toMatch(/\swrap\s/);
  });

  it("a one-word tab is at least 44px wide to a finger", () => {
    render(
      <Tabs
        label="Views"
        items={[
          { value: "steps", label: "Steps" },
          { value: "runs", label: "Leads" },
        ]}
        defaultValue="steps"
      />,
    );
    for (const tab of screen.getAllByRole("tab")) expect(classes(tab)).toContain("touch:min-w-11");
  });

  it("a numbered wizard step is at least 44px wide to a finger", () => {
    render(
      <WizardSteps
        steps={[
          { id: "a", label: "Why", content: <p>one</p> },
          { id: "b", label: "Who", content: <p>two</p> },
        ]}
      />,
    );
    const step = screen.getByRole("button", { name: /Step 1 of 2/ });
    expect(classes(step)).toContain("touch:min-w-11");
  });
});
