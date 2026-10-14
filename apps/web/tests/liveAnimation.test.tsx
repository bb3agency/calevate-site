import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { StatusPill } from "@/components/console/statusPill";
import { continuesFrom, useEnterClass } from "@/components/live/arrivals";

/**
 * The live motion rules (D-774): nothing moves on first load, a row that ARRIVES enters,
 * a page that is replaced does not, a reader scrolled away is told rather than moved, a
 * status that changes is marked, and reduced motion is honoured by the stylesheet itself.
 */

type Row = { id: string; who: string; status: string };
const columns: DataColumn<Row>[] = [
  { id: "who", header: "Caller", cell: (r) => r.who },
  { id: "status", header: "Status", cell: (r) => r.status },
];
const rowsOf = (...ids: string[]): Row[] => ids.map((id) => ({ id, who: `Caller ${id}`, status: "ok" }));
const table = (rows: Row[], extra: Partial<Parameters<typeof DataTable<Row>>[0]> = {}) => (
  <DataTable rows={rows} columns={columns} getRowId={(r) => r.id} label="Calls" {...extra} />
);
const arrivingRows = (container: HTMLElement) =>
  [...container.querySelectorAll("tr.live-arrive")].map((tr) => tr.textContent);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a live row", () => {
  it("does not animate on first load", () => {
    const { container } = render(table(rowsOf("a", "b", "c")));
    expect(arrivingRows(container)).toEqual([]);
    expect(container.querySelector(".live-enter, .value-flash")).toBeNull();
  });

  it("enters when it arrives, and only it", () => {
    const { container, rerender } = render(table(rowsOf("a", "b", "c")));
    rerender(table(rowsOf("d", "a", "b", "c")));
    expect(arrivingRows(container)).toEqual(["Caller dok"]);
  });

  it("does not enter when the page is replaced rather than continued", () => {
    const { container, rerender } = render(table(rowsOf("a", "b", "c", "d")));
    rerender(table(rowsOf("e", "f", "g", "h")));
    expect(arrivingRows(container)).toEqual([]);
  });

  it("offers the arrivals instead of moving a reader who scrolled past the top", async () => {
    let report: ((entries: { isIntersecting: boolean }[]) => void) | null = null;
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
          report = callback;
        }
        observe() {}
        disconnect() {}
      },
    );
    const { rerender } = render(table(rowsOf("a", "b", "c")));
    act(() => report?.([{ isIntersecting: false }]));
    rerender(table(rowsOf("d", "e", "a", "b", "c")));
    const offer = screen.getByRole("button", { name: "2 new rows" });
    expect(offer).toBeTruthy();
    act(() => report?.([{ isIntersecting: true }]));
    await waitFor(() => expect(screen.queryByRole("button", { name: /new rows/ })).toBeNull());
  });

  it("announces only what the screen says is worth announcing", () => {
    const { container, rerender } = render(
      table(rowsOf("a", "b"), {
        announceArrivals: (rows) => (rows.some((r) => r.status === "hot") ? "A new hot lead." : null),
      }),
    );
    const regions = () => [...container.querySelectorAll('[aria-live="polite"]')].map((p) => p.textContent);
    rerender(
      table([{ id: "c", who: "Caller c", status: "ok" }, ...rowsOf("a", "b")], {
        announceArrivals: (rows) => (rows.some((r) => r.status === "hot") ? "A new hot lead." : null),
      }),
    );
    expect(regions()).not.toContain("A new hot lead.");
    rerender(
      table([{ id: "d", who: "Caller d", status: "hot" }, { id: "c", who: "Caller c", status: "ok" }, ...rowsOf("a", "b")], {
        announceArrivals: (rows) => (rows.some((r) => r.status === "hot") ? "A new hot lead." : null),
      }),
    );
    expect(regions()).toContain("A new hot lead.");
  });
});

describe("continuesFrom", () => {
  it("reads a few arrivals as live and a replaced set as a load", () => {
    expect(continuesFrom(new Set(["a", "b", "c"]), ["d", "a", "b", "c"])).toBe(true);
    expect(continuesFrom(new Set(["a", "b", "c"]), ["a", "b"])).toBe(true);
    expect(continuesFrom(new Set(["a", "b"]), ["c", "d"])).toBe(false);
    expect(continuesFrom(new Set(), ["a"])).toBe(true);
    expect(continuesFrom(new Set(), ["a", "b", "c", "d", "e"])).toBe(false);
  });
});

function List({ ids }: { ids: string[] }) {
  const enter = useEnterClass(ids);
  return (
    <ul>
      {ids.map((id) => (
        <li key={id} className={enter(id)}>
          {id}
        </li>
      ))}
    </ul>
  );
}

describe("useEnterClass", () => {
  it("marks an arrival in a plain list, never the first render", () => {
    const { container, rerender } = render(<List ids={["a", "b"]} />);
    expect(container.querySelector(".live-enter")).toBeNull();
    rerender(<List ids={["c", "a", "b"]} />);
    expect([...container.querySelectorAll(".live-enter")].map((li) => li.textContent)).toEqual(["c"]);
  });
});

describe("StatusPill", () => {
  it("marks a state that changes while the screen is open, never the first one", () => {
    const { container, rerender } = render(<StatusPill tone="warn">Ringing</StatusPill>);
    expect(container.querySelector(".value-flash")).toBeNull();
    rerender(<StatusPill tone="warn">Ringing</StatusPill>);
    expect(container.querySelector(".value-flash")).toBeNull();
    rerender(<StatusPill tone="ok">Answered</StatusPill>);
    expect(container.querySelector(".value-flash")).not.toBeNull();
    expect(container.querySelector("[data-tone]")?.getAttribute("data-tone")).toBe("ok");
  });
});

describe("reduced motion", () => {
  const css = readFileSync(join(process.cwd(), "src", "app", "globals.css"), "utf8");

  it.each(["live-enter", "live-arrive", "value-flash"])(
    "%s animates only under prefers-reduced-motion: no-preference",
    (utility) => {
      const block = new RegExp(`@utility ${utility} \\{([\\s\\S]*?)\\n\\}`).exec(css);
      expect(block, `@utility ${utility} in globals.css`).not.toBeNull();
      const body = block?.[1] ?? "";
      const media = body.indexOf("@media (prefers-reduced-motion: no-preference)");
      expect(media).toBeGreaterThanOrEqual(0);
      expect(body.indexOf("animation")).toBeGreaterThan(media);
    },
  );
});
