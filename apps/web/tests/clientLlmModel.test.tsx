import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AgentDetailPage from "@/app/c/[slug]/agents/[agentId]/page";
import ClientLlmModelPage from "@/app/c/[slug]/settings/models/page";
import type { Me } from "@/lib/api/client";
import type { AgentWithLlm, ClientLlmDefaults } from "@/lib/api/llmModels";
import type { PendingState } from "@/lib/api/publishing";

import { problem, renderClientPage, stillLoading } from "./harness";
import {
  AGENT_SPEND_PATH,
  LANES,
  LEGAL_READY,
  prepaidWallet,
  agentScript,
  clientLlmTiers,
  spendThisMonth,
  agentCallHandling,
  clientVoiceTuning,
  agentReadiness,
} from "./fixtures/sharedReads";
import { ENGINE_CATALOGUE_PATH } from "@/lib/api/engineCatalogue";
import { businessProfileFixture } from "./businessProfileFixture";
import { LIVE_ENGINE_MODELS, operatorEngineCatalogue } from "./fixtures/engineCatalogue";

// An agent's own model is the workspace's Model section; the settings page reads no
// section, so the one mock serves both screens in this file.
const nav = vi.hoisted(() => ({ section: "model" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(`section=${nav.section}`),
  usePathname: () => "/c/acme/agents/agent-1",
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
 * A CLIENT CHOOSING THE AI MODEL TIER THEIR AGENTS THINK WITH — the account default, and
 * one agent's override of it (D-680).
 *
 * What can be wrong here, in falling order of what a wrong render costs:
 *
 * 1. **A model or a vendor on a client's screen** (D-679). The client chooses Standard,
 *    Plus or Pro; which company's model answers is ours. Asserted on the whole rendered
 *    text, against every model family and provider word, because the failure is a sentence
 *    somebody added, not a field somebody remembered.
 * 2. **A price that has been through a float.** Every figure is a rate the client is billed
 *    at; asserted on the DIGITS and on the absence of the float artefact.
 * 3. **Inheritance shown as a choice, or a choice shown as inheritance.** `llm_tier_source`
 *    is the server's answer and the screen renders it rather than deriving it. Following the
 *    level above is its own first row and sends `null`; a tier row pins that tier.
 * 4. **A save that looks like it worked.** No optimistic write, and no save offered until
 *    something has changed.
 * 5. **A body that says more than the client moved.** `llm_tier: null` means "go back to
 *    inheriting" while OMITTING the field means "leave this agent alone".
 */

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: [
    "agents:read",
    "calls:read",
    "leads:read",
    "billing:read",
    "org:read",
    "org:manage",
    "kb:write",
  ],
  impersonating: false,
  withheld_acts: [],
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

/** A staff member: everything except the permission that changes an account setting. */
const STAFF: Me = {
  ...OWNER,
  role: "staff",
  permissions: ["agents:read", "org:read"],
};

/** Model families and provider words that must never render on a client surface. */
const VENDOR_WORDS = /\b(gpt|gemini|openai|azure|google|claude|anthropic|prana)\b|gpt-|4o-mini|flash-lite/i;

function defaults(over: Partial<ClientLlmDefaults> = {}): ClientLlmDefaults {
  return clientLlmTiers(over);
}

/** The tiers as a real deployment serves them: Plus not switched on yet. */
function withAnUnavailableTier(): ClientLlmDefaults {
  const base = defaults();
  return {
    ...base,
    available: base.available.map((option) =>
      option.tier === "plus"
        ? {
            ...option,
            is_available: false,
            unavailable_reason:
              "it isn't switched on for your account yet; ask your Calevate team to enable it",
          }
        : option,
    ),
  };
}

/**
 * One picker row by the START of its accessible name. Anchored, because the inherit row's
 * own description says "Today that is Standard".
 */
function radio(name: RegExp): HTMLInputElement {
  return screen.getByRole("radio", { name }) as HTMLInputElement;
}

/** The radio once it can take a click: the picker stays disabled until the write permission
 * is read, and a click before that is silently dropped. */
async function enabledRadio(name: RegExp): Promise<HTMLInputElement> {
  const found = (await screen.findByRole("radio", { name })) as HTMLInputElement;
  await waitFor(() => expect(found.disabled).toBe(false));
  return found;
}

const settingsPage = <ClientLlmModelPage params={Promise.resolve({ slug: "acme" })} />;

function settingsRoutes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/organization/llm-defaults": defaults(),
    ...over,
  };
}

describe("the account's default model tier", () => {
  it("names tiers and never a model or the company behind it", async () => {
    const { container } = await renderClientPage(settingsPage, settingsRoutes());

    await screen.findByRole("radio", { name: /^Standard/ });
    for (const label of ["Standard", "Plus", "Pro"]) {
      expect(radio(new RegExp(`^${label}`))).toBeTruthy();
    }
    expect(container.textContent ?? "").not.toMatch(VENDOR_WORDS);
    // No provider sub-groups: a tier belongs to no vendor on this screen.
    expect(screen.queryByRole("group", { name: VENDOR_WORDS })).toBeNull();
  });

  it("prices every tier at the precision the server sent, and never through a float", async () => {
    const { container } = await renderClientPage(settingsPage, settingsRoutes());

    await screen.findByRole("radio", { name: /^Standard/ });
    expect(container.textContent).toContain("+₹1.5000 / min");
    expect(container.textContent).toContain("No extra charge");
    expect(container.textContent).not.toContain("₹1.50 /");
    expect(container.textContent).toContain("₹1.5000 more a minute");
    expect(container.textContent).not.toContain("1.5000000");
    // The row in force says what it is rather than "same price".
    expect(container.textContent).toContain("the model running now");
  });

  it("keeps the explainer's links inside the sentence, not beside it", async () => {
    await renderClientPage(settingsPage, settingsRoutes());

    for (const [name, rest] of [
      ["Usage tab of Credits & billing", "What you are actually billed for the month"],
      ["Agents", "One agent can be put on a different tier"],
    ] as const) {
      const link = await screen.findByRole("link", { name });
      const wrapper = link.parentElement;
      expect(wrapper?.tagName).toBe("SPAN");
      expect(wrapper?.textContent).toContain(rest);
      expect(wrapper?.parentElement?.tagName).toBe("LI");
      // The sentence is the item's only child: no glyph beside it (D-771).
      expect(wrapper?.parentElement?.childElementCount).toBe(1);
    }
  });

  it("is a skeleton while the read is in flight, and names no tier", async () => {
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/organization/llm-defaults": stillLoading() }),
    );

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(container.textContent).not.toContain("Standard");
    expect(container.textContent).not.toContain("₹");
  });

  it("refuses rather than naming a tier when the read fails", async () => {
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "/v1/organization/llm-defaults": problem(503, {
          title: "Calevate could not read your settings.",
          detail: "Calevate could not read your settings.",
          retryable: true,
        }),
      }),
    );

    await screen.findByRole("alert");
    expect(container.textContent).not.toContain("Standard");
    expect(container.textContent).not.toContain("₹");
  });

  it("sends the tier the client picked, and re-reads what is in force", async () => {
    const { calls } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "PUT /v1/organization/llm-defaults": defaults({
          default_llm_tier: "plus",
          effective_tier: "plus",
          effective_tier_label: "Plus",
        }),
      }),
    );

    await act(async () => {
      fireEvent.click(await enabledRadio(/^Plus/));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ default_llm_tier: "plus" });
    await waitFor(() => {
      const reads = calls.filter(
        (call) => call.method === "GET" && call.path === "/v1/organization/llm-defaults",
      );
      expect(reads.length).toBeGreaterThan(1);
    });
  });

  it("sends null when the client hands the choice back to Calevate", async () => {
    const { calls } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "/v1/organization/llm-defaults": defaults({
          default_llm_tier: "plus",
          effective_tier: "plus",
          effective_tier_label: "Plus",
        }),
        "PUT /v1/organization/llm-defaults": defaults(),
      }),
    );

    const follow = await enabledRadio(/^Calevate's default/);
    await act(async () => {
      fireEvent.click(follow);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ default_llm_tier: null });
  });

  it("shows the server's own refusal and leaves the tier in force unchanged", async () => {
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "PUT /v1/organization/llm-defaults": problem(422, {
          type: "urn:calevate:validation/llm_tier_not_available",
          title: "That AI model tier is not switched on yet",
          detail: "Plus isn't switched on for your account yet.",
          remediation: "Choose one of Standard for now, or ask your Calevate team to enable Plus.",
          retryable: false,
        }),
      }),
    );

    await act(async () => {
      fireEvent.click(await enabledRadio(/^Plus/));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    const refusal = await screen.findByRole("alert");
    expect(refusal.textContent).toContain("Plus isn't switched on for your account yet.");
    // Nothing moved: the account still follows Calevate's default, which is what runs now.
    expect(radio(/^Calevate's default/).closest("label")?.textContent).toContain("the model running now");
    // The bar stays, its button on the error face; no saved tick anywhere.
    expect(screen.getByRole("button", { name: /Save model/ }).getAttribute("data-status")).toBe("error");
    expect(container.querySelector('[data-status="success"]')).toBeNull();
    expect(screen.queryAllByRole("status").some((s) => /saved/i.test(s.textContent ?? ""))).toBe(false);
  });

  it("says so when the tier in force is one this platform cannot run yet", async () => {
    const blocked = defaults({ effective_is_available: false });
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "/v1/organization/llm-defaults": {
          ...blocked,
          available: blocked.available.map((option) =>
            option.is_platform_default
              ? {
                  ...option,
                  is_available: false,
                  unavailable_reason:
                    "it isn't switched on for your account yet; ask your Calevate team to enable it",
                }
              : option,
          ),
        },
      }),
    );

    await waitFor(() =>
      expect(container.textContent).toContain("so calls use our standard model"),
    );
    // Following the default stays possible; pinning a tier that cannot run does not.
    await waitFor(() => expect(radio(/^Calevate's default/).disabled).toBe(false));
    expect(radio(/^Standard/).disabled).toBe(true);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("shows a tier this platform cannot run, disabled, with the server's reason", async () => {
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/organization/llm-defaults": withAnUnavailableTier() }),
    );

    await waitFor(() => expect(radio(/^Standard/).disabled).toBe(false));
    expect(radio(/^Plus/).disabled).toBe(true);
    expect(container.textContent).toContain("ask your Calevate team to enable it");
    expect(container.textContent).not.toContain("deployment");
    expect(container.textContent).not.toContain("ops console");
    expect(container.textContent).toContain("+₹1.5000 / min");
  });

  it("never disables a row on an API build that does not report availability", async () => {
    // Plain JSON rather than today's strict type: this is the wire an older API serves.
    const base = defaults();
    const olderBuild = {
      ...base,
      available: base.available.map((option) => {
        const rest: Record<string, unknown> = { ...option };
        delete rest.is_available;
        delete rest.unavailable_reason;
        return rest;
      }),
    };
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/organization/llm-defaults": olderBuild }),
    );

    await waitFor(() => expect(radio(/^Plus/).disabled).toBe(false));
    expect(container.textContent).not.toContain("Unavailable");
  });

  it("tells a staff member why they cannot change it, instead of letting them find out", async () => {
    const { container } = await renderClientPage(settingsPage, settingsRoutes({ "/v1/me": STAFF }));

    await screen.findByText(/Only an account owner can change which AI model/);
    expect(container.textContent).toContain("your agents use");
    for (const option of screen.getAllByRole("radio")) {
      expect((option as HTMLInputElement).disabled).toBe(true);
    }
    expect(screen.queryByRole("button", { name: /Save model/ })).toBeNull();
  });

  it("opens the picker to a view-as admin (D-587)", async () => {
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/me": { ...OWNER, impersonating: true, withheld_acts: [] } }),
    );

    await screen.findByText("Model for all your agents");
    await waitFor(() => expect(radio(/^Standard/).disabled).toBe(false));
    expect(container.textContent).not.toContain("read-only");
  });
});

/* ═══════════════════════════════════════════════════════════════════════════════════
 * ONE AGENT'S OVERRIDE
 * ═══════════════════════════════════════════════════════════════════════════════════ */

function agent(over: Partial<AgentWithLlm> = {}): AgentWithLlm {
  return {
    id: "agent-1",
    name: "Reception",
    direction: "inbound",
    status: "live",
    published: true,
    engine: "thinnest",
    language_primary: "te-IN",
    reply_languages: ["te-IN"],
    disclosure_line: "Namaste, this is an AI assistant calling on behalf of Sri Clinic.",
    ai_disclosure_line: "Namaste, this is an AI assistant calling on behalf of Sri Clinic.",
    ai_disclosure_enabled: true,
    recording_notice_line: "This call is being recorded.",
    caller_memory_notice_line: "I keep a short note of what you ask about.",
    caller_memory_enabled: false,
    recording_notice_enabled: true,
    opening_line:
      "Namaste, this is an AI assistant calling on behalf of Sri Clinic. This call is being recorded.",
    script_opening_line: "",
    first_words: "Namaste, this is an AI assistant calling on behalf of Sri Clinic. This call is being recorded.",
    truthful_answer_rule:
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    archived_at: null,
    inbound_number_count: 1,
    extraction_fields: [],
    extraction_schema_version: 0,
    llm_tier: null,
    llm_tier_effective: "standard",
    llm_tier_label: "Standard",
    llm_tier_source: "organization",
    llm_surcharged: false,
    ...over,
  };
}

const OWN_PLUS: Partial<AgentWithLlm> = {
  llm_tier: "plus",
  llm_tier_effective: "plus",
  llm_tier_label: "Plus",
  llm_tier_source: "agent",
  llm_surcharged: true,
};

const pending: PendingState = {
  agent_id: "agent-1",
  agent_status: "live",
  published: true,
  has_pending: false,
  pending: [],
  effective_call_cap_s: 600,
  call_cap_is_platform_default: true,
  worst_case_call_cost_inr: "65.00",
  precedence_rule: "Script decides content, rules decide conduct, voice only changes delivery.",
  voice: {
    configured: { voice_id: "engine:anika", provider: null, voice_tier: "clear", catalog: null },
    live: { voice_id: "engine:anika", provider: null, voice_tier: "clear", catalog: null },
    republish_required: false,
    unnamed_note: null,
    headline: "Callers hear Anika.",
  },
  voice_tier_rates: [],
  engine_verification: {
    state: "applied",
    confirmed: true,
    publishable: true,
    verified_at: "2026-08-15T09:20:00Z",
    headline: "The voice platform was read back and is running this script and voice.",
  },
};

const agentPage = (
  <AgentDetailPage params={Promise.resolve({ slug: "acme", agentId: "agent-1" })} />
);

function agentRoutes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/agents/agent-1": agent(),
    "/v1/agents/agent-1/pending": pending,
    "/v1/agents/agent-1/call-handling": agentCallHandling(),
    "/v1/agents/agent-1/script": agentScript(),
    "/v1/kb/sources": [],
    "/v1/organization/llm-defaults": defaults(),
    // The other panels this screen mounts, stubbed so the only alert is the model panel's.
    "/v1/agents/agent-1/actions": {
      api_actions_enabled: false,
      calendar_available: false,
      tools: [],
    },
    "/v1/integrations/credentials": [],
    "/v1/teach/questions?agent_id=agent-1": { items: [], open_count: 0 },
    "/v1/agents/agent-1/handoff": {
      agent_id: "agent-1",
      enabled: false,
      trigger: null,
      effective_trigger: "Hand the call to a person when the caller asks for one.",
      spoken_line: "Okay, I am putting you through to someone from our team now.",
      members: [],
      recent: [],
      on_duty_member_id: null,
      unavailable_reason: "disabled",
      remediation: "Transfer to a person is off for this agent. Turn it on to use it.",
      published: true,
    },
    "/v1/agents/lanes": LANES,
    // "What it is", beside the model in the Settings tab (D-825).
    "/v1/business-profile": businessProfileFixture(),
    // The header's "spent this month" line (owners hold billing:read).
    [AGENT_SPEND_PATH]: spendThisMonth(),
    ...over,
  };
}

describe("where one agent's model tier came from", () => {
  it("says an inheriting agent is following the account, and where to change that", async () => {
    const { container } = await renderClientPage(agentPage, agentRoutes());

    await screen.findByText(/^Follows your organisation default\./);
    expect(screen.getByRole("link", { name: /Change it for every agent/ })).toBeTruthy();
    const follow = await screen.findByRole("radio", { name: /^Organisation default/ });
    expect((follow as HTMLInputElement).checked).toBe(true);
    expect(follow.closest("label")?.textContent).toContain("Standard now");
    expect(follow.closest("label")?.textContent).toContain("the model running now");
    expect((radio(/^Standard/) as HTMLInputElement).checked).toBe(false);
    const model = screen.getByRole("heading", { level: 3, name: "Model" }).closest("section") as HTMLElement;
    expect(within(model).queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Save model/ })).toBeNull();
    expect(container.textContent).not.toContain("Follow my organisation");
    expect(container.textContent ?? "").not.toMatch(VENDOR_WORDS);
  });

  it("says an overridden agent has its own tier, and what it adds to the bill", async () => {
    const { container } = await renderClientPage(
      agentPage,
      agentRoutes({ "/v1/agents/agent-1": agent(OWN_PLUS) }),
    );

    await screen.findByText(/^Set for this agent\./);
    expect(container.textContent).toContain("Your organisation default does not change it");
    expect(screen.queryByText(/^Follows your organisation default\./)).toBeNull();
    const plus = await screen.findByRole("radio", { name: /^Plus/ });
    expect((plus as HTMLInputElement).checked).toBe(true);
    expect(plus.closest("label")?.textContent).toContain("+₹1.5000 / min");
    expect(plus.closest("label")?.textContent).toContain("the model running now");
  });

  it("puts an overridden agent back on the account default with an explicit null", async () => {
    const { calls } = await renderClientPage(
      agentPage,
      agentRoutes({
        "/v1/agents/agent-1": agent(OWN_PLUS),
        "PATCH /v1/agents/agent-1": agent(),
      }),
    );

    await act(async () => {
      fireEvent.click(await enabledRadio(/^Organisation default/));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    const patch = calls.find((call) => call.method === "PATCH");
    expect(JSON.parse(patch?.body ?? "{}")).toEqual({ llm_tier: null });
  });

  it("sends only the tier when an agent is given one of its own", async () => {
    const { calls } = await renderClientPage(
      agentPage,
      agentRoutes({ "PATCH /v1/agents/agent-1": agent(OWN_PLUS) }),
    );

    await act(async () => {
      fireEvent.click(await enabledRadio(/^Plus/));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    const patch = calls.find((call) => call.method === "PATCH");
    expect(JSON.parse(patch?.body ?? "{}")).toEqual({ llm_tier: "plus" });
  });

  it("will not offer one agent a tier this platform cannot run", async () => {
    const { container } = await renderClientPage(
      agentPage,
      agentRoutes({ "/v1/organization/llm-defaults": withAnUnavailableTier() }),
    );

    await waitFor(() => expect(radio(/^Standard/).disabled).toBe(false));
    expect(radio(/^Plus/).disabled).toBe(true);
    expect(container.textContent).toContain("ask your Calevate team to enable it");
    expect(container.textContent).not.toContain("deployment");
  });

  it("keeps an archived agent's tier as a fact, with no control to change it", async () => {
    const { container } = await renderClientPage(
      agentPage,
      agentRoutes({
        "/v1/agents/agent-1": agent({ status: "archived", archived_at: "2026-07-01T00:00:00Z" }),
      }),
    );

    await screen.findByText(/^Follows your organisation default\./);
    expect(screen.queryByRole("radio", { name: /^Standard/ })).toBeNull();
    expect(container.textContent).toContain("part of the record of what it did");
  });
});

describe("each fact is said once", () => {
  it("lists each tier once, after one row for following Calevate's default", async () => {
    const { container } = await renderClientPage(settingsPage, settingsRoutes());

    const follow = await screen.findByRole("radio", { name: /^Calevate's default/ });
    expect((follow as HTMLInputElement).checked).toBe(true);
    expect(follow.closest("label")?.textContent).toContain("Standard now");
    const standard = radio(/^Standard/);
    expect(standard.checked).toBe(false);
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    const text = container.textContent ?? "";
    expect(text).not.toContain("In force now");
    expect(text).not.toContain("Use the Calevate default");
    expect(text).not.toContain("The tier we run by default");
    // Once on the follow row and once on Standard, and nowhere else.
    expect(text.split("No extra charge")).toHaveLength(3);
    expect(follow.closest("label")?.textContent).toContain("No extra charge");
    expect(standard.closest("label")?.textContent).toContain("No extra charge");
  });

  it("pins the default tier only when the owner picks its own row", async () => {
    const { calls } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "PUT /v1/organization/llm-defaults": defaults({ default_llm_tier: "standard" }),
      }),
    );

    // Owner access resolves after the first paint; a click on a still-disabled row is lost.
    await waitFor(() => expect(radio(/^Standard/).disabled).toBe(false));
    await act(async () => {
      fireEvent.click(radio(/^Standard/));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ default_llm_tier: "standard" });
  });

  it("gives an unavailable tier its reason as a sentence, and no price", async () => {
    await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/organization/llm-defaults": withAnUnavailableTier() }),
    );

    const plus = await screen.findByRole("radio", { name: /^Plus/ });
    const row = plus.closest("label")?.textContent ?? "";
    expect(row).toContain("It isn't switched on for your account yet; ask your Calevate team to enable it.");
    expect(row).not.toContain("₹");
    expect(row).not.toContain("No extra charge");
    expect(row).not.toContain("Unavailable");
  });
});

/* ═══════════════════════════════════════════════════════════════════════════════════
 * NO MODEL NAME ON ANY CLIENT SCREEN (D-679)
 * ═══════════════════════════════════════════════════════════════════════════════════ */

describe("a client's screens never name a model", () => {
  afterEach(() => {
    nav.section = "model";
  });

  /**
   * The platform's real model names, as production lists them. The engine catalogue is
   * served here in its OPERATOR shape, names and all, so this fails if any client surface
   * renders what it is given rather than only what a client may read.
   */
  const NAMES = LIVE_ENGINE_MODELS.map((model) => model.name);
  const leaking = (text: string) => NAMES.filter((name) => text.includes(name));

  for (const section of ["overview", "voice", "model", "calls", "advanced"]) {
    it(`renders none on the agent's ${section} section`, async () => {
      nav.section = section;
      const { container } = await renderClientPage(
        agentPage,
        agentRoutes({
          [ENGINE_CATALOGUE_PATH]: operatorEngineCatalogue(),
          "/v1/agents/agent-1": agent({ engine_model_id: "engine-model:gpt-5-mini" }),
          // What Overview and Call handling read besides the model and the voice.
          "/v1/business-profile": businessProfileFixture(),
          "/v1/legal/readiness": LEGAL_READY,
          "/v1/billing/wallet": prepaidWallet(),
          "/v1/calls?agent_id=agent-1&limit=5": [],
          "/v1/agents/agent-1/voice-tuning": clientVoiceTuning(),
          "/v1/agents/agent-1/readiness": agentReadiness(),
        }),
      );
      await screen.findAllByText("Reception");
      if (section === "voice") await screen.findByText("Anjali");
      if (section === "voice") await screen.findByRole("heading", { name: "How it sounds" });
      if (section === "model") await screen.findByRole("radio", { name: /^Standard/ });
      expect(leaking(container.textContent ?? "")).toEqual([]);
      expect(container.textContent ?? "").not.toMatch(VENDOR_WORDS);
    });
  }

  it("renders none on the account's model settings", async () => {
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ [ENGINE_CATALOGUE_PATH]: operatorEngineCatalogue() }),
    );
    await screen.findByRole("radio", { name: /^Standard/ });
    expect(leaking(container.textContent ?? "")).toEqual([]);
  });
});

describe("on a voice platform whose model is included in the minute (D-750)", () => {
  it("shows one quiet line and no tier to choose", async () => {
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "/v1/organization/llm-defaults": defaults({
          tier_choosable: false,
          tier_note: "The language model is included in your per-minute price.",
        }),
      }),
    );

    expect(
      await screen.findByText("The language model is included in your per-minute price."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "About the language model" })).toBeTruthy();
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(screen.queryByText("How the model is billed")).toBeNull();
    expect(container.textContent ?? "").not.toMatch(VENDOR_WORDS);
  });
});
