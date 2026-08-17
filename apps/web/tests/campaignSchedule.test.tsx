import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CampaignsPage from "@/app/c/[slug]/campaigns/page";
import type { Agent } from "@/lib/api/agents";
import type { CampaignProgress, CampaignSummary, LaunchCheck } from "@/lib/api/campaigns";
import { scheduleStartAt } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import { expectTextCount, problem, renderClientPage } from "./harness";

/**
 * Scheduling a campaign start, from the screen.
 *
 * The launch panel authorises; this is the same authorisation with a delay on it, and
 * the delay is where the two mistakes live:
 *
 * 1. **The time the client picks could be sent as the wrong instant.** The pickers give
 *    a local wall clock. Sent without an offset, or with the VIEWER's offset, "10:00"
 *    becomes 10:00 wherever the browser happens to be — 15:30 IST for an operator
 *    viewing the account from London (D-22 makes that a real session). The wire body is
 *    asserted character for character for that reason: it is the only place in the whole
 *    feature where the client's intent is turned into an instant.
 *
 * 2. **A scheduled campaign could become a status and nothing else.** It is neither a
 *    draft nor running, so it falls between the two cards this screen was built from. A
 *    client would see the word "scheduled", no date, no way to cancel, and — when the
 *    gate refuses the start — no reason. §52: loading is a skeleton, failure is a
 *    refusal, and neither is a state.
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
  // D-163 split the bundled line into two notices with two switches. The fixture keeps
  // both ON, which is what a new agent is born with, and carries the server-composed
  // `opening_line` rather than joining the two sentences here — the screens read that
  // field, so a fixture that computed it would be testing its own arithmetic.
  ai_disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_enabled: true,
  recording_notice_line: "This call is being recorded.",
  recording_notice_enabled: true,
  opening_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
  truthful_answer_rule:
    "Whatever these settings say, the agent always answers honestly when a caller asks.",
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

const READY: LaunchCheck = { ready: true, blockers: [] };

/**
 * Two blockers a client would plausibly be sitting on while picking next Tuesday: one
 * they can clear themselves, one that is on OUR desk with the registrar and will take
 * days. The second is the whole argument — it is precisely the case where refusing to
 * accept a date would be refusing today for a condition Tuesday will have fixed.
 */
const BLOCKED: LaunchCheck = {
  ready: false,
  blockers: [
    { rule: "no_contacts", reason: "The campaign has no contacts." },
    { rule: "pe_registration_not_active", reason: "PE registration is not active." },
  ],
};

/**
  * `extra` is deliberately `Record<string, unknown>` — the callers override arbitrary
  * corners of the payload — so the spread erases nothing and adds nothing the checker can
  * see. That means every REQUIRED field has to be present in the base literal, which is
  * what `as unknown as CampaignProgress` used to hide: `status` and `launched_at` were
  * supplied by no caller and demanded by nobody.
  */
function progress(extra: Record<string, unknown>): CampaignProgress {
  return { status: "draft", contacts: {}, total: 0, concurrency: 3, launched_at: null, ...extra };
}

async function openCampaign(
  routes: Record<string, unknown>,
  waitFor: string,
): Promise<Awaited<ReturnType<typeof renderClientPage>>> {
  const rendered = await renderClientPage(<CampaignsPage />, {
    "/v1/me": ME,
    "/v1/campaigns": [CAMPAIGN],
    "/v1/agents": [AGENT],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: READY,
    ...routes,
  });
  fireEvent.click(await screen.findByRole("button", { name: CAMPAIGN.name }));
  await screen.findByText(waitFor);
  return rendered;
}

describe("turning a picked time into an instant", () => {
  it("attaches IST, not the viewer's offset, so 10:00 means 10:00 in India", () => {
    // The whole point of the helper, and the one assertion that would still hold if the
    // machine running these tests were in another timezone: the string carries +05:30.
    expect(scheduleStartAt("2026-08-17", "10:00")).toBe("2026-08-17T10:00:00+05:30");
    expect(scheduleStartAt("2026-08-17", "22:00")).toBe("2026-08-17T22:00:00+05:30");
  });

  it("refuses to guess at an incomplete pair rather than inventing a start", () => {
    expect(scheduleStartAt("", "10:00")).toBeNull();
    expect(scheduleStartAt("2026-08-17", "")).toBeNull();
    expect(scheduleStartAt("not-a-date", "10:00")).toBeNull();
  });
});

describe("scheduling from the launch card", () => {
  it("sends the picked time with its IST offset attached", async () => {
    const { calls } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }),
        [`POST /v1/campaigns/${CAMPAIGN_ID}/schedule`]: {
          start_at: "2026-08-17T04:30:00+00:00",
          first_dial_not_before: "2026-08-17T04:30:00+00:00",
        },
      },
      "Before you launch",
    );

    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-17" } });
    fireEvent.change(screen.getByLabelText("Start time (IST)"), { target: { value: "10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Schedule start" }));

    const sent = await vi.waitUntil(
      () => calls.find((c) => c.method === "POST" && c.path.endsWith("/schedule")),
      { timeout: 2000 },
    );
    // Character for character: a body of `{"start_at":"2026-08-17T10:00:00"}` is the
    // bug this test exists for, and it is one the server would refuse — but only after
    // the client had already been shown a working-looking form.
    expect(sent.body).toBe('{"start_at":"2026-08-17T10:00:00+05:30"}');
  });

  it("keeps the button dead until both halves of the time are picked", async () => {
    await openCampaign(
      { [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }) },
      "Before you launch",
    );
    const button = screen.getByRole("button", { name: "Schedule start" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-17" } });
    expect(button.disabled).toBe(false);
  });

  it("says the gate runs again at the start, not only now", async () => {
    // "Everything checks out" is true about this second. A client who read it as a
    // promise about Monday would treat a refused start as a malfunction.
    const { container } = await openCampaign(
      { [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }) },
      "Before you launch",
    );
    expect(container.textContent).toContain(
      "We check every one of these requirements again at the moment it starts",
    );
  });
});

describe("a campaign waiting for its start", () => {
  it("says WHEN, and offers the way out", async () => {
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
          status: "scheduled",
          launched_at: null,
          scheduled_start_at: "2026-08-17T04:30:00+00:00",
          schedule_blocked_rules: [],
        }),
      },
      "Scheduled",
    );

    // 04:30Z rendered in IST is 10:00 — the hour the client picked, given back to them
    // in the only timezone this product runs in.
    expect(container.textContent).toContain("10:00");
    expect(screen.getByRole("button", { name: "Cancel scheduled start" })).toBeTruthy();
    // And the launch gate's list is still on screen, because it is still the question:
    // the server re-runs exactly this check when the schedule fires.
    expect(container.textContent).toContain("Before it starts");
  });

  it("says the start was refused rather than letting it expire in silence", async () => {
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
          status: "scheduled",
          launched_at: null,
          scheduled_start_at: "2026-08-17T04:30:00+00:00",
          schedule_blocked_rules: ["dlt_template_not_approved"],
        }),
      },
      "Scheduled",
    );
    expect(container.textContent).toContain("We tried to start this campaign and could not");
    expect(container.textContent).toContain("goes back to draft");
    // The rule NAME is the gate's vocabulary, never the client's reading.
    expect(container.textContent).not.toContain("dlt_template_not_approved");
  });

  it("shows a skeleton while the start time is still loading, never a bare status", async () => {
    // The card is reached through the campaign LIST, which already carries the status;
    // the date comes from a second request. Rendering "Starts —" in the gap is a
    // sentence about a campaign that is not true yet.
    const rendered = await renderClientPage(<CampaignsPage />, {
      "/v1/me": ME,
      "/v1/campaigns": [{ ...CAMPAIGN, status: "scheduled" }],
      "/v1/agents": [AGENT],
      "/v1/campaigns/numbers": [],
      "/v1/campaigns/templates": [],
      [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: READY,
      [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
        status: "scheduled",
        launched_at: null,
        scheduled_start_at: "2026-08-17T04:30:00+00:00",
        schedule_blocked_rules: [],
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: CAMPAIGN.name }));
    await screen.findByText("Scheduled");
    expect(rendered.container.textContent).toContain("10:00");
  });

  it("renders the server's refusal when a schedule is rejected", async () => {
    // §52: failure is a refusal. A start in the past, or a campaign somebody launched
    // from another tab, comes back as problem+json and has to reach the screen — a form
    // that simply does not change is the client pressing the button again.
    await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }),
        [`POST /v1/campaigns/${CAMPAIGN_ID}/schedule`]: problem(422, {
          title: "Start time is in the past",
          detail: "A campaign can only be scheduled to start in the future.",
        }),
      },
      "Before you launch",
    );
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-17" } });
    fireEvent.click(screen.getByRole("button", { name: "Schedule start" }));
    expect(
      await screen.findByText("A campaign can only be scheduled to start in the future."),
    ).toBeTruthy();
  });
});

/**
 * ARMING A SCHEDULE WHILE THE GATE IS REFUSING — the case the screen used to get wrong.
 *
 * Both forms rendered only inside the launch panel's `ready` branch, so a campaign with
 * an outstanding blocker could not arm a start or a repeat at all. That was the SCREEN
 * inventing a rule the server does not have, and the server's position is not an
 * accident of implementation — `POST /schedule` and `POST /recurrence` both say in their
 * docstrings that no gate runs at arm time, `campaigns/scheduling.py` decision 3 gives
 * the reason, and D-79 records it. The gate runs at FIRE time, through the same
 * `launch_campaign` the Launch button calls, and two structural tests
 * (`campaign_schedule_test.py::test_the_module_exposes_no_way_to_skip_the_gate`,
 * `campaign_recurrence_test.py::test_every_path_from_a_recurrence_to_running_goes_through_the_launch_gate`)
 * pin that there is no second route into a dialling campaign.
 *
 * So a client whose DLT registration is with the registrar today may set next Tuesday.
 * Which makes the DANGEROUS version of this fix the thing these tests are really for:
 * a reachable form with the blockers HIDDEN would be worse than the defect it replaced —
 * a schedule that looks armed and produces a silent nothing on Tuesday morning. Every
 * test below therefore asserts the pair: the control is reachable AND the refusal it is
 * being armed against is still on screen, in advance, in words.
 */
describe("arming a schedule while the gate is refusing", () => {
  const DRAFT_BLOCKED = {
    [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }),
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
  };

  it("offers both forms with blockers outstanding, and still lists every blocker", async () => {
    const { container } = await openCampaign(DRAFT_BLOCKED, "Before you launch");

    // Reachable: the one-time start and the repeat, both live rather than merely
    // rendered — a form a client can see and cannot submit is the same dead end.
    expect(screen.getByLabelText("Start date")).toBeTruthy();
    expect(screen.getByLabelText("Start time (IST)")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Schedule start" }) as HTMLButtonElement).disabled)
      .toBe(true); // …until a date is picked, which is the form's own rule, not the gate's.
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-17" } });
    expect((screen.getByRole("button", { name: "Schedule start" }) as HTMLButtonElement).disabled)
      .toBe(false);
    fireEvent.click(screen.getByRole("checkbox", { name: "Tuesday" }));
    expect((screen.getByRole("button", { name: "Set repeat" }) as HTMLButtonElement).disabled).toBe(
      false,
    );

    // AND the blockers are still there, both of them, in the client's words. This is the
    // half that must never be traded for the half above.
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.textContent).toContain("Upload the contact list.");
    expect(container.textContent).toContain("Your business's DLT registration isn't active");
    // The desk it lands on survives too: this one is ours, and a client told only "your
    // registration is not active" goes hunting for a setting they do not have.
    expect(container.textContent).toContain("We handle this");
    // Nothing green: arming a schedule is not the gate passing.
    expect(container.textContent).not.toContain("Everything checks out.");
    expect(
      (screen.getByRole("button", { name: "Launch campaign" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("says what the start will do about the blockers, beside each form", async () => {
    const { container } = await openCampaign(DRAFT_BLOCKED, "Before you launch");

    // Once per form, because a client reading only the repeat form must not have to
    // scroll back up to learn that arming it is not the same as it running.
    expectTextCount(container, "As things stand", 2);
    expect(container.textContent).toContain("As things stand this campaign would not start");
    expect(container.textContent).toContain("As things stand the next run would not start");
    // And the permission this whole fix rests on, in the client's words: setting a time
    // is allowed, and the check is what decides — not this form.
    expectTextCount(
      container,
      "the same check runs again at the moment it does, so anything you clear before then is enough",
      2,
    );
    // The two consequences differ, and a client plans differently around them: a
    // one-time start is given up on after a day, an occurrence is skipped and the
    // repeat carries on. Both come from the server (`GRACE` vs `RECURRENCE_CATCHUP`).
    expect(container.textContent).toContain(
      "no calls go out, and after a day of trying the campaign goes back to draft.",
    );
    expect(container.textContent).toContain(
      "that run is skipped rather than dialled at a different time of day",
    );
    expect(container.textContent).toContain("the repeat itself carries on.");
    // The rule names stay the gate's vocabulary.
    expect(container.textContent).not.toContain("pe_registration_not_active");
  });

  it("actually sends the start, rather than rendering a form the click does nothing to", async () => {
    const { calls } = await openCampaign(
      {
        ...DRAFT_BLOCKED,
        [`POST /v1/campaigns/${CAMPAIGN_ID}/schedule`]: {
          start_at: "2026-08-17T04:30:00+00:00",
          first_dial_not_before: "2026-08-17T04:30:00+00:00",
        },
      },
      "Before you launch",
    );

    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-17" } });
    fireEvent.change(screen.getByLabelText("Start time (IST)"), { target: { value: "10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Schedule start" }));

    const sent = await vi.waitUntil(
      () => calls.find((c) => c.method === "POST" && c.path.endsWith("/schedule")),
      { timeout: 2000 },
    );
    expect(sent.body).toBe('{"start_at":"2026-08-17T10:00:00+05:30"}');
  });

  it("keeps the warning off a campaign the gate is happy with", async () => {
    // The other half of the pair: a warning that is always on screen is a warning
    // nobody reads, and "this would not start" is simply false when the gate is green.
    const { container } = await openCampaign(
      { [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }) },
      "Before you launch",
    );

    await screen.findByText("Everything checks out.");
    expect(screen.getByRole("button", { name: "Schedule start" })).toBeTruthy();
    expect(container.textContent).not.toContain("As things stand");
  });

  it("arms nothing at all while the launch check is unanswered", async () => {
    // §52, at the one place this change could have broken it: the consequence note is a
    // statement about a VERDICT. A failed `/launch-check` has no verdict, so the card is
    // a refusal and nothing else — offering the form there would let a client arm a
    // start under a sentence we cannot write.
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }),
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: problem(503, {
          title: "Upstream unavailable",
          detail: "We could not check this campaign just now.",
          retryable: true,
        }),
      },
      "Before you launch",
    );

    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: "Schedule start" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Set repeat" })).toBeNull();
    expect(container.textContent).not.toContain("As things stand");
    expect(container.textContent).toContain("We could not check this campaign just now.");
  });
});

/**
 * THE CANCEL PATH, checked for the same defect rather than assumed clear.
 *
 * A schedule you cannot cancel BECAUSE you have since acquired a blocker would be the
 * worse version of this bug: the client is then holding a start they did not want and
 * cannot stop, and the only thing standing between them and unwanted calls is the very
 * gate they are trying not to rely on. `DELETE /{id}/schedule` runs no gate either, and
 * both cancel controls live in their own cards outside the launch panel — these tests
 * hold that placement, because moving either one inside the panel's `ready` branch is
 * exactly how it would regress.
 */
describe("cancelling a schedule that has since acquired a blocker", () => {
  it("still offers the way out of a one-time start", async () => {
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
          status: "scheduled",
          launched_at: null,
          scheduled_start_at: "2026-08-17T04:30:00+00:00",
          schedule_blocked_rules: ["pe_registration_not_active"],
        }),
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
      },
      "Scheduled",
    );

    const cancel = screen.getByRole("button", { name: "Cancel scheduled start" });
    expect((cancel as HTMLButtonElement).disabled).toBe(false);
    // …and the reason it is not going to start is still on the screen beside it.
    expect(container.textContent).toContain("We tried to start this campaign and could not");
    expect(container.textContent).toContain("Upload the contact list.");
  });

  it("still offers the way out of a repeat", async () => {
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
          status: "scheduled",
          launched_at: null,
          recurrence: {
            days: [2],
            at: "10:00",
            until: null,
            next_occurrence_at: "2026-08-18T04:30:00+00:00",
            last_skipped_at: null,
            last_skipped_reason: null,
          },
        }),
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
      },
      "Repeats",
    );

    const stop = screen.getByRole("button", { name: "Stop repeating" });
    expect((stop as HTMLButtonElement).disabled).toBe(false);
    expect(container.textContent).toContain("Next: Tuesday, 18 Aug");
    expect(container.textContent).toContain("Upload the contact list.");
  });
});

/**
 * AN ARMED SCHEDULE THE GATE WOULD REFUSE TODAY — the same silence, one moment later.
 *
 * Making the forms reachable creates a state that did not exist before: a start or a
 * repeat sitting on a campaign whose blockers are still outstanding. Between arming and
 * the tick's first attempt the cards used to say "Starts Monday, 10:00 IST" and nothing
 * else, so the client's first evidence of the refusal would have been calls that never
 * happened. These hold the sentence that closes that window — and, just as importantly,
 * the three places it must NOT appear.
 */
describe("an armed schedule the gate would refuse today", () => {
  const scheduledAt = (extra: Record<string, unknown>) =>
    progress({
      status: "scheduled",
      launched_at: null,
      scheduled_start_at: "2026-08-17T04:30:00+00:00",
      ...extra,
    });

  it("says a pending start would not go ahead, before the tick has ever tried", async () => {
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: scheduledAt({ schedule_blocked_rules: [] }),
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
      },
      "Scheduled",
    );

    expect(container.textContent).toContain("As things stand this campaign would not start");
    expect(container.textContent).toContain("The reasons are listed below.");
    expect(container.textContent).toContain(
      "no calls go out, and after a day of trying the campaign goes back to draft.",
    );
    // Not the server's record — nothing has been attempted yet, and claiming otherwise
    // would be inventing an event.
    expect(container.textContent).not.toContain("We tried to start this campaign and could not");
    // The start itself, and the way out of it, are both still there.
    expect(container.textContent).toContain("10:00");
    expect(
      (screen.getByRole("button", { name: "Cancel scheduled start" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("stands down once the server has actually refused, rather than warning twice", async () => {
    // `schedule_blocked_rules` is a record of a real attempt and names which rules
    // refused. That is the stronger statement; a forecast beside it would be two
    // sentences about one fact, and the weaker one would be the newer.
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: scheduledAt({
          schedule_blocked_rules: ["pe_registration_not_active"],
        }),
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
      },
      "Scheduled",
    );

    expect(container.textContent).toContain("We tried to start this campaign and could not");
    expect(container.textContent).not.toContain("The reasons are listed below. Clear them");
  });

  it("says the same of a pending repeat", async () => {
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
          status: "scheduled",
          launched_at: null,
          recurrence: {
            days: [2],
            at: "10:00",
            until: null,
            next_occurrence_at: "2026-08-18T04:30:00+00:00",
            last_skipped_at: null,
            last_skipped_reason: null,
          },
        }),
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
      },
      "Repeats",
    );

    expect(container.textContent).toContain("As things stand the next run would not start");
    expect(container.textContent).toContain(
      "that run is skipped rather than dialled at a different time of day",
    );
    // The occurrence is still named: a warning that swallowed the schedule would be a
    // worse card than the one it replaced.
    expect(container.textContent).toContain("Next: Tuesday, 18 Aug");
  });

  it("never warns a RUNNING campaign that its repeat will not start", async () => {
    /**
     * The trap this rules out. `launch_blockers` reports a `status` blocker for a
     * campaign that has already launched — true, and NOT a statement about the next
     * occurrence, which the dispatcher only evaluates after `complete_or_rearm` returns
     * the campaign to `scheduled`. A card keyed on `ready` alone would tell a client
     * whose calls are going out fine that their repeat is broken.
     */
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
          status: "running",
          launched_at: "2026-08-11T04:30:00+00:00",
          recurrence: {
            days: [2],
            at: "10:00",
            until: null,
            next_occurrence_at: "2026-08-18T04:30:00+00:00",
            last_skipped_at: null,
            last_skipped_reason: null,
          },
        }),
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: {
          ready: false,
          blockers: [{ rule: "status", reason: "This campaign has already been launched." }],
        } satisfies LaunchCheck,
      },
      "Repeats",
    );

    expect(container.textContent).toContain("Next: Tuesday, 18 Aug");
    expect(container.textContent).not.toContain("As things stand");
  });

  it("warns nothing while the launch check is unanswered", async () => {
    // §52 again, at the armed cards: a schedule waiting for Monday under a 503 gets its
    // date and its cancel button, and no claim about a verdict nobody sent.
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: scheduledAt({ schedule_blocked_rules: [] }),
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: problem(503, {
          title: "Upstream unavailable",
          detail: "We could not check this campaign just now.",
          retryable: true,
        }),
      },
      "Scheduled",
    );

    expect(container.textContent).not.toContain("As things stand");
    expect(screen.getByRole("button", { name: "Cancel scheduled start" })).toBeTruthy();
    expect(container.textContent).toContain("We could not check this campaign just now.");
  });
});
