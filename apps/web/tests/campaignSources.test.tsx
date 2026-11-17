import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CampaignWorkspace } from "@/app/c/[slug]/campaigns/CampaignWorkspace";
import type { KbNote, KbUpload } from "@/lib/api/kb";

import { FIXTURE_CAMPAIGN_ID, notesFixture, settingsFixture, workspaceFixture } from "./campaignFixtures";
import { renderClientPage, type ApiCall, type Routes } from "./harness";

/**
 * A campaign's Sources fold (founder, 16 Nov 2026): the campaign picks from What your agents
 * know, and "Add a file or note" adds to What your agents know and picks it. One place holds
 * the files, so nothing here keeps a list of its own.
 */

const NOTE_ID = "0192f0aa-5555-7000-8000-000000000001";
const FILE_ID = "0192f0aa-5555-7000-8000-000000000002";
const NEW_ID = "0192f0aa-5555-7000-8000-000000000003";
const base = `/v1/campaigns/${FIXTURE_CAMPAIGN_ID}`;

function note(id: string, name: string): KbNote {
  return { id, name, state: "in_use", version: 1, chunks: 1, changed_at: "2026-11-16T04:00:00Z", restorable: false };
}

const UPLOAD: KbUpload = {
  id: "upload-1",
  source_id: FILE_ID,
  name: "Price list.pdf",
  source_kind: "pdf",
  facts_count: 0,
  ingest_status: "processed",
  review_state: "approved",
  is_live: true,
  reaches_agents: true,
  version: 1,
};

const routes = (extra: Routes = {}): Routes => ({
  [`${base}/workspace`]: workspaceFixture(),
  [`${base}/settings`]: settingsFixture(),
  [`${base}/notes`]: notesFixture(),
  "/v1/kb/notes": { notes: [note(NOTE_ID, "Diwali offer")] },
  "/v1/kb/uploads": [UPLOAD],
  ...extra,
});

const render = (extra: Routes = {}) =>
  renderClientPage(<CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />, routes(extra));

const bodyOf = (calls: ApiCall[], method: string, path: string) => {
  const call = calls.find((c) => c.method === method && c.path === path);
  expect(call, `${method} ${path}`).toBeTruthy();
  return JSON.parse(call?.body ?? "null") as unknown;
};

describe("a campaign's sources", () => {
  it("lists what the agents know and saves the ticked ones", async () => {
    const rendered = await render({
      [`PUT ${base}/sources`]: workspaceFixture({ source_ids: [FILE_ID] }),
    });
    const list = await screen.findByRole("group", { name: "Sources for this campaign" });
    expect(within(list).getByText("Price list.pdf")).toBeTruthy();
    expect(within(list).getByText("Diwali offer")).toBeTruthy();
    fireEvent.click(within(list).getByRole("checkbox", { name: /Price list\.pdf/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save sources" }));
    await waitFor(() =>
      expect(bodyOf(rendered.calls, "PUT", `${base}/sources`)).toEqual({ source_ids: [FILE_ID] }),
    );
    // No campaign-only list of materials is read or written any more.
    expect(rendered.calls.some((c) => c.path.includes("/materials"))).toBe(false);
  });

  it("shows the saved picks ticked", async () => {
    await render({ [`${base}/workspace`]: workspaceFixture({ source_ids: [NOTE_ID] }) });
    const list = await screen.findByRole("group", { name: "Sources for this campaign" });
    expect((within(list).getByRole("checkbox", { name: /Diwali offer/ }) as HTMLInputElement).checked).toBe(true);
    expect((within(list).getByRole("checkbox", { name: /Price list\.pdf/ }) as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText("1 chosen")).toBeTruthy();
  });

  it("adds a note to What your agents know and picks it", async () => {
    const rendered = await render({
      [`POST ${base}/sources/note`]: workspaceFixture({ source_ids: [NEW_ID] }),
    });
    await screen.findByRole("group", { name: "Sources for this campaign" });
    fireEvent.click(screen.getByRole("button", { name: "Add a file or note" }));
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Service plans start at 999." } });
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: "Plan prices" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(bodyOf(rendered.calls, "POST", `${base}/sources/note`)).toEqual({
        note: "Service plans start at 999.",
        title: "Plan prices",
      }),
    );
    // The knowledge lists are read again, so the new note shows in the pick list.
    await waitFor(() =>
      expect(rendered.calls.filter((c) => c.method === "GET" && c.path === "/v1/kb/notes").length).toBeGreaterThan(1),
    );
  });

  it("refuses an empty note before sending anything", async () => {
    const rendered = await render();
    await screen.findByRole("group", { name: "Sources for this campaign" });
    fireEvent.click(screen.getByRole("button", { name: "Add a file or note" }));
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Write the note.");
    expect(rendered.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("clears picked sources that were removed, which have no box to untick", async () => {
    const GONE = "0192f0aa-5555-7000-8000-0000000000ff";
    const rendered = await render({
      [`${base}/workspace`]: workspaceFixture({ source_ids: [NOTE_ID, GONE] }),
      [`PUT ${base}/sources`]: workspaceFixture({ source_ids: [NOTE_ID] }),
    });
    await screen.findByRole("group", { name: "Sources for this campaign" });
    expect(screen.getByText("1 picked source was removed.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear them" }));
    expect(screen.queryByText("1 picked source was removed.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save sources" }));
    await waitFor(() =>
      expect(bodyOf(rendered.calls, "PUT", `${base}/sources`)).toEqual({ source_ids: [NOTE_ID] }),
    );
  });

  it("offers adding a file or note when the account knows nothing yet", async () => {
    await render({ "/v1/kb/notes": { notes: [] }, "/v1/kb/uploads": [] });
    expect(await screen.findByText("Nothing added to What your agents know yet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add a file or note" })).toBeTruthy();
  });
});
