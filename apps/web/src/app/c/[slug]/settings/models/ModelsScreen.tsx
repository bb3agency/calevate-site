"use client";

import { ProblemNotice, Skeleton } from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
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
 * Because they pay for it. Every tier carries `client_surcharge_inr_per_minute` — what
 * choosing it ADDS to this account's bill for every minute it runs (D-455). D-21 reserves
 * what an agent SAYS and what it CAPTURES; a price is neither.
 *
 * A client chooses a TIER and never sees a model or the company behind it (D-679, D-680):
 * which model answers each tier is ours, resolved on the server. OUR cost to run it stays
 * on the operator's console.
 *
 * ## The three things this screen must not do
 *
 * 1. **Resolve the default itself.** `effective_tier` and the surcharge in force are the
 *    server's answers and are rendered as they arrive.
 * 2. **Show a tier without its price.** That is the whole point of the surface, and it
 *    is why an option whose rate the catalogue does not carry renders `—` rather than
 *    being quietly dropped or shown as free.
 * 3. **Look saved before it is.** No optimistic write: the server can refuse a model
 *    (a tier not switched on yet) and the refusal is problem+json with a
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
              label: "The AI model tier this account has chosen",
              value: state.data.default_llm_tier ?? "none — it follows the Calevate default",
            },
            {
              key: "effective_default",
              label: "The tier agents actually run on unless given their own",
              value: state.data.effective_tier_label,
            },
            {
              key: "options",
              label: "Tiers on offer, and what each adds per minute (INR)",
              value: state.data.available
                .map(
                  (option) =>
                    `${option.label}: ${option.client_surcharge_inr_per_minute} per minute${
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
      <PageHeader
        description="The model all your agents use, unless one has been given its own."
        actions={
          <InfoTip label="AI model" align="end">
            <p>
              Your plan may add a per-minute charge for choosing one — each option below says
              exactly what it adds to your bill, and &ldquo;no extra charge&rdquo; means it adds
              nothing.
            </p>
          </InfoTip>
        }
      />
      {state.error != null && (
        <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />
      )}

      {/* Loading is a skeleton and failure is the refusal above — neither is a model name.
          Naming a model over a read that failed is the one wrong answer here: it tells an
          owner what they are paying for a call, and it would be a guess. */}
      {state.isLoading ? (
        <Skeleton rows={5} label="Loading your AI model settings" />
      ) : !state.data ? null : (
        <OrganizationDefault defaults={state.data} slug={slug} />
      )}
    </div>
  );
}
