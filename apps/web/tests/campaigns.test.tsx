import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CampaignsPage from "@/app/c/[slug]/campaigns/page";
import type { Agent } from "@/lib/api/agents";
import type { CampaignProgress, CampaignSummary, LaunchCheck } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import { problem, renderClientPage, type Routes } from "./harness";

/**
 * The campaigns screen either side of the launch panel.
 *
 * `campaignLaunch.test.tsx` covers the panel that authorises the dial. This file covers
 * the two surfaces that lead into it and the one that reports on it — the list, the
 * create form and the progress tiles — because each carries a claim of its own that a
 * wrong render turns into a lie a client acts on:
 *
 * 1. **The create form states, on the record, where a contact list's consent came from.**
 *    It is a compliance artefact (SEC-COMP §3): the answer is audited and is what a
 *    complaint would later be answered with. An answer this screen supplies on the
 *    client's behalf — including by leaving the previous campaign's answer selected — is
 *    an assertion nobody made, and it is the one defect on this page that survives into a
 *    legal record rather than being corrected at the next refetch.
 * 2. **The tiles describe a campaign that may be mid-dial.** A fabricated `0` under
 *    "Connected" while the request is in flight or has failed tells an owner their
 *    campaign reached nobody. Loading is a skeleton, failure is the notice, neither is a
 *    number.
 * 3. **The list decides what a client opens next.** The gate's rule names are not
 *    sentences anyone can act on, and a control rendered from a copy table that does not
 *    own the key is how an unlabelled button appeared on a compliance row once already
 *    (see `LIST_PROVENANCE_COPY`).
 *
 * Mostly negative assertions, because every one of these bugs is something being SHOWN
 * that should not have been.
 */

const CAMPAIGN_ID = "0192f0aa-2222-7000-8000-000000000001";
const REFUSED_ID = "0192f0aa-2222-7000-8000-000000000009";
const AGENT_ID = "0192f0aa-3333-7000-8000-000000000002";

const ME: Me = {
  impersonating: false,
  permissions: ["leads:read", "leads:dispatch"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const AGENT = {
  id: AGENT_ID,
  name: "Outbound follow-up",
  direction: "outbound",
  status: "live",
  language_primary: "te",
} as unknown as Agent;

const CAMPAIGN: CampaignSummary = {
  id: CAMPAIGN_ID,
  name: "Diwali offer",
  status: "draft",
  classification: "promotional",
  contacts: 120,
  connected: 0,
  launched_at: null,
  consent_provenance_blocker: null,
} as unknown as CampaignSummary;

/** The row the gate has already refused: bought list, recorded, unfixable. */
const REFUSED: CampaignSummary = {
  ...CAMPAIGN,
  id: REFUSED_ID,
  name: "Bought list pilot",
  consent_provenance_blocker: "consent_source_refused",
} as unknown as CampaignSummary;

const PROGRESS = {
  status: "draft",
  contacts: {},
  total: 0,
} as unknown as CampaignProgress;

const BLOCKED = {
  ready: false,
  blockers: [{ rule: "no_contacts", reason: "The campaign has no contacts." }],
} as unknown as LaunchCheck;

/** Everything the screen asks for before a campaign is opened. */
function landingRoutes(campaigns: CampaignSummary[], extra: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/campaigns": campaigns,
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    ...extra,
  };
}

/** The consent radios on the CREATE form — `idPrefix="new"` names them. */
function consentRadios(container: HTMLElement): HTMLInputElement[] {
  return Array.from(container.querySelectorAll<HTMLInputElement>('input[name="new-consent-source"]'));
}

function consentDateInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="date"]');
  expect(input, "the create form has no consent date field").not.toBeNull();
  return input!;
}

describe("the create form's consent declaration", () => {
  it("does not carry one campaign's declaration into the next one", async () => {
    /**
     * The defect, in the order a client meets it: answer "where did this list come
     * from" for campaign A, open something else, come back — and campaign B's form is
     * already answered, with `Create campaign` live. Clicking through then records, in
     * an audited table, that a list nobody has described came from the same place on the
     * same date as the last one. That is precisely the "assertion nobody made" the
     * `consentSource` initialiser forbids, and unlike every other stale field on this
     * screen it does not get corrected by the next refetch — it becomes the answer we
     * would give a regulator.
     */
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([CAMPAIGN], {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: PROGRESS,
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
      }),
    );

    await screen.findByText("New campaign");
    const before = consentRadios(container);
    // A premise check: if the form ever stops offering the five answers, the assertions
    // below would pass by rendering nothing at all.
    expect(before).toHaveLength(5);

    fireEvent.click(before[0]);
    fireEvent.change(consentDateInput(container), { target: { value: "2026-08-01" } });
    // The answer really is on the form — otherwise the reset below proves nothing.
    expect(consentRadios(container).some((r) => r.checked)).toBe(true);
    expect(consentDateInput(container).value).toBe("2026-08-01");

    // Away and back, the way the screen allows: open a campaign, then "Start another".
    fireEvent.click(screen.getByRole("button", { name: CAMPAIGN.name }));
    await screen.findByText("Before you launch");
    fireEvent.click(screen.getByRole("button", { name: "Start another campaign" }));
    await screen.findByText("New campaign");

    // The declaration is gone — both halves, because the API takes them as one object
    // and half an answer is still an answer nobody gave.
    expect(consentRadios(container).some((r) => r.checked)).toBe(false);
    expect(consentDateInput(container).value).toBe("");
    // …and the consequence is visible rather than implied: the button is dead again and
    // says why, so the next campaign cannot be created without somebody answering.
    const create = screen.getByRole("button", { name: "Create campaign" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    expect(container.textContent).toContain("Answer both questions about your list above");
  });
});

describe("a campaign whose progress the screen could not read", () => {
  it("reports the failure and invents no counts", async () => {
    /**
     * The tiles used to render unconditionally with `?? 0` (and `?? parsed.length` for
     * the contact count), so a failed `GET /v1/campaigns/{id}` painted "Contacts 0 ·
     * Connected 0 · Not called 0" over a campaign that might be halfway through dialling
     * a list. On a screen a client opens BECAUSE something looks wrong, three confident
     * zeroes are worse than a blank: they answer the question the client came to ask,
     * incorrectly.
     */
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([CAMPAIGN], {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: problem(503, {
          title: "Upstream unavailable",
          detail: "We could not read this campaign just now.",
          retryable: true,
        }),
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: CAMPAIGN.name }));
    // The failure is stated, once, as a problem+json notice — not as a blank panel.
    await screen.findByRole("alert");

    // None of the four tiles exists. Asserted on the labels rather than on the digits,
    // because "0" is a substring of half the ids and timestamps on this page.
    expect(container.textContent).not.toContain("Connected");
    expect(container.textContent).not.toContain("Not called");
    expect(container.textContent).not.toContain("calls answered");
    // The launch panel is keyed on a status we do not have, so it must not appear at
    // all: a campaign we cannot read is not a campaign we can say anything about.
    expect(screen.queryByRole("button", { name: "Launch campaign" })).toBeNull();
    expect(container.textContent).not.toContain("Everything checks out.");
  });

  it("shows a skeleton rather than a zero while the request is still in flight", async () => {
    // The loading state is a real state a client sees on a bad connection, and it is
    // the one where a default `0` is most convincing and most wrong. It is reached by
    // asserting in the same tick as the click, before the stubbed fetch resolves —
    // cheaper and less brittle than a route that never answers, and it exercises the
    // identical branch.
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([CAMPAIGN], {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: PROGRESS,
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
      }),
    );

    // Click and assert SYNCHRONOUSLY, before the query resolves: this is the frame the
    // old code filled with zeroes.
    fireEvent.click(await screen.findByRole("button", { name: CAMPAIGN.name }));
    expect(container.textContent).not.toContain("Connected");
    expect(container.textContent).not.toContain("calls answered");
    expect(container.querySelector(".animate-pulse")).not.toBeNull();

    // …and once it lands, the server's numbers do appear, so the guard above is not
    // simply hiding the tiles for good.
    await screen.findByText("Connected");
  });
});

describe("the campaign list", () => {
  it("keeps the gate's rule names out of the list and labels every control it renders", async () => {
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([CAMPAIGN, REFUSED]),
    );

    await screen.findByRole("button", { name: CAMPAIGN.name });
    const rows = container.querySelectorAll("li");
    expect(rows).toHaveLength(2);

    // `consent_source_refused` is the launch gate's vocabulary. A client reading this
    // list can act on "Can't be launched"; they cannot act on an enum member.
    expect(container.textContent).not.toContain("consent_source_refused");
    expect(container.textContent).not.toContain("consent_provenance_missing");
    expect(container.textContent).toContain("Can't be launched");

    // A row with nothing wrong says nothing: one control, which is the campaign name.
    // The refused row adds exactly one more, the correction link.
    expect(rows[0].querySelectorAll("button")).toHaveLength(1);
    expect(rows[1].querySelectorAll("button")).toHaveLength(2);

    // NO EMPTY CONTROLS. The bug `lookup` closed rendered a badge with no text and a
    // clickable button with no label onto a compliance row, because the copy table
    // resolved a key it does not own to `Object`. An unlabelled button on this row is
    // unreachable by a screen reader and meaningless to everyone else.
    for (const button of container.querySelectorAll("button")) {
      expect(button.textContent?.trim(), "a control was rendered with no label").not.toBe("");
    }
  });

  it("renders no page title of its own", async () => {
    // The app shell prints "Campaigns" from the nav list (layout.tsx). A second one on
    // the page is a duplicate today and a contradiction the day the nav entry is
    // renamed — the screen would keep arguing with the header above it.
    const { container } = await renderClientPage(<CampaignsPage />, landingRoutes([CAMPAIGN]));

    await screen.findByRole("button", { name: CAMPAIGN.name });
    expect(container.querySelector("h1")).toBeNull();
  });
});
