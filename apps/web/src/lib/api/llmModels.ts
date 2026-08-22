"use client";

/**
 * WHICH LANGUAGE MODEL A CLIENT'S AGENTS THINK WITH — the organisation default, and the
 * per-agent override that can decline it.
 *
 *   GET /v1/organization/llm-defaults   what is in force, and what may be chosen
 *   PUT /v1/organization/llm-defaults   the organisation's own default (`null` = ours)
 *   PATCH /v1/agents/{agent_id}         `llm_model` — `null` = inherit the above
 *
 * ## Why a client gets this control at all, when D-21 reserves most of an agent
 *
 * D-21's boundary is about what an agent SAYS and what it CAPTURES: a script or an
 * extraction-schema change regenerates prompt hints and needs a regression run, so both
 * route through us. A model choice is not that. It is a PRICE, and the client is the one
 * paying it — `inr_per_minute_five_min` is on every option precisely so the decision can
 * be made with the number in front of the person making it. That is the same argument
 * `caps.ts` makes for the spending limit and `agents.ts` makes for the two disclosure
 * switches: the money and the legal exposure are the client's, so the switch is too.
 *
 * ## THREE FACTS THIS MODULE KEEPS RATHER THAN RECOMPUTES
 *
 * - **`effective_default` is the SERVER's answer**, not `default_llm_model ?? something`.
 *   A tenant with no default of their own inherits the platform's, and which model that
 *   is changes when we change it (`AZURE_OPENAI_DEFAULT_MODEL`, a live config switch per
 *   CLAUDE.md). A browser that resolved the fallback itself would name last quarter's
 *   model on a screen that is otherwise about a bill.
 * - **`llm_model_source` is how inheritance is DISPLAYED**, and it is a wire string read
 *   through `lookup` rather than derived from `llm_model === null`. The two agree today;
 *   the day the server adds a fourth source — a campaign-level choice, a per-lane
 *   override — the derived version says "your organisation default" about something that
 *   is not it, silently and on the screen where a client checks exactly that.
 * - **Prices are exact decimal STRINGS all the way to the pixel** (hard rule 7's frontend
 *   shadow). Nothing here parses one; `lib/llmRates.ts` compares and subtracts them as
 *   digits, and refuses rather than rounds.
 *
 * ## THE GENERATED TYPES DO NOT CARRY THESE FIELDS YET, AND THAT IS SAID HERE OUT LOUD
 *
 * `lib/api/client.ts` doctrine is that wire types ALIAS `schema.d.ts` so they cannot
 * drift from the API, and every alias below would be one line if the schema had them.
 * The endpoint is being built in parallel and `pnpm gen:api` has not run against it, so
 * the three shapes are written out here, marked, and shaped so that regeneration
 * REPLACES them rather than colliding with them:
 *
 *   - `OrganizationLlmDefaults` -> `Schemas["LlmDefaultsOut"]`,
 *     `LlmModelOption` -> `Schemas["LlmModelOptionOut"]`,
 *     `SetOrganizationLlmDefaultIn` -> `Schemas["LlmDefaultIn"]`
 *     (the server's own model names, read off `apps/api/agents/llm_routes.py`, so the
 *     swap is three lines and not a rename of every caller).
 *   - `AgentLlmFields` becomes nothing at all: the three fields land on `AgentOut`, and
 *     `Agent & AgentLlmFields` is then the same type as `Agent`.
 *   - `AgentModelPatch` becomes `AgentUpdateIn`, for the same reason.
 *
 * Nothing here is hand-edited into `schema.d.ts` — that file is generated and a hand
 * edit is a lie the next `gen:api` silently deletes. Nothing here ASSERTS onto a wire
 * type either (`tests/wireFixtureGuard.test.ts`), so a generated shape that differs from
 * what was agreed fails the build rather than compiling over the difference.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { agentKeys, type Agent, type AgentUpdateIn } from "./agents";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

/**
 * THE WIRE TYPES ARE THE GENERATED ONES, NOT A SECOND COPY OF THEM.
 *
 * These three were hand-written while `gen:api` had not yet run, and were shaped so the
 * swap would be mechanical. It has run, so they are aliases now. A hand-written mirror of
 * a wire shape is the defect class this repo already pays for elsewhere: it does not fail
 * when it drifts, it silently keeps compiling against a contract the server stopped
 * serving. `is_available` and `unavailable_reason` were optional in the hand-written
 * versions because an API build predating them reported neither; the generated shape makes
 * both REQUIRED, which is the correct claim now that every build serves them.
 *
 * `inr_per_minute_five_min` is what a minute costs on a FIVE-MINUTE call — the server
 * publishes one normalised figure per model rather than a raw token price, because a
 * client cannot price a token and can price a call. It is a decimal string and stays one:
 * see `lib/llmRates.ts` for why it is never parsed into a number.
 *
 * `is_available` is CAN THIS PLATFORM ACTUALLY RUN IT. A model with no Azure deployment
 * behind it would be quoted at its own price and answered by a different one, so `PUT`
 * refuses it with `llm_model_not_deployed`. A screen renders such a row DISABLED with
 * `unavailable_reason` beside it rather than hiding it, so the reader can see what is left
 * to configure instead of wondering where a model went.
 */
type Schemas = components["schemas"];

export type LlmModelOption = Schemas["LlmModelOptionOut"];
export type OrganizationLlmDefaults = Schemas["LlmDefaultsOut"];
export type SetOrganizationLlmDefaultIn = Schemas["LlmDefaultIn"];

/**
 * `/v1`, like every other client-realm route in this console.
 *
 * The contract this was built against writes the path as `/organization/llm-defaults`;
 * every route `lib/api` reaches is mounted under the API's `/v1` prefix (`/v1/agents`,
 * `/v1/usage`, `/v1/billing/caps`), so the version is not optional and its absence in the
 * contract note is a shorthand — confirmed against the route itself, which is registered
 * as `/v1/organization/llm-defaults` (`apps/api/agents/llm_routes.py`). Named once here
 * so that if it ever moves, one constant moves rather than four call sites.
 */
export const ORGANIZATION_LLM_DEFAULTS_PATH = "/v1/organization/llm-defaults";

export const llmModelKeys = {
  organizationDefaults: (org: string) => ["llm-defaults", org] as const,
};

/**
 * The catalogue and the organisation's place in it — ONE read, shared by both screens.
 *
 * The agent screen needs exactly the same three things the settings screen does (what may
 * be chosen, what each costs, what the organisation default currently resolves to), so it
 * uses this hook rather than a second endpoint: one key, one cache entry, one answer. A
 * per-agent catalogue read would also make the agent screen disagree with the settings
 * screen for as long as one of the two was stale.
 *
 * A long stale window because a price list changes when we change it, not on a timer —
 * `agents.ts` makes the same judgement about agent configuration.
 *
 * `enabled` exists for ONE caller and one real state: the agent panel cannot know whether
 * it has anything to show until it has read the agent, and on an API build that does not
 * report a model it shows nothing at all. Hooks run before that decision can be made, so
 * without this the panel fetches a catalogue it will never paint — a request per agent
 * screen, on exactly the deployments that have no use for it. Same shape and same
 * argument as `useArchivedAgents(session, enabled)`.
 */
export function useOrganizationLlmDefaults(
  session: Session,
  enabled = true,
): UseQueryResult<OrganizationLlmDefaults> {
  return useQuery({
    queryKey: llmModelKeys.organizationDefaults(session.orgSlug),
    queryFn: () => apiRequest<OrganizationLlmDefaults>(session, ORGANIZATION_LLM_DEFAULTS_PATH),
    enabled,
    staleTime: 5 * 60_000,
  });
}

/**
 * Set — or clear — the organisation's default model.
 *
 * PUT states the WHOLE field, `caps.ts`'s argument: `null` is a real choice ("use
 * Calevate's default, whatever it becomes") rather than "leave this alone", and a partial
 * verb would need a third state that JSON makes easy to send by accident.
 *
 * **The agent reads are invalidated too, and that is the whole correctness of this hook.**
 * Every agent that has NOT been given a model of its own carries `llm_model_effective`
 * computed from this value, so a roster or detail row painted from cache after this
 * returns would name the model the client just moved away from — on the screen where they
 * went to check that it moved. Awaited rather than `void`ed for `agents.ts`'s reason: the
 * button stops saying "Saving…" only once the screens behind it can paint the new answer.
 *
 * NOT optimistic, deliberately. The server may refuse this — an unknown model, a model
 * the tenant's plan does not include — and an optimistic write shows the new price for
 * the moment it takes to be told no, which on a money control is the wrong way round.
 */
export function useSetOrganizationLlmDefault(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: SetOrganizationLlmDefaultIn) =>
      apiRequest<OrganizationLlmDefaults>(session, ORGANIZATION_LLM_DEFAULTS_PATH, {
        method: "PUT",
        body: input,
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: llmModelKeys.organizationDefaults(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.allDetails(session.orgSlug) }),
      ]),
  });
}

/* ═══════════════════════════════════════════════════════════════════════════════════
 * THE AGENT'S OWN CHOICE
 * ═══════════════════════════════════════════════════════════════════════════════════ */

/**
 * The three sources the API names today — the KEY TYPE of a copy table, not a claim that
 * the wire can only carry these.
 *
 * `Record<LlmModelSource, …>` is what makes `tsc` fail when a fourth source arrives and
 * nobody has written words for it, which is the whole value of naming the union. What it
 * is deliberately NOT is the type of `AgentLlmView.source`: that field holds whatever the
 * server sent, and it is narrowed at the READ by `lookup` (src/lib/lookup.ts), so a source
 * this build has never seen leaves the copy table silent instead of indexing past it.
 */
export type LlmModelSource = "agent" | "organization" | "platform";

/**
 * The three fields `GET /v1/agents/{id}` gained — optional here ONLY because the
 * generated `AgentOut` has not been regenerated yet (see the module docstring).
 *
 * Optional is also the honest shape against an API build that predates the endpoint:
 * `undefined` is "this deployment does not report it", which the screen renders as
 * nothing rather than as a model name it made up.
 */
/**
 * An agent as this feature reads one — now simply `Agent`.
 *
 * `AgentLlmFields` stood here declaring the three fields OPTIONAL, because it was written
 * before `gen:api` had run and an API build predating them reported none. `gen:api` has
 * run and `AgentOut` carries all three as REQUIRED, so the shim is deleted rather than
 * left as a second, weaker description of the same wire shape — its own docstring said
 * this was the plan. Keeping it would have been worse than redundant: intersecting a
 * required field with an optional one yields `string | null | undefined`, so every caller
 * would have had to handle an `undefined` the server cannot send.
 *
 * The alias survives the deletion because call sites read better naming what they mean,
 * and because a later API version that made a field optional again would land here.
 */
export type AgentWithLlm = Agent;

/**
 * What `PATCH /v1/agents/{agent_id}` accepts, plus the field the contract adds.
 *
 * The intersection is what lets `useUpdateAgent` stay the ONE mutation for this endpoint.
 * A second hook issuing the same PATCH with its own invalidation set is the shape
 * `agents.ts` deleted twice (`useUpdateLeadStatus`, `useExportLeads`) — one route, two
 * ways, and the second list of cache keys is always the one that forgets a key.
 */
export type AgentModelPatch = AgentUpdateIn & { llm_model?: string | null };

/**
 * The patch that sets — or clears — one agent's model.
 *
 * A function rather than an inline literal at the call site so the `null` is written down
 * once WITH what it means: omitting the field leaves the agent alone, and sending `null`
 * puts it back on the organisation default. Those are different requests and they are one
 * keystroke apart.
 */
export function agentModelPatch(model: string | null): AgentModelPatch {
  return { llm_model: model };
}

/** What an agent screen has to say about where its model came from. */
export interface AgentLlmView {
  /** The agent's own override, or `null` when it is inheriting. */
  chosen: string | null;
  /** The model this agent actually runs on. */
  effective: string;
  /**
   * WHERE that model came from, exactly as the server spelled it.
   *
   * A bare wire string rather than `LlmModelSource`, on purpose: narrowing it here would
   * need an assertion, and an assertion onto a wire value is the instruction to stop
   * checking the one thing that matters (`tests/wireFixtureGuard.test.ts` argues it at
   * length for the generated types). The screen reads it through `lookup` instead.
   */
  source: string | undefined;
}

/**
 * The agent's model state, or `null` when this API build does not report one.
 *
 * `null` rather than a default-shaped object, and the distinction is `VoiceFacts`' in
 * `agents/panels.tsx`: a missing fact is honest and an invented one is not, so the whole
 * panel disappears on an older API rather than announcing that every agent is on the
 * platform default.
 *
 * `source` is passed through UNNARROWED and is read through `lookup` at the screen: it
 * arrives from the wire, and a fourth source the server adds must leave the copy table
 * silent instead of indexing past it.
 */
export function agentLlmView(agent: AgentWithLlm): AgentLlmView | null {
  const effective = agent.llm_model_effective;
  if (effective === undefined || effective === "") return null;
  return { chosen: agent.llm_model ?? null, effective, source: agent.llm_model_source };
}

/**
 * The model this platform puts an account on when the account has chosen nothing.
 *
 * It has to be read out of `available` and CANNOT be read off `effective_default`: that
 * field resolves to the account's own choice the moment they have one, so on exactly the
 * screen where the difference matters it stops naming the platform's. `undefined` when the
 * catalogue names no default — a real state, in which "use the Calevate default" has no
 * stated outcome and the screen says so rather than naming a model.
 *
 * ⚠ `lib/api/llmDefaults.ts` (the ADMIN realm's half of this feature, another lane's file)
 * carries an identical `platformDefaultOption` of its own. It already imports its wire
 * types and `modelOption` from here — its docstring calls this module the shared
 * vocabulary — so that copy should import this one and be deleted. Not done here because
 * that file is the admin realm's and is being written in parallel.
 */
export function platformDefaultOption(
  options: readonly LlmModelOption[],
): LlmModelOption | undefined {
  return options.find((option) => option.is_platform_default);
}

/**
 * The catalogue entry for one model id, or `undefined` when the list does not carry it.
 *
 * `undefined` is a real state rather than a defensive nicety: an agent can sit on a model
 * that has since been withdrawn from the catalogue, and the screens print its bare id
 * with no price instead of dropping the row — the same rule `AgentIdentity` follows for a
 * language this build cannot name.
 */
export function modelOption(
  options: readonly LlmModelOption[],
  model: string | null | undefined,
): LlmModelOption | undefined {
  if (model === null || model === undefined) return undefined;
  return options.find((option) => option.model === model);
}
