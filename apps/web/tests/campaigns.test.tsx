import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EditCampaignPage from "@/app/c/[slug]/campaigns/[campaignId]/edit/page";
import type { Agent } from "@/lib/api/agents";
import type { CampaignSummary, LaunchCheck } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import {
  FIXTURE_AGENT_ID as AGENT_ID,
  FIXTURE_CAMPAIGN_ID as CAMPAIGN_ID,
  LIST_PATH,
  campaignPage,
  contactsFixture,
  contactsPath,
  detailRoutes,
  dltRegistrationRoute,
  leadPickerRoutes,
  listPage,
  newCampaignPage,
  pageFixture,
  pickDate,
  progressFixture,
  resultsFixture,
} from "./campaignFixtures";
import { problem, renderClientPage, stillLoading, type Routes } from "./harness";

/**
 * The campaign screens at their own addresses (D-773): the list, the create page and one
 * campaign. Mostly negative assertions, because each bug here is something SHOWN that
 * should not have been: an assertion nobody made in the consent record, a zero over a
 * campaign we could not read, a control the server refuses, a rule name in the DOM.
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
  // D-163 split the bundled line into two notices with two switches. The fixture keeps
  // both ON, which is what a new agent is born with, and carries the server-composed
  // `opening_line` rather than joining the two sentences here — the screens read that
  // field, so a fixture that computed it would be testing its own arithmetic.
  ai_disclosure_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_enabled: true,
  recording_notice_line: "This call is being recorded.",
  caller_memory_notice_line: "I keep a short note of what you ask about.",
  caller_memory_enabled: false,
  caller_memory_paused: false,
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
  extraction_schema_version: 0,
  // D-454: inheriting all the way up, which is what this fixture always meant.
  llm_tier: null,
  llm_tier_effective: "standard",
  llm_tier_label: "Standard",
  llm_tier_source: "platform",
  llm_surcharged: false,
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
  pause_reason: null,
};

const BLOCKED: LaunchCheck = {
  ready: false,
  blockers: [{ rule: "no_contacts", reason: "The campaign has no contacts." }],
};

/** The reads the create page is built from. */
function newRoutes(extra: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    ...dltRegistrationRoute(),
    ...extra,
  };
}

/** One campaign's page, with `progress` and the launch check answered as given. */
function detail(progress: unknown, extra: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    ...detailRoutes(),
    [`/v1/campaigns/${CAMPAIGN_ID}`]: progress,
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: BLOCKED,
    ...extra,
  };
}

function consentRadios(container: HTMLElement): HTMLInputElement[] {
  return Array.from(container.querySelectorAll<HTMLInputElement>('input[name="new-consent-source"]'));
}

const CONSENT_DATE = "When did they agree?";

function pasteContacts(text: string): void {
  fireEvent.click(screen.getByRole("button", { name: "Paste" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Paste rows" }), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Add these rows" }));
}

/** The create page is four steps; Next checks the step it leaves. */
function next(): void {
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
}

/** Fills the basics and the list, then walks to the review step. */
async function fillNew(
  container: HTMLElement,
  name = "Diwali reminder",
  { atWhoToCall = false }: { atWhoToCall?: boolean } = {},
): Promise<void> {
  if (!atWhoToCall) {
    await screen.findByRole("heading", { name: "The basics" });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: name } });
    next();
  }
  await screen.findByRole("heading", { name: "Who should we call?" });
  pasteContacts("9876543210,Priya");
  fireEvent.click(consentRadios(container)[0]);
  await pickDate(CONSENT_DATE, "2026-08-01");
  next();
  await screen.findByRole("heading", { name: "When should we call?" });
  next();
  await screen.findByRole("heading", { name: "Check it, then create it" });
}

describe("the create page's consent declaration", () => {
  it("opens unanswered and will not create a campaign without it", async () => {
    // Where the list came from is an audited statement. A pre-selected answer would be an
    // assertion nobody made, so the page opens empty and refuses to create without one.
    const { container } = await renderClientPage(newCampaignPage(), newRoutes());
    await screen.findByRole("heading", { name: "The basics" });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "List" } });
    next();
    await screen.findByRole("heading", { name: "Who should we call?" });
    expect(consentRadios(container)).toHaveLength(5);
    expect(consentRadios(container).some((r) => r.checked)).toBe(false);
    expect(screen.getByRole("button", { name: CONSENT_DATE }).textContent).toContain("Choose a date");

    pasteContacts("9876543210");
    next();
    expect((await screen.findByRole("alert")).textContent).toContain("Answer both questions about your list");
    // Still on the step that asks, never moved on to the next one.
    expect(screen.getByRole("heading", { name: "Who should we call?" })).toBeTruthy();
  });

  it("offers Service only while Calevate's telemarketer registration is not live, and never Transactional", async () => {
    await renderClientPage(newCampaignPage(), newRoutes());
    await screen.findByRole("heading", { name: "The basics" });
    expect(screen.getByRole("radio", { name: /Service/ })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /Promotional/ })).toBeNull();
    expect(screen.queryByRole("radio", { name: /Transactional/ })).toBeNull();
  });

  it("offers Promotional once the telemarketer registration is live", async () => {
    await renderClientPage(newCampaignPage(), newRoutes(dltRegistrationRoute(true)));
    expect(await screen.findByRole("radio", { name: /Promotional/ })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Service/ })).toBeTruthy();
  });
});

describe("a campaign whose progress could not be read", () => {
  it("reports the failure and invents no counts", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      detail(
        problem(503, {
          title: "Upstream unavailable",
          detail: "We could not read this campaign just now.",
          retryable: true,
        }),
      ),
    );
    await screen.findByRole("alert");
    expect(container.textContent).toContain("We could not read this campaign just now.");
    expect(container.textContent).not.toContain("Picked up");
    expect(screen.queryByRole("button", { name: "Launch campaign" })).toBeNull();
    expect(container.textContent).not.toContain("Everything checks out.");
  });

  it("shows a skeleton rather than a zero while the request is in flight", async () => {
    const { container } = await renderClientPage(campaignPage(), detail(stillLoading()));
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    expect(container.textContent).not.toContain("0 people");
  });
});

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
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(container.textContent).toContain("Can't be launched");
    expect(container.textContent).not.toContain("consent_source_refused");
    expect(container.querySelector("h1")).toBeNull();
    expect(screen.getByRole("link", { name: "New campaign" }).getAttribute("href")).toBe(
      "/c/acme/campaigns/new",
    );
  });

  it("names an automatic pause and offers no Resume the server would refuse", async () => {
    const paused: CampaignSummary = { ...CAMPAIGN, status: "paused", pause_reason: "out_of_credit" };
    const { container } = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([paused]),
    });
    await screen.findByRole("link", { name: CAMPAIGN.name });
    expect(container.textContent).toContain("Paused: out of credit");
    expect(screen.queryByRole("button", { name: /Resume/ })).toBeNull();
  });

  it("counts every status and asks the server for the one chosen", async () => {
    const rendered = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([CAMPAIGN]),
      "/v1/campaigns/page?limit=25&offset=0&status=draft": pageFixture([CAMPAIGN]),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Drafts 1" }));
    await vi.waitFor(() =>
      expect(rendered.calls.some((c) => c.path.endsWith("status=draft"))).toBe(true),
    );
  });

  it("says there are none only when the server answered with none", async () => {
    const { container } = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([]),
    });
    await screen.findByText("No campaigns yet.");
    expect(container.textContent).not.toContain("No campaign matches");
  });
});

describe("choosing which agent makes the calls (D-440)", () => {
  const agentIn = (over: Partial<Agent>): Agent => ({ ...AGENT, ...over });

  it("never offers an archived agent", async () => {
    const { container } = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "/v1/agents": [
          agentIn({ id: "a-live", name: "Follow-ups" }),
          agentIn({
            id: "a-old",
            name: "Retired dialler",
            status: "archived",
            archived_at: "2026-07-02T09:30:00Z",
            published: false,
          }),
        ],
      }),
    );
    await screen.findByText("Which agent makes these calls");
    const picker = container.querySelector<HTMLSelectElement>("select")!;
    const options = Array.from(picker.options)
      .map((o) => o.textContent)
      .join(" | ");
    expect(options).toContain("Follow-ups");
    expect(options).not.toContain("Retired dialler");
  });

  it("marks an agent that cannot dial yet", async () => {
    const { container } = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "/v1/agents": [agentIn({ id: "a-draft", name: "Half built", status: "draft", published: false })],
      }),
    );
    await screen.findByText("Which agent makes these calls");
    expect(container.querySelector("select")!.options[0].textContent).toContain(
      "not able to call out yet",
    );
  });

  it("does not claim there is no agent when /v1/agents failed", async () => {
    const { container } = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "/v1/agents": problem(503, {
          title: "Upstream unavailable",
          detail: "We could not read that just now.",
          retryable: true,
        }),
      }),
    );
    await screen.findByRole("alert");
    expect(container.textContent).not.toContain("No agent is set up yet");
  });

  it("says so when the server really answered with no agents", async () => {
    await renderClientPage(newCampaignPage(), newRoutes({ "/v1/agents": [] }));
    await screen.findByText(/No agent is set up yet/);
  });
});

describe("the number picker", () => {
  it("offers only numbers that can make this agent's calls", async () => {
    const base = {
      series: "standard",
      dlt_status: "unregistered",
      supplied_by_us: true,
      answerable: true,
      direction: "both" as const,
      inr_per_month: null,
      activated: true,
      releasable: false,
    };
    const { container } = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "/v1/campaigns/numbers": [
          { ...base, id: "n-ok", e164: "+918041000001", agent_id: AGENT_ID, places_calls: true },
          {
            ...base,
            id: "n-in",
            e164: "+918041000002",
            agent_id: AGENT_ID,
            places_calls: false,
            direction: "inbound" as const,
          },
          { ...base, id: "n-other", e164: "+918041000003", agent_id: "someone-else", places_calls: true },
        ],
      }),
    );
    await screen.findByText("Calling from");
    const picker = screen.getByRole("combobox", { name: /^Calling from/ }) as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.value)).toEqual(["", "n-ok"]);
    expect(container.textContent).toContain("Only numbers this agent can make calls from are listed.");
  });
});

describe("creating a campaign", () => {
  it("creates the draft, then sends its list and its retry choice", async () => {
    const rendered = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "POST /v1/campaigns": { id: CAMPAIGN_ID, status: "draft" },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/contacts`]: { added: 1, duplicate: 0, malformed: 0, foreign: 0 },
      }),
    );
    await fillNew(rendered.container);
    fireEvent.click(screen.getByRole("button", { name: "Create campaign" }));
    const upload = await vi.waitFor(() => {
      const call = rendered.calls.find(
        (c) => c.method === "POST" && c.path === `/v1/campaigns/${CAMPAIGN_ID}/contacts`,
      );
      expect(call).toBeDefined();
      return call!;
    });
    expect(JSON.parse(upload.body ?? "{}").contacts).toEqual([{ phone: "+919876543210", name: "Priya" }]);
    const created = rendered.calls.find((c) => c.method === "POST" && c.path === "/v1/campaigns")!;
    expect(JSON.parse(created.body ?? "{}").retry_policy).toEqual({ max_attempts: 3, gaps_minutes: [30, 120] });
  });

  it("says the draft exists and links to it when the list upload is refused", async () => {
    const rendered = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "POST /v1/campaigns": { id: CAMPAIGN_ID, status: "draft" },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/contacts`]: problem(503, {
          title: "Upstream unavailable",
          detail: "We could not save those contacts just now.",
          retryable: true,
        }),
      }),
    );
    await fillNew(rendered.container);
    fireEvent.click(screen.getByRole("button", { name: "Create campaign" }));
    await screen.findByText("We could not save those contacts just now.");
    expect(screen.getByRole("link", { name: "Open it" }).getAttribute("href")).toBe(
      `/c/acme/campaigns/${CAMPAIGN_ID}`,
    );
  });

  it("does not create a second draft when Create is pressed again after a follow-up failed", async () => {
    const rendered = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "POST /v1/campaigns": { id: CAMPAIGN_ID, status: "draft" },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/contacts`]: problem(503, {
          title: "Upstream unavailable",
          detail: "We could not save those contacts just now.",
          retryable: true,
        }),
      }),
    );
    await fillNew(rendered.container);
    fireEvent.click(screen.getByRole("button", { name: "Create campaign" }));
    await screen.findByText("We could not save those contacts just now.");
    const finish = screen.getByRole("button", { name: "Create campaign" }) as HTMLButtonElement;
    expect(finish.disabled).toBe(true);
    fireEvent.click(finish);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(rendered.calls.filter((c) => c.method === "POST" && c.path === "/v1/campaigns")).toHaveLength(1);
  });

  it("adds leads by the Leads lens with the count it showed", async () => {
    const rendered = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        ...leadPickerRoutes(4),
        "POST /v1/campaigns": { id: CAMPAIGN_ID, status: "draft" },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/contacts`]: { added: 1, duplicate: 0, malformed: 0, foreign: 0 },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/contacts/from-leads`]: {
          added: 4,
          duplicate: 0,
          malformed: 0,
          foreign: 0,
          plan_id: null,
        },
      }),
    );
    await screen.findByRole("heading", { name: "The basics" });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Hot leads" } });
    next();
    await screen.findByRole("heading", { name: "Who should we call?" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Also call people from your leads" }));
    const stages = await screen.findByRole("radiogroup", { name: "Filter by status" });
    fireEvent.click(within(stages).getByRole("radio", { name: /^Hot/ }));
    await screen.findByText(/4 leads match/);
    await fillNew(rendered.container, "Hot leads", { atWhoToCall: true });
    expect(screen.getByText(/plus 4 leads/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Create campaign" }));
    const added = await vi.waitFor(() => {
      const call = rendered.calls.find(
        (c) => c.method === "POST" && c.path === `/v1/campaigns/${CAMPAIGN_ID}/contacts/from-leads`,
      );
      expect(call).toBeDefined();
      return call!;
    });
    expect(JSON.parse(added.body ?? "{}")).toEqual({ lens: { status: "hot" }, expected_count: 4 });
  });

  it("arms a chosen start after the draft exists, with its IST offset", async () => {
    const rendered = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "POST /v1/campaigns": { id: CAMPAIGN_ID, status: "draft" },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/contacts`]: { added: 1, duplicate: 0, malformed: 0, foreign: 0 },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/schedule`]: {
          start_at: "2030-01-15T04:30:00+00:00",
          first_dial_not_before: "2030-01-15T04:30:00+00:00",
        },
      }),
    );
    await fillNew(rendered.container);
    fireEvent.click(screen.getByRole("button", { name: "Change starts" }));
    fireEvent.click(await screen.findByRole("radio", { name: /At a set time/ }));
    next();
    expect((await screen.findByRole("alert")).textContent).toContain("Choose the date and time");
    await pickDate("Start date", "2030-01-15");
    next();
    fireEvent.click(await screen.findByRole("button", { name: "Create campaign" }));
    const armed = await vi.waitFor(() => {
      const call = rendered.calls.find(
        (c) => c.method === "POST" && c.path === `/v1/campaigns/${CAMPAIGN_ID}/schedule`,
      );
      expect(call).toBeDefined();
      return call!;
    });
    expect(JSON.parse(armed.body ?? "{}").start_at).toBe("2030-01-15T10:00:00+05:30");
  });
});

describe("adding leads to a draft", () => {
  it("sends the Leads lens and the count shown, and shows a large set as its plan", async () => {
    const rendered = await renderClientPage(
      campaignPage(),
      detail(progressFixture({ id: CAMPAIGN_ID, status: "draft" }), {
        ...leadPickerRoutes(7),
        [`POST /v1/campaigns/${CAMPAIGN_ID}/contacts/from-leads`]: {
          added: 0,
          duplicate: 0,
          malformed: 0,
          plan_id: "0192f0aa-9999-7000-8000-000000000001",
        },
        "/v1/copilot/plans/0192f0aa-9999-7000-8000-000000000001": stillLoading(),
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add people" }));
    fireEvent.change(await screen.findByRole("searchbox", { name: "Search leads" }), {
      target: { value: "Priya" },
    });
    // The count under the typed search, not the one from before it: the button waits.
    await vi.waitFor(() =>
      expect(rendered.calls.some((c) => c.path === "/v1/leads/search" && c.body?.includes("Priya"))).toBe(true),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add 7 leads" }));
    const added = await vi.waitFor(() => {
      const call = rendered.calls.find(
        (c) => c.method === "POST" && c.path === `/v1/campaigns/${CAMPAIGN_ID}/contacts/from-leads`,
      );
      expect(call).toBeDefined();
      return call!;
    });
    expect(JSON.parse(added.body ?? "{}")).toEqual({ lens: { search: "Priya" }, expected_count: 7 });
    expect(rendered.container.textContent).not.toContain("Added 0");
  });
});

describe("one campaign's page", () => {
  it("offers Edit and Delete on a draft, and Delete restates what it does before it acts", async () => {
    const rendered = await renderClientPage(campaignPage(), detail(progressFixture()));
    expect((await screen.findByRole("link", { name: "Edit" })).getAttribute("href")).toBe(
      `/c/acme/campaigns/${CAMPAIGN_ID}/edit`,
    );
    // The group draws a phone menu and a desktop one; CSS shows one, jsdom has both.
    fireEvent.click(screen.getAllByRole("button", { name: "More actions for Diwali offer" })[1]);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete draft…" }));
    expect(screen.getByText("Delete this draft?")).toBeTruthy();
    expect(rendered.calls.some((c) => c.method === "DELETE")).toBe(false);
  });

  it("says Not calling, with the reason, for a running campaign the gate refuses", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      detail(
        progressFixture({
          status: "running",
          launched_at: "2026-10-14T04:30:00Z",
          not_calling: [{ rule: "national_dnd_scrub_expired", reason: "The scrub expired." }],
        }),
      ),
    );
    await screen.findByText("Not calling anyone right now");
    expect(container.textContent).not.toContain("Running");
    expect(container.textContent).toContain("national do-not-disturb register");
  });

  it("holds Resume after a complaint spike until the review is confirmed", async () => {
    const rendered = await renderClientPage(
      campaignPage(),
      detail(
        progressFixture({
          status: "paused",
          launched_at: "2026-10-14T04:30:00Z",
          pause_reason: "complaint_spike",
          complaint_review_required: true,
        }),
        {
          [`/v1/campaigns/${CAMPAIGN_ID}/opt-outs`]: [
            {
              call_id: "call-1",
              at: "2026-10-14T05:00:00Z",
              words_redacted: "stop calling me",
              contact_name: "Priya",
            },
          ],
          [`POST /v1/campaigns/${CAMPAIGN_ID}/complaint-review`]: new Response(null, { status: 204 }),
        },
      ),
    );
    await screen.findByText("stop calling me");
    expect((screen.getByRole("button", { name: /Resume/ }) as HTMLButtonElement).disabled).toBe(true);
    const confirm = screen.getByRole("button", { name: "Confirm I've reviewed them" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(confirm);
    await vi.waitFor(() =>
      expect(
        rendered.calls.some((c) => c.method === "POST" && c.path.endsWith("/complaint-review")),
      ).toBe(true),
    );
  });

  it("names an out-of-credit pause and links to adding credit", async () => {
    await renderClientPage(
      campaignPage(),
      detail(
        progressFixture({ status: "paused", launched_at: "2026-10-14T04:30:00Z", pause_reason: "out_of_credit" }),
      ),
    );
    expect((await screen.findAllByText("Paused: out of credit")).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Add credit" }).getAttribute("href")).toBe(
      "/c/acme/billing?tab=credits",
    );
  });

  it("shows each person's outcome with their next try and a link to the call", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      detail(progressFixture({ status: "running", launched_at: "2026-10-14T04:30:00Z", total: 1 }), {
        [contactsPath()]: contactsFixture({
          total: 1,
          counts: { ...contactsFixture().counts, busy: 1 },
          items: [
            {
              id: "cc-1",
              name: "Priya",
              phone_e164: "+919876543210",
              outcome: "busy",
              attempts: 1,
              last_attempt_at: "2026-10-14T05:00:00Z",
              will_retry: true,
              next_attempt_at: "2026-10-14T05:30:00Z",
              call_id: "call-9",
            },
          ],
        }),
        [`/v1/campaigns/${CAMPAIGN_ID}/results`]: resultsFixture({
          contacts: 1,
          tried: 1,
          pickup_rate: 0,
          credits_spent_inr: "12.50",
        }),
      }),
    );
    await screen.findByText("Priya");
    expect(container.textContent).toContain("Next try");
    expect(container.textContent).toContain("1 of 3");
    expect(screen.getByRole("link", { name: "Open call" }).getAttribute("href")).toBe("/c/acme/calls/call-9");
    expect(container.textContent).toContain("₹12.5");
  });

  it("breaks the results down by the agent's outcomes and each choice it asks about", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      detail(progressFixture({ status: "running", launched_at: "2026-10-14T04:30:00Z", total: 3 }), {
        [`/v1/campaigns/${CAMPAIGN_ID}/results`]: resultsFixture({
          contacts: 3,
          tried: 3,
          business_outcomes: [{ key: "onboarded", label: "Onboarded", count: 2 }],
          business_outcomes_unset: 1,
          fields: [
            {
              key: "registered",
              label: "Registered on the app",
              values: [
                { value: "Yes", count: 2 },
                { value: "No", count: 0 },
              ],
              not_captured: 1,
            },
          ],
          leads: 1,
          recent_leads: [{ id: "lead-1", name: "రాము", status: "contacted", updated_at: "2026-10-14T05:00:00Z" }],
        }),
      }),
    );
    await screen.findByText("What people said");
    expect(container.textContent).toContain("Onboarded");
    expect(container.textContent).toContain("None of these");
    expect(container.textContent).toContain("Registered on the app");
    expect(container.textContent).toContain("Not given");
    expect(screen.getByRole("link", { name: "All its leads" }).getAttribute("href")).toBe(
      `/c/acme/leads?campaign_id=${CAMPAIGN_ID}`,
    );
  });

  it("offers Call the unreached again only once the campaign has finished", async () => {
    await renderClientPage(
      campaignPage(),
      detail(progressFixture({ status: "completed", launched_at: "2026-10-14T04:30:00Z" })),
    );
    await screen.findByRole("button", { name: "Call the unreached again" });
    expect(screen.queryByRole("button", { name: /Stop for good/ })).toBeNull();
  });
});

describe("editing a draft", () => {
  it("reads the draft's settings back and sends only the edit the server takes", async () => {
    const rendered = await renderClientPage(
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture({
          name: "Autumn",
          retry_policy: { max_attempts: 2, gaps_minutes: [60] },
        }),
        [`PATCH /v1/campaigns/${CAMPAIGN_ID}`]: new Response(null, { status: 204 }),
      }),
    );
    const name = (await screen.findByRole("textbox", { name: "Name" })) as HTMLInputElement;
    expect(name.value).toBe("Autumn");
    expect(rendered.container.textContent).toContain("2 tries, 1 hour apart");
    fireEvent.change(name, { target: { value: "Autumn recall" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const sent = await vi.waitFor(() => {
      const call = rendered.calls.find((c) => c.method === "PATCH");
      expect(call).toBeDefined();
      return JSON.parse(call!.body ?? "{}");
    });
    expect(sent.name).toBe("Autumn recall");
    expect(sent.retry_policy).toEqual({ max_attempts: 2, gaps_minutes: [60] });
    expect(sent).not.toHaveProperty("consent_provenance");
  });

  it("offers no form for a campaign that has started", async () => {
    await renderClientPage(
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({ [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture({ status: "running" }) }),
    );
    await screen.findByText(/Only a draft can be changed/);
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
  });
});

describe("Pip on the campaign pages", () => {
  it("offers to build the campaign on the create page, prefilled and never sent", async () => {
    const rendered = await renderClientPage(newCampaignPage(), newRoutes());
    const button = await screen.findByRole("button", { name: /^Build a campaign with Pip/ });
    expect(button.textContent).toContain("Build a campaign with Pip");
    expect(rendered.calls.some((c) => c.path.startsWith("/v1/copilot"))).toBe(false);
  });

  it("offers to answer questions about a launched campaign", async () => {
    await renderClientPage(
      campaignPage(),
      detail(progressFixture({ status: "completed", launched_at: "2026-10-14T04:30:00Z" })),
    );
    await screen.findByRole("button", { name: /^Ask Pip about this campaign/ });
  });
});
