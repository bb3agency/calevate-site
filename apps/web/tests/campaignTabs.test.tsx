import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Me } from "@/lib/api/client";
import { showFinding } from "@/lib/api/scriptChecks";

import {
  FIXTURE_AGENT_ID as AGENT_ID,
  FIXTURE_CAMPAIGN_ID as CAMPAIGN_ID,
  campaignPage,
  detailRoutes,
  progressFixture,
} from "./campaignFixtures";
import { renderClientPage, type Routes } from "./harness";

/**
 * The campaign page in tabs (redesign plan §3): which tabs a draft and a launched campaign
 * show, the old `?tab=` values that must keep opening the right place, the one count of
 * checks left, and every jump to a section switching to its tab first (defect C13-a).
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

const LAUNCHED = { status: "running" as const, launched_at: "2026-10-14T04:30:00Z", total: 2, contacts: { pending: 2 } };

/** Two checks the owner answers (where the list came from counts as one) and one we chase. */
const BLOCKED = {
  ready: false,
  blockers: [
    { rule: "outbound_pledge_missing", reason: "Accept the promise." },
    { rule: "consent_provenance_missing", reason: "Say where the list came from." },
    { rule: "no_contacts", reason: "Add people." },
  ],
};

function routes(progress: unknown, extra: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    ...detailRoutes(),
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    [`/v1/campaigns/${CAMPAIGN_ID}`]: progress,
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: { ready: true, blockers: [] },
    ...extra,
  };
}

const at = (query: string) => window.history.replaceState(null, "", `/c/acme/campaigns/${CAMPAIGN_ID}${query}`);
const tabNames = () => screen.getAllByRole("tab").map((tab) => tab.textContent);
const selected = () => screen.getAllByRole("tab").find((tab) => tab.getAttribute("aria-selected") === "true")?.textContent;

describe("the campaign page's tabs", () => {
  it("gives a draft Script, People, Settings and Checks, opening on Script", async () => {
    await renderClientPage(campaignPage(), routes(progressFixture()));
    await screen.findByRole("tab", { name: "Script" });
    expect(tabNames()).toEqual(["Script", "People", "Settings", "Checks"]);
    expect(selected()).toBe("Script");
  });

  it("gives a launched campaign Progress first and Improve last, with no Checks", async () => {
    await renderClientPage(campaignPage(), routes(progressFixture(LAUNCHED)));
    await screen.findByRole("tab", { name: "Progress" });
    expect(tabNames()).toEqual(["Progress", "Calls", "Script", "People", "Settings", "Improve"]);
    expect(selected()).toBe("Progress");
  });

  it("still opens an old ?tab=setup link on the script", async () => {
    at("?tab=setup");
    await renderClientPage(campaignPage(), routes(progressFixture(LAUNCHED)));
    await waitFor(() => expect(selected()).toBe("Script"));
  });

  it("opens an old ?tab=questions link on Improve, with the questions first", async () => {
    at("?tab=questions");
    await renderClientPage(campaignPage(), routes(progressFixture(LAUNCHED)));
    await waitFor(() => expect(selected()).toBe("Improve"));
    expect(await screen.findByRole("heading", { name: "Questions to answer" })).toBeTruthy();
  });

  it("keeps ?tab=improve, the account Improve page's link, working", async () => {
    at("?tab=improve");
    await renderClientPage(campaignPage(), routes(progressFixture(LAUNCHED)));
    await waitFor(() => expect(selected()).toBe("Improve"));
  });

  it("writes the open tab into the address, so a reload opens the same one", async () => {
    await renderClientPage(campaignPage(), routes(progressFixture()));
    fireEvent.click(await screen.findByRole("tab", { name: "People" }));
    expect(new URLSearchParams(window.location.search).get("tab")).toBe("people");
  });

  it("opens the tab an alert link's section is on", async () => {
    at("#campaign-alerts");
    await renderClientPage(campaignPage(), routes(progressFixture()));
    await waitFor(() => expect(selected()).toBe("Settings"));
  });
});

describe("checks left, said once", () => {
  it("counts the same on the Checks tab, the card and beside Start", async () => {
    await renderClientPage(
      campaignPage(),
      routes(progressFixture(), { [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED }),
    );
    const tab = await screen.findByRole("tab", { name: "Checks (2 left)" });
    const hint = await screen.findByRole("button", { name: "2 checks left. Open Checks" });
    expect(screen.getByText("2 checks to answer")).toBeTruthy();
    expect(tab.getAttribute("aria-selected")).toBe("false");
    fireEvent.click(hint);
    await waitFor(() => expect(selected()).toBe("Checks (2 left)"));
  });

  it("names what else is left once the checks are done, and goes to it", async () => {
    await renderClientPage(
      campaignPage(),
      routes(progressFixture(), {
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: {
          ready: false,
          blockers: [{ rule: "no_contacts", reason: "Add people." }],
        },
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add the people to call." }));
    await waitFor(() => expect(selected()).toBe("People"));
  });
});

describe("going to a section on another tab", () => {
  it("switches to Script when Show me asks for a script line from another tab", async () => {
    await renderClientPage(campaignPage(), routes(progressFixture()));
    fireEvent.click(await screen.findByRole("tab", { name: "Checks" }));
    expect(selected()).toBe("Checks");
    act(() => showFinding({ stage_id: null, path: "opening_line" }));
    await waitFor(() => expect(selected()).toBe("Script"));
  });

  it("takes Start's list of what is left to the tab of the first thing to fix", async () => {
    await renderClientPage(
      campaignPage(),
      routes(progressFixture({ total: 2 }), { [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED }),
    );
    await screen.findByRole("tab", { name: "Checks (2 left)" });
    fireEvent.click(screen.getAllByRole("button", { name: "Start campaign" })[0]!);
    await screen.findByRole("dialog");
    await waitFor(() => expect(selected()).toBe("Checks (2 left)"));
  });
});

describe("the way back", () => {
  it("leads back to the campaign's agent", async () => {
    await renderClientPage(campaignPage(), routes(progressFixture()));
    const back = await screen.findByRole("link", { name: /Agents › Outbound follow-up/ });
    expect(back.getAttribute("href")).toBe(`/c/acme/agents/${AGENT_ID}`);
  });

  it("leads back to the list when the list opened it", async () => {
    at("?from=list");
    await renderClientPage(campaignPage(), routes(progressFixture()));
    const back = await screen.findByRole("link", { name: /All campaigns/ });
    expect(back.getAttribute("href")).toBe("/c/acme/campaigns");
  });
});
