import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import FirstCampaignReviewPage from "@/app/admin/tenants/[tenantId]/first-campaign-review/page";
import type { TenantSummary } from "@/lib/api/admin";
import {
  FIRST_CAMPAIGN_REVIEW_PATH,
  type FirstCampaignHold,
} from "@/lib/api/firstCampaign";
import type { Routes } from "./harness";

import { problem } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The first-campaign review — a COMPLIANCE GATE with a form on it, ranked second only to
 * the invoice, and for the opposite reason: the invoice leaves the building, this one
 * decides whether a new account may dial strangers at all.
 *
 * What the tests pin, worst first:
 *
 * 1. **A decision must not be recordable over a state nobody could read.** The write
 *    replaces the current decision outright, so deciding blind can silently reverse a
 *    colleague's refusal or re-release an account withdrawn an hour ago after complaints.
 *    The form is WITHHELD, not merely unpopulated.
 * 2. **Held must stay held when this build cannot name the rule.** `firstCampaignState`
 *    fails CLOSED on purpose, and this screen must not be the place that reads an
 *    unfamiliar rule as "cleared" — the operator would release an account the gate is
 *    still refusing, and the client's own screen would keep saying so.
 * 3. **The two realms must not contradict each other.** The client's `/c/[slug]/
 *    campaign-review` renders the same five states from the same predicate; a `never_applied`
 *    account (managed, exempt) is NOT a released one, and an operator told otherwise
 *    records a decision believing it changed something.
 * 4. **A control the session may not use is disabled with its reason.** `admin:tenants`
 *    is what the route requires; a 403 after a reviewer has written a client-facing
 *    paragraph is the worst moment to deliver it.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000f1";
const SLUG = "sri-traders";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const CAMPAIGNS_PATH = "/v1/campaigns";
const ME_PATH = ADMIN_ME_PATH;

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: SLUG,
    status: "active",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: ["first_campaign_review_pending"],
    capped: false,
  } as TenantSummary;
}

/** The admin realm's own identity document (`GET /v1/admin/me`) — no tenant in it. */
function me(permissions: string[]): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-7777-7000-8000-0000000000f2",
    role: "operator",
    permissions,
  } as AdminMe;
}

const REVIEWER = me(["org:read", "leads:read", "admin:tenants"]);

function hold(over: Partial<FirstCampaignHold> = {}): FirstCampaignHold {
  return {
    held: true,
    rule: "first_campaign_review_pending",
    status: null,
    reason: "Your first campaign is waiting for a compliance review.",
    decision_note: null,
    decided_at: null,
    reviewed_campaign_id: null,
    ...over,
  } as FirstCampaignHold;
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(
    <FirstCampaignReviewPage params={routeParams({ tenantId: TENANT })} />,
    {
      [TENANT_PATH]: tenant(),
      [ME_PATH]: REVIEWER,
      [CAMPAIGNS_PATH]: [],
      [FIRST_CAMPAIGN_REVIEW_PATH]: hold(),
      ...routes,
    },
  );
}

describe("the first-campaign review", () => {
  it("withholds the form entirely when the current state could not be read", async () => {
    const { container } = await render({
      [FIRST_CAMPAIGN_REVIEW_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this account's review state.",
        retryable: true,
      }),
    });

    await screen.findByText("Cannot decide while the current state is unreadable");

    // Not a disabled button and not an empty form: no decision control exists at all,
    // because a blind write here can reverse a colleague's refusal invisibly.
    expect(screen.queryByRole("button", { name: /Record decision/ })).toBeNull();
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(container.textContent).not.toContain("Released");
  });

  it("keeps an account HELD on a rule this build cannot name", async () => {
    const { container } = await render({
      [FIRST_CAMPAIGN_REVIEW_PATH]: hold({
        rule: "a_gate_added_after_this_build",
        reason: "Held by a newer compliance rule.",
      }),
    });

    await screen.findByText("Held on a rule this console does not recognise.");

    // Fails CLOSED, and prints the server's own sentence rather than inventing a next
    // step this build cannot know.
    expect(container.textContent).toContain("Held by a newer compliance rule.");
    expect(container.textContent).not.toContain("Released — cleared for campaign calling.");
  });

  it("does not read an exempt account as a released one", async () => {
    const { container } = await render({
      [FIRST_CAMPAIGN_REVIEW_PATH]: hold({ held: false, status: null, reason: null }),
    });

    await screen.findByText("This rule does not apply to this account.");

    // The client's own screen says the same thing from the same predicate. "Released"
    // here would tell an operator a decision had been made about an account nobody has
    // ever reviewed.
    expect(container.textContent).not.toContain("Released — cleared for campaign calling.");
    expect(container.textContent).toContain("changes nothing about their calling");
  });

  it("shows a refusal as the words the client is reading", async () => {
    const { container } = await render({
      [FIRST_CAMPAIGN_REVIEW_PATH]: hold({
        rule: "first_campaign_review_rejected",
        status: "rejected",
        decision_note: "The contact list is a purchased list declared as opt-in.",
        decided_at: "2026-08-11T06:00:00Z",
      }),
    });

    await screen.findByText("Held — a reviewer refused this account.");

    expect(container.textContent).toContain("this is what the client is reading now");
    expect(container.textContent).toContain(
      "The contact list is a purchased list declared as opt-in.",
    );
  });

  it("leaves no operable control on the form when the session lacks admin:tenants", async () => {
    await render({ [ME_PATH]: me(["org:read", "leads:read"]) });

    await screen.findByText(/does not have the admin:tenants permission/);

    // EVERY control, not only the submit: a reviewer must not be able to compose a
    // client-facing paragraph that cannot be sent and then lose it to a 403. The submit
    // is disabled for a second, independent reason (nothing is chosen yet), which is why
    // the radios and the note box are asserted in their own right — they are the gate
    // that is load-bearing in this state.
    for (const radio of screen.getAllByRole("radio")) {
      expect((radio as HTMLInputElement).disabled).toBe(true);
    }
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByLabelText(/Campaign read/) as HTMLSelectElement).disabled).toBe(true);
    expect(
      (screen.getByRole("button", { name: /Record decision/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("becomes recordable once a permitted reviewer has said what they read", async () => {
    await render();

    // The negative test above is only worth anything if this form can ever be submitted:
    // an always-dead button would satisfy it and release nobody.
    const approve = await screen.findByRole("radio", { name: /Release/i });
    fireEvent.click(approve);
    fireEvent.change(screen.getByRole("textbox"), {
      target: {
        value:
          "Read campaign Diwali offers: 320 contacts from their own enquiry form, disclosure line present.",
      },
    });

    const record = screen.getByRole("button", { name: /Record decision/ });
    expect((record as HTMLButtonElement).disabled).toBe(false);
    // And the preview says what the write will contain, before it is made — including
    // the two fields the operator cannot supply (the deciding admin and the timestamp),
    // which is why this form has no "decided on" date picker.
    expect(screen.getByText(/Taken from your session, not from this form/)).toBeDefined();
  });

  it("refuses an empty decision before the click rather than after it", async () => {
    await render();

    const record = await screen.findByRole("button", { name: /Record decision/ });

    // Nothing chosen yet: the button is dead and says why, rather than posting a body the
    // route answers with a 422 and the CHECK constraint underneath it with a 500.
    expect((record as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Choose what you are recording.")).toBeDefined();
  });

  it("does not claim an account has no campaigns when the list failed to load", async () => {
    const { container } = await render({
      [CAMPAIGNS_PATH]: problem(500, {
        title: "Upstream unavailable",
        detail: "Campaigns unavailable.",
        retryable: true,
      }),
    });

    await screen.findByText(/Their campaigns could not be listed/);

    // "This account has no campaigns yet" is a premise a reviewer would release an
    // account on. It must come from a 200, never from a failure.
    expect(container.textContent).not.toContain("This account has no campaigns yet");
  });

  it("keeps the client's read-only view one click away, and says it is read-only", async () => {
    await render();

    const link = await screen.findByRole("link", { name: /What the client sees \(read-only\)/ });
    // D-22: the marker selects the impersonating credential; the view grants nothing and
    // every page view of it is audited.
    expect(link.getAttribute("href")).toBe(`/c/${SLUG}/campaign-review?view=admin`);
  });
});
