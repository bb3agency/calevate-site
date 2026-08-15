import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentPromptPage from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page";
import { VOICES_PATH } from "@/lib/api/voices";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, stillLoading, type Routes } from "./harness";

/**
 * The FIRST publish, from the console — the control that did not exist.
 *
 * `POST /v1/admin/tenants/{tid}/agents/{aid}/publish` shipped, was mounted in `main.py`,
 * and had no caller in either realm. Every other publish path in the product is a
 * RE-publish guarded on the agent already being live (`apply_to_live` pushes only
 * `if row.is_live`; `set_call_cap` and `recompile_t0` only when `status == 'live' AND
 * engine_agent_ref`), so an agent minted by the wizard — `draft`, no engine ref — could
 * not be put on the voice platform from any screen. A founder could finish onboarding,
 * invite the owner, and hand over an account whose phone line answered nothing.
 *
 * What is pinned here, in the order the operator meets it:
 *
 * 1. The panel offers the publish only when the SERVER says the agent is not on the
 *    platform, and it sends the admin-realm request to the tenant-scoped path.
 * 2. §52: while the reads are in flight it is a SKELETON, never a button. An "unpublished"
 *    state assembled from an absent read is a claim about a client's phone line.
 * 3. §52: a failed read is a REFUSAL with a retry, not a silent unpublished state.
 * 4. A published agent is not offered a first publish, and says so rather than vanishing.
 * 5. The server's refusal is rendered in the server's own words — the panel does not
 *    substitute a sentence of its own for `agent_has_no_script`.
 * 6. The precondition the server enforces is stated BEFORE the click when we can see it
 *    (an empty version history), so the button is not a trap.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000a1";
const AGENT = "0192f0aa-7777-7000-8000-0000000000b2";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const ME_PATH = "/v1/admin/me";
const HISTORY_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/prompt`;
const PENDING_PATH = `/v1/agents/${AGENT}/pending`;
const LANES_PATH = "/v1/agents/lanes";
const EXPERIMENT_PATH = `/v1/agents/${AGENT}/experiment`;
const PUBLISH_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/publish`;

/** One prompt version, so the script precondition is satisfied unless a test removes it. */
const HISTORY = [
  {
    id: "0192f0aa-7777-7000-8000-0000000000c3",
    version: 1,
    notes: "regenerated from intake (FLOWS §1 step 3)",
    created_at: "2026-08-14T05:00:00Z",
    active: true,
  },
];

function pending(over: Record<string, unknown> = {}) {
  return {
    agent_id: AGENT,
    agent_status: "draft",
    published: false,
    has_pending: false,
    pending: [],
    effective_call_cap_s: 600,
    call_cap_is_platform_default: true,
    worst_case_call_cost_inr: null,
    precedence_rule: "Script decides content.",
    voice: {
      configured: null,
      live: null,
      republish_required: false,
      headline: "No voice has been set on this agent.",
    },
    // Never read back: this agent has never been published (`published: false`), which
    // is exactly what `unverified` means and what the screen must not round up.
    engine_verification: {
      state: "unverified",
      confirmed: false,
      verified_at: null,
      headline: "This agent is not on the voice platform yet; there is nothing to confirm.",
    },
    ...over,
  };
}

function render(over: Partial<Routes> = {}) {
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
      [HISTORY_PATH]: HISTORY,
      [PENDING_PATH]: pending(),
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
      [VOICES_PATH]: { control: "ours", selectable: true, voices: [], note: "" },
      ...over,
    },
  );
}

const publishButton = () => screen.findByRole("button", { name: /Publish to the voice platform/ });

describe("putting an agent on the voice platform for the first time", () => {
  it("posts to the tenant-scoped admin path and reports the engine's own ref", async () => {
    const { calls } = await render({
      [`POST ${PUBLISH_PATH}`]: {
        agent_id: AGENT,
        engine_agent_ref: "bolna_agent_7f21",
        status: "live",
      },
    });

    fireEvent.click(await publishButton());

    await screen.findByText(/bolna_agent_7f21/);
    const posted = calls.filter((call) => call.path === PUBLISH_PATH && call.method === "POST");
    expect(posted).toHaveLength(1);
    // ADMIN realm, tenant in the path: the mutation is not reachable through the
    // read-only impersonation session the two GETs on this page use (D-22).
    expect(posted[0]!.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("shows a skeleton rather than a publish button while the reads are in flight", async () => {
    // A never-resolving pending read: the panel has no answer about whether this agent
    // is on the platform, so it must claim neither.
    const { container } = await render({ [PENDING_PATH]: stillLoading() });

    const panel = (await screen.findByText("Voice platform")).closest("section");
    expect(panel).not.toBeNull();
    // A SKELETON IS PRESENT, not merely "the button is absent": rendering nothing at all
    // also passes an absence check, and an empty card is its own §52 defect — the
    // operator cannot tell a still-loading agent from one with nothing to say.
    expect(panel!.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", { name: /Publish to the voice platform/ }),
    ).toBeNull();
    expect(container.textContent).not.toContain("has never reached the voice platform");
    // And no claim about the read having failed either — it has not.
    expect(container.textContent).not.toContain("We could not read whether this agent");
  });

  it("refuses rather than reporting an unpublished agent when the read fails", async () => {
    await render({
      [PENDING_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this agent's publishing state.",
      }),
    });

    // ONE refusal, from the panel that owns the read and carries the retry — not the
    // same sentence twice because two panels depend on it.
    expect(await screen.findAllByText("We could not read this agent's publishing state.")).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: /Publish to the voice platform/ }),
    ).toBeNull();
    // Not the unpublished panel either: a dead read is not evidence of a draft agent.
    expect(screen.queryByText(/has never reached the voice platform/)).toBeNull();
  });

  it("offers no first publish for an agent already on the platform, and says why", async () => {
    await render({ [PENDING_PATH]: pending({ published: true, agent_status: "live" }) });

    await screen.findByText(/This agent is on the voice platform/);
    expect(
      screen.queryByRole("button", { name: /Publish to the voice platform/ }),
    ).toBeNull();
  });

  it("renders the server's refusal verbatim instead of a sentence of its own", async () => {
    await render({
      [`POST ${PUBLISH_PATH}`]: problem(422, {
        title: "This agent has no script yet",
        detail:
          "The agent has no prompt version, so there is nothing to publish. Publishing it would put a generic placeholder on the client's phone line.",
        remediation: "Complete the intake step for this client, or write a prompt version, then publish.",
      }),
    });

    fireEvent.click(await publishButton());

    await screen.findByText(/would put a generic placeholder on the client's phone line/);
    // And it must NOT claim the publish landed.
    expect(screen.queryByText(/the platform holds this agent as/i)).toBeNull();
  });

  it("disables the button when there is no script to publish, before the click", async () => {
    await render({ [HISTORY_PATH]: [] });

    // `disabled` read off the DOM: this project has no jest-dom matchers.
    await waitFor(async () => expect((await publishButton()).hasAttribute("disabled")).toBe(true));
    await screen.findByText(/This agent has no script yet — complete the client's intake/);
  });
});
