import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentPromptPage from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page";
import type { Experiment, ExperimentState } from "@/lib/api/publishing";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * The A/B script test panel on the agent's prompt screen (ROADMAP M3).
 *
 * This screen decides whether a client's live script is replaced, off a conversion rate.
 * So the defects worth pinning are all one defect — **the screen claiming more than the
 * server did** — in four costumes:
 *
 * 1. **Under the minimum sample, no comparison may appear.** No gap interval, no winner
 *    badge, and the arm that is ahead is labelled "ahead so far". A percentage over 11
 *    calls is not a result, and two percentages side by side with a green box over them
 *    IS a verdict however the caption is worded.
 * 2. **"Ahead" and "better" are different words and must stay different.** A 3-point gap
 *    on 40 calls is inconclusive, and the screen has to say so rather than leaving the
 *    reader to compare the two numbers itself.
 * 3. **A failed results read is a refusal, never an empty state** (BUILD-LOG §52). An
 *    experiment whose endpoint 503s must not render as "no test running" or "no
 *    conversions yet", and the Start form — which is built from the same payload's
 *    `rules` — must not appear either.
 * 4. **A real winner is still allowed to be declared.** A gate so tight that nothing ever
 *    passes it is its own dishonesty, and the test that only asserts refusals would pass
 *    against a panel that never says anything.
 * 5. **A rate over a population that was not randomised cannot be rendered bare.** An
 *    arm can be credited with an inbound call its own line answered (D-60) — a fact, but
 *    not a draw — and that call sits in the denominator of the rate beside calls that
 *    were split. The screen must say so on the row, and must not count the call as one
 *    we dialled.
 * 6. **Every ending names the test it is ending.** The server used to conclude "whatever
 *    is running" on this agent, so a press from a screen showing an ended test would end
 *    the NEXT one — this panel's read is cached for 30s, which is exactly long enough.
 *    The id in the body is the id on screen, and a refusal about a test that has already
 *    ended is rendered as the refusal it is.
 *
 * Everything statistical is the SERVER's: `headline`, `caveat` and `basis` are printed
 * verbatim, so these tests feed the payloads the API produces rather than re-deriving a
 * verdict here.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000a1";
const AGENT = "0192f0aa-7777-7000-8000-0000000000b2";
/** The test the panel is DISPLAYING — and therefore the one every ending must name. */
const EXPERIMENT_ID = "0192f0aa-7777-7000-8000-0000000000d1";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const ME_PATH = "/v1/admin/me";
const HISTORY_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/prompt`;
const PENDING_PATH = `/v1/agents/${AGENT}/pending`;
const LANES_PATH = "/v1/agents/lanes";
const EXPERIMENT_PATH = `/v1/agents/${AGENT}/experiment`;
const CONCLUDE_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/experiment/conclude`;

const RULES = {
  metrics: [
    { key: "call_outcome_resolved", label: "calls the agent resolved" },
    { key: "lead_won", label: "leads eventually won" },
  ],
  default_metric: "call_outcome_resolved",
  minimum_calls_per_variant: 40,
  split_min_bp: 500,
  split_total_bp: 10000,
  peeking_caveat: "The 95% confidence is per reading.",
};

function variant(over: Record<string, unknown> = {}) {
  return {
    variant_id: "0192f0aa-7777-7000-8000-0000000000c1",
    label: "A",
    prompt_version: 1,
    weight_bp: 5000,
    published: true,
    outbound_dialled: 60,
    completed: 50,
    inbound_completed: 0,
    conversions: 10,
    rate: 0.2,
    rate_low: 0.112,
    rate_high: 0.331,
    ...over,
  };
}

function experiment(over: Partial<Experiment> = {}): Experiment {
  return {
    experiment_id: EXPERIMENT_ID,
    agent_id: AGENT,
    name: "Direct booking greeting",
    status: "running",
    conversion_metric: "call_outcome_resolved",
    conversion_metric_label: "calls the agent resolved",
    started_at: "2026-08-01T04:30:00Z",
    concluded_at: null,
    promoted_label: null,
    variants: [variant(), variant({ label: "B", prompt_version: 2 })],
    minimum_calls_per_variant: 40,
    basis: "measured",
    verdict: "inconclusive",
    leader_label: null,
    winner_label: null,
    difference_point: 0,
    difference_low: -0.1,
    difference_high: 0.1,
    headline: "No difference we can stand behind.",
    caveat: RULES.peeking_caveat,
    attributed_directions: ["outbound"],
    coverage_note: "",
    ...over,
  };
}

function state(over: Partial<ExperimentState> = {}): ExperimentState {
  return { agent_id: AGENT, rules: RULES, experiment: null, ...over };
}

const VERSIONS = [
  { id: "v2", version: 2, notes: "challenger", created_at: "2026-08-01T04:00:00Z", active: true },
  { id: "v1", version: 1, notes: "control", created_at: "2026-07-01T04:00:00Z", active: false },
];

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(
    <AgentPromptPage params={routeParams({ tenantId: TENANT, agentId: AGENT })} />,
    {
      [TENANT_PATH]: { id: TENANT, name: "Sunrise Clinic", slug: "sunrise" },
      [ME_PATH]: {
        realm: "admin",
        user_id: "0192f0aa-7777-7000-8000-0000000000f2",
        role: "operator",
        permissions: ["agents:read", "agents:write"],
      },
      [HISTORY_PATH]: VERSIONS,
      [PENDING_PATH]: {
        agent_id: AGENT,
        agent_status: "live",
        published: true,
        has_pending: false,
        pending: [],
        effective_call_cap_s: 600,
        call_cap_is_platform_default: true,
        worst_case_call_cost_inr: null,
        precedence_rule: "Script decides content.",
        engine_verification: {
          state: "applied",
          confirmed: true,
          verified_at: "2026-08-15T09:20:00Z",
          headline:
            "The voice platform was read back and is running this script and voice.",
        },
      },
      [LANES_PATH]: {
        precedence_rule: "Script decides content.",
        lanes: [],
        call_cap_default_s: 600,
        call_cap_min_s: 60,
        call_cap_max_s: 3600,
      },
      [EXPERIMENT_PATH]: state(),
      ...routes,
    },
  );
}

describe("the A/B script test panel", () => {
  it("publishes no comparison and no winner below the minimum sample", async () => {
    const { container } = await render({
      [EXPERIMENT_PATH]: state({
        experiment: experiment({
          variants: [
            variant({ completed: 11, conversions: 5, rate: 0.4545, rate_low: 0.211, rate_high: 0.72 }),
            variant({
              label: "B",
              prompt_version: 2,
              completed: 11,
              conversions: 1,
              rate: 0.0909,
              rate_low: 0.016,
              rate_high: 0.38,
            }),
          ],
          basis: "insufficient_data",
          verdict: "not_enough_data",
          leader_label: "A",
          winner_label: null,
          difference_point: null,
          difference_low: null,
          difference_high: null,
          headline: "Not enough calls to compare yet — 11 completed on the smaller arm.",
        }),
      }),
    });

    await screen.findByText(/Not enough calls to compare yet/);
    // The arm that is ahead is named as an ORDERING. The word "better", and any winner
    // badge, must be nowhere on the screen.
    expect(screen.getByText("ahead so far")).toBeTruthy();
    expect(container.textContent).not.toContain("winner:");
    // And the absent gap says WHY it is absent rather than showing a dash or a zero.
    expect(container.textContent).toContain("No gap is published below 40 completed calls");
    expect(container.textContent).not.toContain("Gap between the arms");
  });

  it("still draws no gap on an unearned basis even if a difference arrives with it", async () => {
    /**
     * The belt to the server's braces, and it earns its place: `results_for` nulls the
     * difference whenever the basis is not `measured`, so the previous test cannot tell
     * whether this screen is checking the BASIS or merely the absence of numbers. This
     * payload is the one a future API change (or a stale cached body) could produce —
     * counts too small, interval present — and the screen must obey the basis.
     */
    const { container } = await render({
      [EXPERIMENT_PATH]: state({
        experiment: experiment({
          variants: [
            variant({ completed: 11, conversions: 5, rate: 0.4545 }),
            variant({ label: "B", prompt_version: 2, completed: 11, conversions: 1, rate: 0.09 }),
          ],
          basis: "insufficient_data",
          verdict: "not_enough_data",
          difference_point: 0.36,
          difference_low: 0.02,
          difference_high: 0.7,
          headline: "Not enough calls to compare yet.",
        }),
      }),
    });

    await screen.findByText(/Not enough calls to compare yet/);
    expect(container.textContent).not.toContain("Gap between the arms");
    expect(container.textContent).toContain("No gap is published below 40 completed calls");
  });

  it("distinguishes 'B is ahead' from 'B is better' on a measured but inconclusive read", async () => {
    const { container } = await render({
      [EXPERIMENT_PATH]: state({
        experiment: experiment({
          variants: [
            variant({ completed: 40, conversions: 8, rate: 0.2 }),
            variant({ label: "B", prompt_version: 2, completed: 40, conversions: 7, rate: 0.175 }),
          ],
          leader_label: "A",
          headline:
            "No difference we can stand behind. The plausible range still includes zero.",
        }),
      }),
    });

    await screen.findByText(/No difference we can stand behind/);
    expect(screen.getByText("ahead so far")).toBeTruthy();
    expect(container.textContent).not.toContain("winner:");
    // Measured, so the interval IS shown — the refusal is about the claim, not the data.
    expect(container.textContent).toContain("Gap between the arms");
  });

  it("declares a winner when the server does, so the gate is not simply always closed", async () => {
    const { container } = await render({
      [EXPERIMENT_PATH]: state({
        experiment: experiment({
          variants: [
            variant({ completed: 200, conversions: 20, rate: 0.1 }),
            variant({ label: "B", prompt_version: 2, completed: 200, conversions: 70, rate: 0.35 }),
          ],
          verdict: "winner",
          leader_label: "B",
          winner_label: "B",
          difference_point: -0.25,
          difference_low: -0.33,
          difference_high: -0.17,
          headline: "Variant B converts better.",
        }),
      }),
    });

    await screen.findByText(/Variant B converts better/);
    expect(container.textContent).toContain("winner: B");
    expect(container.textContent).toContain("Gap between the arms");
    // Promotion is offered per arm, naming the version it would publish.
    expect(screen.getByRole("button", { name: "Promote B (v2)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stop, keep the control" })).toBeTruthy();
  });

  it("refuses rather than reporting an empty experiment when the read fails", async () => {
    const { container } = await render({
      [EXPERIMENT_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this agent's script test.",
        retryable: true,
      }),
    });

    await screen.findByText("We could not read this agent's script test.");
    // §52: not an empty state, not a number, not a state.
    expect(container.textContent).not.toContain("no completed calls yet");
    expect(container.textContent).not.toContain("No gap is published below");
    // And no Start form: it is built from `rules` in the payload that failed, so
    // offering it would mean defaulting a split and a metric from nothing.
    expect(screen.queryByRole("button", { name: /Start test/ })).toBeNull();
  });

  it("prints the server's caveat and the outbound-only coverage note verbatim", async () => {
    const { container } = await render({
      [EXPERIMENT_PATH]: state({
        experiment: experiment({
          coverage_note: "Only outbound calls are assigned to an arm.",
        }),
      }),
    });

    await screen.findByText(/No difference we can stand behind/);
    expect(container.textContent).toContain("The 95% confidence is per reading.");
    expect(container.textContent).toContain("Only outbound calls are assigned to an arm.");
  });

  it("qualifies the rate of an arm whose denominator holds calls nobody split", async () => {
    /**
     * The defect this replaced: one count called `dialled` held every assigned call, so
     * an inbound call an arm's own line answered was reported as a call we placed, and
     * the rate over it read as a clean randomised comparison.
     *
     * Both halves are pinned here. The Dialled column is OUTBOUND — an arm with 40
     * completed calls of which 12 arrived inbound has dialled 30, not 42 — and the rate
     * cell carries the mixture, so no rendering of the number can drop it.
     */
    const { container } = await render({
      [EXPERIMENT_PATH]: state({
        experiment: experiment({
          variants: [
            variant({ outbound_dialled: 45, completed: 40, inbound_completed: 0, conversions: 8 }),
            variant({
              label: "B",
              prompt_version: 2,
              outbound_dialled: 30,
              completed: 40,
              inbound_completed: 12,
              conversions: 7,
              rate: 0.175,
            }),
          ],
          coverage_note: "Some inbound calls were answered by an arm's own line.",
        }),
      }),
    });

    await screen.findByText(/No difference we can stand behind/);
    expect(container.textContent).toContain("includes 12 inbound calls this arm's line answered");
    expect(container.textContent).toContain("not split between the arms");
    // The unmixed arm's rate stays a bare reading — the qualifier is a statement about
    // this arm's data, not a blanket disclaimer bolted onto every row.
    expect(container.textContent).toContain("20.0% (11.2%–33.1%)");
    expect(container.textContent).not.toContain("includes 0 inbound");
    // And the calls we placed are 30, not the 40 that completed.
    expect(screen.getByText("30")).toBeTruthy();
  });

  it("offers a test between two existing versions when none is running, and never authors one", async () => {
    const { container } = await render();

    await screen.findByRole("button", { name: "Start test (50/50)" });
    expect(container.textContent).toContain("40 completed calls");
    // The arms are CHOSEN from history — there is no second script editor here, because
    // `prompt_versions` has exactly one writer.
    expect(screen.getByLabelText("Control (A)")).toBeTruthy();
    expect(screen.getByLabelText("Challenger (B)")).toBeTruthy();
  });

  it("says a test needs two versions rather than offering a dead control", async () => {
    await render({ [HISTORY_PATH]: [VERSIONS[0]] });

    await screen.findByText(/A test needs two prompt versions/);
    expect(screen.queryByRole("button", { name: /Start test/ })).toBeNull();
  });

  it("names the test on screen in every ending, rather than 'whatever is running'", async () => {
    /**
     * The console half of the fix. `POST .../experiment/conclude` requires an
     * `experiment_id`; the server answers about the test that id names and never falls
     * back to the agent's current one. That is only worth anything if the console sends
     * the id it is DISPLAYING — sending "the running one" from here would just move the
     * defect one process to the left.
     *
     * Asserted on the request body rather than on a rendered sentence, because the body
     * is the whole contract: a screen that renders correctly and posts `{promote: "B"}`
     * is the exact failure this pins.
     */
    const { calls } = await render({
      [EXPERIMENT_PATH]: state({ experiment: experiment() }),
      [`POST ${CONCLUDE_PATH}`]: {
        experiment_id: EXPERIMENT_ID,
        promoted_label: "B",
        new_version: 3,
        applied: true,
        engine_synced: true,
        changed: true,
      },
    });

    const concludeBodies = () =>
      calls
        .filter((call) => call.method === "POST" && call.path === CONCLUDE_PATH)
        .map((call) => JSON.parse(call.body ?? "{}"));

    fireEvent.click(await screen.findByRole("button", { name: "Promote B (v2)" }));
    await screen.findByText(/Promoted variant B as v3\./);

    fireEvent.click(screen.getByRole("button", { name: "Stop, keep the control" }));
    await waitFor(() => expect(concludeBodies()).toHaveLength(2));

    expect(concludeBodies()).toEqual([
      { experiment_id: EXPERIMENT_ID, promote: "B" },
      { experiment_id: EXPERIMENT_ID, promote: null },
    ]);
  });

  it("renders the refusal when the test on screen has already ended another way", async () => {
    /**
     * The stale screen, end to end. The read is cached for 30 seconds and refetched on
     * focus, so an operator can press Promote A on a test a colleague ended promoting B.
     * The server names the ending it found; this panel must PRINT that refusal, because
     * the alternative — a silent failure, or worse the old fallback that would have
     * concluded whichever test is running now — is how an operator learns the wrong
     * script is live from a client instead of from us.
     */
    const { container } = await render({
      [EXPERIMENT_PATH]: state({ experiment: experiment() }),
      [`POST ${CONCLUDE_PATH}`]: problem(409, {
        title: "Conflict",
        detail:
          "This script test has already ended promoting variant B, so it cannot now promote variant A.",
        remediation: "Reload the agent to see how it ended.",
      }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Promote A (v1)" }));

    await screen.findByText(/already ended promoting variant B/);
    expect(container.textContent).toContain("Reload the agent to see how it ended.");
    // Nothing was promoted, so nothing may read as a promotion.
    expect(container.textContent).not.toContain("Promoted variant A");
  });

  it("reports a promotion this press performed, with the version it minted", async () => {
    await render({
      [EXPERIMENT_PATH]: state({ experiment: experiment() }),
      [`POST ${CONCLUDE_PATH}`]: {
        experiment_id: EXPERIMENT_ID,
        promoted_label: "B",
        new_version: 3,
        applied: true,
        engine_synced: true,
        changed: true,
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Promote B (v2)" }));

    await screen.findByText(/Promoted variant B as v3\./);
    expect(screen.getByText(/The voice platform has it\./)).toBeTruthy();
  });

  it("does not report a promotion for a conclude that ended nothing", async () => {
    /**
     * The server is idempotent about ending a test: the second operator on this screen,
     * and the retry of a request whose response was lost, both get 200 with the arm the
     * test ENDED on and a null version — nothing was promoted or published twice.
     *
     * Rendering that response through the success branch printed "Promoted variant B as
     * vnull. It is STAGED — press Apply above", which is two false statements about the
     * platform's state at the operator who is least able to check: one who has just been
     * beaten to the button by a colleague.
     */
    const { container } = await render({
      [EXPERIMENT_PATH]: state({ experiment: experiment() }),
      [`POST ${CONCLUDE_PATH}`]: {
        experiment_id: EXPERIMENT_ID,
        promoted_label: "B",
        new_version: null,
        applied: false,
        engine_synced: false,
        changed: false,
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Promote B (v2)" }));

    await screen.findByText(/This test had already ended, promoting variant B\./);
    expect(container.textContent).not.toContain("vnull");
    // The success branch's staged-change sentence, which would send this operator to
    // press Apply for a version that does not exist.
    expect(container.textContent).not.toContain("It is STAGED");
  });
});

describe("the call cap", () => {
  /**
   * ONE READING OF A CAP, SHARED WITH THE CLIENT'S OWN SCREEN.
   *
   * This card had its own `minutesReading` ("10 min") while `c/[slug]/agents` had
   * `formatCallCap` ("10 minutes") — the same field, `effective_call_cap_s`, spelled two
   * ways in the two consoles, so an operator and the client they were on the phone to
   * were reading different sentences about one number. Both now come from
   * `components/ui.tsx::formatCallCap`; `agents.test.tsx` pins the client half.
   */
  it("reads the cap the way the client's own screen reads it", async () => {
    const { container } = await render();

    // WAIT FOR THE CAP, not for the card's heading. "Maximum call length" is static and
    // renders before the read lands, so waiting on it and then asserting synchronously was
    // asserting against a card still showing "Loading…" whenever the query had not settled
    // inside the same flush — green only by the margin of however many microtasks a
    // request happened to take. `findByText` returns the instant it matches, so this costs
    // nothing when the code is right and is the difference between a race and an assertion.
    await screen.findByText(/600s/);
    expect(container.textContent).toContain("(10 minutes, platform default)");
  });
});
