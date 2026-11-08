import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InlineEdit } from "@/components/arc/inline-edit";
import { RowMenu } from "@/components/arc/menu";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { Tabs } from "@/components/interior/tabs";
import { Disclosure, PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM } from "@/components/ui";
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

  /**
   * A bare `<summary>` is one line of small text: the lead source's "Details" and Pip's
   * folded "Done" / "Filled N fields" lines measured 20px tall at 320.
   */
  it.each([
    ["app/c/[slug]/lead-sources/SourcesList.tsx", /touch:(?:py-3|min-h-11)/],
    ["components/copilot/CopilotPanel.tsx", /touch:min-h-11/],
    ["components/copilot/ActionReceipt.tsx", /touch:min-h-11/],
  ])("every disclosure line in %s is a 44px target to a finger", (file, sized) => {
    const source = readFileSync(join(process.cwd(), "src", file), "utf8");
    const summaries = [...source.matchAll(/<summary\b[^>]*>/g)].map((m) => m[0]);
    expect(summaries.length).toBeGreaterThan(0);
    for (const tag of summaries) expect(tag).toMatch(sized);
  });

  it("a two-way page switch wraps its labels on a phone instead of cutting one", () => {
    render(
      <SegmentedControl
        label="Which numbers"
        options={[
          { value: "ours", label: "From Calevate" },
          { value: "existing", label: "Your existing number" },
        ]}
        value="ours"
        onValueChange={() => {}}
        fill
      />,
    );
    const group = screen.getByRole("radiogroup", { name: "Which numbers" });
    expect(group.getAttribute("style")).toMatch(/minmax\(0, 1fr\)/);
    expect(classes(group)).not.toContain("min-w-max");
    expect(classes(screen.getByRole("radio", { name: "Your existing number" }))).toContain(
      "max-sm:whitespace-normal",
    );
  });

  it("a row's ⋯ menu keeps its 44px width in a tight actions cell (it shrank to 37px at 768)", () => {
    render(<RowMenu label="Website form" items={[{ id: "a", label: "Rename", onSelect: () => {} }]} />);
    const trigger = screen.getByRole("button", { name: "More actions for Website form" });
    expect(classes(trigger)).toEqual(expect.arrayContaining(["touch:w-11", "shrink-0"]));
  });

  it("a row disclosure's status wraps in its share instead of squeezing the title", () => {
    render(
      <Disclosure variant="row" title="Leads that arrive after hours" status="Call when you open">
        <p>body</p>
      </Disclosure>,
    );
    const status = screen.getByText("Call when you open");
    expect(classes(status)).toContain("max-w-[45%]");
    expect(classes(status)).not.toContain("shrink-0");
  });

  it("a model card's price wraps under its name on a phone instead of halving the card", () => {
    const source = readFileSync(join(process.cwd(), "src/components/llmModelPicker.tsx"), "utf8");
    const row = /flex flex-wrap items-start justify-between[\s\S]*?<span className="([^"]*)">/.exec(source)?.[1] ?? "";
    expect(row).toMatch(/flex-\[1_1_12rem\]/);
  });

  it("an outcome's meaning shows on two lines and stays one line of text", () => {
    const source = readFileSync(
      join(process.cwd(), "src/components/leadFields/CallOutcomesView.tsx"),
      "utf8",
    );
    const field = /What it means<\/span>[\s\S]*?\/>/.exec(source)?.[0] ?? "";
    expect(field).toMatch(/<textarea\s/);
    expect(field).toMatch(/rows=\{2\}/);
    const strip = /replace\(\/([^/]+)\/g, " "\)/.exec(field)?.[1] ?? "";
    expect(strip).not.toEqual("");
    const pattern = new RegExp(strip, "g");
    expect("Wants a visit\r\n this week".replace(pattern, " ")).toEqual("Wants a visit this week");
  });

  it("the business page's lone Verify link is 44px tall to a finger (it measured 14px)", () => {
    const source = readFileSync(
      join(process.cwd(), "src/app/c/[slug]/settings/business/BusinessProfileScreen.tsx"),
      "utf8",
    );
    const link = /href=\{href\("\/verify-business"\)\}\s*className="([^"]*)"/.exec(source)?.[1] ?? "";
    expect(link).toMatch(/touch:min-h-11/);
  });

  /**
   * Icon-only small buttons (move up, move down, delete, send test lead) measured 40-42px
   * wide: the small button class gave them 44px of height and only their padding in width.
   */
  it.each([
    ["PRIMARY_BUTTON_SM", PRIMARY_BUTTON_SM],
    ["SECONDARY_BUTTON_SM", SECONDARY_BUTTON_SM],
  ])("%s is 44px wide to a finger and keeps an icon centred", (_name, cls) => {
    expect(cls.split(/\s+/)).toEqual(expect.arrayContaining(["touch:min-w-11", "justify-center"]));
  });
});
