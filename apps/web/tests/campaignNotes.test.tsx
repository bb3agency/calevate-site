import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CampaignNotes, JobNotes, lineNotesTakeEffect, notesTakeEffect } from "@/app/c/[slug]/campaigns/CampaignNotes";

import { FIXTURE_CAMPAIGN_ID, notesFixture } from "./campaignFixtures";
import { problem, renderClientPage } from "./harness";
import { OWNER_ME } from "./fixtures/sharedReads";

/**
 * What it notes (D-1028): the list belongs to the campaign or the line, edited in place;
 * another job's list can be loaded into the editor and is kept only by Save.
 */

const notesPath = `/v1/campaigns/${FIXTURE_CAMPAIGN_ID}/notes`;
const FIELD = {
  key: "visit_day",
  label: "Visit day",
  type: "text" as const,
  reason: "when",
  required: false,
};
const BUDGET = { key: "budget", label: "Budget", type: "text" as const, reason: "to quote", required: false };

function campaignRow(id: string, name: string, status = "draft", archived_at: string | null = null) {
  return { id, name, status, archived_at, classification: "service", contacts: 0, connected: 0, created_at: "2026-11-01T05:00:00Z" };
}

describe("a campaign's What it notes", () => {
  it("says when a saved list reaches its calls, by the campaign's state", () => {
    expect(notesTakeEffect(true, "running")).toBe("From its next call.");
    // Running without its own calling agent yet: its next dial makes one.
    expect(notesTakeEffect(false, "running")).toBe("From its next call.");
    expect(notesTakeEffect(false, "paused")).toBe("From its next call.");
    expect(notesTakeEffect(false, "completed")).toBe("From its next Start.");
    expect(notesTakeEffect(false, "cancelled")).toBe("From its next Start.");
    expect(notesTakeEffect(false, "draft")).toBe("From its first call.");
    expect(notesTakeEffect(false, "scheduled")).toBe("From its first call.");
    expect(lineNotesTakeEffect(true)).toBe("From its next call.");
    expect(lineNotesTakeEffect(false)).toBe("When you put it live.");
  });

  it("says why a save was refused", async () => {
    await renderClientPage(
      <CampaignNotes slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} status="running" canWrite />,
      {
        "/v1/me": OWNER_ME,
        "/v1/campaigns": [],
        [notesPath]: notesFixture({ fields: [FIELD], digest: "own" }),
        [`PUT ${notesPath}`]: problem(422, {
          type: "https://calevate.tech/problems/engine_unavailable",
          title: "Saved, but not on its calls yet",
          status: 422,
          detail: "The calling platform did not answer.",
        }),
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add a detail" }));
    fireEvent.change(screen.getAllByLabelText(/^Name/).at(-1)!, { target: { value: "Budget" } });
    const save = screen.getByRole("button", { name: "Save" });
    fireEvent.click(save);
    expect(await screen.findByText("The calling platform did not answer.")).toBeTruthy();
    // Beside the Save that was pressed, below the list, not above it out of view.
    expect(save.parentElement?.textContent).toContain("The calling platform did not answer.");
  });

  it("links Set alerts as a button to the campaign's own alerts", async () => {
    await renderClientPage(<CampaignNotes slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} canWrite />, {
      "/v1/me": OWNER_ME,
      "/v1/campaigns": [],
      [notesPath]: notesFixture({ fields: [FIELD] }),
    });
    const link = await screen.findByRole("link", { name: "Set alerts" });
    expect(link.getAttribute("href")).toBe(`/c/acme/campaigns/${FIXTURE_CAMPAIGN_ID}#campaign-alerts`);
    // A button, so a thumb can hit it: the shared small button grows to 44 px on touch.
    expect(link.className).toContain("touch:min-h-11");
    await waitFor(() => expect(screen.getByText("From its first call.", { exact: false })).toBeTruthy());
  });

  it("imports another active campaign's list as an unsaved change, saved only by Save", async () => {
    const { calls } = await renderClientPage(
      <CampaignNotes slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} status="draft" canWrite />,
      {
        "/v1/me": OWNER_ME,
        "/v1/campaigns": [
          campaignRow(FIXTURE_CAMPAIGN_ID, "This one"),
          campaignRow("camp-2", "Diwali offer", "running"),
          campaignRow("camp-3", "Old list", "completed", "2026-10-01T05:00:00Z"),
        ],
        [notesPath]: notesFixture({ fields: [FIELD], digest: "own" }),
        "/v1/campaigns/camp-2/notes": notesFixture({ fields: [BUDGET], digest: "other" }),
        [`PUT ${notesPath}`]: notesFixture({ fields: [BUDGET], digest: "saved" }),
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: /Import from another campaign/ }));
    await screen.findByRole("menuitem", { name: /Diwali offer/ });
    const items = screen.getAllByRole("menuitem");
    // Only the account's other campaigns that are not archived.
    expect(items.map((item) => item.textContent)).toEqual([expect.stringContaining("Diwali offer")]);
    fireEvent.click(items[0]);
    expect(await screen.findByText("Loaded from Diwali offer. Save to keep it.")).toBeTruthy();
    expect(screen.getByText("Budget")).toBeTruthy();
    expect(screen.queryByText("Visit day")).toBeNull();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === notesPath)).toBe(true));
    const put = calls.find((c) => c.method === "PUT" && c.path === notesPath)!;
    expect(JSON.parse(put.body ?? "{}")).toMatchObject({ expected_digest: "own", fields: [{ key: "budget" }] });
  });

  it("says so when there is no other active campaign to import from", async () => {
    await renderClientPage(<CampaignNotes slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} canWrite />, {
      "/v1/me": OWNER_ME,
      "/v1/campaigns": [campaignRow(FIXTURE_CAMPAIGN_ID, "This one")],
      [notesPath]: notesFixture({ fields: [FIELD] }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /Import from another campaign/ }));
    const item = await screen.findByRole("menuitem", { name: "No other active campaigns" });
    expect(item.getAttribute("aria-disabled")).toBe("true");
  });
});

describe("an inbound line's What it notes", () => {
  const linePath = "/v1/inbound-lines/line-1/notes";
  const lines = {
    lines: [
      { id: "line-1", name: "Front desk", live: true },
      { id: "line-2", name: "After hours", live: false },
    ],
  };

  it("renders the line's list and saves it whole, with the digest it read", async () => {
    const { calls } = await renderClientPage(
      <JobNotes kind="line" jobId="line-1" canWrite takeEffect={lineNotesTakeEffect} />,
      {
        "/v1/me": OWNER_ME,
        "/v1/inbound-lines": lines,
        [linePath]: notesFixture({ fields: [FIELD], digest: "line-own", applied_now: true }),
        [`PUT ${linePath}`]: notesFixture({ fields: [FIELD, BUDGET], digest: "line-saved", applied_now: true }),
      },
    );
    expect(await screen.findByText("Visit day")).toBeTruthy();
    expect(screen.getByText("From its next call.", { exact: false })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add a detail" }));
    fireEvent.change(screen.getAllByLabelText(/^Name/).at(-1)!, { target: { value: "Budget" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === linePath)).toBe(true));
    const put = calls.find((c) => c.method === "PUT" && c.path === linePath)!;
    const body = JSON.parse(put.body ?? "{}");
    expect(body.expected_digest).toBe("line-own");
    expect(body.fields.map((f: { label: string }) => f.label)).toEqual(["Visit day", "Budget"]);
  });

  it("imports another line's list, never its own", async () => {
    await renderClientPage(
      <JobNotes kind="line" jobId="line-1" canWrite takeEffect={lineNotesTakeEffect} />,
      {
        "/v1/me": OWNER_ME,
        "/v1/inbound-lines": lines,
        [linePath]: notesFixture({ fields: [FIELD], digest: "line-own" }),
        "/v1/inbound-lines/line-2/notes": notesFixture({ fields: [BUDGET], digest: "line-2" }),
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: /Import from another line/ }));
    await screen.findByRole("menuitem", { name: /After hours/ });
    const items = screen.getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([expect.stringContaining("After hours")]);
    fireEvent.click(items[0]);
    expect(await screen.findByText("Loaded from After hours. Save to keep it.")).toBeTruthy();
  });
});
