import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CampaignsPage from "@/app/c/[slug]/campaigns/page";
import type { Agent } from "@/lib/api/agents";
import type { CampaignProgress, CampaignSummary, LaunchCheck } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import { expectTextCount, renderClientPage } from "./harness";

/**
 * The launch control's enabled state, read off the DOM property.
 *
 * Not `toBeDisabled()`: `@testing-library/jest-dom` is deliberately not a dependency
 * (see vitest.config.mts), and `disabled` is the property the browser actually acts on.
 */
function launchButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "Launch campaign" }) as HTMLButtonElement;
}

function launchButtonDisabled(): boolean {
  return launchButton().disabled;
}

/**
 * The launch panel — the screen where a client decides whether they may dial.
 *
 * Ranked first of everything left untested because of what a wrong answer here costs.
 * Every other screen in this app misinforms; this one authorises. `/launch-check`
 * returns NAMED blockers so the panel can list them as a to-do, and the panel's job is
 * to convert that list into a decision a business owner acts on. Four ways it can be
 * wrong, in falling order of consequence:
 *
 * 1. A blocker the server sent is not shown at all. The client believes their side is
 *    done, presses nothing, and calls support — or worse, reads the empty list as
 *    permission. The server still refuses (hard rule 5, `POST /launch` re-runs the
 *    identical gate), so this is not an illegal-call bug; it is the bug that makes the
 *    compliance gate look like a malfunction, which is how bypasses get requested.
 * 2. A blocker is shown as the client's to-do when it is OURS, or vice versa. A client
 *    hunting for a DLT setting they do not have is the failure `owner` exists to stop.
 * 3. Our platform-wide outage is rendered as an item on this client's list — counted,
 *    bulleted and badged beside "upload your contacts". `PLATFORM_BLOCKER` is pulled
 *    out BEFORE render precisely so that cannot happen, and that is a structural claim
 *    a test can hold.
 * 4. The enum name leaks into the DOM. `consent_source_refused` is the gate's
 *    vocabulary, not a sentence anyone can act on.
 *
 * Everything is asserted through the rendered panel rather than against the derivation,
 * because the derivation is four one-line `find`/`filter`s — the risk is not that they
 * compute wrongly, it is that the JSX below them renders a branch nobody intended.
 */

const CAMPAIGN_ID = "0192f0aa-2222-7000-8000-000000000001";
const AGENT_ID = "0192f0aa-3333-7000-8000-000000000002";

const ME: Me = {
  impersonating: false,
  permissions: ["leads:read", "leads:dispatch"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const AGENT: Agent = {
  id: AGENT_ID,
  name: "Outbound follow-up",
  direction: "outbound",
  status: "live",
  language_primary: "te",
  // Hard rule 5: an agent ALWAYS carries a non-null disclosure line, and an outbound
  // campaign agent is the case the rule exists for. This fixture omitted it entirely —
  // `as unknown as Agent` is why nobody noticed.
  disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  engine: "bolna",
  published: true,
  extraction_fields: [],
};

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
};

/** Draft, because the "Before you launch" card only exists for a draft. */
const PROGRESS: CampaignProgress = {
  status: "draft",
  contacts: {},
  total: 0,
  concurrency: 3,
  launched_at: null,
};

function check(...blockers: { rule: string; reason: string }[]): LaunchCheck {
  return { ready: blockers.length === 0, blockers };
}

/**
 * Open the panel the way a client does: land on the list, click the campaign.
 *
 * `campaignId` is component state set by that click, and every query the panel reads is
 * `enabled` on it. Seeding it any other way would be testing a screen state the app
 * cannot reach.
 */
async function openLaunchPanel(launchCheck: LaunchCheck, me: Me = ME) {
  const rendered = await renderClientPage(<CampaignsPage />, {
    "/v1/me": me,
    "/v1/campaigns": [CAMPAIGN],
    "/v1/agents": [AGENT],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    [`/v1/campaigns/${CAMPAIGN_ID}`]: PROGRESS,
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: launchCheck,
  });
  fireEvent.click(await screen.findByRole("button", { name: CAMPAIGN.name }));
  await screen.findByText("Before you launch");
  return rendered;
}

describe("the launch panel with blockers outstanding", () => {
  it("shows every blocker the server sent, and no launch button that works", async () => {
    const { container } = await openLaunchPanel(
      check(
        { rule: "no_contacts", reason: "The campaign has no contacts." },
        { rule: "agent_not_live", reason: "The agent is not published." },
        { rule: "dlt_template_missing", reason: "No DLT template attached." },
      ),
    );

    // The count is the assertion, not the presence: a panel that renders two of three
    // blockers is the failure mode — the client fixes what they were shown, presses
    // launch, and meets a refusal for the one that was dropped.
    expect(container.querySelectorAll("li")).toHaveLength(3);
    expect(container.textContent).toContain("Upload the contact list.");
    expect(container.textContent).toContain("Your agent has to be published");
    expect(container.textContent).toContain("Attach the DLT voice template");

    // Disabled WITH the reasons, never absent. There is exactly one launch control and
    // it cannot be pressed.
    expect(launchButtonDisabled()).toBe(true);
    expect(container.textContent).not.toContain("Everything checks out.");
  });

  it("names the desk a blocker lands on, so a client does not hunt for a setting they do not have", async () => {
    const { container } = await openLaunchPanel(
      check(
        { rule: "pe_registration_not_active", reason: "PE registration inactive." },
        { rule: "no_contacts", reason: "The campaign has no contacts." },
      ),
    );

    // The DLT registrations are OUR paperwork. Without the badge, "your DLT
    // registration isn't active" reads as a to-do on a screen full of to-dos.
    expect(container.textContent).toContain("We handle this");
    // …and the one the client genuinely cannot be helped with must not borrow it.
    expectTextCount(container, "We handle this", 1);
    // `no_contacts` carries no owner at all: a bare instruction needs no desk.
    expect(container.textContent).not.toContain("You can fix this");
  });

  it("renders the server's own reason for a rule this build has never heard of", async () => {
    // The fail-VISIBLE direction, at the site where failing closed would be silence.
    // A gate added after this build ships must still reach the client as a blocker —
    // "you cannot launch, and we will not say why" is the one outcome this card exists
    // to prevent, and an unnamed rule is exactly how it would happen.
    const { container } = await openLaunchPanel(
      check({
        rule: "a_gate_this_build_predates",
        reason: "Calling hours for this campaign fall outside the platform window.",
      }),
    );

    expect(container.querySelectorAll("li")).toHaveLength(1);
    expect(container.textContent).toContain("Calling hours for this campaign fall outside");
    // The rule NAME is the gate's vocabulary and must not be what the client reads.
    expect(container.textContent).not.toContain("a_gate_this_build_predates");
    expect(launchButtonDisabled()).toBe(true);
  });

  it("keeps the enum names out of the DOM for the rules it does know", async () => {
    const { container } = await openLaunchPanel(
      check({
        rule: "consent_source_refused",
        reason: "The list is recorded as purchased.",
      }),
    );

    expect(container.textContent).toContain("Calevate doesn't dial purchased lists");
    expect(container.textContent).not.toContain("consent_source_refused");
    // This one the client CAN act on — the correction form is the point of the badge.
    expect(container.textContent).toContain("You can fix this");
  });
});

/**
 * The platform outage, which is the structural claim on this screen.
 *
 * `tm_registration_missing` is CALEVATE's own telemarketer registration failing. Every
 * tenant is refused at the same instant for a reason no business can act on. It is
 * deliberately absent from `BLOCKER_COPY` so that the `<li>`-per-entry list CANNOT
 * render it as a bullet, and pulled out of the array before anything is counted. Both
 * halves are asserted, because either one alone would silently stop protecting the
 * other.
 */
describe("the launch panel during a platform-wide outage", () => {
  const OUTAGE = {
    rule: "tm_registration_missing",
    reason: "Calevate's TM registration is not active with the registrar.",
  };

  it("never lists our outage among the client's to-dos", async () => {
    const { container } = await openLaunchPanel(
      check(OUTAGE, { rule: "no_contacts", reason: "The campaign has no contacts." }),
    );

    // One bullet, and it is the client's. The outage is above the list in its own
    // shape — a `role="status"` notice — not an item in it.
    expect(container.querySelectorAll("li")).toHaveLength(1);
    expect(container.querySelector("li")?.textContent).toContain("Upload the contact list.");

    const notice = screen.getByRole("status");
    expect(notice.textContent).toContain("Outbound calling is paused across Calevate");
    // No owner badge on the outage: "We handle this" describes a queue with a desk
    // attached, and this is the product not working.
    expect(notice.textContent).not.toContain("We handle this");
    expect(container.textContent).not.toContain("tm_registration_missing");
  });

  it("tells a client whose own side is finished that it is finished", async () => {
    // The empty-list case, which is the one an outage produces most often. An empty
    // list under "Before you launch" reads as "we will not say why" — the exact thing
    // the panel exists to avoid — so the true sentence gets said instead.
    const { container } = await openLaunchPanel(check(OUTAGE));

    expect(container.querySelectorAll("li")).toHaveLength(0);
    expect(container.textContent).toContain("Everything on your side is ready");
    expect(screen.getByRole("status").textContent).toContain(
      "Outbound calling is paused across Calevate",
    );
    // Still not launchable, and still no green sentence anywhere.
    expect(launchButtonDisabled()).toBe(true);
    expect(container.textContent).not.toContain("Everything checks out.");
  });

  it("keeps the server's precise sentence, demoted rather than dropped", async () => {
    // It is what support and the audit trail quote. It must not be the headline a
    // business owner reads first, and it must not vanish.
    const { container } = await openLaunchPanel(check(OUTAGE));
    expectTextCount(container, OUTAGE.reason, 1);
  });
});

describe("the launch panel with nothing outstanding", () => {
  it("offers a live launch button only when the server says ready", async () => {
    await openLaunchPanel(check());

    await screen.findByText("Everything checks out.");
    expect(launchButtonDisabled()).toBe(false);
  });

  it("says nothing about permissions to a viewer who holds them", async () => {
    // The other half of the pair below: the refusal copy must not be ambient. An owner
    // who CAN launch and is shown "Only an account owner can…" beside a live button is
    // being told the control is dead when it is not.
    const { container } = await openLaunchPanel(check());

    await screen.findByText("Everything checks out.");
    expect(container.textContent).not.toContain("Only an account owner can");
    expect(launchButton().title).toBe("");
  });

  it("does not treat an empty blocker list as ready", async () => {
    // `ready` is the server's verdict and the panel keys on it, not on
    // `blockers.length === 0`. They agree today; a future gate that reports a
    // not-ready state without an itemised blocker would put a WORKING launch button on
    // a campaign the server will refuse — fail-closed is the only safe direction on a
    // control that places calls.
    const { container } = await openLaunchPanel({
      ready: false,
      blockers: [],
    });

    expect(container.textContent).not.toContain("Everything checks out.");
    expect(launchButtonDisabled()).toBe(true);
    expect(container.textContent).toContain("Everything on your side is ready");
  });
});

/**
 * Who may press it — the second way this panel can authorise wrongly.
 *
 * `POST /v1/campaigns/{id}/launch` requires `leads:dispatch` (campaigns/routes.py), which
 * `staff` does not hold (core/rbac.py) and which an impersonating operator is refused
 * however senior they are (D-22, `MUTATING_PERMISSIONS`). `/launch-check` deliberately
 * requires only `leads:read`, so BOTH of those viewers reach a panel that can legitimately
 * say "Everything checks out." over a button they may not press.
 *
 * That combination is the one this screen must not ship: an encouraging sentence, a dead
 * control, and the explanation a screenful away at the top of the page. It is the same
 * defect the leads Export button had — a refusal delivered after the click, or not at all,
 * reads as a fault in the product rather than as the boundary it is. So the reason is
 * asserted ON THE CONTROL (`title`, which is what a hover answers) as well as beside it.
 *
 * The server still refuses either way. This is a preview of its answer, never a substitute
 * for it — which is why the assertions are about what is SAID, not about the request.
 */
describe("the launch panel for a viewer who may not launch", () => {
  const STAFF: Me = { ...ME, role: "staff", permissions: ["leads:read"] };
  const STAFF_REASON = "Only an account owner can start or run campaigns.";

  const OPERATOR: Me = { ...ME, impersonating: true };
  const OPERATOR_REASON =
    "You are viewing this account read-only, so you cannot start or run campaigns from here.";

  it("refuses a staff user at the control, with the reason attached to it", async () => {
    const { container } = await openLaunchPanel(check(), STAFF);

    // The gate itself is clean, and the panel must keep saying so — hiding the verdict
    // from a staff user would make them report a compliance problem that does not exist.
    await screen.findByText("Everything checks out.");
    expect(launchButtonDisabled()).toBe(true);
    // On the control, so a hover answers without scrolling.
    expect(launchButton().title).toBe(STAFF_REASON);
    // …and beside it. Twice on the page is deliberate here and only here: once in the
    // screen-level RestrictionNote, once under the button that the sentence above it
    // has just told the reader is ready to press.
    expectTextCount(container, STAFF_REASON, 2);
  });

  it("refuses an impersonating operator the same way, and never as a 403 to come", async () => {
    const { container, calls } = await openLaunchPanel(check(), OPERATOR);

    expect(launchButtonDisabled()).toBe(true);
    expect(launchButton().title).toContain(OPERATOR_REASON);
    expect(container.textContent).toContain(OPERATOR_REASON);
    // D-22 is read-only: nothing on this screen may have POSTed on the way to rendering
    // a disabled button. A screen that mutates first and explains afterwards is the
    // failure the whole doctrine exists to prevent.
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("still shows a blocked campaign its blockers when the viewer may not launch", async () => {
    // The failure mode this rules out: gating the EXPLANATION on the mutating permission.
    // `/launch-check` is `leads:read` precisely so support and staff see the same reasons
    // the owner does — a staff user who can see neither the reason nor the button has
    // nothing to relay to the person who can act.
    const { container } = await openLaunchPanel(
      check({ rule: "no_contacts", reason: "The campaign has no contacts." }),
      STAFF,
    );

    expect(container.querySelectorAll("li")).toHaveLength(1);
    expect(container.textContent).toContain("Upload the contact list.");
    expect(launchButtonDisabled()).toBe(true);
  });
});
