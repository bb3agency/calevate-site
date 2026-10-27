import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import { ToastProvider } from "@/components/arc/toast";
import type { Me } from "@/lib/api/client";
import type { KbNote } from "@/lib/api/kb";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage, type Routes } from "./harness";

/**
 * Typed notes on the knowledge page (D-893 L7): rename in place, remove behind a question
 * with an Undo, and put a removed note back. The buttons call `/v1/kb/notes/*`, the same
 * `kb/store` functions Pip's knowledge actions call.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "kb:write"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};
const STAFF: Me = { ...OWNER, role: "staff", permissions: ["agents:read"] };

const PARKING: KbNote = {
  id: "n1",
  name: "Parking",
  state: "in_use",
  version: 2,
  chunks: 1,
  changed_at: "2026-10-20T06:00:00Z",
  restorable: true,
};
const DIWALI: KbNote = {
  id: "n2",
  name: "Diwali hours",
  state: "removed",
  version: 1,
  chunks: 1,
  changed_at: "2026-10-21T06:00:00Z",
  restorable: true,
};

async function renderNotes(me: Me = OWNER, notes: KbNote[] = [PARKING, DIWALI], over: Routes = {}) {
  return await renderClientPage(
    <ToastProvider>
      <KnowledgePage />
    </ToastProvider>,
    {
    "/v1/me": me,
    "/v1/kb/notes": { notes },
    "/v1/kb/uploads": [],
    "/v1/teach/questions": { items: [], open_count: 0 },
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
    "/v1/kb/teach/open": { teaching: null },
    ...over,
  });
}

describe("typed notes", () => {
  it("renames a note in place through the notes route", async () => {
    const { calls } = await renderNotes(OWNER, [PARKING], {
      "PATCH /v1/kb/notes/n1": { ...PARKING, name: "Car park" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Rename note: Parking" }));
    const field = screen.getByLabelText("Note name");
    fireEvent.change(field, { target: { value: "Car park" } });
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH" && c.path === "/v1/kb/notes/n1");
      expect(patch?.body).toBe(JSON.stringify({ name: "Car park" }));
    });
  });

  it("refuses a one-letter name without sending it", async () => {
    const { calls } = await renderNotes(OWNER, [PARKING]);
    fireEvent.click(await screen.findByRole("button", { name: "Rename note: Parking" }));
    const field = screen.getByLabelText("Note name");
    fireEvent.change(field, { target: { value: "P" } });
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    expect(await screen.findByText("A name needs at least 2 characters.")).toBeTruthy();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("asks before removing, then offers Undo, which puts it back", async () => {
    const { calls } = await renderNotes(OWNER, [PARKING], {
      "POST /v1/kb/notes/n1/remove": { ...PARKING, state: "removed" },
      "POST /v1/kb/notes/n1/restore": PARKING,
    });
    fireEvent.click(await screen.findByRole("button", { name: "Remove Parking" }));
    const question = await screen.findByRole("dialog", { name: "Remove Parking?" });
    expect(question.textContent).toContain("put it back");
    expect(calls.some((c) => c.path === "/v1/kb/notes/n1/remove")).toBe(false);
    await act(async () => fireEvent.click(within(question).getByRole("button", { name: "Remove it" })));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/kb/notes/n1/remove")).toBe(true),
    );
    await act(async () => fireEvent.click(await screen.findByRole("button", { name: "Undo" })));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/kb/notes/n1/restore")).toBe(true),
    );
  });

  it("folds removed notes away and puts one back", async () => {
    const { calls } = await renderNotes(OWNER, [PARKING, DIWALI], {
      "POST /v1/kb/notes/n2/restore": { ...DIWALI, state: "in_use" },
    });
    fireEvent.click(await screen.findByText("Removed notes"));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Put back" })));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/kb/notes/n2/restore")).toBe(true),
    );
  });

  it("says why a removed note that never went live cannot be put back", async () => {
    await renderNotes(OWNER, [{ ...DIWALI, restorable: false }]);
    fireEvent.click(await screen.findByText("Removed notes"));
    expect(screen.getByText("Never went live, so there is nothing to put back.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Put back" })).toBeNull();
  });

  it("shows a reader who may not change knowledge the notes and no buttons", async () => {
    await renderNotes(STAFF);
    expect(await screen.findByText("Parking")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove Parking" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Rename note/ })).toBeNull();
  });

  it("shows the server's reason when a remove fails, in the question", async () => {
    await renderNotes(OWNER, [PARKING], {
      "POST /v1/kb/notes/n1/remove": problem(409, { title: "Conflict", detail: "Try again in a moment." }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Remove Parking" }));
    const question = await screen.findByRole("dialog", { name: "Remove Parking?" });
    await act(async () => fireEvent.click(within(question).getByRole("button", { name: "Remove it" })));
    expect(await within(question).findByText(/Try again in a moment/)).toBeTruthy();
  });

  it("survives a very long note name", async () => {
    const long = { ...PARKING, name: "Valet parking and drop-off rules for weddings ".repeat(2).trim() };
    await renderNotes(OWNER, [long]);
    expect(await screen.findByRole("button", { name: `Rename note: ${long.name}` })).toBeTruthy();
  });

  it("is accessible", async () => {
    const { container } = await renderNotes();
    await screen.findByText("Parking");
    await expectNoA11yViolations(container, "knowledge notes");
  });
});
