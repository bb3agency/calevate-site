import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { campaignPage, detailRoutes, dltRegistrationRoute, progressFixture } from "./campaignFixtures";
import type { Agent } from "@/lib/api/agents";
import type {
  CampaignProgress,
  LaunchCheck,
} from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import {
  expectTextCount,
  problem,
  renderClientPage,
  type Routes,
} from "./harness";
import { CALLING_NUMBERS_NOT_APPLICABLE, CALLING_NUMBERS_PATH } from "./harness";

/**
 * The control that stands where a launch begins — whichever of the two it is.
 *
 * There is exactly ONE at a time and the branches are mutually exclusive: a campaign with
 * outstanding blockers gets a dead "Launch campaign", and a campaign the gate has cleared
 * gets a live "Call N people" that launches at once (`LaunchConfirm`). One finder
 * keeps every assertion below about the SAME question — may this person start dialling,
 * and are they told why not.
 *
 * Not `toBeDisabled()`: `@testing-library/jest-dom` is deliberately not a dependency
 * (see vitest.config.mts), and `disabled` is the property the browser actually acts on.
 */
function launchButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /^(Launch campaign|Call \d[\d,]* (people|person))$/,
  }) as HTMLButtonElement;
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
  withheld_acts: [],
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
  // `te-IN`, not `te`: the column now carries a CHECK and `AgentOut` a union, so a
  // fixture holding a tag the server cannot store no longer compiles.
  language_primary: "te-IN",
  reply_languages: ["te-IN"],
  // Hard rule 5: an agent ALWAYS carries a non-null disclosure line, and an outbound
  // campaign agent is the case the rule exists for. This fixture omitted it entirely —
  // `as unknown as Agent` is why nobody noticed.
  disclosure_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  // D-163: the bundled line splits into two notices with two switches. Both ON, which is
  // what a new agent is born with; `opening_line` comes from the server rather than being
  // joined here, because that is the field every screen reads.
  ai_disclosure_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_enabled: true,
  recording_notice_line: "This call is being recorded.",
  caller_memory_notice_line: "I keep a short note of what you ask about.",
  caller_memory_enabled: false,
  caller_memory_paused: false,
  caller_has_screen: false,
  purpose: "sales",
  recording_notice_enabled: true,
  opening_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
  script_opening_line: "",
  first_words: "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
  truthful_answer_rule:
    "Whatever these settings say, the agent always answers honestly when a caller asks.",
  engine: "thinnest",
  published: true,
  // D-440 widened `AgentOut`: an agent knows when it was retired (NULL until it is) and
  // how many lines it answers in parallel, which is the one honest per-agent deployment
  // fact the API carries. Both are REQUIRED on the wire, so a fixture without them is not
  // an agent this server can send.
  archived_at: null,
  inbound_number_count: 1,
  extraction_fields: [],
  // D-454: inheriting all the way up, which is what this fixture always meant.
  llm_tier: null,
  llm_tier_effective: "standard",
  llm_tier_label: "Standard",
  llm_tier_source: "platform",
  llm_surcharged: false,
};

/** Draft, because the "Mandatory Regulatory Compliance Checks" card only exists for a draft. */
const PROGRESS: CampaignProgress = progressFixture({ total: 4 });

function check(...blockers: { rule: string; reason: string }[]): LaunchCheck {
  return { ready: blockers.length === 0, blockers };
}

/**
 * Open the panel the way a client does: at the campaign's own address.
 */
async function openLaunchPanel(
  launchCheck: LaunchCheck,
  me: Me = ME,
  over: Routes = {},
) {
  const rendered = await renderClientPage(campaignPage(), {
    "/v1/me": me,
    ...detailRoutes(),
    "/v1/agents": [AGENT],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    [`/v1/campaigns/${CAMPAIGN_ID}`]: PROGRESS,
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: launchCheck,
    ...over,
  });
  await screen.findByText("Mandatory Regulatory Compliance Checks");
  return rendered;
}

/** Presses the first Start campaign and returns the box it asks in. */
async function openStart(): Promise<HTMLElement> {
  fireEvent.click(screen.getAllByRole("button", { name: "Start campaign" })[0]);
  return screen.findByRole("dialog");
}

/** The rows of the compliance card's checklist, not every list on the page. */
function gateRows(): NodeListOf<HTMLLIElement> {
  const card = screen.getByText("Mandatory Regulatory Compliance Checks").closest("section");
  return card!.querySelectorAll("li");
}

describe("the launch panel with blockers outstanding", () => {
  it("shows every blocker the server sent, and no launch button that works", async () => {
    const { container } = await openLaunchPanel(
      check(
        { rule: "no_contacts", reason: "The campaign has no contacts." },
        { rule: "agent_not_live", reason: "The agent is not published." },
        { rule: "outbound_pledge_missing", reason: "Accept the no-cold-calls pledge first." },
      ),
    );

    // `no_contacts` and `agent_not_live` are not rows: Add people and the agent's own page
    // are where those are fixed (founder, 15 Nov 2026).
    expect(gateRows()).toHaveLength(1);
    // L3-09: one short line; the server's sentence, which names the state, is behind "Why?".
    expect(container.textContent).toContain("Accept the no-cold-calls promise.");
    expect(container.textContent).not.toContain("Accept the no-cold-calls pledge first.");
    expect(screen.queryByRole("button", { name: /^Call \d/ })).toBeNull();
    expect(container.textContent).not.toContain("Everything checks out.");

    // The count is the assertion, not the presence: Start names all three, and holds.
    const box = await openStart();
    const named = Array.from(box.querySelectorAll(".text-danger")).map((line) => line.textContent);
    expect(named).toEqual([
      "• Add the people to call.",
      "• Publish your agent first.",
      "• Accept the no-cold-calls promise.",
    ]);
    expect((within(box).getByRole("button", { name: "Start campaign" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("names the desk a blocker lands on, so a client does not hunt for a setting they do not have", async () => {
    const { container } = await openLaunchPanel(
      check(
        {
          rule: "national_dnd_scrub_missing",
          reason: "No national DND scrub on record."
        },
        { rule: "no_contacts", reason: "The campaign has no contacts." },
      ),
      // Calevate's telemarketer registration is live, so the national check is ours to run.
      ME,
      dltRegistrationRoute(true),
    );

    // The national do-not-disturb check is OUR task. Without the badge, it
    // reads as a to-do on a screen full of to-dos.
    expect(container.textContent).toContain("We handle this");
    // …and the one the client genuinely cannot be helped with must not borrow it.
    expectTextCount(container, "We handle this", 1);
    // A client's own task carries no badge; only a wait on us is labelled.
    expectTextCount(container, "You can fix this", 0);
  });

  it("never promises a national check that cannot be run while promotional calls are unavailable (L3-08)", async () => {
    const { container } = await openLaunchPanel(
      check({ rule: "national_dnd_scrub_missing", reason: "No national DND scrub on record." }),
    );
    await screen.findByText("Promotional calls are not available yet.");
    expect(container.textContent).not.toContain("We handle this");
    expect(screen.getByRole("link", { name: "Edit campaign" })).toBeTruthy();
  });

  it("renders the server's own reason for a rule this build has never heard of", async () => {
    // The fail-VISIBLE direction, at the site where failing closed would be silence.
    // A gate added after this build ships must still reach the client as a blocker —
    // "you cannot launch, and we will not say why" is the one outcome this card exists
    // to prevent, and an unnamed rule is exactly how it would happen.
    const { container } = await openLaunchPanel(
      check({
        rule: "a_gate_this_build_predates",
        reason:
          "Calling hours for this campaign fall outside the platform window.",
      }),
    );

    expect(gateRows()).toHaveLength(1);
    expect(container.textContent).toContain(
      "Calling hours for this campaign fall outside",
    );
    // The rule NAME is the gate's vocabulary and must not be what the client reads.
    expect(container.textContent).not.toContain("a_gate_this_build_predates");
    expect(screen.queryByRole("button", { name: /^Call \d/ })).toBeNull();
  });

  it("tells a client whose credit ran out that their agents have stopped answering too", async () => {
    /*
     * THE BLOCKER EVERY PREPAID ACCOUNT CAN MEET, and since prepaid is what an account
     * gets unless an operator deliberately says otherwise, the one most clients will meet
     * first. It had no copy at all, so it rendered the server's own sentence — "This
     * account has no calling credit left." — which is true and leaves the reader with the
     * two questions that actually matter unanswered.
     */
    const { container } = await openLaunchPanel(
      check({
        rule: "no_credits",
        reason: "This account has no calling credit left.",
      }),
    );

    const text = container.textContent ?? "";
    expect(text).toContain("Out of credit.");
    // ⚠ THIS USED TO ASSERT "People ringing you still get through", which D-551 withdrew:
    // an empty wallet now silences answering as well as dialling, so the campaign panel
    // says both halves and says a top-up undoes both. The `spend_cap` test below still
    // asserts the reassurance, because for a CAP it is still true.
    expect(text).not.toContain("still get through");
    // Both halves on the one default line: inbound stops with outbound.
    expect(text).toContain("Calls in and out have stopped.");
    // That a top-up undoes both is behind "Why?".
    fireEvent.click(screen.getAllByRole("button", { name: "Why?" })[0]);
    expect(container.textContent).toContain("start again straight away");
    // Not a queue to wait in — a two-minute fix, with the screen that does it attached.
    expect(text).not.toContain("We handle this");
    const link = screen.getByRole("link", { name: /Add credit/ });
    expect(link.getAttribute("href")).toContain("/billing?tab=credits");
    // And the gate's own name is not what the client reads.
    expect(text).not.toContain("no_credits");
  });

  it("sends a capped account to the limit that is its own, not to an account manager", async () => {
    const { container } = await openLaunchPanel(
      check({
        rule: "spend_cap",
        reason: "This account has reached its spending cap.",
      }),
    );

    const text = container.textContent ?? "";
    expect(text).toContain("Monthly spending limit reached.");
    expect(text).toContain("Calls to you still work.");
    // The limit is the client's own (D-34 R-11), so the destination is their screen.
    expect(
      screen
        .getByRole("link", { name: /Raise spending limit/ })
        .getAttribute("href"),
    ).toContain("/billing?tab=usage");
    expect(text).not.toContain("spend_cap");
  });

  it("sends an unconfirmed calling number to the calling numbers card (D-941)", async () => {
    await openLaunchPanel(
      check({
        rule: "a2p_number_undeclared",
        reason: "This agent calls from a number you have not confirmed.",
      }),
    );
    expect(
      screen.getByRole("link", { name: /Confirm your calling numbers/ }).getAttribute("href"),
    ).toBe("/c/acme/verify-business#calling-numbers");
  });

  it("reminds an account to confirm before the date, while nothing is refused yet", async () => {
    await openLaunchPanel(check(), ME, {
      [CALLING_NUMBERS_PATH]: {
        ...CALLING_NUMBERS_NOT_APPLICABLE,
        applies: true,
        blocker: { rule: "a2p_declaration_missing", reason: "Confirm your calling numbers." },
      },
    });
    expect(await screen.findByText("Confirm your calling numbers before 17 Nov")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Confirm numbers" })).toBeTruthy();
    expect(screen.getByText("From that day, calls from numbers you have not confirmed are refused.")).toBeTruthy();
  });

  it("keeps the enum names out of the DOM for the rules it does know", async () => {
    const { container } = await openLaunchPanel(
      check({
        rule: "consent_source_refused",
        reason: "The list is recorded as purchased.",
      }),
    );

    expect(container.textContent).toContain(
      "We don't call bought or rented lists.",
    );
    expect(container.textContent).not.toContain("consent_source_refused");
    // This one the client CAN act on: the question is asked right there, marked mandatory.
    expect(container.textContent).toContain("Where did this list come from?");
    expect(container.textContent).toContain("Mandatory under TRAI's TCCCPR 2018 and the DPDP Act 2023");
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
    expect(screen.queryByRole("button", { name: /^Call \d/ })).toBeNull();
    expect(container.textContent).toContain("Everything on your side is ready");
    // Start holds too, rather than offering a press the server will refuse.
    const box = await openStart();
    expect(box.textContent).toContain("It isn't ready to start yet.");
    expect((within(box).getByRole("button", { name: "Start campaign" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

/**
 * Who may press it — the second way this panel can authorise wrongly.
 *
 * `POST /v1/campaigns/{id}/launch` requires `leads:dispatch` (campaigns/routes.py), which
 * `staff` does not hold (core/rbac.py). ⚠ IT ALSO SAID an impersonating operator is
 * refused it "however senior they are" — D-587 reversed that, and the operator test below
 * now asserts the opposite; `staff` is the viewer this block is about. `/launch-check`
 * deliberately requires only `leads:read`, so that viewer reaches a panel that can
 * legitimately say "Everything checks out." over a button they may not press.
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

  /**
   * The operator in view-as, who since D-587 MAY press it — see the test below. Kept in
   * this describe block because the block is about "a viewer who may not launch" and the
   * operator is the one viewer who moved out of it.
   */
  const OPERATOR: Me = { ...ME, impersonating: true, withheld_acts: [] };

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

  it("lets an impersonating operator launch, and still POSTs nothing on the way in", async () => {
    /**
     * IT USED TO ASSERT A REFUSAL — "refuses an impersonating operator the same way" —
     * with the sentence "You are viewing this account read-only, so you cannot start or
     * run campaigns from here." D-587 deleted the rule under it: `leads:dispatch` is
     * writable in a view-as session (`rbac.VIEW_AS_MUTATIONS`), no named act covers a
     * launch, and `core/auth.requires` no longer refuses it — so a disabled button here
     * would be a browser-side copy of a policy the server has dropped, which is the exact
     * defect `useWriteAccess` was rewritten to stop carrying.
     *
     * The second half of the old test SURVIVES UNCHANGED and is why this is not simply
     * deleted: rendering the panel must still send no mutation. An operator is now the
     * one viewer for whom an accidental POST would actually dial.
     */
    const { container, calls } = await openLaunchPanel(check(), OPERATOR);

    await screen.findByText("Everything checks out.");
    expect(launchButtonDisabled()).toBe(false);
    expect(container.textContent).not.toContain("read-only");
    expect(container.textContent).not.toContain("stays with the client");
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("still shows a blocked campaign its blockers when the viewer may not launch", async () => {
    // The failure mode this rules out: gating the EXPLANATION on the mutating permission.
    // `/launch-check` is `leads:read` precisely so support and staff see the same reasons
    // the owner does — a staff user who can see neither the reason nor the button has
    // nothing to relay to the person who can act.
    const { container } = await openLaunchPanel(
      check({ rule: "outbound_pledge_missing", reason: "Accept the no-cold-calls pledge first." }),
      STAFF,
    );

    expect(gateRows()).toHaveLength(1);
    expect(container.textContent).toContain("Accept the no-cold-calls promise.");
    const start = screen.getAllByRole("button", { name: "Start campaign" })[0] as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    expect(start.title).toBe(STAFF_REASON);
  });
});

/**
 * The gate in front of the gate — `LaunchConfirm`.
 *
 * `/launch-check` answering `ready` means the compliance gate has nothing to say. It does
 * NOT mean the client meant to press the button, and this control had no second step at
 * all: `<button onClick={() => launch.mutate()}>` under the sentence "Everything checks
 * out." One click dialled every contact on the campaign, irreversibly, under TRAI.
 *
 * The server had already assumed otherwise — `campaigns/service.py::launch_campaign` says
 * the scrub makes "the 'N contacts will be dialled' number **the client confirms** true".
 * These are the tests that make that sentence describe something real.
 */
describe("launching", () => {
  const LAUNCHED = { status: "running", dialable: 120, dnc_scrubbed: 0 };
  const READY_PROGRESS: CampaignProgress = { ...PROGRESS, total: 120 };
  const LAUNCH_ROUTE = `POST /v1/campaigns/${CAMPAIGN_ID}/launch`;

  it("launches on one press (founder, 4 Nov 2026: pause and cancel are the way back)", async () => {
    const { calls } = await openLaunchPanel(check(), ME, {
      [`/v1/campaigns/${CAMPAIGN_ID}`]: READY_PROGRESS,
      [LAUNCH_ROUTE]: LAUNCHED,
    });
    expect(calls.some((call) => call.path.endsWith("/launch"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Call 120 people" }));

    await screen.findByText(/Calling 120 people/);
    const launched = calls.filter((call) => call.path.endsWith("/launch"));
    expect(launched).toHaveLength(1);
    expect(launched[0].method).toBe("POST");
  });

  it("says why a launch from the checks card was refused, beside the button", async () => {
    await openLaunchPanel(check(), ME, {
      [`/v1/campaigns/${CAMPAIGN_ID}`]: READY_PROGRESS,
      [LAUNCH_ROUTE]: problem(402, { title: "Your credit has run out", detail: "Top up to start calling." }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Call 120 people" }));
    const card = screen.getByText("Mandatory Regulatory Compliance Checks").closest("section") as HTMLElement;
    expect(await within(card).findByText(/Top up to start calling\./)).toBeTruthy();
  });

  /** The Other call settings section, where hours, calls at once, the number and the kind of call sit. */
  function otherSettings(): HTMLElement {
    return screen.getByRole("button", { name: "Other call settings" }).closest("section") as HTMLElement;
  }

  it("shows the hours, calls at once and the calling number in Other call settings", async () => {
    await openLaunchPanel(check(), ME, {
      [`/v1/campaigns/${CAMPAIGN_ID}`]: { ...READY_PROGRESS, calling_hours: { start: "10:00", end: "18:00" } },
      [LAUNCH_ROUTE]: LAUNCHED,
    });
    await screen.findByRole("button", { name: "Call 120 people" });
    const section = within(otherSettings());
    expect((section.getByLabelText("From") as HTMLInputElement).value).toBe("10:00");
    expect((section.getByLabelText("To") as HTMLInputElement).value).toBe("18:00");
    expect((section.getByLabelText("Up to") as HTMLSelectElement).value).toBe("3");
    // No number of its own: it rings from the agent's, said in words.
    const from = section.getByLabelText("Number") as HTMLSelectElement;
    expect(from.selectedOptions[0].textContent).toBe("Your agent\u2019s number");
  });

  it("names the account's call lines when they are what holds the campaign back", async () => {
    await openLaunchPanel(check(), ME, {
      [`/v1/campaigns/${CAMPAIGN_ID}`]: { ...READY_PROGRESS, concurrency: 5, effective_concurrency: 2 },
      "/v1/call-lines": { call_lines: 2, in_progress: 0, on_trial: false },
      [LAUNCH_ROUTE]: LAUNCHED,
    });
    await screen.findByRole("button", { name: "Call 120 people" });
    await vi.waitFor(() =>
      expect(otherSettings().textContent).toContain("You set 5. Your account runs up to 2 calls at once."),
    );
    expect(screen.queryByText(/plan allows/)).toBeNull();
  });

  it("gives the number without a cause when the account's lines are not the limit", async () => {
    // Lines of 10 under an effective 2: the plan or the inbound pool held it, and the
    // progress read does not say which, so the line names neither.
    const { container } = await openLaunchPanel(check(), ME, {
      [`/v1/campaigns/${CAMPAIGN_ID}`]: { ...READY_PROGRESS, concurrency: 5, effective_concurrency: 2 },
      "/v1/call-lines": { call_lines: 10, in_progress: 0, on_trial: false },
      [LAUNCH_ROUTE]: LAUNCHED,
    });
    expect((await screen.findAllByText("You set 5. Up to 2 can run at once right now.")).length).toBeGreaterThan(0);
    expect(container.textContent).not.toContain("plan allows");
    expect(container.textContent).not.toContain("Your account runs");
  });

  it("states the kind of call the list makes it, with the window it is held to", async () => {
    await openLaunchPanel(check(), ME, {
      [`/v1/campaigns/${CAMPAIGN_ID}`]: {
        ...READY_PROGRESS,
        classification: "service",
        consent_source: "web_form_optin",
      },
      [`/v1/compliance/call-purpose/campaigns/${CAMPAIGN_ID}`]: {
        campaign_id: CAMPAIGN_ID,
        agent_id: AGENT_ID,
        purpose: {
          purpose: "relationship_enquiry",
          label: "Follow-up to an enquiry",
          basis: "x",
          window: "7 days from their enquiry",
          explanation: "Calling back someone who asked you about something.",
        },
        report: { verdict: "clear", blocks_launch: false, findings: [], truncated: false, fix: "" },
        blocks_launch: false,
      },
      [LAUNCH_ROUTE]: LAUNCHED,
    });
    await screen.findByRole("button", { name: "Call 120 people" });
    const section = otherSettings();
    await vi.waitFor(() => expect(section.textContent).toContain("Follow-up to an enquiry"));
    expect(section.textContent).toContain("Permission lasts 7 days from their enquiry.");
    // What the launch check does not do sits behind the tap.
    fireEvent.click(within(section).getByRole("button", { name: "Why?" }));
    expect(section.textContent).toContain("We don't check each person's date for you.");
  });

  it("offers no launch at all when the campaign's progress could not be read", async () => {
    // A manufactured `0` under "Call N people" is the one number nobody would question, so
    // a failed progress read takes the launch off screen, with the green sentence.
    const { container } = await renderClientPage(campaignPage(), {
      "/v1/me": ME,
      ...detailRoutes(),
      "/v1/agents": [AGENT],
      "/v1/campaigns/numbers": [],
      "/v1/campaigns/templates": [],
      [`/v1/campaigns/${CAMPAIGN_ID}`]: problem(503, {
        title: "Service unavailable",
      }),
      [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: check(),
    });
    await screen.findByRole("alert");

    expect(screen.queryByRole("button", { name: "Launch campaign" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Call \d/ })).toBeNull();
    expect(container.textContent).not.toContain("Everything checks out.");
  });
});
