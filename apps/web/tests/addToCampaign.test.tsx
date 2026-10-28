import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AddToCampaign } from "@/app/c/[slug]/leads/AddToCampaign";
import { EMPTY_SELECTION, type BulkSelection } from "@/app/c/[slug]/leads/BulkActionBar";
import type { Session } from "@/lib/api/client";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage } from "./harness";

/**
 * The Leads screen's "Add to a campaign" (D-893 lane L3): the table's selection or lens goes
 * to `POST …/contacts/from-leads` with the confirmed count, and the answer is the server's.
 */

const SESSION: Session = { orgSlug: "acme" };
const DRAFT = "0192f0aa-5555-7000-8000-000000000001";
const RUNNING = "0192f0aa-5555-7000-8000-000000000002";

function campaign(id: string, name: string, status: string) {
  return {
    id,
    name,
    status,
    classification: "service",
    contacts: 0,
    connected: 0,
    created_at: "2026-10-27T05:00:00Z",
  };
}

const CAMPAIGNS = [campaign(DRAFT, "Diwali offers", "draft"), campaign(RUNNING, "Recall", "running")];

function view(selection: BulkSelection, routes: Record<string, unknown>, onAdded = () => {}) {
  return renderClientPage(
    <AddToCampaign
      session={SESSION}
      slug="acme"
      href={(path) => path}
      selection={selection}
      lens={{ status: "hot" }}
      filteredTotal={3}
      canAdd
      addReason={null}
      renderPlan={(planId) => <p>Plan {planId}</p>}
      onAdded={onAdded}
    />,
    { "/v1/campaigns": CAMPAIGNS, ...routes },
  );
}

describe("adding the selected leads to a campaign", () => {
  it("offers only campaigns that have not started, and is accessible", async () => {
    const { container } = await view({ ids: ["a"], wholeQuery: false }, {});
    const select = await screen.findByLabelText("Add to a campaign");
    expect(Array.from((select as HTMLSelectElement).options).map((o) => o.text)).toEqual([
      "Diwali offers",
    ]);
    expect(screen.getByRole("button", { name: "Add 1 lead" })).toBeTruthy();
    await expectNoA11yViolations(container, "add-to-campaign");
  });

  it("sends the table's lens with the count the person confirmed, and says what was added", async () => {
    let added = 0;
    const { calls } = await view(
      { ids: [], wholeQuery: true },
      {
        [`POST /v1/campaigns/${DRAFT}/contacts/from-leads`]: {
          added: 2,
          malformed: 0,
          duplicate: 1,
          foreign: 0,
          plan_id: null,
        },
      },
      () => {
        added += 1;
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add 3 leads" }));
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Add 3" }));
    });
    await waitFor(() => expect(added).toBe(1));
    const sent = calls.find((c) => c.method === "POST");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ lens: { status: "hot" }, expected_count: 3 });
  });

  it("shows the plan card when the set is larger than one add", async () => {
    await view(
      { ids: ["a"], wholeQuery: false },
      {
        [`POST /v1/campaigns/${DRAFT}/contacts/from-leads`]: {
          added: 0,
          malformed: 0,
          duplicate: 0,
          foreign: 0,
          plan_id: "plan-1",
        },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add 1 lead" }));
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Add 1" }));
    });
    expect(await screen.findByText("Plan plan-1")).toBeTruthy();
  });

  it("names a refused add inside the confirmation, keeping the person's choice", async () => {
    await view(
      { ids: ["a"], wholeQuery: false },
      {
        [`POST /v1/campaigns/${DRAFT}/contacts/from-leads`]: problem(409, {
          title: "The set moved",
          detail: "This now matches 4 leads rather than the 3 you confirmed.",
        }),
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add 1 lead" }));
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Add 1" }));
    });
    expect(await screen.findByText(/rather than the 3 you confirmed/)).toBeTruthy();
  });

  it("points to creating a campaign when none is waiting to start", async () => {
    await view({ ids: ["a"], wholeQuery: false }, { "/v1/campaigns": [CAMPAIGNS[1]] });
    expect(await screen.findByText("No campaign waiting to start.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Create a campaign" }).getAttribute("href")).toBe(
      "/c/acme/campaigns/new",
    );
  });

  it("draws nothing with nothing selected", async () => {
    const { container } = await view(EMPTY_SELECTION, {});
    expect(container.textContent).toBe("");
  });
});
