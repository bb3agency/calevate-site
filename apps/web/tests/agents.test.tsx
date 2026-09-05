import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentsPage from "@/app/c/[slug]/agents/page";
import { ARCHIVED_QUERY, type Agent, type AgentStats } from "@/lib/api/agents";
import type { Lanes } from "@/lib/api/publishing";

import { problem, renderClientPage } from "./harness";

/**
 * The agents ROSTER — the screen that answers "which of my agents is working right now".
 *
 * Everything about ONE agent moved to `/c/<slug>/agents/<id>` and is tested in
 * `agentDetail.test.tsx`; what is left here is the question this screen exists for, and
 * the four ways it can answer it wrongly:
 *
 * 1. **An agent in the wrong bucket.** "Working right now" is `published AND status ===
 *    'live'`, the same two facts the server's `_is_live` checks in the same order. An
 *    agent switched on but never built has never taken a call, and putting it under a
 *    heading that says it is working is the one thing a client would act on.
 * 2. **A confident roster over a request that never landed.** "You have no agents" is a
 *    statement about the client's account; a 503 is a statement about us.
 * 3. **A silent archive.** `GET /v1/agents` deliberately EXCLUDES retired agents, so the
 *    archive is a second request — and a failed second request must not read as "you have
 *    never retired an agent".
 * 4. **A number this build invented.** The call counts come from a third request; a row
 *    that has not got them yet says nothing rather than "0 calls handled".
 */

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  // The full client-owner set (core/rbac.py). `agents:write` is NOT in it and cannot be:
  // it is admin-realm only. `org:manage` is what the D-440 lifecycle routes require, and
  // it is the permission every control in this section is gated on.
  permissions: [
    "agents:read",
    "calls:read",
    "calls:read_raw",
    "leads:read",
    "leads:write",
    "leads:dispatch",
    "billing:read",
    "org:read",
    "org:manage",
    "kb:write",
  ],
  impersonating: false,
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: "agent-1",
    name: "Reception",
    direction: "inbound",
    status: "live",
    archived_at: null,
    language_primary: "te-IN",
    disclosure_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_enabled: true,
    recording_notice_line: "This call is being recorded.",
    caller_memory_notice_line: "I keep a short note of what you ask about.",
    caller_memory_enabled: false,
    recording_notice_enabled: true,
    opening_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
    truthful_answer_rule:
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    engine: "bolna",
    published: true,
    inbound_number_count: 1,
    extraction_fields: [],
    // D-454: inheriting all the way up — what this fixture always meant
    // implicitly, back when an agent had no opinion about its model.
    llm_model: null,
    llm_model_effective: "gpt-4o-mini",
    llm_model_source: "platform",
    ...over,
  };
}

function stats(over: Partial<AgentStats> = {}): AgentStats {
  return {
    agent_id: "agent-1",
    status: "live",
    calls_total: 0,
    calls_inbound: 0,
    calls_outbound: 0,
    calls_connected: 0,
    outcomes: {},
    last_call_at: null,
    ...over,
  };
}

const LANES: Lanes = {
  precedence_rule:
    "Script decides content, rules decide conduct, voice only changes delivery.",
  lanes: [
    {
      field: "script",
      lane: "staged",
      precedence: 1,
      why: "The script decides what the agent says. It waits for Apply.",
    },
    {
      field: "voice",
      lane: "live",
      precedence: 3,
      why: "A voice only changes delivery.",
    },
  ],
  call_cap_default_s: 600,
  call_cap_min_s: 60,
  call_cap_max_s: 3600,
};

const page = <AgentsPage params={Promise.resolve({ slug: "acme" })} />;

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/agents": [agent()],
    [ARCHIVED_QUERY]: [],
    "/v1/agents/stats": [stats()],
    "/v1/agents/lanes": LANES,
    ...over,
  };
}

/**
 * A control that is ready to be pressed.
 *
 * The permission read (`useWriteAccess`) resolves a moment after first paint, so a button
 * gated on it is momentarily DISABLED — and `fireEvent.click` on a disabled button is a
 * no-op that fails later, in an assertion about a request that never went out. Waiting for
 * the enabled state is the difference between a test that pins behaviour and one that
 * pins timing.
 */
async function pressable(
  scope: HTMLElement,
  name: RegExp | string,
): Promise<HTMLElement> {
  const button = within(scope).getByRole("button", { name });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  return button;
}

/** The rows under one section heading, so a claim is read off the section it is about. */
function section(title: string): HTMLElement {
  // The heading's card — `Card` renders `<h2>` inside a `<section>`, which is the element
  // that owns the rows. Scoped rather than global, because "Working right now" and "Not
  // working" both contain agent names and a bare `getByText` cannot say which one it read.
  const heading = screen.getByRole("heading", { name: title });
  const card = heading.closest("section");
  expect(card, `no <section> around "${title}"`).not.toBeNull();
  return card as HTMLElement;
}

describe("which agents are working right now", () => {
  it("puts a live, published agent under 'Working right now' and nothing else there", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents": [
          agent({ id: "a-live", name: "Front desk" }),
          agent({ id: "a-paused", name: "Weekend line", status: "paused" }),
        ],
        "/v1/agents/stats": [],
      }),
    );

    await screen.findByText("Front desk");
    const working = section("Working right now");
    expect(within(working).getByText("Front desk")).toBeTruthy();
    expect(within(working).queryByText("Weekend line")).toBeNull();
    expect(
      within(section("Not working")).getByText("Weekend line"),
    ).toBeTruthy();
  });

  it("does not call an agent live when it is not on the calling system, whatever its status says", async () => {
    // The two facts have to LINE UP, in the server's order: `published` first, because an
    // agent that does not exist at the voice platform cannot ring whatever its status
    // column says. This is the one bucket a client acts on.
    await renderClientPage(
      page,
      routes({
        "/v1/agents": [
          agent({
            id: "a-1",
            name: "Half built",
            status: "live",
            published: false,
          }),
        ],
        "/v1/agents/stats": [],
      }),
    );

    await screen.findByText("Half built");
    expect(
      within(section("Working right now")).queryByText("Half built"),
    ).toBeNull();
    const idle = section("Not working");
    expect(within(idle).getByText("Half built")).toBeTruthy();
    expect(within(idle).getByText("Being set up")).toBeTruthy();
  });

  it("says how many lines each answering agent picks up in parallel", async () => {
    // The honest per-agent deployment fact and the only one: inbound is a per-number
    // binding at the engine, so an agent bound to three numbers takes three calls at once.
    // Outbound concurrency is an account-level pool, so an outbound-only agent gets no
    // such line rather than a number that could not be true.
    await renderClientPage(
      page,
      routes({
        "/v1/agents": [
          agent({ id: "a-in", name: "Front desk", inbound_number_count: 3 }),
          agent({
            id: "a-out",
            name: "Follow-ups",
            direction: "outbound",
            inbound_number_count: 0,
          }),
        ],
        "/v1/agents/stats": [],
      }),
    );

    await screen.findByText("Front desk");
    const working = section("Working right now");
    expect(within(working).getByText(/Answers 3 numbers/)).toBeTruthy();
    expect(within(working).queryByText(/Answers 0 numbers/)).toBeNull();
  });
});

describe("what the screen says when it could not read the agents", () => {
  it("renders the refusal and claims nothing about the account", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents": problem(503, {
          title: "Service unavailable",
          detail: "We could not read your agents.",
        }),
      }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // "You have no agents" is a claim about the client's account, and a failed read is not
    // evidence for it. Nor may the section headings render — an empty "Working right now"
    // says nothing is answering the phone.
    expect(container.textContent).not.toContain("No agents yet");
    expect(container.textContent).not.toContain("Working right now");
    expect(container.textContent).not.toContain("How changes take effect");
  });

  it("does say the account has no agents when the server said exactly that", async () => {
    // The positive control for the assertion above: a negative assertion is only worth
    // what its positive twin proves is reachable. This is also the first-run screen, so it
    // must offer the way forward rather than only stating the absence.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents": [] }),
    );

    await screen.findByText("No agents yet");
    expect(
      screen.getByRole("link", { name: /Build your first agent/ }),
    ).toBeTruthy();
    // The lane table hangs off the roster: explaining how changes reach agents that do not
    // exist yet is noise, and one more request for nothing.
    expect(container.textContent).not.toContain("How changes take effect");
  });
});

/**
 * DELETING AN AGENT FROM THE ROSTER (D-527).
 *
 * The founder asked for a delete on every agent, working or not, and for a working one to
 * be undeletable until it is switched off. Both halves are load-bearing and they fail in
 * opposite directions: a Delete missing from a row sends an owner hunting through screens
 * for it, and a Delete that fires on a live agent takes a business's phone line down in
 * one click. The server refuses that second one by itself (`agent_is_live`); what these
 * pin is that nobody meets that refusal by surprise, and that the way out is offered.
 */
describe("deleting an agent from the roster", () => {
  const ROSTER = {
    "/v1/agents": [
      agent({ id: "a-live", name: "Front desk" }),
      agent({ id: "a-off", name: "Weekend line", status: "paused" }),
    ],
    "/v1/agents/stats": [],
  };

  it("offers a delete on every agent, working or not, named for the one it deletes", async () => {
    await renderClientPage(page, routes(ROSTER));
    await screen.findByText("Front desk");

    // NAMED, because six rows each offering a control called only "Delete" is a list a
    // screen-reader user cannot navigate and a voice user cannot address.
    expect(
      screen.getByRole("button", { name: "Delete Front desk" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Delete Weekend line" }),
    ).toBeTruthy();
  });

  it("will not delete a working agent, and offers the one thing to do first", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        ...ROSTER,
        "POST /v1/agents/a-live/deactivate": {
          agent_id: "a-live",
          status: "paused",
          changed: true,
          numbers_released: 1,
        },
      }),
    );
    await screen.findByText("Front desk");

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Delete Front desk" }),
      );
    });

    /* Scoped to the SECTION, not the document: a `Skeleton` is also `role="status"` (it
       carries the sr-only "Loading…"), and the lane guide below is still fetching while
       this panel is open — a document-wide query is a race, not an assertion. */
    const panel = within(section("Working right now")).getByRole("status");
    expect(panel.textContent).toContain("Front desk is working right now");
    expect(panel.textContent).toContain(
      "switched off before it can be deleted",
    );
    // NOT A REQUEST. The refusal is the server's to make, but a screen that fires it and
    // renders the 409 has taught the owner nothing about what to do next.
    expect(calls.some((call) => call.method === "POST")).toBe(false);
    expect(
      within(panel).queryByRole("button", { name: /Delete Front desk/ }),
    ).toBeNull();

    // The next step is offered IN the refusal, which is the whole two-step on one screen.
    await act(async () => {
      fireEvent.click(await pressable(panel, /Switch it off/));
    });
    await waitFor(() =>
      expect(calls.find((call) => call.method === "POST")?.path).toBe(
        "/v1/agents/a-live/deactivate",
      ),
    );
  });

  it("deletes an agent that is not working, after restating what survives", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        ...ROSTER,
        "POST /v1/agents/a-off/archive": {
          agent_id: "a-off",
          status: "archived",
          changed: true,
          numbers_released: 0,
        },
      }),
    );
    await screen.findByText("Weekend line");

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Delete Weekend line" }),
      );
    });

    const panel = within(section("Not working")).getByRole("status");
    // The sentence that makes the word "delete" honest, and it is the DETAIL screen's
    // sentence — `MOVE_COPY`, imported, not a second wording that could drift from it.
    expect(panel.textContent).toContain("stay in your call log");
    expect(calls.some((call) => call.method === "POST")).toBe(false);

    await act(async () => {
      fireEvent.click(await pressable(panel, /Delete Weekend line/));
    });
    await waitFor(() =>
      expect(calls.find((call) => call.method === "POST")?.path).toBe(
        "/v1/agents/a-off/archive",
      ),
    );
  });

  it("offers no delete on an agent that is already deleted", async () => {
    await renderClientPage(
      page,
      routes({
        ...ROSTER,
        [ARCHIVED_QUERY]: [
          agent({
            id: "a-old",
            name: "Old receptionist",
            status: "archived",
            archived_at: "2026-07-02T09:30:00Z",
          }),
        ],
      }),
    );
    await screen.findByText("Old receptionist");

    // Bringing it back is on its own screen, where the rest of that agent's life is.
    expect(
      screen.queryByRole("button", { name: "Delete Old receptionist" }),
    ).toBeNull();
  });
});

describe("the archive is a second request, and a failed one is not an empty one", () => {
  it("shows no archive section when the server sent no retired agents", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Reception");
    // A heading that renders empty on every account that has never retired an agent is a
    // heading people learn to skip.
    expect(container.textContent).not.toContain("Deleted");
  });

  it("shows the archive, with when each agent was retired, when the server sent one", async () => {
    await renderClientPage(
      page,
      routes({
        [ARCHIVED_QUERY]: [
          agent({
            id: "a-old",
            name: "Old receptionist",
            status: "archived",
            archived_at: "2026-07-02T09:30:00Z",
          }),
        ],
      }),
    );

    await screen.findByText("Old receptionist");
    const archive = section("Deleted");
    expect(within(archive).getByText("Old receptionist")).toBeTruthy();
    /* Read off the SECTION's own text, not by a regex over the document: "Retired " sits
       on a `<span>` inside an `<a>` that also matches it, and a bare `getByText` there
       fails on "found multiple elements" for a reason that has nothing to do with the
       claim. The date is asserted with it so this pins `archived_at` being rendered in IST
       rather than merely the word appearing. */
    expect(archive.textContent).toContain("Deleted 02 Jul");
    // And it is not in the working roster, which is the whole reason it is a second read.
    expect(
      within(section("Working right now")).queryByText("Old receptionist"),
    ).toBeNull();
  });

  it("renders a refusal rather than an absent section when the archive read failed", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        [ARCHIVED_QUERY]: problem(503, { title: "Service unavailable" }),
      }),
    );

    await screen.findByRole("alert");
    // The working roster still paints — one failed read must not take the screen with it.
    expect(screen.getByText("Reception")).toBeTruthy();
    expect(container.textContent).not.toContain("Deleted");
  });
});

/**
 * WHICH AGENTS ARE OFF THE ACCOUNT DEFAULT — the roster's own model question (D-454/455).
 *
 * `/c/<slug>/settings/models` tells an owner in as many words that "one agent can be put
 * on a different model from the rest", and the roster is where they would look for which.
 * It is a MONEY question, not a curiosity: a per-agent override is charged at the plan's
 * `llm_model_surcharge` for every minute that agent runs (D-455), so the busiest agent on
 * the dearest model is the combination nobody sets on purpose and nobody could find.
 *
 * The badge is read off `llm_model_source`, never off `llm_model !== null`. The two agree
 * today; the day the server adds a fourth level the derived version starts badging agents
 * as having their OWN model when they do not, on the one screen an owner scans for exactly
 * that — and it would be silent about it.
 */
describe("the roster says which agents carry their own AI model", () => {
  it("names the model on an agent that overrides, and on no other row", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents": [
          agent({
            id: "a-own",
            name: "Front desk",
            llm_model: "gpt-4.1-mini",
            llm_model_effective: "gpt-4.1-mini",
            llm_model_source: "agent",
          }),
          agent({ id: "a-inherits", name: "Weekend line" }),
        ],
      }),
    );

    await screen.findByText("Front desk");
    const live = section("Working right now");
    const own = within(live)
      .getByText("Front desk")
      .closest("li") as HTMLElement;
    const inherits = within(live)
      .getByText("Weekend line")
      .closest("li") as HTMLElement;

    expect(own.textContent).toContain("Its own AI model: gpt-4.1-mini");
    // The default is NOT printed on every row: a column of identical identifiers hides the
    // one row that differs, which is the opposite of what a roster scan is for.
    expect(inherits.textContent).not.toContain("gpt-4o-mini");
    expect(inherits.textContent).not.toContain("Its own AI model");
  });

  it("says nothing about an agent following its organisation's choice", async () => {
    // `organization` is the client having chosen — for ALL their agents. It is the
    // settings screen's fact, not this row's: badging it here would mark every agent on
    // the account and say nothing about any of them.
    await renderClientPage(
      page,
      routes({
        "/v1/agents": [
          agent({
            id: "a-org",
            name: "Front desk",
            llm_model: null,
            llm_model_effective: "gpt-4.1-mini",
            llm_model_source: "organization",
          }),
        ],
      }),
    );

    await screen.findByText("Front desk");
    const row = within(section("Working right now"))
      .getByText("Front desk")
      .closest("li");
    expect(row!.textContent).not.toContain("Its own AI model");
  });
});

describe("the activity figures come from the server or are absent", () => {
  it("prints the call count and when the agent was last used", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents/stats": [
          stats({ calls_total: 4102, last_call_at: "2026-08-20T11:05:00Z" }),
        ],
      }),
    );

    await screen.findByText("Reception");
    const working = section("Working right now");
    expect(within(working).getByText(/4,102 calls handled/)).toBeTruthy();
    expect(within(working).getByText(/last used /)).toBeTruthy();
  });

  it("says nothing at all rather than '0 calls' while the figures have not arrived", async () => {
    // The stats route answers for a DIFFERENT agent, so this agent has no row — the same
    // shape as a request still in flight. "This agent has taken 0 calls" is a claim about
    // a client's business, and a missing answer is not evidence for it.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/stats": [stats({ agent_id: "someone-else" })] }),
    );

    await screen.findByText("Reception");
    expect(container.textContent).not.toContain("calls handled");
  });
});

describe("how changes take effect", () => {
  it("reads the call-cap bounds off the API instead of hardcoding ten minutes", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/lanes": {
          ...LANES,
          call_cap_default_s: 900,
          call_cap_min_s: 120,
          call_cap_max_s: 1800,
        },
      }),
    );

    // WAIT FOR THE BODY, NOT THE SUMMARY. "How changes take effect" is now the title of a
    // `<Disclosure>` (UX-DOCTRINE §3 — platform reference material, read once), and a
    // disclosure's summary paints immediately while `GET /v1/agents/lanes` is still in
    // flight. Awaiting the summary would let every assertion below run against an empty
    // body and pass vacuously, which is worse than failing.
    await screen.findByText(/Every call is capped at 15 minutes by default/);
    expect(container.textContent).toContain(
      "Every call is capped at 15 minutes by default",
    );
    expect(container.textContent).toContain("between 2 minutes and 30 minutes");
    expect(container.textContent).not.toContain("10 minutes");
  });

  it("puts an unrecognised lane where it claims nothing, not under 'applies straight away'", async () => {
    // `lane` is a bare `string` on `LaneOut`. A split of staged-versus-everything would
    // announce a lane this build has never seen as immediate — a promise about a live
    // phone line, made from a value we do not understand.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/lanes": {
          ...LANES,
          lanes: [
            ...LANES.lanes,
            {
              field: "webhook",
              lane: "scheduled",
              precedence: 2,
              why: "Applied at the next maintenance window.",
            },
          ],
        },
      }),
    );

    // The disclosure's BODY, for the reason given on the test above.
    const immediate = (await screen.findByText("Applies straight away"))
      .parentElement;
    expect(immediate?.textContent).toContain("Its voice");
    expect(immediate?.textContent).not.toContain("webhook");
    expect(container.textContent).toContain("Ask your account manager");
    // The unnamed field still appears — a lane the client cannot see is worse than an ugly
    // label (FIELD_LABELS falls through to the field's own name).
    expect(container.textContent).toContain("webhook");
  });
});

describe("the page's own chrome", () => {
  it("renders no heading of its own, because the shell already prints one", async () => {
    // The shell prints "Agents" from the nav list (layout.tsx). A second heading here is a
    // visible duplicate, and the copy that drifts when the nav is renamed.
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Reception");
    expect(container.querySelectorAll("h1")).toHaveLength(0);
  });

  it("offers the way to build an agent from the roster itself", async () => {
    await renderClientPage(page, routes());

    await screen.findByText("Reception");
    const build = screen.getByRole("link", { name: /New agent/ });
    expect(build.getAttribute("href")).toBe("/c/acme/agents/new");
  });

  it("makes each row a link to that agent", async () => {
    await renderClientPage(page, routes());

    const row = await screen.findByRole("link", { name: /Reception/ });
    expect(row.getAttribute("href")).toBe("/c/acme/agents/agent-1");
  });
});
