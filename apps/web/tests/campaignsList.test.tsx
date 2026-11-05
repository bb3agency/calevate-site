import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CampaignSummary } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import { FIXTURE_CAMPAIGN_ID as CAMPAIGN_ID, LIST_PATH, listPage, pageFixture } from "./campaignFixtures";
import { renderClientPage } from "./harness";

/**
 * `/c/{slug}/campaigns`. Each assertion guards something the list must not SHOW: a rule
 * name, a Resume the server refuses, a bar over a campaign that has not started, a
 * first-run panel over an account that has campaigns, a button a reader may not press.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["leads:read", "leads:dispatch", "billing:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const READER: Me = { ...ME, permissions: ["leads:read"], role: "viewer" };

const CAMPAIGN: CampaignSummary = {
  id: CAMPAIGN_ID,
  name: "Diwali offer",
  status: "draft",
  classification: "promotional",
  contacts: 120,
  connected: 0,
  launched_at: null,
  created_at: "2026-08-10T06:00:00Z",
  consent_provenance_blocker: null,
  pause_reason: null,
};

const RUNNING: CampaignSummary = {
  ...CAMPAIGN,
  id: "0192f0aa-2222-7000-8000-000000000010",
  name: "Renewal reminders",
  status: "running",
  contacts: 200,
  connected: 50,
  launched_at: "2026-08-11T05:00:00Z",
};

describe("the campaign list", () => {
  it("links every campaign to its own address and keeps rule names out of the DOM", async () => {
    const refused: CampaignSummary = {
      ...CAMPAIGN,
      id: "0192f0aa-2222-7000-8000-000000000009",
      name: "Bought list pilot",
      consent_provenance_blocker: "consent_source_refused",
    };
    const { container } = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([CAMPAIGN, refused]),
    });
    const link = await screen.findByRole("link", { name: CAMPAIGN.name });
    expect(link.getAttribute("href")).toBe(`/c/acme/campaigns/${CAMPAIGN_ID}`);
    const list = screen.getByRole("list", { name: "Your campaigns" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(container.textContent).toContain("Can't be launched");
    expect(container.textContent).not.toContain("consent_source_refused");
    expect(container.querySelector("h1")).toBeNull();
    expect(screen.getByRole("link", { name: "New campaign" }).getAttribute("href")).toBe(
      "/c/acme/campaigns/new",
    );
  });

  it("names an automatic pause and offers no Resume the server would refuse", async () => {
    const paused: CampaignSummary = {
      ...RUNNING,
      status: "paused",
      pause_reason: "out_of_credit",
    };
    const { container } = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([paused]),
    });
    await screen.findByRole("link", { name: RUNNING.name });
    expect(container.textContent).toContain("Paused: out of credit");
    expect(screen.queryByRole("button", { name: /Resume/ })).toBeNull();
    expect(screen.getByRole("link", { name: `Add credit: ${RUNNING.name}` })).toBeTruthy();
  });

  it("measures a launched campaign's reach and draws no bar for one that has not started", async () => {
    const { container } = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([RUNNING, CAMPAIGN]),
    });
    const bar = await screen.findByRole("progressbar", { name: `${RUNNING.name}: reached` });
    expect(bar.getAttribute("aria-valuenow")).toBe("50");
    expect(bar.getAttribute("aria-valuemax")).toBe("200");
    expect(container.textContent).toContain("25%");
    expect(screen.getAllByRole("progressbar")).toHaveLength(1);
    const draftRow = container.querySelector('li[data-status="draft"]');
    expect(draftRow?.textContent).toContain("120 people to call");
    // Only the running row carries the live mark.
    expect(container.querySelectorAll("[data-live-sheen]")).toHaveLength(1);
    expect(container.querySelector('li[data-status="running"] [data-live-sheen]')).not.toBeNull();
    expect(screen.getByRole("button", { name: `Pause ${RUNNING.name}` })).toBeTruthy();
  });

  it("offers only the statuses the account has, with counts, and asks the server for the one chosen", async () => {
    const rendered = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([CAMPAIGN, RUNNING]),
      "/v1/campaigns/page?limit=25&offset=0&status=draft": pageFixture([CAMPAIGN]),
    });
    const segments = await screen.findByRole("radiogroup", { name: "Show campaigns by status" });
    await vi.waitFor(() => expect(within(segments).getAllByRole("radio")).toHaveLength(3));
    const names = within(segments)
      .getAllByRole("radio")
      .map((radio) => radio.textContent);
    expect(names).toEqual(["All2", "Running1", "Drafts1"]);
    fireEvent.click(within(segments).getByRole("radio", { name: /Drafts/ }));
    await vi.waitFor(() =>
      expect(rendered.calls.some((c) => c.path.endsWith("status=draft"))).toBe(true),
    );
  });

  it("says nothing matches, not that there are none, when a search hides every campaign", async () => {
    const rendered = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([CAMPAIGN]),
      "/v1/campaigns/page?limit=25&offset=0&q=zzz": {
        items: [],
        total: 0,
        status_counts: pageFixture([CAMPAIGN]).status_counts,
      },
    });
    const search = await screen.findByRole("searchbox", { name: "Search campaigns by name" });
    fireEvent.change(search, { target: { value: "zzz" } });
    fireEvent.keyDown(search, { key: "Enter" });
    await screen.findByText("No campaign matches.");
    expect(rendered.container.textContent).not.toContain("No campaigns yet");
  });
});

describe("archived campaigns (F-10)", () => {
  const FINISHED: CampaignSummary = {
    ...RUNNING,
    id: "0192f0aa-2222-7000-8000-000000000011",
    name: "Old reminders",
    status: "completed",
  };
  const SHELVED: CampaignSummary = { ...FINISHED, archived_at: "2026-11-05T10:00:00Z", status: "paused" };

  it("offers an Archived list when there is one, and Restore on its rows", async () => {
    const rendered = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: { ...pageFixture([RUNNING]), archived_total: 1 },
      "/v1/campaigns/page?limit=25&offset=0&archived=true": { ...pageFixture([SHELVED]), archived_total: 1 },
      [`POST /v1/campaigns/${SHELVED.id}/restore`]: { changed: true, status: "paused" },
    });
    const segments = await screen.findByRole("radiogroup", { name: "Show campaigns by status" });
    fireEvent.click(await within(segments).findByRole("radio", { name: /Archived/ }));
    const restore = await screen.findByRole("button", { name: "Restore Old reminders" });
    fireEvent.click(restore);
    await vi.waitFor(() =>
      expect(rendered.calls.some((c) => c.method === "POST" && c.path.endsWith("/restore"))).toBe(true),
    );
  });

  it("archives a finished campaign from its row only after a one-line confirm", async () => {
    const rendered = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([FINISHED]),
      [`POST /v1/campaigns/${FINISHED.id}/archive`]: { changed: true, status: "completed" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Archive Old reminders" }));
    expect(rendered.calls.some((c) => c.path.endsWith("/archive"))).toBe(false);
    expect(await screen.findByText("Its calls and results are kept. You can restore it.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await vi.waitFor(() =>
      expect(rendered.calls.some((c) => c.method === "POST" && c.path.endsWith("/archive"))).toBe(true),
    );
  });
});

describe("the first visit", () => {
  it("shows the three steps and one way to start, and no toolbar over nothing", async () => {
    const { container } = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([]),
    });
    await screen.findByRole("heading", { name: "No campaigns yet" });
    expect(screen.getByRole("link", { name: "Start a campaign" }).getAttribute("href")).toBe(
      "/c/acme/campaigns/new",
    );
    expect(screen.queryByRole("link", { name: "New campaign" })).toBeNull();
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(container.querySelectorAll("ol li")).toHaveLength(3);
    expect(container.textContent).not.toContain("No campaign matches");
  });

  it("offers no start to a reader who may not run campaigns", async () => {
    await renderClientPage(listPage(), {
      "/v1/me": READER,
      [LIST_PATH]: pageFixture([]),
    });
    await screen.findByRole("heading", { name: "No campaigns yet" });
    expect(screen.queryByRole("link", { name: "Start a campaign" })).toBeNull();
  });
});
