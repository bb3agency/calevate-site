import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Checklist } from "@/components/console/checklist";
import { Drawer } from "@/components/console/drawer";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { RowMenu } from "@/components/console/rowMenu";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { SettingsLayout } from "@/components/console/settingsLayout";
import { StepFlow } from "@/components/console/stepFlow";
import { formatPhone } from "@/components/ui";
import { printDocument } from "@/lib/printDocument";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

/**
 * The round-2 console foundation: every screen is rebuilt on these, so each behaviour a
 * screen will lean on without restating it is pinned here — keyboard paths, focus moves,
 * the unsaved-edits guard, and what reduced motion paints.
 */

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  usePathname: () => "/c/acme/agents/a1",
  useRouter: () => ({
    push: nav.push,
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const CSS = readFileSync(join(process.cwd(), "src", "app", "globals.css"), "utf8");

describe("formatPhone", () => {
  it("groups an Indian mobile for reading and leaves anything else exactly as sent", () => {
    expect(formatPhone("+919876543210")).toBe("+91 98765 43210");
    expect(formatPhone("+14155550100")).toBe("+14155550100");
    expect(formatPhone("+91402345678")).toBe("+91402345678");
    expect(formatPhone(null)).toBe("—");
  });
});

describe("PageHeader", () => {
  it("names the thing below the shell's own h1, with its state and its action", () => {
    render(
      <PageHeader
        title="Reception"
        status={<span>Live</span>}
        description="Answers calls to your clinic."
        actions={<button type="button">Publish</button>}
        back={{ href: "/c/acme/agents", label: "Agents" }}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Reception" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.getByRole("link", { name: "Agents" }).getAttribute("href")).toBe("/c/acme/agents");
    expect(screen.getByRole("button", { name: "Publish" })).toBeTruthy();
  });
});

describe("EmptyState", () => {
  it("is one line and one action", () => {
    render(<EmptyState message="No campaigns yet" action={<button type="button">New campaign</button>} />);
    expect(screen.getByText("No campaigns yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New campaign" })).toBeTruthy();
  });
});

describe("Checklist", () => {
  const items = [
    { id: "a", label: "Accept the agreements", state: "done" as const },
    { id: "b", label: "Add a phone number", state: "todo" as const, link: { href: "/c/acme/phone-number", label: "Add" } },
    {
      id: "c",
      label: "Verify your business",
      state: "blocked" as const,
      disabledReason: "Opens once the agreements are accepted.",
      link: { href: "/c/acme/verification", label: "Verify" },
    },
  ];

  it("counts what is done, says each state in words, and offers no action on a disabled item", () => {
    render(<Checklist label="Before your first call" items={items} />);
    expect(screen.getByText("1 of 3 done")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("1");
    expect(screen.getByText("Done:")).toBeTruthy();
    expect(screen.getByText("Blocked:")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add" }).getAttribute("href")).toBe("/c/acme/phone-number");
    expect(screen.queryByRole("link", { name: "Verify" })).toBeNull();
    expect(screen.getByText("Opens once the agreements are accepted.")).toBeTruthy();
  });

  it("says All done, and a collapsible one folds away once it is", () => {
    const { container } = render(
      <Checklist
        collapsible
        label="Setup"
        items={[{ id: "a", label: "One", state: "done" }]}
      />,
    );
    expect(screen.getByText("All done")).toBeTruthy();
    expect(container.querySelector("details")?.hasAttribute("open")).toBe(false);
  });

  it("keeps the count readable when collapsed", () => {
    const { container } = render(<Checklist collapsible defaultOpen={false} label="Setup" items={items} />);
    const summary = container.querySelector("summary");
    expect(summary?.textContent).toContain("1 of 3 done");
    expect(container.querySelector("details")?.hasAttribute("open")).toBe(false);
  });
});

describe("SettingRow", () => {
  it("labels its control when told which control it is", () => {
    render(
      <SettingRows>
        <SettingRow label="Call limit" htmlFor="cap" hint="Longest a call may run." control={<input id="cap" />} />
        <SettingRow label="Voice" value="Studio" info={<p>Studio costs more per minute.</p>} />
      </SettingRows>,
    );
    expect(screen.getByLabelText("Call limit")).toBeTruthy();
    expect(screen.getByText("Studio")).toBeTruthy();
    expect(screen.getByRole("button", { name: "About Voice" })).toBeTruthy();
  });
});

function Draft() {
  const [text, setText] = useState("");
  useUnsavedGuard(text !== "");
  return <input aria-label="Script" value={text} onChange={(e) => setText(e.target.value)} />;
}

const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "script", label: "Script" },
  { id: "voice", label: "Voice", badge: "2" },
];

describe("SettingsLayout", () => {
  it("opens the section the URL names, links each section by URL and keeps other params", () => {
    nav.params = new URLSearchParams("view_as=admin&section=voice");
    render(<SettingsLayout label="Agent settings" sections={SECTIONS} renderSection={(id) => <p>body {id}</p>} />);
    expect(screen.getByRole("heading", { level: 2, name: "Voice" })).toBeTruthy();
    expect(screen.getByText("body voice")).toBeTruthy();
    expect(screen.queryByText("body overview")).toBeNull();
    const script = screen.getByRole("link", { name: "Script" });
    expect(script.getAttribute("href")).toBe("/c/acme/agents/a1?view_as=admin&section=script");
    expect(screen.getByRole("link", { name: /Voice/ }).getAttribute("aria-current")).toBe("true");
    // One link per section in the document, whatever the width.
    expect(screen.getAllByRole("link", { name: "Script" })).toHaveLength(1);
  });

  it("falls back to the first section for a value it does not know", () => {
    nav.params = new URLSearchParams("section=nonsense");
    render(<SettingsLayout label="Agent settings" sections={SECTIONS} renderSection={(id) => <p>body {id}</p>} />);
    expect(screen.getByText("body overview")).toBeTruthy();
  });

  it("moves focus to the section the reader picked, and not on first load", () => {
    nav.params = new URLSearchParams("section=overview");
    const { rerender } = render(
      <SettingsLayout label="Agent settings" sections={SECTIONS} renderSection={(id) => <p>body {id}</p>} />,
    );
    expect(document.activeElement).toBe(document.body);
    fireEvent.click(screen.getByRole("link", { name: "Script" }));
    nav.params = new URLSearchParams("section=script");
    rerender(<SettingsLayout label="Agent settings" sections={SECTIONS} renderSection={(id) => <p>body {id}</p>} />);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 2, name: "Script" }));
  });

  it("asks before a switch would throw away unsaved typing, and switches only when told to", () => {
    nav.params = new URLSearchParams("section=script");
    nav.push.mockClear();
    render(
      <SettingsLayout
        label="Agent settings"
        sections={SECTIONS}
        renderSection={(id) => (id === "script" ? <Draft /> : <p>body {id}</p>)}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Script" }), { target: { value: "Namaskaram" } });
    fireEvent.click(screen.getByRole("link", { name: /Voice/ }));
    const dialog = screen.getByRole("dialog", { name: "Leave without saving?" });
    expect(dialog.textContent).toContain("Script");
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect((screen.getByRole("textbox", { name: "Script" }) as HTMLInputElement).value).toBe("Namaskaram");
    expect(nav.push).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("link", { name: /Voice/ }));
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(nav.push).toHaveBeenCalledWith("/c/acme/agents/a1?section=voice", { scroll: false });
  });

  it("switches without asking when nothing is unsaved", () => {
    nav.params = new URLSearchParams("section=script");
    render(
      <SettingsLayout
        label="Agent settings"
        sections={SECTIONS}
        renderSection={(id) => (id === "script" ? <Draft /> : <p>body {id}</p>)}
      />,
    );
    fireEvent.click(screen.getByRole("link", { name: /Voice/ }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

function Flow({ onSubmit, onCancel }: { onSubmit: () => void; onCancel?: () => void }) {
  const [name, setName] = useState("");
  return (
    <StepFlow
      label="New campaign"
      onCancel={onCancel}
      steps={[
        {
          id: "name",
          title: "What is it called?",
          content: <input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} />,
          validate: () => (name.trim() ? null : "Give it a name."),
        },
        { id: "when", title: "When should it run?", content: <p>Schedule</p> },
      ]}
      review={{ content: <p>Review {name}</p> }}
      submitLabel="Create campaign"
      onSubmit={onSubmit}
    />
  );
}

describe("StepFlow", () => {
  it("refuses Next with a reason, then walks forward with focus on each question", () => {
    const onSubmit = vi.fn();
    render(<Flow onSubmit={onSubmit} />);
    expect(screen.getByText("Step 1 of 3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("alert").textContent).toBe("Give it a name.");
    expect(screen.getByText("Step 1 of 3")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Diwali recall" } });
    // Enter in the field is Next: each step is a form.
    fireEvent.submit(screen.getByLabelText("Name").closest("form")!);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "When should it run?" }));
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Review Diwali recall")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "When should it run?" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Create campaign" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("is full screen on a phone only when it has a way out", () => {
    const { container, rerender } = render(<Flow onSubmit={vi.fn()} />);
    expect((container.firstElementChild as HTMLElement).className).not.toContain("fixed");
    const onCancel = vi.fn();
    rerender(<Flow onSubmit={vi.fn()} onCancel={onCancel} />);
    expect((container.firstElementChild as HTMLElement).className).toContain("fixed inset-0");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
  });
});

describe("RowMenu", () => {
  function Menu({ onArchive }: { onArchive: () => void }) {
    return (
      <div>
        <RowMenu
          label="Reception"
          items={[
            { id: "open", label: "Open", href: "/c/acme/agents/a1" },
            { id: "rename", label: "Rename", disabled: true, hint: "Owner only" },
            { id: "archive", label: "Archive", tone: "danger", onSelect: onArchive },
          ]}
        />
      </div>
    );
  }

  it("is named for its row, opens on ArrowDown into the first item, skips a disabled one, and gives focus back on Escape", async () => {
    render(<Menu onArchive={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "More actions for Reception" });
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const menu = await screen.findByRole("menu", { name: "Actions for Reception" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Open" })));
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Archive" }));
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Open" }));
    fireEvent.keyDown(menu, { key: "a" });
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: "Archive" }));
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(trigger);
  });

  it("runs the chosen action and closes", async () => {
    const onArchive = vi.fn();
    render(<Menu onArchive={onArchive} />);
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reception" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Archive" }));
    expect(onArchive).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "More actions for Reception" }).getAttribute("aria-expanded")).toBe("false");
  });
});

describe("Drawer", () => {
  function Host() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Open details
        </button>
        <Drawer open={open} onClose={() => setOpen(false)} title="Lead" description="Anitha Reddy" footer={<button type="button">Save</button>}>
          <input aria-label="Note" />
        </Drawer>
      </>
    );
  }

  it("is absent while closed, takes focus inside when open, and returns it on Escape", async () => {
    render(<Host />);
    expect(screen.queryByRole("dialog")).toBeNull();
    const opener = screen.getByRole("button", { name: "Open details" });
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Lead" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});

describe("reduced motion paints the final frame", () => {
  for (const utility of ["settings-enter", "sheet-enter"]) {
    it(`turns the ${utility} transition off`, () => {
      const block = CSS.slice(CSS.indexOf(`@utility ${utility} {`));
      const body = block.slice(0, block.indexOf("\n}\n"));
      expect(body).toMatch(/prefers-reduced-motion: reduce\)\s*\{\s*transition-property: none;/);
    });
  }
});

describe("printDocument", () => {
  it("prints a clone of one node with the app's stylesheets, not the console around it", async () => {
    const style = document.createElement("style");
    style.textContent = ".doc { color: rgb(1, 2, 3); }";
    document.head.appendChild(style);
    const node = document.createElement("article");
    node.className = "doc";
    node.textContent = "Privacy notice for callers";
    document.body.appendChild(node);

    let printedBody = "";
    let printedHead = "";
    await act(async () => {
      await printDocument(node, {
        title: "Caller notice",
        print: (win) => {
          printedBody = win.document.body.innerHTML;
          printedHead = win.document.head.innerHTML;
          win.dispatchEvent(new Event("afterprint"));
        },
      });
    });
    expect(printedBody).toContain("Privacy notice for callers");
    expect(printedHead).toContain(".doc { color: rgb(1, 2, 3); }");
    expect(printedHead).toContain("@page");
    // The frame is gone once the dialog closed, and the live node was not moved.
    expect(document.querySelector("iframe")).toBeNull();
    expect(document.body.contains(node)).toBe(true);
    style.remove();
    node.remove();
  });
});
