import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentPromptPage from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page";
import { VOICES_PATH } from "@/lib/api/voices";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * "Live" versus "confirmed live" — the publish read-back on the agent screen.
 *
 * The server now reads the agent back out of the voice platform after every publish and
 * stores one of four verdicts. That distinction is the whole feature, and it is exactly
 * the kind a screen erases by accident: `unverified`, `unreadable` and `unreachable` all
 * sit next to the word "live", and a UI that renders any of them as reassurance puts the
 * defect back with a nicer font.
 *
 * Five properties, each its own test:
 *
 * 1. **`confirmed` is what is rendered, never `state !== "unverified"`.** The four states
 *    are four different answers.
 * 2. **An unconfirmed publish is visibly unconfirmed**, and says what to do about it.
 * 3. **The re-check costs a vendor round trip, so it does not happen on mount.** A query
 *    that ran on render would dial the vendor once per page view of every agent.
 * 4. **A failed re-check is a REFUSAL** (BUILD-LOG §52), never a blank panel and never
 *    the previous green answer left standing.
 * 5. **A tri-state property renders as three readings.** `null` is "the voice platform's
 *    answer did not contain this" — neither a tick nor a cross, because sending an
 *    operator to fix a working agent and telling them a broken one is fine are both
 *    failures and the tri-state exists to avoid choosing between them.
 */

const TENANT = "0192f0aa-9999-7000-8000-0000000000a1";
const AGENT = "0192f0aa-9999-7000-8000-0000000000b2";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const ME_PATH = "/v1/admin/me";
const HISTORY_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/prompt`;
const PENDING_PATH = `/v1/agents/${AGENT}/pending`;
const ENGINE_STATE_PATH = `/v1/agents/${AGENT}/engine-state`;
const LANES_PATH = "/v1/agents/lanes";
const EXPERIMENT_PATH = `/v1/agents/${AGENT}/experiment`;

const CONFIRMED = {
  state: "applied",
  confirmed: true,
  // The engine hosts agents of ours. `false` is the other shape (D-281) and it hides the
  // read-back's amber prompt as well as the Publish button, because there is nothing a
  // republish could confirm — `agentGoLive.test.tsx` covers that case.
  publishable: true,
  verified_at: "2026-08-15T09:20:00Z",
  headline: "The voice platform was read back and is running this script and voice.",
};

const UNREACHABLE = {
  state: "unreachable",
  confirmed: false,
  publishable: true,
  verified_at: null,
  headline:
    "The voice platform accepted this publish and did not answer when we read it back, " +
    "so we cannot confirm it is running it. Publish again to re-check.",
};

function pending(verification: Record<string, unknown>) {
  return {
    agent_id: AGENT,
    agent_status: "live",
    published: true,
    has_pending: false,
    pending: [],
    effective_call_cap_s: 600,
    call_cap_is_platform_default: true,
    worst_case_call_cost_inr: null,
    precedence_rule: "Script decides content.",
    voice: {
      configured: { voice_id: "anushka", provider: "sarvam", catalog: null },
      live: { voice_id: "anushka", provider: "sarvam", catalog: null },
      republish_required: false,
      headline: "Callers hear anushka.",
    },
    engine_verification: verification,
  };
}

function engineState(over: Record<string, unknown> = {}) {
  return {
    agent_id: AGENT,
    engine: "fake",
    engine_agent_ref: "fakeagent_1",
    checked: true,
    state: "applied",
    in_sync: true,
    prompt_applied: true,
    disclosure_applied: true,
    prompt_disclosure_applied: true,
    // D-163's fourth verdict: the platform rules that make the agent answer honestly when
    // a caller asks. Healthy in the base fixture like its neighbours, so a case that
    // wants it unreadable has to say so — the same reason every other property here is
    // spelled out rather than defaulted.
    truthful_answer_applied: true,
    voice_applied: true,
    detail: "The voice platform was read back and is holding the published script and voice.",
    ...over,
  };
}

function render(verification: Record<string, unknown>, over: Partial<Routes> = {}) {
  return renderAdminRoute(
    <AgentPromptPage params={routeParams({ tenantId: TENANT, agentId: AGENT })} />,
    {
      [TENANT_PATH]: { id: TENANT, name: "Sunrise Clinic", slug: "sunrise" },
      [ME_PATH]: {
        realm: "admin",
        user_id: "0192f0aa-9999-7000-8000-0000000000f2",
        role: "operator",
        permissions: ["agents:read", "agents:write"],
      },
      [HISTORY_PATH]: [],
      [PENDING_PATH]: pending(verification),
      [LANES_PATH]: {
        precedence_rule: "Script decides content.",
        lanes: [],
        call_cap_default_s: 600,
        call_cap_min_s: 60,
        call_cap_max_s: 3600,
      },
      [EXPERIMENT_PATH]: {
        agent_id: AGENT,
        rules: {
          metrics: [{ key: "call_outcome_resolved", label: "calls the agent resolved" }],
          default_metric: "call_outcome_resolved",
          minimum_calls_per_variant: 40,
          split_min_bp: 500,
          split_total_bp: 10000,
          peeking_caveat: "The 95% confidence is per reading.",
        },
        experiment: null,
      },
      [VOICES_PATH]: { voices: [], default_voice_id: null },
      ...over,
    },
  );
}

describe("what the agent screen claims about being live", () => {
  it("prints the server's own verdict and the time it was confirmed", async () => {
    await render(CONFIRMED);

    expect(await screen.findByText(CONFIRMED.headline)).toBeTruthy();
    expect(screen.getByText(/Confirmed /)).toBeTruthy();
    // No amber warning, because this one WAS confirmed.
    expect(screen.queryByText(/Nothing here is wrong yet/)).toBeNull();
  });

  it("says an unconfirmed publish is unconfirmed rather than rounding it up", async () => {
    await render(UNREACHABLE);

    expect(await screen.findByText(UNREACHABLE.headline)).toBeTruthy();
    expect(screen.getByText(/Nothing here is wrong yet — it is unconfirmed/)).toBeTruthy();
    // The confirmation TIMESTAMP is the thing that must not appear: a screen that shows
    // "Confirmed 2 minutes ago" over an answer nobody could read is the exact defect.
    expect(screen.queryByText(/Confirmed /)).toBeNull();
  });

  it("does not dial the voice platform until someone asks it to", async () => {
    const { calls } = await render(CONFIRMED);

    await screen.findByText(CONFIRMED.headline);
    expect(calls.filter((call) => call.path === ENGINE_STATE_PATH)).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: /Check the voice platform now/ }));
    await waitFor(() =>
      expect(calls.filter((call) => call.path === ENGINE_STATE_PATH).length).toBeGreaterThan(0),
    );
  });

  it("reports a drift the stored verdict cannot know about", async () => {
    await render(CONFIRMED, {
      [ENGINE_STATE_PATH]: engineState({
        state: "not_applied",
        in_sync: false,
        prompt_applied: false,
        detail:
          "The voice platform is running a different script, disclosure line or voice " +
          "from the one this agent last published.",
      }),
    });

    await screen.findByText(CONFIRMED.headline);
    fireEvent.click(screen.getByRole("button", { name: /Check the voice platform now/ }));

    expect(await screen.findByText(/running a different script/)).toBeTruthy();
    expect(screen.getByText("Does not match")).toBeTruthy();
  });

  it("renders an unreadable property as neither a match nor a mismatch", async () => {
    await render(CONFIRMED, {
      [ENGINE_STATE_PATH]: engineState({
        state: "unreadable",
        in_sync: false,
        voice_applied: null,
        detail: "The voice platform did not report back enough for us to confirm it.",
      }),
    });

    await screen.findByText(CONFIRMED.headline);
    fireEvent.click(screen.getByRole("button", { name: /Check the voice platform now/ }));

    expect(await screen.findByText("Could not read")).toBeTruthy();
    expect(screen.queryByText("Does not match")).toBeNull();
  });

  it("refuses rather than showing an empty answer when the re-check fails", async () => {
    await render(CONFIRMED, {
      [ENGINE_STATE_PATH]: problem(502, {
        title: "The voice platform did not answer",
        detail: "We could not reach the voice platform to check this agent.",
      }),
    });

    await screen.findByText(CONFIRMED.headline);
    fireEvent.click(screen.getByRole("button", { name: /Check the voice platform now/ }));

    expect(await screen.findByText(/could not reach the voice platform/i)).toBeTruthy();
    // And the stored verdict is NOT quietly re-used as the answer to the question asked.
    expect(screen.queryByText("Matches")).toBeNull();
  });
});
