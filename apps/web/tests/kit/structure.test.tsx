import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnnouncementBar } from "@/components/arc/announcement-bar";
import { releaseCloses, rubberBand } from "@/components/arc/bottom-sheet";
import { ButtonGroup, SplitButton } from "@/components/arc/button-group";
import { FilterToolbar, SelectionBar } from "@/components/arc/filter-toolbar";
import { HoverCard } from "@/components/arc/hover-card";
import { NotificationCenter } from "@/components/arc/notification-center";
import { SwipeActions } from "@/components/arc/swipe-actions";
import { ConfirmDialog } from "@/components/confirmDialog";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { Drawer } from "@/components/console/drawer";
import { PageHeader } from "@/components/console/pageHeader";
import { ModalDialog } from "@/components/modalDialog";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

/**
 * The structure half of the kit (docs/design/KIT.md): sheets that drag closed on a phone,
 * the top-bar bell, row actions that a swipe and a menu reach alike, and list chrome.
 */

const original = window.matchMedia;
afterEach(() => {
  window.matchMedia = original;
});

/** A phone: the sheet breakpoint matches, nothing else (no hover, motion allowed). */
function asPhone() {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("max-width"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

function drag(handle: Element, from: number, to: number, ms: number) {
  fireEvent.pointerDown(handle, { pointerId: 1, pointerType: "touch", clientY: from, timeStamp: 0 });
  fireEvent.pointerMove(handle, { pointerId: 1, pointerType: "touch", clientY: (from + to) / 2, timeStamp: ms / 2 });
  fireEvent.pointerMove(handle, { pointerId: 1, pointerType: "touch", clientY: to, timeStamp: ms });
  fireEvent.pointerUp(handle, { pointerId: 1, pointerType: "touch", clientY: to, timeStamp: ms });
}

describe("bottom sheet gesture", () => {
  it("resists an upward pull more the further it goes", () => {
    expect(rubberBand(0, 400)).toBe(0);
    expect(rubberBand(100, 400)).toBeLessThan(100);
    expect(rubberBand(400, 400) - rubberBand(300, 400)).toBeLessThan(rubberBand(100, 400));
  });

  it("closes on a long drag or a fast flick, never on an upward one", () => {
    expect(releaseCloses(200, 0.1, 500)).toBe(true);
    expect(releaseCloses(40, 0.9, 500)).toBe(true);
    expect(releaseCloses(40, 0.1, 500)).toBe(false);
    expect(releaseCloses(-80, 2, 500)).toBe(false);
  });

  it("drags a dialog closed from its grab strip on a phone", async () => {
    asPhone();
    const onClose = vi.fn();
    render(<ModalDialog title="Send a test call?" description="We ring you once." onClose={onClose} />);
    const handle = document.querySelector("[data-sheet-handle]");
    expect(handle?.getAttribute("aria-hidden")).toBe("true");
    drag(handle as Element, 100, 400, 120);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("does nothing for a mouse, and a short slow drag springs back", () => {
    asPhone();
    const onClose = vi.fn();
    render(<ModalDialog title="Send a test call?" description="We ring you once." onClose={onClose} />);
    const handle = document.querySelector("[data-sheet-handle]") as Element;
    fireEvent.pointerDown(handle, { pointerId: 2, pointerType: "mouse", clientY: 0 });
    fireEvent.pointerUp(handle, { pointerId: 2, pointerType: "mouse", clientY: 400 });
    drag(handle, 100, 120, 400);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("asks before a drag discards unsaved typing in a drawer", async () => {
    asPhone();
    const onClose = vi.fn();
    function Body() {
      useUnsavedGuard(true);
      return <p>Note</p>;
    }
    render(
      <Drawer open onClose={onClose} title="Priya Reddy">
        <Body />
      </Drawer>,
    );
    drag(document.querySelector("[data-sheet-handle]") as Element, 100, 500, 100);
    expect(await screen.findByRole("group", { name: "Unsaved changes" })).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("ConfirmDialog's confirm button carries the action's state", () => {
  function renderWith(status: "idle" | "pending" | "error", pending?: boolean) {
    return render(
      <ConfirmDialog
        title="Remove Venkat Rao?"
        confirmLabel="Remove"
        pendingLabel="Removing…"
        status={pending === undefined ? status : undefined}
        pending={pending}
        error={null}
        onCancel={() => undefined}
        onConfirm={() => undefined}
      >
        <p>He will not be called again.</p>
      </ConfirmDialog>,
    );
  }

  it("is busy and keeps its name while pending, and cancel waits", () => {
    renderWith("pending");
    const confirm = screen.getByRole("button", { name: "Remove" });
    expect(confirm.getAttribute("aria-busy")).toBe("true");
    expect(confirm.getAttribute("data-status")).toBe("pending");
    expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("still honours the old pending flag", () => {
    renderWith("idle", true);
    expect(screen.getByRole("button", { name: "Remove" }).getAttribute("data-status")).toBe("pending");
  });

  it("shows a failure on the button", () => {
    renderWith("error");
    const confirm = screen.getByRole("button", { name: "Remove" });
    expect(confirm.getAttribute("data-status")).toBe("error");
    expect(confirm.textContent).toContain("Try again");
  });
});

describe("NotificationCenter", () => {
  const items = [
    { id: "a", title: "Priya Reddy is ready to book", detail: "After 6 pm.", at: "2026-10-24T09:12:00Z", href: "/c/acme/leads" },
    { id: "b", title: "Credit is running low", meta: "2 waiting" },
  ];

  it("counts what it is given and lists each item with its link and IST time", async () => {
    render(<NotificationCenter heading="Needs attention" label="Needs attention: 2 items" state="ready" count={2} items={items} />);
    const bell = screen.getByRole("button", { name: "Needs attention: 2 items" });
    expect(bell.textContent).toContain("2");
    fireEvent.click(bell);
    const panel = await screen.findByRole("dialog", { name: "Needs attention" });
    expect(within(panel).getByRole("link", { name: /Priya Reddy is ready to book/ }).getAttribute("href")).toBe("/c/acme/leads");
    expect(panel.textContent).toContain("24 Oct");
    expect(panel.textContent).toContain("2 waiting");
  });

  it("caps the badge and draws none for zero or while loading", () => {
    const { rerender } = render(
      <NotificationCenter heading="H" label="Bell" state="ready" count={140} items={[]} />,
    );
    expect(screen.getByRole("button", { name: "Bell" }).textContent).toContain("99+");
    rerender(<NotificationCenter heading="H" label="Bell" state="ready" count={0} items={[]} />);
    expect(screen.getByRole("button", { name: "Bell" }).textContent).toBe("");
    rerender(<NotificationCenter heading="H" label="Bell" state="loading" count={5} items={[]} />);
    expect(screen.getByRole("button", { name: "Bell" }).textContent).toBe("");
  });

  it("says a failed read in words, marks the bell, and offers a retry", async () => {
    const onRetry = vi.fn();
    render(<NotificationCenter heading="H" label="Bell: we couldn't check" state="error" items={[]} onRetry={onRetry} />);
    const bell = screen.getByRole("button", { name: "Bell: we couldn't check" });
    expect(bell.querySelector("[data-testid=attention-unchecked]")).toBeTruthy();
    fireEvent.click(bell);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("marks a partial failure while still listing what answered, and says an empty list", async () => {
    const { rerender } = render(
      <NotificationCenter heading="H" label="Bell" state="ready" partial count={2} items={items} />,
    );
    expect(screen.getByRole("button", { name: "Bell" }).querySelector("[data-testid=attention-unchecked]")).toBeTruthy();
    rerender(<NotificationCenter heading="H" label="Bell" state="ready" count={0} items={[]} emptyText="All clear." />);
    fireEvent.click(screen.getByRole("button", { name: "Bell" }));
    expect(await screen.findByText("All clear.")).toBeTruthy();
  });
});

describe("SwipeActions", () => {
  it("offers every swipe action in the row's ⋯ menu, for a mouse and a keyboard", async () => {
    const call = vi.fn();
    render(
      <SwipeActions
        label="Priya Reddy"
        primary={{ id: "call", label: "Call back", onSelect: call }}
        secondary={[
          { id: "status", label: "Mark status", onSelect: () => undefined },
          { id: "wa", label: "WhatsApp", onSelect: () => undefined, disabled: true, hint: "No consent on record" },
        ]}
      >
        <p>Priya Reddy</p>
      </SwipeActions>,
    );
    fireEvent.keyDown(screen.getByRole("button", { name: "More actions for Priya Reddy" }), { key: "ArrowDown" });
    const menu = await screen.findByRole("menu");
    const names = within(menu).getAllByRole("menuitem").map((item) => item.textContent);
    expect(names).toEqual(["Call back", "Mark status", "WhatsAppNo consent on record"]);
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Call back" }));
    expect(call).toHaveBeenCalled();
  });

  it("asks before a destructive action and closes the question when it succeeds", async () => {
    const remove = vi.fn();
    function Row({ status }: { status: "idle" | "success" }) {
      return (
        <SwipeActions
          label="Venkat Rao"
          secondary={[
            {
              id: "remove",
              label: "Remove",
              tone: "danger",
              onSelect: remove,
              status,
              confirm: { title: "Remove Venkat Rao?", body: "He will not be called.", confirmLabel: "Remove", pendingLabel: "Removing…" },
            },
          ]}
        >
          <p>Venkat Rao</p>
        </SwipeActions>
      );
    }
    const { rerender } = render(<Row status="idle" />);
    // The swipe panel's own button (always in the DOM, shown on touch).
    fireEvent.click(within(screen.getByRole("group", { name: "More actions for Venkat Rao" })).getByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Venkat Rao?" });
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(remove).toHaveBeenCalled();
    rerender(<Row status="success" />);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("AnnouncementBar", () => {
  it("says its line, links its action, and dismisses once even if pressed twice", () => {
    const onDismiss = vi.fn();
    const { rerender } = render(
      <AnnouncementBar title="Calls may connect slowly tonight." detail="Network work 2–3 am." action={{ href: "/status", label: "Read more" }} onDismiss={onDismiss} />,
    );
    expect(screen.getByRole("status").textContent).toContain("Calls may connect slowly tonight.");
    expect(screen.getByRole("link", { name: "Read more" }).getAttribute("href")).toBe("/status");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
    rerender(<AnnouncementBar title="x" onDismiss={onDismiss} dismissStatus="pending" />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("has no close button when it cannot be dismissed", () => {
    render(<AnnouncementBar tone="critical" title="Outbound calling is paused." />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("ButtonGroup and SplitButton", () => {
  it("folds what does not fit into ⋯ menus and shows each action's state", async () => {
    render(
      <ButtonGroup
        label="Call actions"
        moreLabel="More actions for this call"
        actions={[
          { id: "a", label: "Call back", onSelect: () => undefined, status: "pending" },
          { id: "b", label: "Mark resolved", onSelect: () => undefined },
          { id: "c", label: "Open lead", href: "/lead" },
          { id: "d", label: "Report a problem", onSelect: () => undefined },
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: "Call back" }).getAttribute("aria-busy")).toBe("true");
    const menus = screen.getAllByRole("button", { name: "More actions for this call" });
    expect(menus).toHaveLength(2);
    fireEvent.keyDown(menus[1], { key: "ArrowDown" });
    const menu = await screen.findByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Report a problem"]);
  });

  it("puts the variants of one action behind the chevron", async () => {
    const later = vi.fn();
    render(
      <SplitButton onClick={() => undefined} menuLabel="More ways to call back" items={[{ id: "l", label: "Call back later", onSelect: later }]}>
        Call back
      </SplitButton>,
    );
    fireEvent.keyDown(screen.getByRole("button", { name: "More ways to call back" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Call back later" }));
    expect(later).toHaveBeenCalled();
  });
});

describe("FilterToolbar and SelectionBar", () => {
  it("counts the rows, removes one filter, and offers clear-all only for two or more", () => {
    const removeHot = vi.fn();
    const clear = vi.fn();
    const { rerender } = render(
      <FilterToolbar
        filters={<span>chips</span>}
        active={[
          { id: "h", label: "Status: Hot", onRemove: removeHot },
          { id: "a", label: "Agent: Reception", onRemove: () => undefined },
        ]}
        onClearAll={clear}
        count={{ shown: 12, total: 1340, noun: "lead" }}
      />,
    );
    expect(screen.getByRole("status").textContent).toBe("12 of 1,340 leads");
    fireEvent.click(screen.getByRole("button", { name: "Remove filter Status: Hot" }));
    expect(removeHot).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(clear).toHaveBeenCalled();
    const toggle = screen.getByRole("button", { name: /Filters/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    rerender(
      <FilterToolbar active={[{ id: "h", label: "Status: Hot", onRemove: removeHot }]} onClearAll={clear} count={{ shown: 1, noun: "lead" }} />,
    );
    expect(screen.queryByRole("button", { name: "Clear all" })).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("1 lead");
  });

  it("says how many are selected and clears them", () => {
    const onClear = vi.fn();
    const { rerender } = render(
      <SelectionBar count={0} noun="lead" onClear={onClear}>
        <button type="button">Mark status</button>
      </SelectionBar>,
    );
    expect(screen.queryByRole("region")).toBeNull();
    rerender(
      <SelectionBar count={3} noun="lead" onClear={onClear}>
        <button type="button">Mark status</button>
      </SelectionBar>,
    );
    expect(screen.getByRole("region", { name: "3 leads selected" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onClear).toHaveBeenCalled();
  });
});

describe("DataTable selection and empty state", () => {
  type Row = { id: string; name: string };
  const rows: Row[] = [
    { id: "1", name: "Priya" },
    { id: "2", name: "Venkat" },
  ];
  const columns: DataColumn<Row>[] = [{ id: "name", header: "Name", cell: (row) => row.name }];

  it("selects a row, then all, then none, and shows the mixed state between", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <DataTable label="Leads" rows={rows} columns={columns} getRowId={(r) => r.id} selection={{ selected: new Set(["1"]), onChange, rowLabel: (r) => `Select ${r.name}` }} />,
    );
    const all = screen.getByRole("checkbox", { name: "Select all rows" }) as HTMLInputElement;
    expect(all.indeterminate).toBe(true);
    fireEvent.click(all);
    expect([...onChange.mock.calls[0][0]].sort()).toEqual(["1", "2"]);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Venkat" }));
    expect([...onChange.mock.calls[1][0]].sort()).toEqual(["1", "2"]);
    rerender(
      <DataTable label="Leads" rows={rows} columns={columns} getRowId={(r) => r.id} selection={{ selected: new Set(["1", "2"]), onChange, rowLabel: (r) => `Select ${r.name}` }} />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all rows" }));
    expect([...onChange.mock.calls[2][0]]).toEqual([]);
  });

  it("shows the empty state in place of rows", () => {
    render(<DataTable label="Leads" rows={[]} columns={columns} getRowId={(r: Row) => r.id} empty={<p>No leads match.</p>} />);
    expect(screen.getByText("No leads match.")).toBeTruthy();
  });
});

describe("HoverCard and PageHeader", () => {
  it("is only the link on a device that cannot hover", () => {
    asPhone();
    render(
      <HoverCard label="Preview of Priya" trigger={<a href="/lead">Priya</a>}>
        <p>Hot lead</p>
      </HoverCard>,
    );
    fireEvent.pointerEnter(screen.getByRole("link", { name: "Priya" }));
    expect(screen.queryByText("Hot lead")).toBeNull();
  });

  it("opens on a resting pointer where hover exists, without taking focus", async () => {
    vi.useFakeTimers();
    window.matchMedia = ((query: string) => ({
      matches: query.includes("hover"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia;
    render(
      <HoverCard label="Preview of Priya" trigger={<a href="/lead">Priya</a>}>
        <p>Hot lead</p>
      </HoverCard>,
    );
    const link = screen.getByRole("link", { name: "Priya" });
    fireEvent.pointerEnter(link.parentElement as Element);
    act(() => vi.advanceTimersByTime(600));
    vi.useRealTimers();
    expect(await screen.findByText("Hot lead")).toBeTruthy();
    expect(document.activeElement).not.toBe(screen.getByText("Hot lead").parentElement);
  });

  it("prints a record's facts in its meta row", () => {
    render(<PageHeader title="Call with Priya" meta={<span>3 min 12 s</span>} />);
    expect(screen.getByText("3 min 12 s")).toBeTruthy();
  });
});
