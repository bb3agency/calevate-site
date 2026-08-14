import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentPromptPage from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page";
import type { AgentVoiceState } from "@/lib/api/publishing";
import { VOICES_PATH, type Voice, type VoiceCatalogue } from "@/lib/api/voices";

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
 * 3. **CONFIGURED IS NOT LIVE, and both are on screen.** This is the whole reason the
 *    panel is more than a dropdown. `PATCH .../voice` writes our row and does not touch
 *    the engine, so a published agent keeps its old voice until the next publish. The
 *    select pre-selects `voice.configured` — the thing being edited — while the panel
 *    names `voice.live` beside it as what callers actually hear. The panel used to say it
 *    could not report the voice in force at all; the fix was to make the server answer,
 *    not to start guessing, and the tests below fail if either half goes missing.
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

const VOICES: Voice[] = [
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

/**
 * The catalogue AS THE SERVER ANSWERS IT (D-93): the rows AND the verdict about them.
 *
 * It stopped being a bare `Voice[]` because a bare list cannot say "no selection here,
 * and that is normal" — its only way to express it is `[]`, which this very panel renders
 * as "this agent has no voices available", a claim about the product rather than about the
 * engine. `selectable` and `control` carry the verdict; `note` is the sentence to print.
 */
const CATALOGUE: VoiceCatalogue = {
  control: "ours",
  selectable: true,
  voices: VOICES,
  note: "Pick the voice this agent speaks in.",
};

/** The same endpoint on an engine that supplies its own voices — no rows, and a reason. */
const DICTATED_CATALOGUE: VoiceCatalogue = {
  control: "engine",
  selectable: false,
  voices: [],
  note: "The voice platform in use supplies its own voices, so a voice cannot be chosen here. Nothing is wrong with this agent.",
};

/** One stored voice as `GET /v1/agents/{id}/pending` answers it. */
function stored(id: string): NonNullable<AgentVoiceState["configured"]> {
  return {
    voice_id: id,
    provider: "sarvam",
    catalog: VOICES.find((entry) => entry.id === id) ?? null,
  };
}

/**
 * The default agent for these tests: published, and the engine is holding the voice the
 * row says it is. The interesting cases override it.
 */
const VOICE_IN_SYNC: AgentVoiceState = {
  configured: stored("anushka"),
  live: stored("anushka"),
  republish_required: false,
  headline: "Callers hear Anushka — the voice platform is holding the configured voice.",
};

function pendingRoute(voiceState: AgentVoiceState) {
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
    voice: voiceState,
  };
}

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
      [PENDING_PATH]: pendingRoute(VOICE_IN_SYNC),
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

  it("pre-selects the voice the agent is configured with", async () => {
    // The gap this slice closed. `voice.configured` is the thing the operator is
    // editing, so it is what the select opens on — not `voice.live` (the past), not the
    // catalogue's `is_default` (D-36's written default, not this agent's state), and not
    // a blank, which invites an operator to re-pick a value that is already set.
    const { container } = await render();

    const select = await screen.findByLabelText("Voice");
    expect((select as HTMLSelectElement).value).toBe("anushka");
    // The detail block follows the selection without anyone touching the control.
    expect(container.textContent).toContain(
      "Warm, unhurried; the default for Telugu receptionists.",
    );
  });

  it("shows an agent with no voice set as exactly that, with nothing pre-selected", async () => {
    // A blank select is still correct for an agent nobody has configured — but it is now
    // a state the SERVER reported, not a state the screen could not read.
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: null,
        live: null,
        republish_required: false,
        headline: "No voice has been set on this agent.",
      }),
    });

    const select = await screen.findByLabelText("Voice");
    expect((select as HTMLSelectElement).value).toBe("");
    expect(container.textContent).toContain("No voice has been set on this agent.");
    expect(container.textContent).toContain("None set");
  });

  it("names the LIVE voice and the CONFIGURED one separately when they differ", async () => {
    // The distinction this panel exists for. A voice change lands in our row and stops:
    // `publish_agent` re-reads the column, so the caller keeps hearing the old voice.
    // Showing one value and calling it "the voice" is the defect — so both are rendered
    // as labelled data, and the server's own sentence sits above them.
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: stored("vidya"),
        live: stored("anushka"),
        republish_required: true,
        headline: "Callers still hear Anushka; Vidya reaches them at the next publish.",
      }),
    });

    const select = await screen.findByLabelText("Voice");
    // Pre-selection follows CONFIGURED — the operator edits the configuration.
    expect((select as HTMLSelectElement).value).toBe("vidya");

    expect(container.textContent).toContain("Callers hear now");
    expect(container.textContent).toContain("Anushka (bulbul:v3)");
    expect(container.textContent).toContain("Configured");
    expect(container.textContent).toContain("Vidya (bulbul:v2)");
    // The server's sentence, printed rather than paraphrased.
    expect(container.textContent).toContain(
      "Callers still hear Anushka; Vidya reaches them at the next publish.",
    );
    // And WHO closes the gap. Only a publish does; nothing on this screen is it.
    expect(container.textContent).toContain(
      "Publishing this agent is what moves the voice callers hear.",
    );
  });

  it("says a published agent's live voice is unrecorded rather than calling it in sync", async () => {
    // An agent published before the server recorded what it sent. "We cannot prove it"
    // is not "nothing is live" and is certainly not "in sync" — the server still asks
    // for a republish, and the screen must not soften that into a green state.
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: stored("vidya"),
        live: null,
        republish_required: true,
        headline:
          "Callers hear whatever voice was last published; we have no record of which. Vidya reaches them at the next publish.",
      }),
    });

    await screen.findByLabelText("Voice");
    expect(container.textContent).toContain("Not recorded — publish to be sure");
    expect(container.textContent).toContain("we have no record of which");
  });

  it("says an unpublished agent has no live voice at all", async () => {
    // A different null from the one above, and a different sentence: nothing is on the
    // engine, so no caller hears anything and no republish is owed.
    const { container } = await render({
      [PENDING_PATH]: {
        ...pendingRoute({
          configured: stored("vidya"),
          live: null,
          republish_required: false,
          headline:
            "This agent is not on the voice platform yet; publishing it will use Vidya.",
        }),
        published: false,
        agent_status: "draft",
      },
    });

    await screen.findByLabelText("Voice");
    expect(container.textContent).toContain("Nothing — not on the voice platform yet");
    expect(container.textContent).not.toContain(
      "Publishing this agent is what moves the voice callers hear.",
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
        live_voice_id: "anushka",
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

    // And the read that feeds the "in force" block is refetched, because the write moved
    // `voice.configured` and deliberately left `voice.live` alone. Without this the panel
    // would keep showing the previous configuration next to the sentence saying it just
    // changed.
    await waitFor(() =>
      expect(calls.filter((c) => c.path === PENDING_PATH).length).toBeGreaterThan(1),
    );
  });

  it("states the reason, not an error, when the engine supplies its own voices", async () => {
    // D-93. THREE things must all be true at once, and each of them is a way the screen
    // used to be able to lie:
    //
    //  - no picker. A dropdown listing Bulbul entries against an engine that only speaks
    //    its own voices is a screen offering a choice the caller will never hear. Not
    //    rendered-and-disabled either: a disabled list still says "these are your options".
    //  - no ProblemNotice. Nothing is broken. An error card here sends an operator to a
    //    runbook for a deployment working exactly as designed.
    //  - the voice in force is STILL shown. "What do callers hear right now" remains a
    //    fair question; it is only the answer that is not ours to change.
    const { container } = await render({ [VOICES_PATH]: DICTATED_CATALOGUE });

    await screen.findByText(/supplies its own voices/);
    expect(screen.queryByLabelText("Voice")).toBeNull();
    expect(screen.queryByRole("button", { name: "Set voice" })).toBeNull();
    // The server's sentence, verbatim — the panel does not compose its own from the flags
    // and get the tone wrong.
    expect(container.textContent).toContain("Nothing is wrong with this agent.");
    // Still answering the question it can answer.
    expect(container.textContent).toContain("Callers hear now");
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
