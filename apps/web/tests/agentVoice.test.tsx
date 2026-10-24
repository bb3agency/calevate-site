import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentPromptPage from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page";
import { ENGINE_CATALOGUE_PATH, type EngineCatalogue } from "@/lib/api/engineCatalogue";
import type { AgentVoice, AgentVoiceState } from "@/lib/api/publishing";
import type { VoiceTuning } from "@/lib/api/voiceTuning";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";
import { agentRow } from "./fixtures/sharedReads";
/*
 * The agent page is a settings layout (D-661, D-657): one section is mounted at a time,
 * chosen by `?section=`. Every case here opens Voice.
 */
const nav = vi.hoisted(() => ({ params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  usePathname: () => "/admin/tenants/t/agents/a/prompt",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

/**
 * The Voice section of the operator's agent screen: the voice platform's own voices, read
 * through the tenant's view-as session, and the voice in force beside the configured one.
 *
 * What is pinned:
 *
 * 1. **The catalogue is read through the tenant's impersonation session**, and the save goes
 *    through the agent update route on that same session, sending only the field that moved.
 * 2. **A failed catalogue read is a refusal, never an empty picker** — a list with no voices
 *    reads as "this account has none", a claim built from a dead request.
 * 3. **CONFIGURED IS NOT LIVE, and both are on screen.** The write touches our row only; the
 *    voice platform keeps the voice it was last published with until the next publish, so
 *    both are rendered as labelled data and the server's own sentence sits above them.
 * 4. **An engine that hosts no voices shows no picker and no error**, and still answers what
 *    callers hear now.
 */

const TENANT = "0192f0aa-8888-7000-8000-0000000000a1";
const AGENT = "0192f0aa-8888-7000-8000-0000000000b2";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const ME_PATH = "/v1/admin/me";
const HISTORY_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/prompt`;
const PENDING_PATH = `/v1/agents/${AGENT}/pending`;
const LANES_PATH = "/v1/agents/lanes";
const EXPERIMENT_PATH = `/v1/agents/${AGENT}/experiment`;
const TUNING_PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/voice-tuning`;

const TUNING_OPTIONS: VoiceTuning["options"] = {
  speed_min: "0.6",
  speed_max: "1.5",
  volume_min: "0.5",
  volume_max: "2.0",
  emotions: ["neutral", "calm", "happy"],
  models: ["sonic-3.6", "sonic-3.5", "sonic-2"],
  old_model: "sonic-2",
  dictionary_id_pattern: "^[A-Za-z0-9][A-Za-z0-9_-]{2,79}$",
  preview_text_max_chars: 200,
};

function tuning(over: Partial<VoiceTuning> = {}): VoiceTuning {
  return {
    agent_id: AGENT,
    studio: false,
    speed: null,
    volume: null,
    emotion: null,
    model: null,
    dictionary_id: null,
    options: TUNING_OPTIONS,
    ...over,
  };
}

/** A platform that speaks its own voices: one voice priced, one not. */
const ENGINE_CATALOGUE: EngineCatalogue = {
  available: true,
  complete: true,
  choosable: true,
  studio_available: false,
  note: "1 of 2 voices can be chosen today.",
  voices: [
    {
      voice_id: "engine:3b7e",
      label: "Anjali",
      rung: "clear",
      language_note: "Speaks Telugu, Hindi and English.",
      preview_available: false,
      is_custom: false,
      offerable: true,
      reason: null,
      standing: "offered",
    },
    {
      voice_id: "engine:priya",
      label: "Priya",
      rung: "clear",
      language_note: "Speaks Hindi.",
      preview_available: false,
      is_custom: false,
      offerable: false,
      reason: "No rupee-per-minute rate is attested for the Clear rung.",
      standing: "offered",
    },
  ],
  models: [
    {
      model_id: "gpt-4.1",
      label: "GPT-4.1",
      call_capable: false,
      plan_allows: false,
      offerable: false,
      reason: "ThinnestAI lists this model as too slow to answer a phone call.",
      usable_with_studio_voice: true,
      band_disagrees: false,
    },
  ],
};

/** The platform publishes no voices of its own — the list renders nothing. */
const NO_ENGINE_CATALOGUE: EngineCatalogue = {
  available: false,
  complete: true,
  choosable: true,
  studio_available: false,
  note: "Voices on this account come from Calevate's own catalogue.",
  voices: [],
  models: [],
};

/** A stored voice the server can name, as `GET /v1/agents/{id}/pending` answers it. */
function named(speaker: string): AgentVoice {
  const id = `sonic-3.5:${speaker.toLowerCase()}`;
  return {
    voice_id: id,
    provider: "cartesia",
    voice_tier: "studio",
    catalog: {
      id,
      label: speaker,
      provider: "cartesia",
      tts_model: "sonic-3.5",
      speaker: speaker.toLowerCase(),
      gender: "female",
      languages: ["te-IN", "hi-IN", "en-IN"],
      note: "A studio read.",
      verified: true,
    },
  };
}

/** The default agent: published, and the platform holding the voice the row says it is. */
const VOICE_IN_SYNC: AgentVoiceState = {
  configured: named("Ananya"),
  live: named("Ananya"),
  republish_required: false,
  unnamed_note: null,
  headline: "Callers hear Ananya — the voice platform is holding the configured voice.",
};

function pendingRoute(voiceState: AgentVoiceState) {
  return {
    voice_tier_rates: [],
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
    engine_verification: {
      state: "applied",
      confirmed: true,
      verified_at: "2026-08-15T09:20:00Z",
      headline: "The voice platform was read back and is running this script and voice.",
    },
  };
}

function render(over: Partial<Routes> = {}) {
  return renderAdminRoute(
    <AgentPromptPage params={routeParams({ tenantId: TENANT, agentId: AGENT })} />,
    {
      [TENANT_PATH]: { id: TENANT, name: "Sunrise Clinic", slug: "sunrise" },
      "/v1/agents": [agentRow({ id: AGENT })],
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
      [ENGINE_CATALOGUE_PATH]: ENGINE_CATALOGUE,
      [TUNING_PATH]: tuning(),
      ...over,
    },
  );
}

const radio = (name: RegExp) => screen.getByRole("radio", { name }) as HTMLInputElement;

describe("the voice panel", () => {
  beforeEach(() => {
    nav.params = new URLSearchParams("section=voice");
  });

  it("reads the platform's voices through the tenant's impersonation session", async () => {
    const { calls } = await render();

    await screen.findByRole("radio", { name: /Anjali/ });
    const read = calls.filter((call) => call.path === ENGINE_CATALOGUE_PATH);
    expect(read.length).toBeGreaterThan(0);
    // Without the header the client verifier rejects the admin token on a `/v1/agents/…` path.
    expect(read.every((call) => call.headers["X-Impersonate-Org"] === "sunrise")).toBe(true);
  });

  it("lists the platform's voices with the reason each cannot be used, quietly", async () => {
    const { container } = await render();

    await screen.findByText("Anjali");
    expect(container.textContent).toContain("1 of 2 voices can be chosen today.");
    expect(container.textContent).toContain(
      "No rupee-per-minute rate is attested for the Clear rung",
    );
    expect(container.querySelector(".text-warn")).toBeNull();
    expect(radio(/Anjali/).disabled).toBe(false);
    expect(radio(/Priya/).disabled).toBe(true);
    // The models are their own section, not part of Voice.
    expect(screen.queryByRole("radio", { name: /GPT-4\.1/ })).toBeNull();
  });

  it("saves the voice it picks through the agent update route, as the client", async () => {
    const { calls } = await render({
      [`PATCH /v1/agents/${AGENT}`]: agentRow({ id: AGENT, engine_voice_id: "engine:3b7e" }),
    });

    // Nothing saved yet, so "Platform default" is checked and no save is offered.
    const fallback = await screen.findByRole("radio", { name: /Platform default/ });
    await waitFor(() => expect((fallback as HTMLInputElement).checked).toBe(true));
    expect(screen.queryByRole("button", { name: "Use this voice" })).toBeNull();
    fireEvent.click(radio(/Anjali/));
    fireEvent.click(await screen.findByRole("button", { name: "Use this voice" }));

    const path = `/v1/agents/${AGENT}`;
    await waitFor(() =>
      expect(calls.some((c) => c.path === path && c.method === "PATCH")).toBe(true),
    );
    const write = calls.find((c) => c.path === path && c.method === "PATCH")!;
    expect(JSON.parse(write.body!)).toEqual({ engine_voice_id: "engine:3b7e" });
    expect(write.headers["X-Impersonate-Org"]).toBe("sunrise");
  });

  it("renders a refusal, not an empty picker, when the voices cannot be read", async () => {
    await render({
      [ENGINE_CATALOGUE_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "The voice platform is unavailable.",
        retryable: true,
      }),
    });

    await screen.findByText("The voice platform is unavailable.");
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
  });

  it("shows no picker and no error where the platform hosts no voices, and still says what callers hear", async () => {
    const { container } = await render({ [ENGINE_CATALOGUE_PATH]: NO_ENGINE_CATALOGUE });

    await screen.findByText("Callers hear now");
    await waitFor(() =>
      expect(radios(container).some((input) => input.name === "engine-voice")).toBe(false),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.textContent).toContain("Ananya (sonic-3.5)");
  });

  it("shows an agent with no voice set as exactly that", async () => {
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: null,
        live: null,
        republish_required: false,
        unnamed_note: null,
        headline: "No voice has been set on this agent.",
      }),
    });

    await screen.findByText("No voice has been set on this agent.");
    expect(container.textContent).toContain("None set");
  });

  it("names the LIVE voice and the CONFIGURED one separately when they differ", async () => {
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: named("Lehara"),
        live: named("Ananya"),
        republish_required: true,
        unnamed_note: null,
        headline: "Callers still hear Ananya; Lehara reaches them at the next publish.",
      }),
    });

    await screen.findByText("Callers still hear Ananya; Lehara reaches them at the next publish.");
    expect(container.textContent).toContain("Callers hear now");
    expect(container.textContent).toContain("Ananya (sonic-3.5)");
    expect(container.textContent).toContain("Configured");
    expect(container.textContent).toContain("Lehara (sonic-3.5)");
    // And who closes the gap: only a publish does.
    expect(container.textContent).toContain(
      "Publishing this agent is what moves the voice callers hear.",
    );
  });

  it("says a published agent's live voice is unrecorded rather than calling it in sync", async () => {
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: named("Lehara"),
        live: null,
        republish_required: true,
        unnamed_note: null,
        headline:
          "Callers hear whatever voice was last published; we have no record of which. Lehara reaches them at the next publish.",
      }),
    });

    await screen.findByText(/we have no record of which/);
    expect(container.textContent).toContain("Not recorded — publish to be sure");
  });

  it("says an unpublished agent has no live voice at all", async () => {
    const { container } = await render({
      [PENDING_PATH]: {
        ...pendingRoute({
          configured: named("Lehara"),
          live: null,
          republish_required: false,
          unnamed_note: null,
          headline: "This agent is not on the voice platform yet; publishing it will use Lehara.",
        }),
        published: false,
        agent_status: "draft",
      },
    });

    await screen.findByText(/not on the voice platform yet; publishing it will use Lehara/);
    expect(container.textContent).toContain("Nothing — not on the voice platform yet");
    expect(container.textContent).not.toContain(
      "Publishing this agent is what moves the voice callers hear.",
    );
  });

  it("says a raw platform ref is a raw platform ref, instead of printing it bare", async () => {
    const ref = "engine:b6dafaa0-3a87-40b2-823c-1e4cf3c07314";
    const unnamed: AgentVoice = { voice_id: ref, provider: null, voice_tier: "clear", catalog: null };
    const note = "The code shown is the voice platform's own reference for this voice.";
    const { container } = await render({
      [PENDING_PATH]: pendingRoute({
        configured: unnamed,
        live: unnamed,
        republish_required: false,
        unnamed_note: note,
        headline: `Callers hear ${ref} — the voice platform is holding the configured voice.`,
      }),
    });

    await screen.findByText(note);
    expect(container.textContent).toContain(ref);
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

    await screen.findByRole("radio", { name: /Anjali/ });
    expect(radio(/Anjali/).disabled).toBe(true);
    expect(container.textContent).toContain(
      "does not have permission to change this agent's script",
    );
  });
});

function radios(container: HTMLElement): HTMLInputElement[] {
  return Array.from(container.querySelectorAll("input[type=radio]"));
}

describe("how a Studio voice sounds (operators only)", () => {
  beforeEach(() => {
    nav.params = new URLSearchParams("section=voice");
  });

  it("says the settings are for Studio voices on an agent that speaks none", async () => {
    const { calls } = await render();
    await screen.findByText(/can be set for a Studio voice/);
    expect(screen.queryByRole("button", { name: "Save settings" })).toBeNull();
    // Read through the operator's own session, never the tenant's view-as one.
    const read = calls.find((call) => call.path === TUNING_PATH)!;
    expect(read.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("saves every field as shown, an empty one as null, through the operator's door", async () => {
    const { calls } = await render({
      [TUNING_PATH]: tuning({ studio: true, speed: "0.95", emotion: "calm" }),
      [`PATCH ${TUNING_PATH}`]: tuning({ studio: true, speed: "0.95", volume: "1.40" }),
    });
    const volume = await screen.findByLabelText("Volume");
    expect((screen.getByLabelText("Speed") as HTMLInputElement).value).toBe("0.95");
    fireEvent.change(volume, { target: { value: "1.4" } });
    // The kit number box applies typing when it is left.
    fireEvent.blur(volume);
    fireEvent.change(screen.getByLabelText("Emotion"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() =>
      expect(calls.some((c) => c.path === TUNING_PATH && c.method === "PATCH")).toBe(true),
    );
    const write = calls.find((c) => c.path === TUNING_PATH && c.method === "PATCH")!;
    expect(JSON.parse(write.body!)).toEqual({
      speed: 0.95,
      volume: 1.4,
      emotion: null,
      model: null,
      dictionary_id: null,
    });
    await screen.findByText(/A live agent uses them from its next call/);
  });

  it("speaks the settings in the form before they are saved", async () => {
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:tuned"), revokeObjectURL: vi.fn() });
    Object.defineProperty(HTMLMediaElement.prototype, "play", {
      configurable: true,
      value: vi.fn(() => Promise.resolve()),
    });
    const preview = `POST ${TUNING_PATH}/preview`;
    const { calls } = await render({
      [TUNING_PATH]: tuning({ studio: true }),
      [preview]: () =>
        new Response(new Blob(["ID3"], { type: "audio/mpeg" }), {
          status: 200,
          headers: { "content-type": "audio/mpeg" },
        }),
    });
    const speed = await screen.findByLabelText("Speed");
    fireEvent.change(speed, { target: { value: "1.1" } });
    fireEvent.blur(speed);
    fireEvent.click(screen.getByRole("button", { name: "Hear it" }));

    await waitFor(() =>
      expect(calls.some((c) => c.path === `${TUNING_PATH}/preview`)).toBe(true),
    );
    const heard = calls.find((c) => c.path === `${TUNING_PATH}/preview`)!;
    expect(JSON.parse(heard.body!)).toMatchObject({ speed: 1.1, volume: null });
    expect(calls.some((c) => c.path === TUNING_PATH && c.method === "PATCH")).toBe(false);
  });

  it("says the older model takes no speed, volume or emotion", async () => {
    await render({ [TUNING_PATH]: tuning({ studio: true, model: "sonic-2" }) });
    await screen.findByText(/sonic-2 takes no speed, volume or emotion/);
  });
});
