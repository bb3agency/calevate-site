import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentPromptPage from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page";
import { VOICES_PATH, type Voice } from "@/lib/api/voices";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * Voice selection on the agent screen — `GET /v1/agents/voices` finally has a consumer.
 *
 * The catalogue was readable over the API and selectable nowhere: D-36's premium/value
 * ladder existed as data, the admin write existed (`PATCH /v1/agents/{id}/voice`), and no
 * screen joined them. It lives on this screen because voice is agent CONFIGURATION and the
 * write is admin-realm `agents:write` (D-21: which voice speaks Telugu well is an ear
 * test, so it routes through us) — the same gate every other control here is behind.
 *
 * Four things worth pinning:
 *
 * 1. **The catalogue is read through the tenant's impersonation session.** `list_voices` is
 *    `realm="any"`, and `current_any` consults the admin realm only when the impersonation
 *    header is present — so an admin session with no header is rejected on a `/v1/agents/…`
 *    path even for static data. Getting this wrong produces a 401 on a screen that
 *    otherwise looks fine.
 * 2. **A failed catalogue read is a refusal, never an empty `<select>`** (BUILD-LOG §52).
 *    A picker with no options reads as "this agent has no voices available", which is a
 *    claim about the product made from a dead request.
 * 3. **Nothing is pre-selected, and the screen says why.** No endpoint exposes an agent's
 *    current `tts_voice`, so a highlighted option would be a state we never read rendered
 *    as a fact.
 * 4. **The save does not reach the engine, and the screen prints the server's own sentence
 *    about that.** `publish_agent` re-reads the column, so a live agent keeps its old
 *    voice until the next publish — `republish_required` and `next_step` are the server's
 *    answer and are not paraphrased here.
 */

const TENANT = "0192f0aa-8888-7000-8000-0000000000a1";
const AGENT = "0192f0aa-8888-7000-8000-0000000000b2";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const ME_PATH = "/v1/admin/me";
const HISTORY_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/prompt`;
const PENDING_PATH = `/v1/agents/${AGENT}/pending`;
const LANES_PATH = "/v1/agents/lanes";
const EXPERIMENT_PATH = `/v1/agents/${AGENT}/experiment`;
const SET_VOICE_PATH = `/v1/agents/${AGENT}/voice`;

function voice(over: Partial<Voice> = {}): Voice {
  return {
    id: "anushka",
    label: "Anushka",
    provider: "sarvam",
    tts_model: "bulbul:v3",
    tier: "premium",
    gender: "female",
    languages: ["te-IN", "hi-IN", "en-IN"],
    note: "Warm, unhurried; the default for Telugu receptionists.",
    is_default: true,
    verified: false,
    ...over,
  };
}

const CATALOGUE: Voice[] = [
  voice(),
  voice({
    id: "vidya",
    label: "Vidya",
    tts_model: "bulbul:v2",
    tier: "value",
    is_default: false,
    verified: true,
    note: "The value tier — half the TTS cost, a flatter read.",
  }),
];

function render(over: Partial<Routes> = {}) {
  return renderAdminRoute(
    <AgentPromptPage params={routeParams({ tenantId: TENANT, agentId: AGENT })} />,
    {
      [TENANT_PATH]: { id: TENANT, name: "Sunrise Clinic", slug: "sunrise" },
      [ME_PATH]: {
        realm: "admin",
        user_id: "0192f0aa-8888-7000-8000-0000000000f2",
        role: "operator",
        permissions: ["agents:read", "agents:write"],
      },
      [HISTORY_PATH]: [],
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
      },
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
      [VOICES_PATH]: CATALOGUE,
      ...over,
    },
  );
}

describe("the voice panel", () => {
  it("reads the catalogue through the tenant's impersonation session", async () => {
    const { calls } = await render();

    await screen.findByLabelText("Voice");
    const read = calls.filter((call) => call.path === VOICES_PATH);
    expect(read).toHaveLength(1);
    // The header IS the mechanism: without it `current_any` falls through to the client
    // verifier and rejects the admin token, on an endpoint that touches no tenant data.
    expect(read[0]!.headers["X-Impersonate-Org"]).toBe("sunrise");
  });

  it("offers every catalogue entry and marks the unverified ones", async () => {
    const { container } = await render();

    const select = await screen.findByLabelText("Voice");
    const options = [...select.querySelectorAll("option")].map((o) => o.textContent);
    expect(options).toEqual([
      "Choose a voice",
      "Anushka — premium (bulbul:v3) · unverified",
      "Vidya — value (bulbul:v2)",
    ]);
    // The catalogue carries `verified: false` until the pilot confirms the engine accepts
    // the string (OPERATIONS §2 gate 3). Rendered, not hidden.
    expect(container.textContent).toContain("unverified");
  });

  it("pre-selects nothing and says why", async () => {
    // No endpoint exposes `agents.tts_voice`, so a highlighted option would be a state
    // this screen never read, rendered as a fact — §52 at its purest.
    const { container } = await render();

    const select = await screen.findByLabelText("Voice");
    expect((select as HTMLSelectElement).value).toBe("");
    expect(container.textContent).toContain(
      "The voice currently in force is not readable over the API",
    );
  });

  it("shows the chosen voice's detail before it is saved", async () => {
    const { container } = await render();

    fireEvent.change(await screen.findByLabelText("Voice"), { target: { value: "vidya" } });

    await waitFor(() =>
      expect(container.textContent).toContain("The value tier — half the TTS cost"),
    );
    expect(container.textContent).toContain("te-IN, hi-IN, en-IN");
  });

  it("names the tenant in the BODY and reports that a republish is still needed", async () => {
    // The tenant rides in the body because the route's shape says so: an admin principal
    // has no tenant of its own, and the one way it could get one — impersonation — is
    // refused for every mutation by D-22.
    const { container, calls } = await render({
      [SET_VOICE_PATH]: {
        agent_id: AGENT,
        voice: voice({ id: "vidya", label: "Vidya", tier: "value", tts_model: "bulbul:v2" }),
        agent_status: "live",
        published: true,
        engine_synced: false,
        republish_required: true,
        next_step:
          "Publish the agent to send this voice to the engine — until then callers hear the previous voice.",
      },
    });

    fireEvent.change(await screen.findByLabelText("Voice"), { target: { value: "vidya" } });
    fireEvent.click(screen.getByRole("button", { name: "Set voice" }));

    await waitFor(() => expect(calls.some((c) => c.path === SET_VOICE_PATH)).toBe(true));
    const write = calls.find((c) => c.path === SET_VOICE_PATH)!;
    expect(write.method).toBe("PATCH");
    expect(JSON.parse(write.body!)).toEqual({ tenant_id: TENANT, voice_id: "vidya" });
    // The admin write is NOT impersonating — the impersonation header on a mutation is a
    // guaranteed 403 under D-22.
    expect(write.headers["X-Impersonate-Org"]).toBeUndefined();

    // The server's own sentence, printed rather than paraphrased: a live agent keeps its
    // old voice until someone publishes, and implying otherwise is the expensive lie.
    await waitFor(() =>
      expect(container.textContent).toContain(
        "Publish the agent to send this voice to the engine",
      ),
    );
    expect(container.textContent).toContain("Saved — Vidya (value tier, bulbul:v2)");
  });

  it("renders a refusal, not an empty picker, when the catalogue cannot be read", async () => {
    // §52. A `<select>` with only "Choose a voice" in it says "there are no voices",
    // which is a claim about the product built from a dead request.
    const { container } = await render({
      [VOICES_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "The voice catalogue is unavailable.",
        retryable: true,
      }),
    });

    await screen.findByText("The voice catalogue is unavailable.");
    expect(screen.queryByLabelText("Voice")).toBeNull();
    expect(screen.queryByRole("button", { name: "Set voice" })).toBeNull();
    expect(container.querySelectorAll("option")).toHaveLength(0);
  });

  it("surfaces the server's refusal of an unknown voice rather than pre-empting it", async () => {
    // Membership in the catalogue is the SERVER's check, and its refusal carries the whole
    // list in its remediation. A second copy of that rule here is a rule that drifts.
    const { container } = await render({
      [SET_VOICE_PATH]: problem(422, {
        type: "urn:calevate:business_rule/unknown_voice",
        title: "Unknown voice",
        detail: "That voice is not in the catalog, so it cannot be set on an agent.",
        remediation: "Pick one of: anushka, vidya (GET /v1/agents/voices).",
        kind: "business_rule",
      }),
    });

    fireEvent.change(await screen.findByLabelText("Voice"), { target: { value: "anushka" } });
    fireEvent.click(screen.getByRole("button", { name: "Set voice" }));

    await screen.findByText("That voice is not in the catalog, so it cannot be set on an agent.");
    expect(container.textContent).toContain("Pick one of: anushka, vidya");
    // Still usable: the operator can pick another entry without reloading.
    expect(screen.getByRole("button", { name: "Set voice" })).toBeTruthy();
  });

  it("explains the disabled control to an operator without agents:write", async () => {
    const { container } = await render({
      [ME_PATH]: {
        realm: "admin",
        user_id: "0192f0aa-8888-7000-8000-0000000000f3",
        role: "support",
        permissions: ["agents:read"],
      },
    });

    const select = await screen.findByLabelText("Voice");
    expect(select).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Set voice" })).toHaveProperty("disabled", true);
    expect(container.textContent).toContain(
      "does not have the agents:write permission, so you cannot change this agent's script",
    );
  });
});
