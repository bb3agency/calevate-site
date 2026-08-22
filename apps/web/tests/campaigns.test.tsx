import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CampaignsPage from "@/app/c/[slug]/campaigns/page";
import type { Agent } from "@/lib/api/agents";
import type { CampaignProgress, CampaignSummary, LaunchCheck } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import { problem, renderClientPage, stillLoading, type Routes } from "./harness";

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

/** The row the gate has already refused: bought list, recorded, unfixable. */
const REFUSED: CampaignSummary = {
  ...CAMPAIGN,
  id: REFUSED_ID,
  name: "Bought list pilot",
  consent_provenance_blocker: "consent_source_refused",
};

const PROGRESS: CampaignProgress = {
  status: "draft",
  contacts: {},
  total: 0,
  concurrency: 3,
  launched_at: null,
};

const BLOCKED: LaunchCheck = {
  ready: false,
  blockers: [{ rule: "no_contacts", reason: "The campaign has no contacts." }],
};

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

describe("choosing which agent makes the calls (D-440)", () => {
  /**
   * The campaign form binds an agent, and two of the four agent states must be treated
   * differently — a rule the SERVER owns and this screen only previews.
   *
   * `lifecycle.ASSIGNABLE_STATUSES` is every state except `archived`: a draft agent is a
   * legitimate choice while its script is being written, and `launch_blockers` refuses
   * the LAUNCH with `agent_not_live` until it is published. Archived is different in
   * kind — there is no state of the world in which that campaign becomes launchable — so
   * binding one is a dead end the client cannot diagnose.
   */

  /** The same agent, in another state. `AGENT` above is live, published and outbound. */
  function agentIn(over: Partial<Agent>): Agent {
    return { ...AGENT, ...over };
  }

  it("never offers an archived agent, because no campaign bound to one can ever launch", async () => {
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([], {
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

    await screen.findByText("New campaign");
    const picker = container.querySelector<HTMLSelectElement>("select");
    expect(picker, "the create form has no agent picker").not.toBeNull();
    const options = Array.from(picker!.options).map((option) => option.textContent);
    expect(options.join(" | ")).toContain("Follow-ups");
    expect(options.join(" | ")).not.toContain("Retired dialler");
  });

  it("asks which agent even when there is only one, and names the one it will bind", async () => {
    // It used to ask only when there was more than one, which silently bound `agents[0]`
    // — a campaign whose caller nobody chose. With an agents console that can mint a
    // second agent in a minute, "there is only one" stopped being a safe assumption the
    // moment the form rendered.
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([], { "/v1/agents": [agentIn({ name: "Follow-ups" })] }),
    );

    await screen.findByText("Which agent makes these calls");
    const picker = container.querySelector<HTMLSelectElement>("select");
    expect(Array.from(picker!.options).map((option) => option.textContent)).toEqual([
      "Follow-ups",
    ]);
  });

  it("marks an agent that cannot dial yet, rather than letting launch be the first news", async () => {
    // A draft agent IS assignable and is NOT launchable. Saying so at the point of
    // choosing turns an `agent_not_live` refusal nobody expected into a wait somebody
    // planned for.
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([], {
        "/v1/agents": [
          agentIn({ id: "a-draft", name: "Half built", status: "draft", published: false }),
        ],
      }),
    );

    await screen.findByText("Which agent makes these calls");
    const picker = container.querySelector<HTMLSelectElement>("select");
    expect(picker!.options[0].textContent).toContain("not able to call out yet");
    expect(container.textContent).toContain("it will not launch until the agent is switched on");
  });

  it("offers no picker at all while the agent list is still in flight", async () => {
    // §52 on a control: a `<select>` built from an empty list is a campaign form that
    // looks answerable and binds nothing.
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([], { "/v1/agents": stillLoading() }),
    );

    expect(container.textContent).toContain("New campaign");
    expect(container.textContent).not.toContain("Which agent makes these calls");
  });
});

describe("the three reads the create form is built from", () => {
  /**
   * §52, on the screen where a client decides whether their campaigns can run.
   *
   * `campaigns`, `progress`, `check` and `create` all surfaced their refusals from the
   * start. The three lists BEHIND the create form did not, and each failure then
   * degraded into something the screen stated as a fact about this business:
   *
   *  - `/v1/agents` failing left `agentOptions` empty, which is the exact shape of
   *    "this account has no agent" — and the sentence gated on it sends an owner to
   *    their account manager to have one built. They have one. The request failed.
   *  - `/v1/campaigns/numbers` and `/v1/campaigns/templates` failing left two pickers
   *    holding only their placeholder, with no refusal anywhere on the page: a dead
   *    form and no explanation.
   *
   * The fix is the spelling `/c/<slug>/knowledge` already uses — `Boolean(agents.data)`
   * for the empty state, `ProblemNotice` for the failure — rather than a fourth one.
   */

  /** A 503 in the shape `apiRequest` turns into a retryable `ApiProblem`. */
  const OUTAGE = problem(503, {
    type: "urn:calevate:internal/upstream_unavailable",
    kind: "internal",
    title: "Upstream unavailable",
    detail: "We could not read that just now.",
    retryable: true,
  });

  /** The claim that must never be made on the strength of a request that failed. */
  const NO_AGENT_CLAIM = "No agent is set up yet";

  it("does not tell a client they have no agent when /v1/agents failed", async () => {
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([], { "/v1/agents": OUTAGE }),
    );

    // The refusal is on screen, once, with the server's own sentence.
    await screen.findByRole("alert");
    expect(container.textContent).toContain("We could not read that just now.");
    // …and the empty-state claim is NOT, because nothing answered the question it
    // purports to answer. `!agents.isLoading` was true here — a settled-and-failed
    // query is not loading — which is exactly why the old gate let this through.
    expect(container.textContent).not.toContain(NO_AGENT_CLAIM);
  });

  it("still makes that claim when the server actually answered with no agents", async () => {
    // The other direction, so the fix cannot be "delete the sentence": a client with a
    // genuinely empty agent list needs to know why the form will not submit.
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([], { "/v1/agents": [] }),
    );

    await screen.findByText("New campaign");
    expect(container.textContent).toContain(NO_AGENT_CLAIM);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("makes no claim while /v1/agents is still in flight", async () => {
    // The third state §52 names, and the one an empty list is most convincing in.
    //
    // IN FLIGHT IS HELD, NOT RACED. This used to assert immediately after the render and
    // trust that the stubbed fetch had not resolved yet — which is not a property of the
    // code under test, it is a property of how fast the box is. It held locally and lost
    // in CI, where the sentence had already appeared by the assertion. `stillLoading()`
    // hands back a promise that never settles, so the in-flight frame is a state the test
    // OWNS rather than a window it hopes to hit. No amount of waiting could have fixed
    // this one: the failure is the query resolving too EARLY.
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([], { "/v1/agents": stillLoading() }),
    );

    // A premise check: the form really is on screen, so the absence below is the gate
    // holding and not simply an unrendered card.
    expect(container.textContent).toContain("New campaign");
    expect(container.textContent).not.toContain(NO_AGENT_CLAIM);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("makes the claim once the empty list actually lands", async () => {
    // The other half of the test above, which used to be its last two lines: with the
    // in-flight frame now held open forever, the "and then it appears" half needs its own
    // render — otherwise the guard could be suppressing the sentence for good and this
    // suite would not notice.
    await renderClientPage(<CampaignsPage />, landingRoutes([], { "/v1/agents": [] }));

    await screen.findByText(new RegExp(NO_AGENT_CLAIM));
  });

  it("says so when the number and template lists could not be read", async () => {
    /**
     * Two `<select>`s that can never be filled, and — before this — nothing on the page
     * admitting it. A client reading "Choose a number…" over an empty list concludes
     * their account has no numbers, which on this screen is a conclusion about whether
     * they can dial at all.
     */
    const { container } = await renderClientPage(
      <CampaignsPage />,
      landingRoutes([], { "/v1/campaigns/numbers": OUTAGE, "/v1/campaigns/templates": OUTAGE }),
    );

    await screen.findByText("New campaign");
    // One refusal per failed read: two failures, two notices.
    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(2);
    // And neither failure is dressed as an empty list — those hints are the answer to
    // "the server said you have none", which the server did not say.
    expect(container.textContent).not.toContain("No numbers yet");
    expect(container.textContent).not.toContain("None registered yet");
  });

  it("keeps the empty-list hints for lists the server really answered as empty", async () => {
    const { container } = await renderClientPage(<CampaignsPage />, landingRoutes([]));

    await screen.findByText("New campaign");
    expect(container.textContent).toContain("No numbers yet");
    expect(container.textContent).toContain("None registered yet");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
