import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContactEditor } from "@/app/c/[slug]/campaigns/ContactEditor";
import {
  MAX_CONTACTS_PER_UPLOAD,
  SAMPLE_CSV,
  checkContacts,
  normalizePhone,
  parseCsv,
  rowsToEntries,
  type ContactEntry,
} from "@/app/c/[slug]/campaigns/contactList";

/**
 * The campaign contact list: the CSV reader, the per-row verdicts that mirror the server's
 * `normalize_phone` and `ContactIn` limits, and the editor that builds a list from a file,
 * a paste or one contact at a time.
 */

const entries = (text: string) => rowsToEntries(parseCsv(text)).entries;

describe("reading a CSV", () => {
  it("drops a byte-order mark and reads CRLF, LF and CR line ends alike", () => {
    expect(parseCsv("﻿phone,name\r\n9876543210,Priya\n9876501234,Ravi\r9876512345,Asha")).toEqual([
      ["phone", "name"],
      ["9876543210", "Priya"],
      ["9876501234", "Ravi"],
      ["9876512345", "Asha"],
    ]);
  });

  it("keeps commas, quotes and line breaks that sit inside quoted fields", () => {
    expect(parseCsv('phone,name,note\n9876543210,"Rao, Priya","said ""call me""\nafter 5"')).toEqual([
      ["phone", "name", "note"],
      ["9876543210", "Rao, Priya", 'said "call me"\nafter 5'],
    ]);
  });

  it("reads a semicolon export and a pasted tab-separated range", () => {
    expect(parseCsv("phone;name\n9876543210;Priya")).toEqual([["phone", "name"], ["9876543210", "Priya"]]);
    expect(parseCsv("phone\tname\n9876543210\tPriya")).toEqual([["phone", "name"], ["9876543210", "Priya"]]);
  });

  it("skips blank lines, including the trailing one Excel writes", () => {
    expect(parseCsv("phone\n9876543210\n\n,\n")).toEqual([["phone"], ["9876543210"]]);
  });

  it("finds the phone and name columns by header and keeps the rest as variables", () => {
    const [row] = entries("Name,Mobile Number,appointment_time\nPriya,98765 43210,Tue 4pm");
    expect(row.phone).toBe("98765 43210");
    expect(row.name).toBe("Priya");
    expect(row.vars).toEqual({ appointment_time: "Tue 4pm" });
  });

  it("reads a file with no header as phone, then name", () => {
    const [row] = entries("9876543210,Priya,ignored");
    expect([row.phone, row.name, row.vars]).toEqual(["9876543210", "Priya", {}]);
  });

  it("keeps at most ten variables and never one called phone or name", () => {
    const header = ["phone", ...Array.from({ length: 12 }, (_, i) => `v${i}`), "name "].join(",");
    const { dropped } = rowsToEntries(parseCsv(`${header}\n9876543210`));
    expect(dropped).toEqual(["v10", "v11"]);
  });
});

describe("the server's phone rules, mirrored", () => {
  it.each([
    ["9876543210", "+919876543210"],
    ["98765 43210", "+919876543210"],
    ["09876543210", "+919876543210"],
    ["919876543210", "+919876543210"],
    ["+91 98765-43210", "+919876543210"],
    ["+14155550123", "+14155550123"],
  ])("reads %s as %s", (raw, e164) => expect(normalizePhone(raw)).toBe(e164));

  it.each(["12345", "5876543210", "++919876543210", "98765+43210", "", "phone"])(
    "refuses %j rather than guessing",
    (raw) => expect(normalizePhone(raw)).toBeNull(),
  );
});

describe("checking a list", () => {
  it("counts ready, invalid and duplicate rows, and sends only the ready ones", () => {
    const list = checkContacts(
      entries("phone,name\n9876543210,Priya\n+91 98765 43210,Again\n12345,Bad\n+14155550123,Abroad\n9876501234,Ravi"),
    );
    expect(list.counts).toEqual({ ready: 2, invalid: 2, duplicate: 1 });
    expect(list.ready).toEqual([
      { phone: "+919876543210", name: "Priya" },
      { phone: "+919876501234", name: "Ravi" },
    ]);
    const reasons = list.rows.filter((r) => r.status.kind === "invalid").map((r) =>
      r.status.kind === "invalid" ? r.status.reason : "",
    );
    expect(reasons).toEqual(["We can't read this number", "Only Indian (+91) numbers are called"]);
  });

  it("marks a row whose name or value is longer than the server takes", () => {
    const list = checkContacts([
      { id: "a", phone: "9876543210", name: "x".repeat(121), vars: {} },
      { id: "b", phone: "9876501234", name: "", vars: { note: "y".repeat(201) } },
    ]);
    expect(list.counts.invalid).toBe(2);
  });

  it("refuses a list larger than one upload takes", () => {
    const many: ContactEntry[] = Array.from({ length: MAX_CONTACTS_PER_UPLOAD + 1 }, (_, i) => ({
      id: String(i),
      phone: `98${String(i).padStart(8, "0")}`,
      name: "",
      vars: {},
    }));
    expect(checkContacts(many).refusal).toMatch(/at most 5,000/);
  });

  it("carries variables as `custom`", () => {
    expect(checkContacts(entries("phone,slot\n9876543210,4pm")).ready).toEqual([
      { phone: "+919876543210", custom: { slot: "4pm" } },
    ]);
  });
});

/** The editor with its own state, as the flow and the campaign page hold it. */
function Harness({ initial = [] }: { initial?: ContactEntry[] }) {
  const [list, setList] = useState<ContactEntry[]>(initial);
  return <ContactEditor entries={list} onChange={setList} />;
}

describe("the contact editor", () => {
  afterEach(() => vi.restoreAllMocks());

  it("imports a chosen file and reports what it found", async () => {
    render(<Harness />);
    const file = new File(["phone,name\n9876543210,Priya\n12345,Bad\n9876543210,Dup"], "list.csv", {
      type: "text/csv",
    });
    fireEvent.change(screen.getByLabelText("Import a CSV file"), { target: { files: [file] } });

    await screen.findByText(/Added 3 rows from list\.csv/);
    expect(screen.getByText("1 ready")).toBeTruthy();
    expect(screen.getByText(/1 can't be called/)).toBeTruthy();
    expect(screen.getByText(/1 duplicate/)).toBeTruthy();
    expect(screen.getByText("We can't read this number")).toBeTruthy();
  });

  it("removes a row, and clears every row that will not be called in one press", async () => {
    render(<Harness initial={entries("phone\n9876543210\n12345\n9876543210")} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove 2 that won't be called" }));
    expect(screen.getByText("1 ready")).toBeTruthy();
    expect(screen.queryByText(/can't be called/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Remove 9876543210" }));
    expect(screen.queryByText("1 ready")).toBeNull();
  });

  it("adds one contact, and pastes rows from a spreadsheet", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Add contact" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Phone" }), { target: { value: "98765 43210" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByText("+91 98765 43210")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Paste" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Paste rows" }), {
      target: { value: "phone\tname\n9876501234\tRavi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add these rows" }));
    expect(screen.getByText("2 ready")).toBeTruthy();
  });

  it("finds a row by search", () => {
    render(<Harness initial={entries("phone,name\n9876543210,Priya\n9876501234,Ravi")} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search contacts" }), { target: { value: "rav" } });
    const table = screen.getByRole("table");
    expect(within(table).queryByText("Priya")).toBeNull();
    expect(within(table).getByText("Ravi")).toBeTruthy();
  });

  it("downloads a sample built only from non-dialable demo numbers", async () => {
    const blobs: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      blobs.push(blob as Blob);
      return "blob:sample";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Sample CSV" }));

    expect(click).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(blobs).toHaveLength(1));
    const text = await blobs[0].text();
    expect(text).toBe(SAMPLE_CSV);
    for (const [phone] of parseCsv(text).slice(1)) expect(phone.startsWith("+9199000")).toBe(true);
  });

  it("states the do-not-call rule as a fact, with no control to turn it off", () => {
    render(<Harness />);
    expect(screen.getByText(/Numbers on your do-not-call list are never dialled/)).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });
});
