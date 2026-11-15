import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EditCampaignPage from "@/app/c/[slug]/campaigns/[campaignId]/edit/page";
import { nameFromMainTask } from "@/app/c/[slug]/campaigns/NewCampaignScreen";
import { nameFromGoal } from "@/app/c/[slug]/campaigns/campaignForm";
import type { Agent } from "@/lib/api/agents";
import type { CallOutcomes } from "@/lib/api/callOutcomes";
import type { LaunchCheck } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import {
  FIXTURE_AGENT_ID as AGENT_ID,
  FIXTURE_CAMPAIGN_ID as CAMPAIGN_ID,
  campaignPage,
  contactsFixture,
  contactsPath,
  detailRoutes,
  dltRegistrationRoute,
  leadPickerRoutes,
  newCampaignPage,
  openTab,
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
  caller_has_screen: false,
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

const BLOCKED: LaunchCheck = {
  ready: false,
  blockers: [{ rule: "no_contacts", reason: "The campaign has no contacts." }],
};

/** The account's own lines: two calls at once, the paid default. */
const CALL_LINES = { call_lines: 2, in_progress: 0, on_trial: false };

/** The reads the create page is built from. */
function newRoutes(extra: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    "/v1/call-outcomes": OUTCOMES,
    "/v1/call-lines": CALL_LINES,
    ...dltRegistrationRoute(),
    ...extra,
  };
}

/** The agent's own outcomes: the two that move a lead up are offered as goals. */
const OUTCOMES: CallOutcomes = {
  max_outcomes: 8,
  agents: [
    {
      id: AGENT_ID,
      name: "Outbound follow-up",
      direction: "outbound",
      status: "live",
      starting: false,
      draft: "done",
      outcomes: [
        { key: "booked_visit", label: "Booked a visit", meaning: "", lead_status: "hot" },
        { key: "wants_price", label: "Wants the price list", meaning: "", lead_status: "interested" },
        { key: "not_now", label: "Not now", meaning: "", lead_status: "contacted" },
      ],
    },
  ],
};

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

/** The create page is four steps; Next names the step it goes to, and checks the one it leaves. */
function next(): void {
  fireEvent.click(screen.getByRole("button", { name: /^Next: / }));
}

const PURPOSE_FIELD = "Why are you calling them?";
/** The first step's question: what the calls are for comes before anything else. */
const BASICS = "What are these calls for?";

/** Opens the settings that already have an answer, e.g. "How the calls go out". */
function change(title: string): void {
  fireEvent.click(screen.getByRole("button", { name: `Change ${title.toLowerCase()}` }));
}
const GOAL_FIELD = "What should a good call end with?";

/** The basics step's three typed answers: the name, why it calls and the goal. */
function fillBasics(name: string, purpose = "Our Diwali service offer", goal = "They book a visit"): void {
  fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: name } });
  fireEvent.change(screen.getByRole("textbox", { name: PURPOSE_FIELD }), { target: { value: purpose } });
  fireEvent.change(screen.getByRole("textbox", { name: GOAL_FIELD }), { target: { value: goal } });
}

const MAIN_TASK = "Call customers about our Diwali offer on service plans and book a visit.";

/** The create page's first section: the main task, in the owner's words. */
async function writeMainTask(text: string): Promise<void> {
  const box = await screen.findByRole("textbox", { name: "Main task" });
  fireEvent.change(box, { target: { value: text } });
}

/** Writes a note in Materials and adds it to the list the draft will carry. */
function addNote(text: string): void {
  fireEvent.click(screen.getByRole("button", { name: "Write a note" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Note" }), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
}

describe("the create page's consent declaration", () => {
  it("opens unanswered and will not create a campaign without it", async () => {
    // Where the list came from is an audited statement. A pre-selected answer would be an
    // assertion nobody made, so the page opens empty and refuses to create without one.
    const { container } = await renderClientPage(newCampaignPage(), newRoutes());
    await screen.findByRole("heading", { name: BASICS });
    fillBasics("List");
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
    await screen.findByRole("heading", { name: BASICS });
    change("How the calls go out");
    expect(screen.getByRole("radio", { name: /Service/ })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /Promotional/ })).toBeNull();
    expect(screen.queryByRole("radio", { name: /Transactional/ })).toBeNull();
  });

  it("offers Promotional once the telemarketer registration is live", async () => {
    await renderClientPage(newCampaignPage(), newRoutes(dltRegistrationRoute(true)));
    await screen.findByRole("heading", { name: BASICS });
    change("How the calls go out");
    expect(await screen.findByRole("radio", { name: /Promotional/ })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Service/ })).toBeTruthy();
  });
});

describe("the consent declaration on a draft", () => {
  it("opens unanswered and records nothing until both questions are answered", async () => {
    // Where the list came from is an audited statement, asked on the draft before it can
    // launch. A pre-selected answer would be an assertion nobody made.
    const rendered = await renderClientPage(
      campaignPage(),
      detail(progressFixture(), {
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: {
          ready: false,
          blockers: [{ rule: "consent_provenance_missing", reason: "Say where the list came from." }],
        },
      }),
    );
    const radios = await vi.waitFor(() => {
      const found = Array.from(
        rendered.container.querySelectorAll<HTMLInputElement>(`input[name="answer-${CAMPAIGN_ID}-consent-source"]`),
      );
      expect(found).toHaveLength(5);
      return found;
    });
    expect(radios.some((r) => r.checked)).toBe(false);
    expect(screen.getByRole("button", { name: CONSENT_DATE }).textContent).toContain("Choose a date");
    fireEvent.click(screen.getByRole("button", { name: "Record this" }));
    expect(await screen.findByText("Choose where the list came from.")).toBeTruthy();
    expect(screen.getByText("Choose the day they agreed.")).toBeTruthy();
    expect(rendered.calls.filter((c) => c.method !== "GET")).toEqual([]);
    expect(screen.getByRole("button", { name: "Launch campaign" }).hasAttribute("disabled")).toBe(true);
  });
});

describe("the kind of call on Edit", () => {
  it("offers Service only while Calevate's telemarketer registration is not live, and never Transactional", async () => {
    await renderClientPage(
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({ [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture({ classification: "service" }) }),
    );
    expect(await screen.findByRole("radio", { name: /Service/ })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /Promotional/ })).toBeNull();
    expect(screen.queryByRole("radio", { name: /Transactional/ })).toBeNull();
  });

  it("offers Promotional once the telemarketer registration is live", async () => {
    await renderClientPage(
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture({ classification: "service" }),
        ...dltRegistrationRoute(true),
      }),
    );
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
    const agents = await screen.findByRole("group", { name: "Which agent makes these calls" });
    const options = within(agents)
      .getAllByRole("radio")
      .map((radio) => radio.closest("label")?.textContent ?? "")
      .join(" | ");
    expect(options).toContain("Follow-ups");
    expect(options).not.toContain("Retired dialler");
    expect(container.textContent).not.toContain("Retired dialler");
  });

  it("marks an agent that cannot dial yet", async () => {
    const { container } = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "/v1/agents": [agentIn({ id: "a-draft", name: "Half built", status: "draft", published: false })],
      }),
    );
    const agents = await screen.findByRole("group", { name: "Which agent makes these calls" });
    expect(within(agents).getByRole("radio", { name: /Half built/ }).closest("label")?.textContent).toContain(
      "Not calling yet",
    );
    // Said kindly, with the way to fix it: the campaign can still be built.
    expect(container.textContent).toContain("Build it now.");
    expect(screen.getByRole("link", { name: "Open Half built" })).toBeTruthy();
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
  it("offers every number of the account that can make calls on Edit, whichever agent answers it", async () => {
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
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture(),
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
    const picker = (await screen.findByRole("combobox", { name: /^Calling from/ })) as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.value)).toEqual(["", "n-ok", "n-other"]);
    expect(container.textContent).toContain("Any of your numbers. Every agent can call from them.");
  });
});

describe("creating a campaign", () => {
  it("creates the draft from the main task, attaches its materials, then asks Pip for the script", async () => {
    const rendered = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "POST /v1/campaigns": { id: CAMPAIGN_ID, status: "draft" },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/materials`]: { id: "m-1" },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/script/proposal`]: { id: "p-1", status: "drafting" },
      }),
    );
    await writeMainTask(MAIN_TASK);
    addNote("Open Monday to Saturday, 9am to 7pm.");
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    const asked = await vi.waitFor(() => {
      const call = rendered.calls.find(
        (c) => c.method === "POST" && c.path === `/v1/campaigns/${CAMPAIGN_ID}/script/proposal`,
      );
      expect(call).toBeDefined();
      return call!;
    });
    const created = JSON.parse(rendered.calls.find((c) => c.method === "POST" && c.path === "/v1/campaigns")!.body ?? "{}");
    expect(created).toMatchObject({ agent_id: AGENT_ID, main_task: MAIN_TASK, name: nameFromMainTask(MAIN_TASK) });
    const material = rendered.calls.find(
      (c) => c.method === "POST" && c.path === `/v1/campaigns/${CAMPAIGN_ID}/materials`,
    );
    expect(JSON.parse(material?.body ?? "{}")).toMatchObject({ kind: "note", note: "Open Monday to Saturday, 9am to 7pm." });
    // In that order: the materials are on the campaign before Pip reads it.
    expect(rendered.calls.indexOf(material!)).toBeLessThan(rendered.calls.indexOf(asked));
  });

  it("says the draft exists and links to it when a material is refused", async () => {
    await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "POST /v1/campaigns": { id: CAMPAIGN_ID, status: "draft" },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/materials`]: problem(503, {
          title: "Upstream unavailable",
          detail: "We could not save that note just now.",
          retryable: true,
        }),
      }),
    );
    await writeMainTask(MAIN_TASK);
    addNote("Open Monday to Saturday.");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("We could not save that note just now.");
    expect(screen.getByRole("link", { name: "Open the draft" }).getAttribute("href")).toBe(
      `/c/acme/campaigns/${CAMPAIGN_ID}`,
    );
  });

  it("does not create a second draft when Save is pressed again after a follow-up failed", async () => {
    const rendered = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "POST /v1/campaigns": { id: CAMPAIGN_ID, status: "draft" },
        [`POST /v1/campaigns/${CAMPAIGN_ID}/materials`]: problem(503, {
          title: "Upstream unavailable",
          detail: "We could not save that note just now.",
          retryable: true,
        }),
      }),
    );
    await writeMainTask(MAIN_TASK);
    addNote("Open Monday to Saturday.");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("We could not save that note just now.");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() =>
      expect(
        rendered.calls.filter((c) => c.method === "POST" && c.path === `/v1/campaigns/${CAMPAIGN_ID}/materials`),
      ).toHaveLength(2),
    );
    expect(rendered.calls.filter((c) => c.method === "POST" && c.path === "/v1/campaigns")).toHaveLength(1);
  });

  it("shows the server's refusal when the draft itself is refused, and links to nothing", async () => {
    await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "POST /v1/campaigns": problem(409, {
          title: "Campaigns are locked",
          detail: "Campaigns open once your account is verified.",
          retryable: false,
        }),
      }),
    );
    await writeMainTask(MAIN_TASK);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Campaigns open once your account is verified.");
    expect(screen.queryByRole("link", { name: "Open the draft" })).toBeNull();
  });

});

describe("calls at once on the create page", () => {
  it("asks for no more calls at once than the account's lines", async () => {
    const rendered = await renderClientPage(
      newCampaignPage(),
      newRoutes({
        "POST /v1/campaigns": { id: CAMPAIGN_ID, status: "draft" },
      }),
    );
    await writeMainTask(MAIN_TASK);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const created = await vi.waitFor(() => {
      const call = rendered.calls.find((c) => c.method === "POST" && c.path === "/v1/campaigns");
      expect(call).toBeDefined();
      return JSON.parse(call!.body ?? "{}");
    });
    expect(created.concurrency).toBe(2);
  });

  it("offers the campaign's own bound on Edit and says so when the account's lines could not be read", async () => {
    await renderClientPage(
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture(),
        "/v1/call-lines": problem(503, { title: "Unavailable", retryable: true }),
      }),
    );
    expect(await screen.findByText("We couldn't check your account's limit. It still applies.")).toBeTruthy();
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
    // The launch checklist's "Add people" (first) opens the same panel as the section's own.
    fireEvent.click((await screen.findAllByRole("button", { name: "Add people" }))[0]);
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

  it("says an operator-archived campaign calls nobody, why, and offers only Restore and a copy (F-10)", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      detail(
        progressFixture({
          status: "paused",
          launched_at: "2026-10-14T04:30:00Z",
          archived_at: "2026-11-05T10:00:00Z",
          archived_by_realm: "admin",
          archive_reason: "Several people asked not to be called",
        }),
      ),
    );
    await screen.findByText("Archived. It calls nobody.");
    expect(container.textContent).toContain("Why: Several people asked not to be called");
    expect(screen.getAllByRole("button", { name: /Restore/ }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /^Resume/ })).toBeNull();
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
    expect(container.textContent).toContain("national do-not-disturb check");
  });

  it("gives a running campaign stopped by an offer in its agent's script a way to that agent", async () => {
    await renderClientPage(
      campaignPage(),
      detail(
        progressFixture({
          status: "running",
          launched_at: "2026-10-14T04:30:00Z",
          not_calling: [{ rule: "script_promotional", reason: "The script is promotional." }],
        }),
      ),
    );
    await screen.findByText("Not calling anyone right now");
    expect(screen.getByRole("link", { name: "Open the agent" }).getAttribute("href")).toBe(
      `/c/acme/agents/${AGENT_ID}`,
    );
  });

  it("gives a draft refused for the truthful-answer rule a way to the agent that lost it", async () => {
    await renderClientPage(
      campaignPage(),
      detail(progressFixture({ status: "draft" }), {
        [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: {
          ready: false,
          blockers: [
            { rule: "truthful_answer_drift", reason: "This agent is no longer carrying the rule. Publish it again." },
          ],
        },
      }),
    );
    await screen.findByText(/no longer carrying the rule/);
    expect(screen.getByRole("link", { name: "Open the agent" }).getAttribute("href")).toBe(
      `/c/acme/agents/${AGENT_ID}`,
    );
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
    expect(container.textContent).toContain("Try 1 of 3");
    expect(screen.getByRole("link", { name: "Open the call with Priya" }).getAttribute("href")).toBe(
      "/c/acme/calls/call-9",
    );
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
    await openTab("What happened");
    await screen.findByText("What people said");
    // How the counts are made sits behind the heading's info button, not on the page.
    expect(screen.getByRole("button", { name: "About What people said" })).toBeTruthy();
    expect(container.textContent).toContain("How it ended, per person");
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

  it("holds a draft that asked for more calls at once than the account's lines to those lines", async () => {
    const rendered = await renderClientPage(
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture({ concurrency: 5 }),
        [`PATCH /v1/campaigns/${CAMPAIGN_ID}`]: new Response(null, { status: 204 }),
      }),
    );
    const pace = await screen.findByRole("radiogroup", { name: "Calls at the same time" });
    expect(within(pace).getByRole("radio", { name: "2" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const sent = await vi.waitFor(() => {
      const call = rendered.calls.find((c) => c.method === "PATCH");
      expect(call).toBeDefined();
      return JSON.parse(call!.body ?? "{}");
    });
    expect(sent.concurrency).toBe(2);
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
  it("offers Pip to write the script on the create page, and sends nothing until asked", async () => {
    const rendered = await renderClientPage(newCampaignPage(), newRoutes());
    await screen.findByRole("heading", { name: "Let Pip, our AI agent, generate the script" });
    // Nothing to write from yet: the button waits for the main task.
    expect((screen.getByRole("button", { name: "Generate" }) as HTMLButtonElement).disabled).toBe(true);
    expect(rendered.calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("offers to answer questions about a launched campaign", async () => {
    await renderClientPage(
      campaignPage(),
      detail(progressFixture({ status: "completed", launched_at: "2026-10-14T04:30:00Z" })),
    );
    await screen.findByRole("button", { name: /^Ask Pip about this campaign/ });
  });
});

describe("nameFromGoal", () => {
  it("names the goal and the IST day, and gives nothing for a blank goal", () => {
    // 19:00 UTC on 4 Nov is already 5 Nov in India.
    expect(nameFromGoal("  Booked   a visit ", new Date("2026-11-04T19:00:00Z"))).toBe("Booked a visit, 5 Nov");
    expect(nameFromGoal("   ")).toBe("");
  });
});

describe("what a campaign is for", () => {
  it("offers the agent's own outcomes that move a lead up as goals on Edit, and sends the one picked", async () => {
    const rendered = await renderClientPage(
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture(),
        [`PATCH /v1/campaigns/${CAMPAIGN_ID}`]: new Response(null, { status: 204 }),
      }),
    );
    const suggestions = await screen.findByRole("group", { name: "Goal suggestions" });
    expect(within(suggestions).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Booked a visit",
      "Wants the price list",
    ]);
    fireEvent.click(within(suggestions).getByRole("button", { name: "Booked a visit" }));
    expect((screen.getByRole("textbox", { name: GOAL_FIELD }) as HTMLInputElement).value).toBe("Booked a visit");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const sent = await vi.waitFor(() => {
      const call = rendered.calls.find((c) => c.method === "PATCH");
      expect(call).toBeDefined();
      return JSON.parse(call!.body ?? "{}");
    });
    expect(sent.goal).toBe("Booked a visit");
  });

  it("reads them back on Edit and sends the changed goal", async () => {
    const rendered = await renderClientPage(
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture(),
        [`PATCH /v1/campaigns/${CAMPAIGN_ID}`]: new Response(null, { status: 204 }),
      }),
    );
    const goal = (await screen.findByRole("textbox", { name: GOAL_FIELD })) as HTMLInputElement;
    expect(goal.value).toBe("They book a service visit");
    expect((screen.getByRole("textbox", { name: PURPOSE_FIELD }) as HTMLInputElement).value).toBe(
      "Our Diwali offer on service plans",
    );
    fireEvent.change(goal, { target: { value: "They renew the plan" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const sent = await vi.waitFor(() => {
      const call = rendered.calls.find((c) => c.method === "PATCH");
      expect(call).toBeDefined();
      return JSON.parse(call!.body ?? "{}");
    });
    expect(sent.goal).toBe("They renew the plan");
    expect(sent.purpose).toBe("Our Diwali offer on service plans");
  });

  it("keeps the draft's saved name when its goal is read back on Edit", async () => {
    // The edit page sets the saved name and then the saved goal in one pass; the name must
    // not be replaced by one made from the goal.
    await renderClientPage(
      <EditCampaignPage params={Promise.resolve({ slug: "acme", campaignId: CAMPAIGN_ID })} />,
      newRoutes({ [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture() }),
    );
    const name = (await screen.findByRole("textbox", { name: "Name" })) as HTMLInputElement;
    expect(name.value).toBe("Diwali offer");
    fireEvent.change(screen.getByRole("textbox", { name: GOAL_FIELD }), { target: { value: "They renew" } });
    expect(name.value).toBe("Diwali offer");
  });

  it("names a new campaign from its main task's first line and the IST day", () => {
    const day = new Date("2026-11-04T19:00:00Z");
    expect(nameFromMainTask("  Call farmers   who registered \nand never opened the app")).toBe(
      nameFromGoal("Call farmers who registered"),
    );
    expect(nameFromGoal("Call farmers", day)).toBe("Call farmers, 5 Nov");
    const long = "Call every farmer who registered on the app last season and help them install it";
    expect(nameFromMainTask(long)).toBe(nameFromGoal("Call every farmer who registered on the app last season and…"));
  });

  it("shows the goal on the campaign, how many reached it, and each person's verdict", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      detail(progressFixture({ status: "running", launched_at: "2026-10-14T04:30:00Z", total: 1 }), {
        [contactsPath()]: contactsFixture({
          total: 1,
          counts: { ...contactsFixture().counts, connected: 1 },
          items: [
            {
              id: "cc-1",
              name: "Priya",
              phone_e164: "+919876543210",
              outcome: "connected",
              attempts: 1,
              last_attempt_at: "2026-10-14T05:00:00Z",
              will_retry: false,
              next_attempt_at: null,
              call_id: "call-9",
              goal_reached: "yes",
              goal_reason: "They booked a visit for Saturday before the call ended.",
            },
          ],
        }),
        [`/v1/campaigns/${CAMPAIGN_ID}/results`]: resultsFixture({
          contacts: 1,
          tried: 1,
          people_answered: 4,
          goal: { reached: 3, not_reached: 0, unclear: 1, not_judged: 0 },
        }),
      }),
    );
    await screen.findByText("Priya");
    expect(container.textContent).toContain("They book a service visit");
    expect(container.textContent).toContain("Goal reached");
    // The why sits under the verdict, so "Goal unclear" on a row says what was missing.
    expect(container.textContent).toContain("They booked a visit for Saturday before the call ended.");
    expect(container.textContent).toContain("3 of 4");
    expect(container.textContent).toContain("1 unclear");
  });
});

describe("deleting a draft", () => {
  it("does not re-read the deleted campaign, so its page never flashes a not-found before it moves on", async () => {
    const PROGRESS = `/v1/campaigns/${CAMPAIGN_ID}`;
    const rendered = await renderClientPage(
      campaignPage(),
      detail(progressFixture(), { [`DELETE ${PROGRESS}`]: { outcome: "deleted" } }),
    );
    fireEvent.click((await screen.findAllByRole("button", { name: "More actions for Diwali offer" }))[1]);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete draft…" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete draft" }));

    await vi.waitFor(() => expect(rendered.calls.some((c) => c.method === "DELETE")).toBe(true));
    const deletedAt = rendered.calls.findIndex((c) => c.method === "DELETE");
    // Give any re-read the invalidation would start time to go out.
    await new Promise((resolve) => setTimeout(resolve, 50));
    const rereads = rendered.calls
      .slice(deletedAt + 1)
      .filter((c) => c.method === "GET" && c.path.startsWith(PROGRESS));
    expect(rereads.map((c) => c.path)).toEqual([]);
  });
});
