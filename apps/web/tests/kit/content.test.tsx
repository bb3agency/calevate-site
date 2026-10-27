import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, onTestFinished, vi } from "vitest";

import { Accordion } from "@/components/arc/accordion";
import { ChangelogFeed } from "@/components/arc/changelog-feed";
import { ExpandableText } from "@/components/arc/expandable-text";
import { JsonViewer } from "@/components/arc/json-viewer";
import {
  ScriptEditor,
  scriptOverBudget,
  unknownVariables,
  type ScriptEditorSection,
} from "@/components/arc/script-editor";
import { codePoints, fillVariables, toSpokenPlainText, variablesIn } from "@/components/arc/spoken-text";
import { TextShimmer } from "@/components/arc/text-shimmer";
import { TierComparison } from "@/components/arc/tier-comparison";
import { ToastProvider } from "@/components/arc/toast";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { EmptyState } from "@/components/console/emptyState";
import { CopyButton } from "@/components/interior/copy-button";
import { ApiProblem } from "@/lib/api/client";

describe("spoken text: what a script may contain", () => {
  it("removes markdown, list markers, HTML and emoji, and keeps the words", () => {
    const pasted = "# Greeting\n- **Namaste** {{caller_name}}! \u{1F600}\n2. Ask about _the order_\n<b>Thanks</b>";
    expect(toSpokenPlainText(pasted)).toBe("Greeting\nNamaste {{caller_name}}! \nAsk about the order\nThanks");
  });

  it("keeps a variable key's underscores and Indian scripts untouched", () => {
    expect(toSpokenPlainText("నమస్తే {{caller_name}}, ఎలా ఉన్నారు?")).toBe("నమస్తే {{caller_name}}, ఎలా ఉన్నారు?");
  });

  it("finds, fills and counts like the server", () => {
    expect(variablesIn("Hi {{a}} and {{ b }} and {{a}}")).toEqual(["a", "b"]);
    expect(fillVariables("Hi {{a}}, {{zzz}}", { a: "Priya" })).toBe("Hi Priya, {{zzz}}");
    expect(codePoints("నమస్తే")).toBe(6);
  });
});

const SECTIONS: ScriptEditorSection[] = [
  { id: "opening", title: "Opening line", value: "Namaste {{caller_name}}", maxChars: 30 },
  { id: "closing", title: "Closing", value: "", maxChars: 10 },
];
const VARIABLES = [{ key: "caller_name", label: "Caller's name", sample: "Priya" }];

function Harness({ onSave }: { onSave?: () => void }) {
  const [sections, setSections] = useState(SECTIONS);
  return (
    <ScriptEditor
      sections={sections}
      variables={VARIABLES}
      totalMaxChars={100}
      onChange={(id, value) => setSections((all) => all.map((s) => (s.id === id ? { ...s, value } : s)))}
      onSave={onSave}
    />
  );
}

describe("ScriptEditor", () => {
  it("strips formatting the moment it is typed or pasted, and says so", () => {
    render(<Harness />);
    const box = screen.getByRole("textbox", { name: /Closing/ }) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "**Thanks** for calling" } });
    expect(box.value).toBe("Thanks for calling");
    expect(screen.getByRole("status").textContent).toContain("Formatting was removed");
  });

  it("shows the fields a section uses by name and flags one nobody knows", () => {
    render(<Harness />);
    const box = screen.getByRole("textbox", { name: /Opening line/ }) as HTMLTextAreaElement;
    expect(screen.getAllByText("Caller's name").length).toBeGreaterThan(0);
    fireEvent.change(box, { target: { value: "Hi {{pincode}}" } });
    expect(box.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText(/{{pincode}} is not a detail this agent knows/)).toBeTruthy();
  });

  it("inserts a field from the list", () => {
    render(<Harness />);
    const group = screen.getByRole("group", { name: /Add a caller detail: Closing/ });
    fireEvent.click(within(group).getByRole("button", { name: /Caller's name/ }));
    expect((screen.getByRole("textbox", { name: /Closing/ }) as HTMLTextAreaElement).value).toBe("{{caller_name}}");
  });

  it("marks a section over its budget and says by how much", () => {
    render(<Harness />);
    const box = screen.getByRole("textbox", { name: /Closing/ }) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "Thank you very much" } });
    expect(box.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getAllByText("9 characters over").length).toBeGreaterThan(0);
  });

  it("previews the script with sample values in place of the fields", () => {
    render(<Harness />);
    const preview = screen.getByRole("complementary", { name: "How it will sound" });
    expect(preview.textContent).toContain("Namaste Priya");
  });

  it("puts the save on its own button", () => {
    const onSave = vi.fn();
    render(<Harness onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Save script" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("answers the budget and unknown-field questions a screen holds its save on", () => {
    expect(scriptOverBudget(SECTIONS)).toBe(false);
    expect(scriptOverBudget([{ ...SECTIONS[1], value: "far too long here" }])).toBe(true);
    expect(unknownVariables([{ ...SECTIONS[0], value: "{{x}} {{caller_name}}" }], VARIABLES)).toEqual(["x"]);
  });
});

describe("TierComparison", () => {
  const tiers = [
    { id: "clear", name: "Clear", ratePerMinute: "4.50", includes: ["Calls"], bestFor: "Most businesses" },
    { id: "studio", name: "Studio", ratePerMinute: "6.00", includes: ["Richer voice"], bestFor: "Premium brands" },
  ];

  it("prints the server's rate string, marks the current tier and offers the other", () => {
    const onChoose = vi.fn();
    render(<TierComparison tiers={tiers} currentId="clear" onChoose={onChoose} />);
    expect(screen.getByText("₹4.5")).toBeTruthy();
    expect(screen.getByText("Your agents use this")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Use Clear" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Use Studio" }));
    expect(onChoose).toHaveBeenCalledWith("studio");
  });

  it("shows the change's state on the button being chosen", () => {
    render(<TierComparison tiers={tiers} currentId="clear" onChoose={() => {}} choosingId="studio" chooseStatus="pending" />);
    expect(screen.getByRole("button", { name: "Use Studio" }).getAttribute("aria-busy")).toBe("true");
  });
});

const ITEMS: ChecklistItem[] = [
  { id: "a", label: "Create your agent", state: "done" },
  { id: "b", label: "Add knowledge", state: "todo", link: { href: "/k", label: "Add knowledge" } },
  { id: "c", label: "Go live", state: "todo", link: { href: "/l", label: "Go live" } },
];

describe("Checklist: the borrowed onboarding patterns", () => {
  it("draws one next step and folds what is done", () => {
    const { container } = render(<Checklist label="Setup" items={ITEMS} emphasizeNext foldDone />);
    const next = container.querySelector("[data-next]");
    expect(next?.textContent).toContain("Add knowledge");
    expect(next?.textContent).toContain("Next");
    expect(screen.getByText("1 done").closest("summary")).toBeTruthy();
    expect(screen.getByText("1 of 3 done")).toBeTruthy();
  });

  it("hands focus to the next step when the one being worked on is done", () => {
    const { rerender } = render(<Checklist label="Setup" items={ITEMS} emphasizeNext />);
    (screen.getByRole("link", { name: /Add knowledge/ }) as HTMLElement).focus();
    const after = ITEMS.map((i) => (i.id === "b" ? { ...i, state: "done" as const } : i));
    rerender(<Checklist label="Setup" items={after} emphasizeNext />);
    expect(document.activeElement).toBe(screen.getByRole("link", { name: /Go live/ }));
  });
});

describe("EmptyState variants", () => {
  it("offers to clear filters when the list is only narrowed", () => {
    const onClear = vi.fn();
    render(<EmptyState variant="filtered" message="No leads match." onClear={onClear} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onClear).toHaveBeenCalled();
  });

  it("never says 'nothing here' for a read that failed", () => {
    render(
      <EmptyState
        variant="error"
        message="Calls did not load."
        error={new ApiProblem(503, { detail: "Calevate is not answering right now.", retryable: true })}
        onRetry={() => {}}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain("not answering");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("offers no action a restricted person would be refused", () => {
    render(<EmptyState variant="restricted" message="Only the owner can see billing." action={<button type="button">Top up</button>} />);
    expect(screen.queryByRole("button", { name: "Top up" })).toBeNull();
  });
});

describe("ExpandableText", () => {
  it("shows a toggle only when the text overflows, and opens it", () => {
    const scroll = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(200);
    const client = vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(60);
    onTestFinished(() => {
      scroll.mockRestore();
      client.mockRestore();
    });
    render(<ExpandableText>Long words</ExpandableText>);
    const toggle = screen.getByRole("button", { name: "Show more" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("has no toggle for text that fits", () => {
    render(<ExpandableText>Short</ExpandableText>);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("Accordion", () => {
  it("groups its sections so opening one closes the others", () => {
    const { container } = render(
      <Accordion
        items={[
          { id: "a", title: "One", content: "1" },
          { id: "b", title: "Two", content: "2" },
        ]}
      />,
    );
    const names = [...container.querySelectorAll("details")].map((d) => d.getAttribute("name"));
    expect(names[0]).toBeTruthy();
    expect(new Set(names).size).toBe(1);
  });
});

describe("JsonViewer", () => {
  it("opens the top levels, closes deeper ones, and pages long arrays", () => {
    render(
      <JsonViewer
        label="Response"
        expandDepth={1}
        pageSize={3}
        value={{ status: 502, nested: { deep: { x: 1 } }, list: [1, 2, 3, 4, 5, 6, 7] }}
      />,
    );
    expect(screen.getByText("502")).toBeTruthy();
    const nested = screen.getByRole("button", { name: /^nested/ });
    expect(nested.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(nested);
    expect(nested.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /^list/ }));
    fireEvent.click(screen.getByRole("button", { name: "Show 3 more" }));
    expect(screen.getByRole("button", { name: "Show 1 more" })).toBeTruthy();
  });
});

describe("ChangelogFeed and TextShimmer", () => {
  it("dates each entry in IST", () => {
    render(<ChangelogFeed entries={[{ id: "1", date: "2026-10-21T20:00:00Z", title: "New", body: "Body" }]} />);
    // 20:00 UTC is 01:30 the next morning in India.
    const time = document.querySelector("time");
    expect(time?.getAttribute("dateTime")).toBe("2026-10-21T20:00:00Z");
    expect(time?.textContent).toMatch(/22/);
  });

  it("announces a standalone working line", () => {
    render(<TextShimmer>Reading your price list…</TextShimmer>);
    expect(screen.getByRole("status").textContent).toBe("Reading your price list…");
  });
});

describe("CopyButton under the feedback standard", () => {
  it("keeps a failure in the toast stack with the way round it", async () => {
    const write = vi.fn().mockRejectedValue(new Error("denied"));
    const original = navigator.clipboard;
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: write } });
    const exec = vi.fn().mockReturnValue(false);
    const doc = document as unknown as { execCommand: (cmd: string) => boolean };
    const priorExec = doc.execCommand;
    doc.execCommand = exec;
    onTestFinished(() => {
      Object.defineProperty(navigator, "clipboard", { configurable: true, value: original });
      doc.execCommand = priorExec;
    });
    render(
      <ToastProvider>
        <CopyButton value="+919876543210" label="Copy phone number" />
      </ToastProvider>,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy phone number" }));
    });
    expect(await screen.findByRole("group", { name: "Error: Could not copy" })).toBeTruthy();
  });
});
