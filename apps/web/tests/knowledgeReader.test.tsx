import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import type { Me } from "@/lib/api/client";
import type { KbUpload, KbUploadText } from "@/lib/api/kb";

import { expectNoA11yViolations } from "./a11y";
import { renderClientPage, type Routes } from "./harness";

/**
 * THE READER (D-893 L8): a file's or link's row opens the words we hold for it, a page at a
 * time, says plainly whether the agents use it, and offers Rename, Replace file and Remove.
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

const MENU: KbUpload = {
  id: "u1",
  source_id: "s1",
  name: "Menu.pdf",
  source_kind: "pdf",
  ingest_status: "processed",
  ingest_detail: null,
  review_state: "approved",
  is_live: true,
  version: 1,
  filename: "Menu.pdf",
  byte_size: 2048,
  source_url: null,
  text_provenance: null,
  change_detected_at: null,
  read_state: "ready",
  read_detail: null,
  page_count: 2,
  reaches_agents: false,
};

function page(n: number, words: string): KbUploadText {
  return {
    upload_id: "u1",
    name: "Menu.pdf",
    kind: "file",
    state: "not_used_yet",
    reaches_agents: false,
    origin: "Menu.pdf",
    version: 1,
    page: n,
    pages: 2,
    sections: [{ label: `Page ${n}`, content: words }],
    note: "2 pages",
  };
}

async function openReader(me: Me = OWNER, over: Routes = {}) {
  const rendered = await renderClientPage(<KnowledgePage />, {
    "/v1/me": me,
    "/v1/kb/sources": [],
    "/v1/kb/uploads": [MENU],
    "/v1/kb/struggles": [],
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
    "/v1/kb/teach/open": { teaching: null },
    "/v1/kb/uploads/u1/text?page=1": page(1, "Thali costs 180 rupees."),
    "/v1/kb/uploads/u1/text?page=2": page(2, "Open all seven days."),
    ...over,
  });
  fireEvent.click(await screen.findByRole("button", { name: "Menu.pdf" }));
  const dialog = await screen.findByRole("dialog", { name: "Menu.pdf" });
  return { ...rendered, dialog };
}

describe("the reader", () => {
  it("shows the stored words a page at a time and says the agents don't use them yet", async () => {
    const { dialog } = await openReader();
    expect(await within(dialog).findByText("Thali costs 180 rupees.")).toBeTruthy();
    expect(within(dialog).getByText("Your agents don't use this yet.")).toBeTruthy();
    expect(within(dialog).getByText("Page 1")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Next" }));
    expect(await within(dialog).findByText("Open all seven days.")).toBeTruthy();
    expect(within(dialog).getByText("2 of 2")).toBeTruthy();
  });

  it("renames through the API, the same call Pip's rename makes", async () => {
    const { dialog, calls } = await openReader(OWNER, {
      "PATCH /v1/kb/uploads/u1": { ...MENU, name: "Lunch menu" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Rename" }));
    const field = within(dialog).getByLabelText("New name");
    fireEvent.change(field, { target: { value: "Lunch menu" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save name" }));
    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH" && c.path === "/v1/kb/uploads/u1");
      expect(patch?.body).toBe(JSON.stringify({ name: "Lunch menu" }));
    });
  });

  it("offers Read it again for a PDF and asks the API to read it", async () => {
    const { dialog, calls } = await openReader(OWNER, {
      "POST /v1/kb/uploads/u1/read": { ...MENU, read_state: "reading" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Read it again" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/kb/uploads/u1/read")).toBe(true),
    );
  });

  it("hands Remove to the row's own question", async () => {
    const { dialog } = await openReader();
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("dialog", { name: "Remove Menu.pdf?" })).toBeTruthy();
    // The reader closed: one modal at a time, so the question owns focus.
    expect(screen.queryByRole("dialog", { name: "Menu.pdf" })).toBeNull();
  });

  it("shows a reader who may not change knowledge the words and no buttons", async () => {
    const { dialog } = await openReader(STAFF);
    expect(await within(dialog).findByText("Thali costs 180 rupees.")).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Rename" })).toBeNull();
  });

  it("is accessible", async () => {
    const { dialog } = await openReader();
    await within(dialog).findByText("Thali costs 180 rupees.");
    await expectNoA11yViolations(dialog, "knowledge reader");
  });
});
