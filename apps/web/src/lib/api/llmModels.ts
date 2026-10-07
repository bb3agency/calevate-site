"use client";

/**
 * WHICH LANGUAGE MODEL A CLIENT'S AGENTS THINK WITH — the organisation default, and the
 * per-agent override that can decline it.
 *
 *   GET /v1/organization/llm-defaults   what is in force, and which TIERS may be chosen
 *   PUT /v1/organization/llm-defaults   the organisation's own tier (`null` = ours)
 *   PATCH /v1/agents/{agent_id}         `llm_tier` — `null` = inherit the above
 *
 * ## A client chooses a tier, never a model (D-679, D-680)
 *
 * The client realm's wire carries `standard` / `plus` / `pro` and the server's own words for
 * each. Which company's model answers a tier is ours and is resolved server-side
 * (`apps/api/agents/llm_tiers.py`), so nothing in the client realm can render a model id or a
 * provider: there is none on the wire to render. The ADMIN realm still reads real models —
 * `LlmModelOption` / `OrganizationLlmDefaults` below are the admin endpoint's shapes, used by
 * `lib/api/llmDefaults.ts` and the operator's model page.
 *
 * ## Why a client gets this control at all, when D-21 reserves most of an agent
 *
 * A tier choice is a PRICE, and the client is the one paying it —
 * `client_surcharge_inr_per_minute` is on every tier so the decision is made with the number
 * in front of the person making it.
 *
 * ## Facts this module keeps rather than recomputes
 *
 * - **`effective_tier` and `in_force_surcharge_inr_per_minute` are the SERVER's answers.** The
 *   surcharge in force depends on who chose the model (following Calevate's default is never
 *   surcharged) and on the model behind the tier, and only the server knows the second.
 * - **`llm_tier_source` is how inheritance is DISPLAYED**, read through `lookup` rather than
 *   derived from `llm_tier === null`, so a fourth source the server adds leaves the copy
 *   table silent instead of being described as something it is not.
 * - **Prices are exact decimal STRINGS all the way to the pixel** (hard rule 7's frontend
 *   shadow); `lib/llmRates.ts` compares them as digits.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { agentKeys, type Agent, type AgentUpdateIn } from "./agents";
import { apiRequest, type Session } from "./client";
import { lookup } from "@/lib/lookup";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The CLIENT realm's shapes: tiers, never models. */
export type LlmTierOption = Schemas["LlmTierOptionOut"];
export type ClientLlmDefaults = Schemas["ClientLlmDefaultsOut"];
export type SetClientLlmTierIn = Schemas["ClientLlmDefaultIn"];
export type LlmTier = LlmTierOption["tier"];

/**
 * The ADMIN realm's shapes: real models, with what each costs Calevate and adds to the
 * client's bill. Read only by the operator's console (`lib/api/llmDefaults.ts`).
 */
export type LlmModelOption = Schemas["LlmModelOptionOut"];
export type OrganizationLlmDefaults = Schemas["LlmDefaultsOut"];
export type SetOrganizationLlmDefaultIn = Schemas["LlmDefaultIn"];

/** `/v1`, like every other client-realm route; named once so a move is one edit. */
export const ORGANIZATION_LLM_DEFAULTS_PATH = "/v1/organization/llm-defaults";

export const llmModelKeys = {
  organizationDefaults: (org: string) => ["llm-defaults", org] as const,
};

/**
 * The tiers and the organisation's place among them — ONE read, shared by the settings screen
 * and the agent screen, so the two cannot disagree while one is stale.
 *
 * `enabled` exists for the agent panel, which cannot know whether it has anything to show
 * until it has read the agent; without it the panel fetches a catalogue it never paints.
 */
export function useOrganizationLlmDefaults(
  session: Session,
  enabled = true,
): UseQueryResult<ClientLlmDefaults> {
  return useQuery({
    queryKey: llmModelKeys.organizationDefaults(session.orgSlug),
    queryFn: () => apiRequest<ClientLlmDefaults>(session, ORGANIZATION_LLM_DEFAULTS_PATH),
    enabled,
    staleTime: 5 * 60_000,
  });
}

/**
 * Set — or clear — the organisation's tier.
 *
 * PUT states the WHOLE field: `null` is a real choice ("use Calevate's default, whatever it
 * becomes"). The agent reads are invalidated too, because every agent that has not chosen
 * carries a tier computed from this value. NOT optimistic: the server may refuse a tier that
 * is not switched on, and a money control must not show the new price for the moment it takes
 * to be told no.
 */
export function useSetOrganizationLlmDefault(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: SetClientLlmTierIn) =>
      apiRequest<ClientLlmDefaults>(session, ORGANIZATION_LLM_DEFAULTS_PATH, {
        method: "PUT",
        body: input,
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({
          queryKey: llmModelKeys.organizationDefaults(session.orgSlug),
        }),
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
        client.invalidateQueries({
          queryKey: agentKeys.allDetails(session.orgSlug),
        }),
      ]),
  });
}

/* ═══════════════════════════════════════════════════════════════════════════════════
 * THE AGENT'S OWN CHOICE
 * ═══════════════════════════════════════════════════════════════════════════════════ */

/**
 * The three sources the API names today — the KEY TYPE of a copy table, so `tsc` fails when a
 * fourth arrives with no words written for it. NOT the type of `AgentLlmView.source`, which
 * holds whatever the server sent and is narrowed at the read by `lookup`.
 */
export type LlmModelSource = "agent" | "organization" | "platform";

export type AgentWithLlm = Agent;
export type AgentModelPatch = AgentUpdateIn;

/**
 * The patch that sets — or clears — one agent's tier. Omitting the field leaves the agent
 * alone and sending `null` puts it back on the organisation default: different requests one
 * keystroke apart, so the `null` is written down once with what it means.
 */
export function agentModelPatch(tier: LlmTier | null): AgentModelPatch {
  return { llm_tier: tier };
}

/** What an agent screen has to say about where its tier came from. */
export interface AgentLlmView {
  /** The agent's own tier, or `null` when it is inheriting. */
  chosen: LlmTier | null;
  /** The tier this agent actually runs on. */
  effective: LlmTier;
  /** The server's word for `effective`. */
  label: string;
  /** WHERE it came from, exactly as the server spelled it (read through `lookup`). */
  source: string;
  /** Does the plan's model surcharge apply to this agent's minutes? The server's answer. */
  surcharged: boolean;
}

export function agentLlmView(agent: AgentWithLlm): AgentLlmView {
  return {
    chosen: agent.llm_tier ?? null,
    effective: agent.llm_tier_effective,
    label: agent.llm_tier_label,
    source: agent.llm_tier_source,
    surcharged: agent.llm_surcharged,
  };
}

/**
 * THE TIER THIS AGENT WAS GIVEN OF ITS OWN, as its label, or `null` when it follows a level
 * above it — the roster's question ("which of my agents has been taken off the account
 * default?"). Keyed on `source`, never `chosen !== null`, for `AgentLlmView.source`'s reason.
 */
export function agentOwnTier(agent: AgentWithLlm): string | null {
  const view = agentLlmView(agent);
  return view.source === "agent" ? view.label : null;
}

/**
 * WHAT THE TIER IN FORCE ADDS TO THIS AGENT'S BILL, per minute (D-455). The server decides
 * WHETHER (`llm_surcharged`: an upgraded model the client chose) and the plan decides HOW MUCH
 * (`upgrade_surcharge_inr_per_minute`), so nothing here re-derives the billing rule.
 */
export function agentInForceSurcharge(
  view: AgentLlmView,
  defaults: ClientLlmDefaults,
): string {
  return view.surcharged ? defaults.upgrade_surcharge_inr_per_minute : "0";
}

/** The tier Calevate puts an account on when it has chosen nothing. */
export function platformDefaultTier(
  options: readonly LlmTierOption[],
): LlmTierOption | undefined {
  return options.find((option) => option.is_platform_default);
}

/** The tier row for one tier, or `undefined` when the list does not carry it. */
export function tierOption(
  options: readonly LlmTierOption[],
  tier: string | null | undefined,
): LlmTierOption | undefined {
  if (tier === null || tier === undefined) return undefined;
  return options.find((option) => option.tier === tier);
}

/**
 * THE CLIENT FALLBACK for a tier the server marks unavailable without a reason. It mirrors the
 * server's `CLIENT_UNAVAILABLE_REASON` (`apps/api/agents/llm_models.py`) and is reached only on
 * an API build that omits it.
 */
export const MODEL_UNAVAILABLE_FALLBACK_CLIENT =
  "it isn't switched on for your account yet; ask your Calevate team to enable it.";

/** Why this tier cannot be chosen, or `null` when it can. */
export function tierUnavailableReason(option: LlmTierOption): string | null {
  if (option.is_available !== false) return null;
  return option.unavailable_reason ?? MODEL_UNAVAILABLE_FALLBACK_CLIENT;
}

/* ═══════════════════════════════════════════════════════════════════════════════════
 * THE OPERATOR'S VIEW — real models. Never imported by a client-realm screen.
 * ═══════════════════════════════════════════════════════════════════════════════════ */

/**
 * WHAT THE MODEL IN FORCE ADDS TO THE ACCOUNT'S BILL, on the admin realm's model rows. An
 * account that has chosen nothing FOLLOWS the platform default and is never surcharged, so
 * the resolved model's row would quote a charge the meter will not apply.
 */
export function inForceSurcharge(defaults: OrganizationLlmDefaults): string | null {
  if (defaults.default_llm_model === null) return "0";
  return (
    modelOption(defaults.available, defaults.effective_default)
      ?.client_surcharge_inr_per_minute ?? null
  );
}

export function platformDefaultOption(
  options: readonly LlmModelOption[],
): LlmModelOption | undefined {
  return options.find((option) => option.is_platform_default);
}

/**
 * OUR NAME FOR EACH MODEL PROVIDER, for the operator. An unknown key returns unchanged, so a
 * provider the server adds before this table learns its name still renders as something.
 */
export const PROVIDER_LABELS: Readonly<Record<string, string>> = {
  azure_openai: "Azure OpenAI",
  openai: "OpenAI",
  google: "Google Gemini",
};

export function providerLabel(provider: string): string {
  return lookup(PROVIDER_LABELS, provider) ?? provider;
}

/** The operator's fallback for a model marked unavailable with no reason. */
export const MODEL_UNAVAILABLE_FALLBACK =
  "it is not set up to run here yet — either no provider credential is installed for it, or its price has not been attested — so a call would run a different model.";

/**
 * Why this model cannot be chosen, or `null` when it can. `=== false`, never a truthiness
 * test: an API build predating the field reports `undefined`, which must disable nothing.
 */
export function unavailableReason(option: LlmModelOption): string | null {
  if (option.is_available !== false) return null;
  return option.unavailable_reason ?? MODEL_UNAVAILABLE_FALLBACK;
}

/**
 * The catalogue entry for one model id, or `undefined` when the list does not carry it — a
 * real state: an account can sit on a model since withdrawn from the catalogue.
 */
export function modelOption(
  options: readonly LlmModelOption[],
  model: string | null | undefined,
): LlmModelOption | undefined {
  if (model === null || model === undefined) return undefined;
  return options.find((option) => option.model === model);
}
