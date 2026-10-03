import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { DataTable, sortRows, type DataColumn } from "@/components/console/dataTable";
import { InfoTip } from "@/components/console/infoTip";
import { SPEAKER_HOLD_MS, SpeakingIndicator } from "@/components/console/speakingIndicator";
import { compareDecimal } from "@/components/console/valueFlash";
import { CopyButton } from "@/components/interior/copy-button";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { Tabs } from "@/components/interior/tabs";

/**
 * The shared console pieces the pilot screens are built from. Each assertion is a
 * behaviour a screen relies on without restating it: focus that follows the keyboard,
 * money that is never compared as a float, help that is reachable without a mouse, and a
 * live indicator that a screen reader is not made to listen to.
 */

describe("Tabs (vendored interior)", () => {
  it("moves FOCUS with the arrow keys, not only the selection", () => {
    // The styled `Tabs` passed its own ref over `getTabProps().ref`, so the roving-focus
    // map stayed empty: ArrowRight selected the next tab and left focus on a button whose
    // tabIndex had just become -1.
    render(
      <Tabs
        label="Call views"
        items={[
          { value: "a", label: "Summary" },
          { value: "b", label: "Transcript" },
          { value: "c", label: "Captured details" },
        ]}
        renderPanel={(value) => <p>panel {value}</p>}
      />,
    );
    const first = screen.getByRole("tab", { name: "Summary" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    const second = screen.getByRole("tab", { name: "Transcript" });
    expect(document.activeElement).toBe(second);
    expect(second.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(second, { key: "End" });
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Captured details" }));
  });

  it("points aria-controls only at the panel that exists", () => {
    render(
      <Tabs
        items={[
          { value: "a", label: "One" },
          { value: "b", label: "Two" },
        ]}
        renderPanel={(value) => <p>panel {value}</p>}
      />,
    );
    const selected = screen.getByRole("tab", { name: "One" });
    const other = screen.getByRole("tab", { name: "Two" });
    expect(document.getElementById(selected.getAttribute("aria-controls") ?? "")).not.toBeNull();
    expect(other.getAttribute("aria-controls")).toBeNull();
  });
});

function Segmented({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial);
  return (
    <SegmentedControl
      label="Show calls"
      value={value}
      onValueChange={setValue}
      options={[
        { value: "", label: "All" },
        { value: "live", label: "In progress", count: "2" },
        { value: "off", label: "Archived", disabled: true },
        { value: "done", label: "Completed" },
      ]}
    />
  );
}

describe("SegmentedControl", () => {
  it("is a radio group whose arrow keys move focus and choose, skipping a disabled option", () => {
    render(<Segmented initial="live" />);
    expect(screen.getByRole("radiogroup", { name: "Show calls" })).toBeTruthy();
    const live = screen.getByRole("radio", { name: /In progress/ });
    expect(live.getAttribute("aria-checked")).toBe("true");
    expect(live.textContent).toContain("2");
    live.focus();
    fireEvent.keyDown(live, { key: "ArrowRight" });
    const done = screen.getByRole("radio", { name: "Completed" });
    expect(document.activeElement).toBe(done);
    expect(done.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "Archived" }).getAttribute("aria-disabled")).toBe("true");
  });

  it("checks nothing when the value matches no option, rather than pretending the first", () => {
    render(<Segmented initial="unknown" />);
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio.getAttribute("aria-checked")).toBe("false");
    }
  });
});

describe("CopyButton", () => {
  it("names what it copies, writes it, and says so outside the button", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const { container } = render(<CopyButton value="+919876543210" label="Copy phone number" />);
    const button = screen.getByRole("button", { name: "Copy phone number" });
    await act(async () => {
      fireEvent.click(button);
    });
    expect(writeText).toHaveBeenCalledWith("+919876543210");
    const live = container.querySelector("[aria-live='polite']");
    expect(live?.textContent).toBe("Copied");
    expect(button.contains(live)).toBe(false);
  });
});

describe("InfoTip", () => {
  it("keeps its prose out of the page until asked, opens by keyboard or tap, and gives focus back", async () => {
    render(
      <div>
        <InfoTip label="the CSV export">
          <p>Each download is recorded.</p>
        </InfoTip>
      </div>,
    );
    expect(screen.queryByText("Each download is recorded.")).toBeNull();
    const trigger = screen.getByRole("button", { name: "About the CSV export" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    const panel = await screen.findByRole("dialog", { name: "the CSV export" });
    expect(panel.textContent).toContain("Each download is recorded.");
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    await waitFor(() => expect(panel.contains(document.activeElement)).toBe(true));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(trigger);
  });
});

describe("money and ordering", () => {
  it("compares decimal strings exactly, never through a float", () => {
    expect(compareDecimal("10159.00", "9999.99")).toBe(1);
    expect(compareDecimal("0.10", "0.1")).toBe(0);
    expect(compareDecimal("-3.5", "2")).toBe(-1);
    // Past float precision: these two differ only in the 17th significant digit.
    expect(compareDecimal("12345678901234567.01", "12345678901234567.02")).toBe(-1);
    expect(compareDecimal("₹10", "5")).toBeNull();
  });

  it("sorts a decimal column by value and keeps empty cells last in both directions", () => {
    type Row = { id: string; amount: string | null };
    const rows: Row[] = [
      { id: "a", amount: "9.50" },
      { id: "b", amount: null },
      { id: "c", amount: "10159.00" },
      { id: "d", amount: "100.00" },
    ];
    const columns: DataColumn<Row>[] = [
      { id: "amount", header: "Amount", cell: (r) => r.amount, sort: { value: (r) => r.amount, kind: "decimal" } },
    ];
    expect(sortRows(rows, columns, { id: "amount", direction: "asc" }).map((r) => r.id)).toEqual(["a", "d", "c", "b"]);
    expect(sortRows(rows, columns, { id: "amount", direction: "desc" }).map((r) => r.id)).toEqual(["c", "d", "a", "b"]);
    expect(sortRows(rows, columns, null).map((r) => r.id)).toEqual(["a", "b", "c", "d"]);
  });
});

describe("DataTable", () => {
  type Call = { id: string; who: string; seconds: number; status: string };
  const columns: DataColumn<Call>[] = [
    { id: "who", header: "Caller", cell: (c) => c.who },
    {
      id: "seconds",
      header: "Length",
      cell: (c) => String(c.seconds),
      sort: { value: (c) => c.seconds, kind: "number", first: "desc" },
    },
    { id: "status", header: "Outcome", cell: (c) => c.status, flash: (c) => c.status },
  ];
  const rows: Call[] = [
    { id: "1", who: "Asha", seconds: 30, status: "in_progress" },
    { id: "2", who: "Ravi", seconds: 90, status: "completed" },
  ];

  it("sorts from its header, says which way, and notes when it holds only part of the list", () => {
    render(
      <DataTable rows={rows} columns={columns} getRowId={(c) => c.id} label="Calls" partialNote="Sorted within the 2 calls loaded." />,
    );
    const header = screen.getByRole("columnheader", { name: /Length/ });
    expect(header.getAttribute("aria-sort")).toBeNull();
    expect(screen.queryByText("Sorted within the 2 calls loaded.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Length/ }));
    expect(header.getAttribute("aria-sort")).toBe("descending");
    const firstCells = screen.getAllByRole("row").slice(1).map((row) => row.textContent);
    expect(firstCells[0]).toContain("Ravi");
    expect(screen.getByText("Sorted within the 2 calls loaded.")).toBeTruthy();
    // Announced with the order, not only printed: the caveat is what stops "descending"
    // being heard as "the longest call of all".
    expect(screen.getByText(/Sorted by Length, descending. Sorted within the 2 calls loaded./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Length/ }));
    expect(header.getAttribute("aria-sort")).toBe("ascending");
    fireEvent.click(screen.getByRole("button", { name: /Length/ }));
    expect(header.getAttribute("aria-sort")).toBeNull();
  });

  it("marks a cell only when a poll changes its value, never on first paint", () => {
    const { container, rerender } = render(
      <DataTable rows={rows} columns={columns} getRowId={(c) => c.id} label="Calls" />,
    );
    expect(container.querySelector(".value-flash")).toBeNull();
    // The same answer again: nothing moved, nothing is marked.
    rerender(<DataTable rows={[...rows]} columns={columns} getRowId={(c) => c.id} label="Calls" />);
    expect(container.querySelector(".value-flash")).toBeNull();
    const ended = [{ ...rows[0], status: "completed" }, rows[1]];
    rerender(<DataTable rows={ended} columns={columns} getRowId={(c) => c.id} label="Calls" />);
    const marked = container.querySelectorAll(".value-flash");
    expect(marked).toHaveLength(1);
    expect(marked[0].textContent).toBe("completed");
  });
});

describe("SpeakingIndicator", () => {
  it("is invisible to a screen reader and marks the side that is speaking", () => {
    const { container, rerender } = render(<SpeakingIndicator speaker={null} />);
    expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
    expect(container.textContent).not.toContain("Speaking");
    rerender(<SpeakingIndicator speaker="agent" labels={{ caller: "Caller", agent: "Reception" }} />);
    const agentSide = screen.getByText("Reception").closest("div");
    expect(agentSide?.textContent).toContain("Speaking");
    expect(screen.getByText("Caller").closest("div")?.textContent).not.toContain("Speaking");
  });

  it("holds the last speaker briefly through a pause, then lets go", () => {
    vi.useFakeTimers();
    try {
      const { container, rerender } = render(<SpeakingIndicator speaker="caller" />);
      rerender(<SpeakingIndicator speaker={null} />);
      expect(container.textContent).toContain("Speaking");
      act(() => {
        vi.advanceTimersByTime(SPEAKER_HOLD_MS + 10);
      });
      expect(container.textContent).not.toContain("Speaking");
    } finally {
      vi.useRealTimers();
    }
  });
});
