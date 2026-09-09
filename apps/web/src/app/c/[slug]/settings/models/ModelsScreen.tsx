"use client";

import {
  Card,
  ProblemNotice,
  Skeleton,
} from "@/components/ui";
import { useOrganizationLlmDefaults } from "@/lib/api/llmModels";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { OrganizationDefault } from "./OrganizationDefault";

/**
 * THE AI MODEL A CLIENT'S AGENTS THINK WITH — the organisation-wide default.
 *
 * ## Why a client decides this
 *
 * Because they pay for it. Every option carries `client_surcharge_inr_per_minute` — what
 * choosing that model ADDS to this account's bill for every minute it runs (D-455) — and
 * the difference between the cheapest and the dearest is the difference between two phone
 * bills. D-21 reserves what an agent SAYS and what it CAPTURES because both need a
 * regression run against real calls; a price is neither, and the same argument that gives
 * a client their own spending limit (`/c/[slug]/usage`) and their own disclosure switches
 * (D-163) gives them this.
 *
 * **THIS SCREEN USED TO SAY THE CHOICE WAS FREE, AND UNTIL D-455 IT WAS.** The sentence
 * was "what you are charged for a call does not change when you switch, because your plan
 * prices a minute of conversation rather than the model behind it" — true, and the defect:
 * `gpt-4.1-mini` costs Calevate 2.7x the default and earned nothing. `plans
 * .llm_model_surcharge` is what a client now pays for the upgrade, so that sentence is
 * false and is gone. The figure this screen shows is theirs; OUR cost to run the model
 * (`platform_cost_inr_per_minute`) stays on the operator's console, because publishing a
 * supplier cost to the account it is a margin on is a different mistake.
 *
 * ## The three things this screen must not do
 *
 * 1. **Resolve the default itself.** A tenant with no choice of their own runs on ours,
 *    and which model that is is a live config switch (CLAUDE.md — `gpt-4o-mini` today,
 *    `gpt-4.1-mini` a switch away). `effective_default` is the server's answer and is
 *    rendered as it arrives; `default_llm_model ?? "gpt-4o-mini"` in a browser bundle
 *    would name last quarter's model on the screen where a client checks the price.
 * 2. **Show a model without its price.** That is the whole point of the surface, and it
 *    is why an option whose rate the catalogue does not carry renders `—` rather than
 *    being quietly dropped or shown as free.
 * 3. **Look saved before it is.** No optimistic write: the server can refuse a model
 *    (unknown id, one this plan does not include) and the refusal is problem+json with a
 *    sentence in it. An optimistic picker shows the new price for as long as it takes to
 *    be told no, which on a money control is exactly backwards. §52 governs the rest —
 *    loading is a skeleton, failure is a refusal, and neither is a model name.
 *
 * NO `<h1>`: the app shell renders the page title from the nav list it also renders.
 */
export function ModelsScreen({ slug }: { slug: string }) {
  const session = useClientSession();
  const state = useOrganizationLlmDefaults(session);

  /*
   * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * ## Declared HERE and not in `OrganizationDefault`, where the picker lives
   *
   * `registry.ts` keeps a stack and the innermost registration wins — and child effects
   * commit before their parent's, so a surface declared in the child would be shadowed by
   * one declared here. One of the two, therefore, and it is this one: the child renders
   * only after the read lands, so a declaration down there would leave the launcher
   * missing on the loading screen and on the failed one, which are the two screens a
   * person is most likely to be asking a question from.
   *
   * ## And nothing is writable
   *
   * Choosing the model is a per-minute CHARGE on every call this account makes
   * (`client_surcharge_inr_per_minute`, D-455). It is one click behind an explicit Save,
   * and it is not an act to hand to an assistant. The catalogue IS declared, with each
   * option's surcharge, so "which of these is cheaper" is answerable without the
   * assistant being able to act on the answer.
   */
  useCopilotSurface({
    route: "/c/{slug}/settings/models",
    title: "Which AI model your agents use",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: state.data
          ? "the model settings below have loaded"
          : state.error != null
            ? "the settings failed to load, so no model is named on screen"
            : "still loading",
      },
      ...(state.data
        ? [
            {
              key: "account_choice",
              label: "The model this account has chosen",
              value: state.data.default_llm_model ?? "none — it follows the Calevate default",
            },
            {
              key: "effective_default",
              label: "The model agents actually run on unless given their own",
              value: state.data.effective_default,
            },
            {
              key: "options",
              label: "Models on offer, and what each adds per minute (INR)",
              value: state.data.available
                .map(
                  (option) =>
                    `${option.model} (${option.provider}): ${option.client_surcharge_inr_per_minute} per minute${
                      option.is_platform_default ? ", the Calevate default" : ""
                    }${option.is_available ? "" : ` — unavailable: ${option.unavailable_reason ?? "no reason given"}`}`,
                )
                .join("; "),
            },
          ]
        : []),
    ],
    apply: noFill,
  });

  return (
    <div className="max-w-2xl space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        The model you pick here is the one all your agents use, unless a particular agent
        has been given its own. Your plan may add a per-minute charge for choosing one —
        each option below says exactly what it adds to your bill, and &ldquo;no extra
        charge&rdquo; means it adds nothing.
      </p>

      {state.error != null && (
        <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />
      )}

      {/* Loading is a skeleton and failure is the refusal above — neither is a model name.
          Naming a model over a read that failed is the one wrong answer here: it tells an
          owner what they are paying for a call, and it would be a guess. */}
      {state.isLoading ? (
        <Card>
          <Skeleton rows={5} label="Loading your AI model settings" />
        </Card>
      ) : !state.data ? null : (
        <OrganizationDefault defaults={state.data} slug={slug} />
      )}
    </div>
  );
}
