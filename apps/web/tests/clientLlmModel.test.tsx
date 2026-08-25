import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentDetailPage from "@/app/c/[slug]/agents/[agentId]/page";
import ClientLlmModelPage from "@/app/c/[slug]/settings/models/page";
import type { Me } from "@/lib/api/client";
import type { AgentWithLlm, OrganizationLlmDefaults } from "@/lib/api/llmModels";
import type { PendingState } from "@/lib/api/publishing";

import { problem, renderClientPage, stillLoading } from "./harness";

/**
 * A CLIENT CHOOSING THE MODEL THEIR AGENTS THINK WITH — the account default, and one
 * agent's override of it.
 *
 * Five things can be wrong here, in falling order of what a wrong render costs:
 *
 * 1. **A price that has been through a float.** Every figure on these screens is a rate
 *    the client is billed at, and the difference between two adjacent models is the whole
 *    decision. `Number("0.4830") - Number("0.2400")` is `0.24300000000000002` — a number
 *    nobody was ever charged, on the screen where somebody decides what to pay. Hard rule
 *    7's frontend shadow, one step from the wallet, so it is asserted on the DIGITS and
 *    on the absence of the float artefact rather than on "a rupee sign is present".
 * 2. **A model named over a read that did not arrive.** §52: loading is a skeleton,
 *    failure is a refusal, and neither is a model name — because a model name here is
 *    also a claim about what a call costs.
 * 3. **Inheritance shown as a choice, or a choice shown as inheritance.** Three agents can
 *    print the same model name for three different reasons, and only one of them moves
 *    when the client changes their account default. `llm_model_source` is the server's
 *    answer to that and the screen renders it rather than deriving it.
 * 4. **A save that looks like it worked.** No optimistic write: a refused PUT must leave
 *    the sentence about what is in force exactly as it was, and must show the SERVER's
 *    problem+json — an unknown model and a model outside the plan are different refusals.
 * 5. **A body that says more than the client moved.** `llm_model: null` means "go back to
 *    inheriting" while OMITTING the field means "leave this agent alone"; they are one
 *    keystroke apart and they are opposite requests.
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
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

/** A staff member: everything except the permission that changes an account setting. */
const STAFF: Me = { ...OWNER, role: "staff", permissions: ["agents:read", "org:read"] };

/**
 * Two models a paisa-fraction apart, priced at FOUR decimal places.
 *
 * Deliberately not round numbers: `0.4830 - 0.2400` is the subtraction that a float gets
 * wrong, and two decimals would let `formatINR`-style rounding pass unnoticed.
 */
function defaults(over: Partial<OrganizationLlmDefaults> = {}): OrganizationLlmDefaults {
  return {
    default_llm_model: null,
    effective_default: "gpt-4o-mini",
    available: [
      {
        model: "gpt-4o-mini",
        provider: "azure_openai",
        platform_cost_inr_per_minute: "0.2400",
        client_surcharge_inr_per_minute: "0",
        is_platform_default: true,
        is_available: true,
        unavailable_reason: null,
      },
      {
        model: "gpt-4.1-mini",
        provider: "azure_openai",
        platform_cost_inr_per_minute: "0.4830",
        client_surcharge_inr_per_minute: "1.5000",
        is_platform_default: false,
        is_available: true,
        unavailable_reason: null,
      },
    ],
    ...over,
  };
}

/**
 * The catalogue as a REAL deployment serves it: one model addressable, the other allow-
 * listed but not runnable here yet.
 *
 * This is not an exotic state — it is the shipped one. The API marks such a row
 * `is_available: false` and refuses selecting it with `llm_model_not_deployed`, because
 * the wire addresses a deployment id and a selection we accepted but could not address
 * would quote a client one model's price for calls another model answered.
 *
 * THE REASON IS THE CLIENT SENTENCE, because this is the CLIENT endpoint. The server sends
 * the client realm the audience-appropriate wording (`agents/llm_models.py::unofferable_
 * reason(audience="client")`), never the operator ground — a client has no ops console, no
 * keys and no vendor portal, so "install the provider's key" would tell them to do the
 * impossible. The operator sees the ground on the admin console; the client sees the one
 * action they have.
 */
function withAnUndeployedModel(): OrganizationLlmDefaults {
  const base = defaults();
  return {
    ...base,
    available: base.available.map((option) =>
      option.model === "gpt-4.1-mini"
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
 * One picker row by the START of its accessible name.
 *
 * Anchored, because the label wraps the whole row: the "Use the Calevate default" row's
 * own description says "Today that is gpt-4o-mini", so an unanchored /gpt-4o-mini/
 * matches two radios and `getByRole` throws on the ambiguity rather than testing anything.
 */
function radio(name: RegExp): HTMLInputElement {
  return screen.getByRole("radio", { name }) as HTMLInputElement;
}

const settingsPage = <ClientLlmModelPage params={Promise.resolve({ slug: "acme" })} />;

function settingsRoutes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/organization/llm-defaults": defaults(),
    ...over,
  };
}

describe("the account's default model", () => {
  it("prices every option at the precision the server sent, and never through a float", async () => {
    const { container } = await renderClientPage(settingsPage, settingsRoutes());

    await screen.findByText(/In force now: gpt-4o-mini/);
    // The server's own digits, at four decimal places. ₹1.50 would be `formatINR`'s
    // two-decimal rounding, which misquotes a rate by enough to matter over a month.
    expect(container.textContent).toContain("+₹1.5000 / min");
    // A model that adds nothing says so in WORDS. "₹0.0000 / min" is a rupee amount of
    // nothing on a screen answering a yes/no question.
    expect(container.textContent).toContain("No extra charge");
    expect(container.textContent).not.toContain("₹1.50 /");
    // ⚠ OUR SUPPLIER COST IS NOT ON THIS SCREEN (D-455). It used to be, under the words
    // "what a minute costs" — a figure nobody is charged, and our margin published to the
    // account it is a margin on (`apps/api/billing/rates.py::llm_cost_inr_per_minute`
    // states both halves). It lives on the admin console now.
    expect(container.textContent).not.toContain("0.2400");
    expect(container.textContent).not.toContain("0.4830");
  });

  it("states the difference between two models exactly", async () => {
    const { container } = await renderClientPage(settingsPage, settingsRoutes());

    await screen.findByText(/In force now/);
    // 1.5000 − 0, in decimal, and the difference is now a claim about the CLIENT'S BILL
    // rather than about our supplier cost (D-455): choosing this model really does add
    // ₹1.5000 to every minute they are charged for. `Number()` arithmetic on rates like
    // 0.4830 − 0.2400 produces 0.24300000000000002, which is what `lib/llmRates.ts`
    // exists to make unwriteable — asserted below on a value that would show it.
    expect(container.textContent).toContain("₹1.5000 more a minute");
    expect(container.textContent).not.toContain("0.24300000000000002");
    // The row in force says what it is rather than "same price", which would otherwise
    // appear on two rows with no way to tell which is which.
    expect(container.textContent).toContain("the model running now");
    // AND THE SCREEN NO LONGER PROMISES THE BILL DOES NOT MOVE. That sentence was true
    // until `plans.llm_model_surcharge` existed and is false the moment a founder sets
    // one, so it is gone rather than qualified.
    expect(container.textContent).not.toContain("does not change when you switch");
  });

  it("is a skeleton while the read is in flight, and names no model", async () => {
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/organization/llm-defaults": stillLoading() }),
    );

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(container.textContent).not.toContain("gpt-4o-mini");
    expect(container.textContent).not.toContain("₹");
  });

  it("refuses rather than naming a model when the read fails", async () => {
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
    expect(container.textContent).not.toContain("gpt-4o-mini");
    expect(container.textContent).not.toContain("In force now");
    expect(container.textContent).not.toContain("₹");
  });

  it("sends the model the client picked, and re-reads what is in force", async () => {
    const { calls } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "PUT /v1/organization/llm-defaults": defaults({ default_llm_model: "gpt-4.1-mini" }),
      }),
    );

    await act(async () => {
      fireEvent.click(await screen.findByRole("radio", { name: /gpt-4\.1-mini/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    const put = calls.find((call) => call.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ default_llm_model: "gpt-4.1-mini" });
    // The write invalidates the read rather than patching the cache: what is in force is
    // the server's answer, and after a change it is the server that should say it.
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
        "/v1/organization/llm-defaults": defaults({ default_llm_model: "gpt-4.1-mini" }),
        "PUT /v1/organization/llm-defaults": defaults(),
      }),
    );

    await act(async () => {
      fireEvent.click(await screen.findByRole("radio", { name: /Use the Calevate default/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    const put = calls.find((call) => call.method === "PUT");
    // `null`, not an absent field: the API reads absence as "leave this alone" and `null`
    // as "follow whatever we run by default".
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ default_llm_model: null });
  });

  it("shows the server's own refusal and leaves the model in force unchanged", async () => {
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "PUT /v1/organization/llm-defaults": problem(422, {
          type: "urn:calevate:validation/model_not_in_plan",
          title: "That model is not included in your plan.",
          detail: "That model is not included in your plan.",
          remediation: "Ask your account manager to add it, or pick another model.",
          retryable: false,
        }),
      }),
    );

    await act(async () => {
      fireEvent.click(await screen.findByRole("radio", { name: /gpt-4\.1-mini/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    const refusal = await screen.findByRole("alert");
    expect(refusal.textContent).toContain("That model is not included in your plan.");
    expect(refusal.textContent).toContain("Ask your account manager to add it");
    // Nothing optimistic: the account is still on the model it was on.
    expect(container.textContent).toContain("In force now: gpt-4o-mini");
  });

  it("keeps a withdrawn model on screen rather than showing nothing selected", async () => {
    // A model is retired while an account is pinned to it. Dropping the row would leave a
    // picker with no selection on an account that is definitely running on something, and
    // would hide the one fact worth knowing: what it costs cannot be shown.
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({
        "/v1/organization/llm-defaults": defaults({
          default_llm_model: "gpt-4o-preview",
          effective_default: "gpt-4o-preview",
        }),
      }),
    );

    const pinned = await screen.findByRole("radio", { name: /gpt-4o-preview/ });
    expect((pinned as HTMLInputElement).checked).toBe(true);
    expect(container.textContent).toContain("We no longer offer this model");
    // Never ₹0.00 for a model we cannot price — the same rule the worst-case call cost
    // follows on the agent screen.
    expect(container.textContent).not.toContain("₹0.0000 / min");
  });

  it("shows a model this platform cannot run, disabled, with the server's reason", async () => {
    // THE DEFECT THIS PINS: the picker mapped every catalogue row into a selectable radio
    // and never read `is_available`, so on the shipped deployment a client could pick
    // `gpt-4.1-mini`, see its price beside it, and be answered with a 422. A control whose
    // only outcome is a refusal is worse than no control, and the price makes it worse
    // still — the screen quoted a rate for a choice the server would not take.
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/organization/llm-defaults": withAnUndeployedModel() }),
    );

    // The DEPLOYED row first, and awaited: the whole group is disabled until `/v1/me`
    // lands, so asserting on the blocked row at first paint would pass on a build that
    // disabled nothing. This is the assertion that proves the form is live.
    await waitFor(() => expect(radio(/^gpt-4o-mini/).disabled).toBe(false));
    expect(radio(/^gpt-4\.1-mini/).disabled).toBe(true);
    // Shown and explained, never hidden: a missing row tells a reader nothing, and the
    // reason is the one thing a CLIENT can act on — asking their Calevate team. The
    // operator ground (a deployment, a key, a price) never reaches this screen.
    expect(container.textContent).toContain("ask your Calevate team to enable it");
    expect(container.textContent).not.toContain("deployment");
    expect(container.textContent).not.toContain("ops console");
    // Priced as well as explained: the row states what it WOULD add to their bill, so a
    // client can see whether the model they cannot have is one they would have wanted.
    expect(container.textContent).toContain("+₹1.5000 / min");
  });

  it("never disables a row on an API build that does not report availability", async () => {
    // `undefined` is "this deployment does not say", which must disable nothing — the
    // same `=== false` rule the admin console follows. A truthiness test here would grey
    // out every option on an older server.
    // Written as plain JSON rather than annotated with today's strict type: annotating it
    // would assert the very shape under test, and `LlmModelOptionOut` makes both fields
    // required. This is the wire an older API serves, not a `LlmModelOption`.
    const olderBuild = {
      default_llm_model: null,
      effective_default: "gpt-4o-mini",
      available: [
        {
          model: "gpt-4o-mini",
          provider: "azure_openai",
          platform_cost_inr_per_minute: "0.2400",
          client_surcharge_inr_per_minute: "0",
          is_platform_default: true,
        },
        {
          model: "gpt-4.1-mini",
          provider: "azure_openai",
          platform_cost_inr_per_minute: "0.4830",
          client_surcharge_inr_per_minute: "1.5000",
          is_platform_default: false,
        },
      ],
    };
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/organization/llm-defaults": olderBuild }),
    );

    await waitFor(() => expect(radio(/^gpt-4\.1-mini/).disabled).toBe(false));
    expect(container.textContent).not.toContain("Cannot be chosen");
  });

  it("tells a staff member why they cannot change it, instead of letting them find out", async () => {
    const { container } = await renderClientPage(settingsPage, settingsRoutes({ "/v1/me": STAFF }));

    // Awaited rather than read after the defaults land: the reason comes from `/v1/me`,
    // which is a SECOND request, and asserting on the first one's paint is how a gate
    // that never renders passes.
    await screen.findByText(/Only an account owner can change which AI model/);
    expect(container.textContent).toContain("your agents use");
    const save = screen.getByRole("button", { name: /Save model/ });
    expect((save as HTMLButtonElement).disabled).toBe(true);
  });

  it("groups the offerable models under their provider labels, on equal footing", async () => {
    // THE FOUNDER'S DECISION (D-456): OpenAI and Gemini shown on par with Azure. The picker
    // turns each wire provider token (`azure_openai`, `openai`, `google`) into a friendly
    // heading through `providerLabel` and gathers that provider's models under it — one
    // radio group throughout, three labelled sub-groups within, no vendor the header act.
    const threeProviders = defaults({
      available: [
        ...defaults().available, // the two azure_openai models
        {
          model: "gpt-5-mini",
          provider: "openai",
          platform_cost_inr_per_minute: "0.3000",
          client_surcharge_inr_per_minute: "0.5000",
          is_platform_default: false,
          is_available: true,
          unavailable_reason: null,
        },
        {
          // A Gemini model CHEAPER than the base rate — its surcharge is "0", never a
          // negative, so the row reads "No extra charge" (the surcharge floors at zero on
          // the server; the picker must never render a minus sign against a cheaper model).
          model: "gemini-2.5-flash-lite",
          provider: "google",
          platform_cost_inr_per_minute: "0.1000",
          client_surcharge_inr_per_minute: "0",
          is_platform_default: false,
          is_available: true,
          unavailable_reason: null,
        },
      ],
    });
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/organization/llm-defaults": threeProviders }),
    );

    // Anchored: the inherit row's own name also contains "gpt-4o-mini" ("Today that is …").
    await screen.findByRole("radio", { name: /^gpt-4o-mini/ });
    // An EXACT string name, so "OpenAI" does not also match "Azure OpenAI".
    for (const label of ["Azure OpenAI", "OpenAI", "Google Gemini"]) {
      expect(
        screen.getByRole("group", { name: label }),
        `provider ${label} must head its own group`,
      ).toBeTruthy();
    }
    // Each model sits under its own provider, never crammed into another's group.
    const google = screen.getByRole("group", { name: "Google Gemini" });
    expect(google.textContent).toContain("gemini-2.5-flash-lite");
    expect(google.textContent).toContain("No extra charge");
    expect(screen.getByRole("group", { name: "OpenAI" }).textContent).toContain("gpt-5-mini");
    // A cheaper model is not a negative charge, anywhere on the screen.
    expect(container.textContent).not.toContain("-₹");
  });

  it("blocks the picker under a view-as admin, and says why — the D-22 gap flagged for RBAC", async () => {
    /**
     * THE FOUNDER WANTS AN IMPERSONATING ADMIN TO BE ABLE TO CHANGE THIS, and today they
     * cannot. `useWriteAccess` (`lib/api/hooks.ts`) disables every write for
     * `me.impersonating`, and the server would refuse it regardless: `org:manage` is in
     * `MUTATING_PERMISSIONS` and `core/auth.py::requires()` refuses a mutating permission to
     * an impersonating principal — D-22 view-as is read-only end to end. Enabling the
     * control on the client alone would hand the operator a 403, the reachable-but-refused
     * shape `useWriteAccess` exists to prevent.
     *
     * So this pins the CURRENT, truthful state — disabled, with the reason on screen, and
     * pointed at the admin console where the write DOES work — and FLAGS the gap: letting an
     * impersonating admin set the model needs an RBAC/back-end carve-out permitting this one
     * write under view-as. This lane must not weaken that permission check itself. When the
     * carve-out lands, this expectation flips to a submit. A gap no test names is one the
     * next change reopens silently.
     */
    const { container } = await renderClientPage(
      settingsPage,
      settingsRoutes({ "/v1/me": { ...OWNER, impersonating: true } }),
    );

    await screen.findByText(/viewing this account read-only/);
    // Directed at the working path, not a dead end.
    expect(container.textContent).toContain("Do it from the admin console instead");
    const save = screen.getByRole("button", { name: /Save model/ });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    // Awaited: the group is disabled by the same flag, which arrives on the /v1/me read.
    await waitFor(() => expect(radio(/^gpt-4o-mini/).disabled).toBe(true));
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
    engine: "bolna",
    language_primary: "te-IN",
    disclosure_line: "Namaste, this is an AI assistant calling on behalf of Sri Clinic.",
    ai_disclosure_line: "Namaste, this is an AI assistant calling on behalf of Sri Clinic.",
    ai_disclosure_enabled: true,
    recording_notice_line: "This call is being recorded.",
    recording_notice_enabled: true,
    opening_line:
      "Namaste, this is an AI assistant calling on behalf of Sri Clinic. This call is being recorded.",
    truthful_answer_rule:
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    archived_at: null,
    inbound_number_count: 1,
    extraction_fields: [],
    llm_model: null,
    llm_model_effective: "gpt-4o-mini",
    llm_model_source: "organization",
    ...over,
  };
}

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
    configured: { voice_id: "bulbul:v3", provider: "sarvam", catalog: null },
    live: { voice_id: "bulbul:v3", provider: "sarvam", catalog: null },
    republish_required: false,
    headline: "Callers hear Bulbul v3.",
  },
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
    "/v1/kb/sources": [],
    "/v1/organization/llm-defaults": defaults(),
    // The other panels this screen mounts. They are not this file's subject, but an
    // unstubbed route makes the harness THROW, and the panel then renders the generic
    // "We could not reach Calevate" notice — a second element with role="alert". The two
    // `findByRole("alert")` assertions below are about the MODEL panel's refusal, and
    // `findByRole` fails on ambiguity, so leaving these unstubbed turns those tests into a
    // race that CI loses more often than a laptop does.
    "/v1/agents/agent-1/actions": { api_actions_enabled: false, calendar_available: false, tools: [] },
    "/v1/integrations/credentials": [],
    "/v1/knowledge-gaps?agent_id=agent-1&status=open&limit=20": {
      items: [],
      open_count: 0,
      total: 0,
    },
    ...over,
  };
}

describe("where one agent's model came from", () => {
  it("says an inheriting agent is following the account, and where to change that", async () => {
    const { container } = await renderClientPage(agentPage, agentRoutes());

    await screen.findByText(/Using your organisation default: gpt-4o-mini/);
    expect(container.textContent).toContain("Every agent that has not been given its own");
    expect(screen.getByRole("link", { name: /Change it for every agent/ })).toBeTruthy();
    // WHAT IT ADDS TO THEIR BILL, from the same catalogue the picker uses — an override
    // is a per-agent price and is stated as one. Awaited on the PICKER rather than
    // asserted straight away: the catalogue is a second request, and until it lands the
    // panel deliberately states the model with no figure rather than a made-up one.
    //
    // This agent inherits the ACCOUNT default and the account is itself following the
    // PLATFORM default, so nothing was chosen by the client at any level and nothing is
    // surcharged — the server's own rule (`rates.CLIENT_CHOSEN_LLM_SOURCES` excludes
    // `platform`), rendered here rather than re-derived.
    await screen.findByRole("radio", { name: /Follow my organisation/ });
    expect(container.textContent).toContain("It adds nothing to what you are charged");
    // Never OUR cost on a client's screen (D-455).
    expect(container.textContent).not.toContain("0.2400");
  });

  it("says an overridden agent has its own model, not that it is inheriting", async () => {
    const { container } = await renderClientPage(
      agentPage,
      agentRoutes({
        "/v1/agents/agent-1": agent({
          llm_model: "gpt-4.1-mini",
          llm_model_effective: "gpt-4.1-mini",
          llm_model_source: "agent",
        }),
      }),
    );

    await screen.findByText(/This agent has its own model: gpt-4\.1-mini/);
    expect(container.textContent).toContain("ignores your organisation default");
    expect(container.textContent).not.toContain("Using your organisation default");
  });

  it("puts an overridden agent back on the account default with an explicit null", async () => {
    const { calls } = await renderClientPage(
      agentPage,
      agentRoutes({
        "/v1/agents/agent-1": agent({
          llm_model: "gpt-4.1-mini",
          llm_model_effective: "gpt-4.1-mini",
          llm_model_source: "agent",
        }),
        "PATCH /v1/agents/agent-1": agent(),
      }),
    );

    await act(async () => {
      fireEvent.click(await screen.findByRole("radio", { name: /Follow my organisation/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Go back to the organisation default/ }));
    });

    const patch = calls.find((call) => call.method === "PATCH");
    // ONLY `llm_model`, and `null` rather than absent: omitting the field would leave the
    // override in place, which is the opposite of what the button says.
    expect(JSON.parse(patch?.body ?? "{}")).toEqual({ llm_model: null });
  });

  it("sends only the model when an agent is given one of its own", async () => {
    const { calls } = await renderClientPage(
      agentPage,
      agentRoutes({ "PATCH /v1/agents/agent-1": agent({ llm_model: "gpt-4.1-mini" }) }),
    );

    await act(async () => {
      fireEvent.click(await screen.findByRole("radio", { name: /gpt-4\.1-mini/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save model/ }));
    });

    const patch = calls.find((call) => call.method === "PATCH");
    expect(JSON.parse(patch?.body ?? "{}")).toEqual({ llm_model: "gpt-4.1-mini" });
  });

  it("says nothing at all about a model on an API build that does not report one", async () => {
    // The three fields are absent until the endpoint ships. A card headed "The model it
    // thinks with" containing a shrug is worse than no card, and inventing "the Calevate
    // default" would be a price claim nobody made.
    // A route stub serves JSON, so this fixture is JSON — not an `Agent` with three holes
    // punched in it. The generated wire type makes all three fields REQUIRED, which is
    // correct for every build we serve; what this test describes is an OLDER build that
    // sends none of them. Typing it as a plain record says exactly that, and keeps `delete`
    // legal without casting away the shape the test exists to check.
    const bare: Record<string, unknown> = { ...agent() };
    delete bare.llm_model;
    delete bare.llm_model_effective;
    delete bare.llm_model_source;

    const { container, calls } = await renderClientPage(
      agentPage,
      agentRoutes({ "/v1/agents/agent-1": bare }),
    );

    await screen.findByText("What it is");
    expect(container.textContent).not.toContain("The model it thinks with");
    // And it does not fetch a catalogue it has nothing to show from.
    expect(calls.some((call) => call.path === "/v1/organization/llm-defaults")).toBe(false);
  });

  it("will not offer one agent a model this platform cannot run", async () => {
    // The agent panel had the same gap as the settings screen and for the same reason:
    // it mapped `available` straight into rows. `PATCH /v1/agents/{id}` refuses an
    // undeployed model with `llm_model_not_deployed` — the same predicate that decides
    // whether the agent could be PUBLISHED on it — so the click had one outcome.
    const { container } = await renderClientPage(
      agentPage,
      agentRoutes({ "/v1/organization/llm-defaults": withAnUndeployedModel() }),
    );

    // "Follow my organisation" is untouched — it resolves to a model that IS deployed —
    // and it is awaited first because the group is disabled until `/v1/me` lands.
    await waitFor(() => expect(radio(/^Follow my organisation/).disabled).toBe(false));
    expect(radio(/^gpt-4\.1-mini/).disabled).toBe(true);
    // The client sentence, never the operator ground — same audience rule as the settings
    // screen: a client has no deployment to create and no key to install.
    expect(container.textContent).toContain("ask your Calevate team to enable it");
    expect(container.textContent).not.toContain("deployment");
  });

  it("keeps an archived agent's model as a fact, with no control to change it", async () => {
    const { container } = await renderClientPage(
      agentPage,
      agentRoutes({
        "/v1/agents/agent-1": agent({ status: "archived", archived_at: "2026-07-01T00:00:00Z" }),
      }),
    );

    await screen.findByText(/Using your organisation default: gpt-4o-mini/);
    expect(screen.queryByRole("radio", { name: /Follow my organisation/ })).toBeNull();
    expect(container.textContent).toContain("part of the record of what it did");
  });
});
