import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CampaignsPage from "@/app/c/[slug]/campaigns/page";
import type { Agent } from "@/lib/api/agents";
import type { CampaignProgress, CampaignSummary, LaunchCheck } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import { problem, renderClientPage, type Routes } from "./harness";

/**
 * The repeat, on the screen a client decides from.
 *
 * A repeat is the only control on this console that causes phone calls WEEKS after the
 * click, to people the client will not be thinking about at the time. That makes two
 * things load-bearing on this screen and nothing else particularly:
 *
 * 1. **The next occurrence has to be legible against a real calendar.** "Repeats weekly"
 *    is not a schedule anyone can check; "Next: Tuesday 19 Aug, 10:00 IST" is. The
 *    weekday is the part that answers the question a client actually asks ("is that this
 *    Tuesday?"), which is why this screen formats occurrences differently from every
 *    other time on the console.
 * 2. **The skip has to be explained, not just recorded.** The server skips a missed run
 *    rather than firing it late (`campaigns/scheduling.py` decision 2). A client who sees
 *    a week with no calls and no sentence concludes we dropped their campaign.
 *
 * Plus §52 in the place it bites hardest here: "this campaign does not repeat" is a
 * CLAIM, and a request in flight or a 503 does not support it. Every assertion about the
 * absence of the repeat card is paired with one that it appears when the server answers.
 */

const CAMPAIGN_ID = "0192f0aa-4444-7000-8000-000000000001";
const AGENT_ID = "0192f0aa-4444-7000-8000-000000000002";

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
  // D-440 widened `AgentOut`: an agent knows when it was retired (NULL until it is) and
  // how many lines it answers in parallel, which is the one honest per-agent deployment
  // fact the API carries. Both are REQUIRED on the wire, so a fixture without them is not
  // an agent this server can send.
  archived_at: null,
  inbound_number_count: 1,
  extraction_fields: [],
  // D-454: inheriting all the way up, which is what this fixture always meant.
  llm_model: null,
  llm_model_effective: "gpt-4o-mini",
  llm_model_source: "platform",
};

const CAMPAIGN: CampaignSummary = {
  id: CAMPAIGN_ID,
  name: "Weekly follow-up",
  status: "scheduled",
  classification: "promotional",
  contacts: 120,
  connected: 0,
  launched_at: null,
  created_at: "2026-08-10T06:00:00Z",
  consent_provenance_blocker: null,
};

/** 10:00 IST on Tuesday 18 August 2026 is 04:30Z — the instant, not the digits. */
const NEXT_TUESDAY = "2026-08-18T04:30:00+00:00";
/** The Tuesday before it: the run that was missed. */
const LAST_TUESDAY = "2026-08-11T04:30:00+00:00";

const REPEATING: CampaignProgress = {
  status: "scheduled",
  contacts: {},
  total: 0,
  concurrency: 3,
  launched_at: null,
  recurrence: {
    days: [2],
    at: "10:00",
    until: null,
    next_occurrence_at: NEXT_TUESDAY,
    last_skipped_at: null,
    last_skipped_reason: null,
  },
};

const DRAFT: CampaignProgress = {
  status: "draft",
  contacts: {},
  total: 0,
  concurrency: 3,
  launched_at: null,
};

const READY: LaunchCheck = { ready: true, blockers: [] };

function routes(progress: unknown, extra: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/campaigns": [CAMPAIGN],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    [`/v1/campaigns/${CAMPAIGN_ID}`]: progress,
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: READY,
    ...extra,
  };
}

async function openCampaign(progress: unknown, extra: Routes = {}) {
  const rendered = await renderClientPage(<CampaignsPage />, routes(progress, extra));
  fireEvent.click(await screen.findByRole("button", { name: CAMPAIGN.name }));
  return rendered;
}

describe("a campaign that repeats", () => {
  it("names the next occurrence with its weekday, not just 'repeats weekly'", async () => {
    const { container } = await openCampaign(REPEATING);

    await screen.findByText("Repeats");
    expect(container.textContent).toContain("Calls every Tuesday at 10:00 IST");
    // The date a client can hold against their own calendar. Asserted on the weekday and
    // the date together: either alone would pass on a render that dropped the other.
    expect(container.textContent).toContain("Next: Tuesday, 18 Aug");
    expect(container.textContent).toContain("IST");
  });

  it("says a skipped run was skipped, and why", async () => {
    /**
     * The server does not catch up a missed occurrence — it abandons it and waits for the
     * next. That is the right call and it is INVISIBLE: the campaign still says
     * "scheduled" on a week it never dialled. Without this sentence the client's only
     * evidence is calls that did not happen.
     */
    const skipped = {
      ...REPEATING,
      recurrence: {
        ...REPEATING.recurrence,
        last_skipped_at: LAST_TUESDAY,
        last_skipped_reason: "missed",
      },
    };
    const { container } = await openCampaign(skipped);

    await screen.findByText("Repeats");
    expect(container.textContent).toContain("We skipped the run due Tuesday, 11 Aug");
    expect(container.textContent).toContain("calling people at a different time of day");
    // The server's enum is never rendered: "missed" is our vocabulary, not a sentence.
    expect(container.textContent).not.toContain("last_skipped_reason");
  });

  it("offers one labelled stop, and says what stopping does not do", async () => {
    const { container } = await openCampaign(REPEATING);

    const stop = await screen.findByRole("button", { name: "Stop repeating" });
    expect((stop as HTMLButtonElement).disabled).toBe(false);
    // The half a client would otherwise assume: stopping a repeat is not a pause.
    expect(container.textContent).toContain("Calls already going out are not affected");
    for (const button of container.querySelectorAll("button")) {
      expect(button.textContent?.trim(), "a control was rendered with no label").not.toBe("");
    }
  });

  it("keeps repeating visible on a campaign that is already dialling", async () => {
    // A one-time start is spent when it fires; a repeat is not. A client watching a
    // running campaign needs to know it will do this again — and needs the stop button
    // there, rather than only on a screen they can no longer reach.
    const running = { ...REPEATING, status: "running", launched_at: NEXT_TUESDAY };
    const { container } = await openCampaign(running);

    await screen.findByText("Repeats");
    expect(container.textContent).toContain("Next: Tuesday, 18 Aug");
    expect(screen.getByRole("button", { name: "Stop repeating" })).toBeTruthy();
  });
});

describe("a repeat the screen could not read", () => {
  it("reports the failure and claims nothing about repeating", async () => {
    const { container } = await openCampaign(
      problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this campaign just now.",
        retryable: true,
      }),
    );

    await screen.findByRole("alert");
    // §52: no repeat card, and — the part that matters — no assertion that it does not
    // repeat. Absence of a claim is the honest render of a failed read.
    expect(container.textContent).not.toContain("Repeats");
    expect(container.textContent).not.toContain("Next:");
  });

  it("shows no repeat while the request is still in flight", async () => {
    const { container } = await openCampaign(REPEATING);
    // Asserted in the same tick as the click, before the stubbed fetch resolves.
    expect(container.textContent).not.toContain("Next: Tuesday, 18 Aug");
    // …and it appears once the answer lands, so the guard is not hiding it for good.
    await screen.findByText("Repeats");
  });
});

describe("setting a repeat", () => {
  it("cannot be submitted until a day is chosen, and says so", async () => {
    const { container } = await openCampaign(DRAFT);

    await screen.findByText("Or repeat it every week");
    const set = screen.getByRole("button", { name: "Set repeat" }) as HTMLButtonElement;
    expect(set.disabled).toBe(true);
    expect(container.textContent).toContain("Choose at least one day");

    // Every day toggle is reachable by its full name, not by a three-letter abbreviation
    // a screen reader spells out.
    fireEvent.click(screen.getByRole("checkbox", { name: "Tuesday" }));
    expect((screen.getByRole("button", { name: "Set repeat" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("sends ISO weekday numbers and an IST wall-clock time", async () => {
    /**
     * The wire contract, asserted at the seam rather than trusted: `days` is 1 = Monday
     * (the server's and `isoweekday()`'s numbering, NOT `Date.getDay()`'s Sunday = 0),
     * and `at` is a wall-clock "HH:MM" rather than an instant. Both are off-by-one
     * mistakes that would dial on the wrong day or at the wrong hour, and neither shows
     * up in a render.
     */
    const { calls } = await openCampaign(DRAFT, {
      [`POST /v1/campaigns/${CAMPAIGN_ID}/recurrence`]: {
        days: [2],
        at: "10:00",
        until: null,
        next_occurrence_at: NEXT_TUESDAY,
        first_dial_not_before: NEXT_TUESDAY,
      },
    });

    await screen.findByText("Or repeat it every week");
    fireEvent.click(screen.getByRole("checkbox", { name: "Tuesday" }));
    fireEvent.click(screen.getByRole("button", { name: "Set repeat" }));

    const posted = await vi.waitFor(() => {
      const call = calls.find((c) => c.path.endsWith("/recurrence") && c.method === "POST");
      expect(call, "the repeat was never sent").toBeTruthy();
      return call!;
    });
    expect(JSON.parse(posted.body ?? "{}")).toEqual({
      days: [2],
      at: "10:00",
      until: null,
    });
  });

  it("renders the server's refusal rather than a form that silently did nothing", async () => {
    /**
     * A repeat outside 9am-9pm is refused by name (`campaign_recurrence_outside_calling_
     * hours`). The client can only act on that if it is on screen — and this is a
     * refusal they CAN act on, which is exactly what §52 asks a failure to be.
     */
    const { container } = await openCampaign(DRAFT, {
      [`POST /v1/campaigns/${CAMPAIGN_ID}/recurrence`]: problem(422, {
        title: "That time is outside calling hours",
        detail: "Calls may only be placed between 09:00 and 21:00 IST.",
      }),
    });

    await screen.findByText("Or repeat it every week");
    fireEvent.click(screen.getByRole("checkbox", { name: "Tuesday" }));
    fireEvent.click(screen.getByRole("button", { name: "Set repeat" }));

    await screen.findByRole("alert");
    expect(container.textContent).toContain(
      "Calls may only be placed between 09:00 and 21:00 IST.",
    );
  });
});
