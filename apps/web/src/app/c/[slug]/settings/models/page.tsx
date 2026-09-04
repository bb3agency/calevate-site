"use client";

import Link from "next/link";
import { use, useState } from "react";
import { BrainCircuit, Info, IndianRupee, Save, Sparkles } from "lucide-react";

import {
  Card,
  FIELD_HINT,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatRupeeRate,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { useToast } from "@/components/interior/toaster";
import { ModelPicker, type ModelChoice } from "@/components/llmModelPicker";
import { useWriteAccess } from "@/lib/api/hooks";
import { compareRates } from "@/lib/llmRates";
import {
  inForceSurcharge,
  modelOption,
  platformDefaultOption,
  unavailableReason,
  useOrganizationLlmDefaults,
  useSetOrganizationLlmDefault,
  type OrganizationLlmDefaults,
} from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

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
export default function ModelsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
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
        Your agents use an AI model to understand a caller and decide what to say next. The
        model you pick here is the one they all use, unless a particular agent has been
        given its own. A better model can answer harder questions and costs more to run, so
        your plan may add a per-minute charge for choosing one — each option below says
        exactly what it adds to your bill, and &ldquo;no extra charge&rdquo; means it adds
        nothing.
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

/**
 * The screen, given defaults that ARRIVED.
 *
 * Takes the payload rather than the query envelope for `AgentDetail`'s reason: every
 * sentence below is a claim about this client's account, and a component that cannot see
 * `undefined` cannot make one out of it.
 */
function OrganizationDefault({
  defaults,
  slug,
}: {
  defaults: OrganizationLlmDefaults;
  slug: string;
}) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const save = useSetOrganizationLlmDefault(session);
  // Transient confirmation of the write: no-op-safe when no ToastProvider is mounted
  // (the client realm layout mounts one), and additive to the "In force now" panel that
  // refetches — the panel proves the new state, the toast acknowledges the click.
  const { toast } = useToast();
  /**
   * `org:manage` — the owner's own permission, the one that already governs the account's
   * settings and its spending limit, and the one no admin or impersonating session holds
   * against a tenant (D-22). NOT `agents:write`, which is admin-only and which neither
   * client role holds: gating this on it would disable it for the owner it was built for.
   */
  const write = useWriteAccess(session, "org:manage", "change which AI model your agents use");

  /**
   * The choice, WRAPPED, because `null` is a real value here.
   *
   * "Nothing picked yet" and "picked: use Calevate's default" are different states and
   * both are spelled `null` on the wire, so a bare `string | null` state could not tell
   * them apart — the form would either think a fresh screen had already been edited or
   * would refuse to let anyone choose the inherit row.
   */
  const [picked, setPicked] = useState<{ model: string | null } | null>(null);
  const selected = picked ? picked.model : defaults.default_llm_model;
  const changed = selected !== defaults.default_llm_model;

  const platformDefault = platformDefaultOption(defaults.available);
  /*
   * IS THE MODEL IN FORCE ONE THIS PLATFORM CAN ACTUALLY RUN RIGHT NOW?
   *
   * A real state and not a defensive one: the platform default is a live setting and its
   * leg's credential and price are live properties of the deployment (server-side,
   * `agents/llm_models.offerable_models()`), so a default can be named on this screen
   * before the key that runs it is installed. When that happens the inherit row's
   * "Today that is X" and the panel's "In force now: X" are both TRUE about which model we
   * intend and FALSE about which one answers the call — the account falls back to our
   * standard model until the leg is switched on. Saying so is the whole point of this
   * screen; the alternative is a client reading a model name their calls are not running.
   */
  const inForceOption = modelOption(defaults.available, defaults.effective_default);
  const inForceBlocked = inForceOption ? unavailableReason(inForceOption) !== null : false;
  // WHAT THE MODEL IN FORCE ACTUALLY ADDS, which is not the same as what its catalogue
  // row would cost to choose: an account following the platform default is never
  // surcharged (`lib/api/llmModels.ts::inForceSurcharge` holds the rule once).
  const inForceSurchargeInr = inForceSurcharge(defaults);

  /**
   * A model this account is PINNED to that the catalogue no longer offers.
   *
   * A real state — a model is withdrawn while somebody is on it — and dropping the row
   * would leave the picker with nothing selected and no way to see what the account is
   * actually running. So it is offered as its own option, priced `—` because the
   * catalogue cannot price it, and moving OFF it is one click. `AgentIdentity` keeps a
   * retired language on screen for the same reason: opening a settings screen must never
   * silently change the setting.
   */
  const retired =
    defaults.default_llm_model !== null && modelOption(defaults.available, defaults.default_llm_model) === undefined
      ? defaults.default_llm_model
      : null;

  const choices: ModelChoice[] = [
    ...(retired === null
      ? []
      : [
          {
            value: retired,
            label: retired,
            detail: "We no longer offer this model, so we cannot show what it costs.",
            surcharge: null,
            badge: "in use",
            baseline: true,
          } satisfies ModelChoice,
        ]),
    {
      value: null,
      label: "Use the Calevate default",
      detail: !platformDefault
        ? "Whatever model we run by default, including after we change it."
        : unavailableReason(platformDefault) !== null
          ? `Today that is ${platformDefault.model}, and it is not switched on for your account yet — your agents run our standard model until it is.`
          : `Today that is ${platformDefault.model}. If we change it, your agents follow.`,
      // FOLLOWING THE PLATFORM DEFAULT IS NEVER SURCHARGED, whatever model it resolves
      // to today or tomorrow: a surcharge is the price of an upgrade the client asked
      // for, and this row is the client asking for nothing (the server's own rule —
      // `rates.CLIENT_CHOSEN_LLM_SOURCES` excludes `platform`). So `"0"` here rather
      // than the resolved model's row, which would quote a charge the meter will not
      // apply.
      surcharge: "0",
      badge: defaults.default_llm_model === null ? "in use" : undefined,
      baseline: defaults.default_llm_model === null,
    },
    ...defaults.available.map<ModelChoice>((option) => ({
      value: option.model,
      label: option.model,
      // The provider is the GROUP heading now (D-456), so the row's own note carries only
      // what is specific to this model — nothing, unless it is the one we run by default.
      provider: option.provider,
      detail: option.is_platform_default ? "The model we run by default" : "",
      surcharge: option.client_surcharge_inr_per_minute,
      badge: defaults.default_llm_model === option.model ? "in use" : undefined,
      baseline:
        defaults.default_llm_model !== null && defaults.effective_default === option.model,
      // SHOWN, PRICED AND NOT SELECTABLE. `PUT` refuses a model this platform has no
      // deployment for (`llm_model_not_deployed`), so offering the row would price a
      // choice and then answer it with a 422 — the one thing a picker built around a
      // price must not do. `unavailableReason` is the single reading of `is_available`.
      unavailable: unavailableReason(option),
    })),
  ];

  return (
    <>
      <Card title="The model your agents use">
        <form
          className="space-y-5"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!changed) return;
            save.mutate(
              { default_llm_model: selected },
              { onSuccess: () => toast({ tone: "success", title: "AI model saved" }) },
            );
          }}
        >
          <NoticeBox
            tone="neutral"
            icon={<BrainCircuit aria-hidden className="h-5 w-5" />}
            title={`In force now: ${defaults.effective_default}`}
          >
            <p className="mt-1">
              {defaults.default_llm_model === null
                ? "You have not picked a model, so your agents run on the one Calevate uses by default."
                : "You picked this model for your account."}
              {/* The model named above is the one we INTEND to run; this says when it is
                  not the one answering yet. Same sentence the picker's rows carry, because
                  it is the same fact and the same one action. */}
              {inForceBlocked && (
                <> It is not switched on for your account yet, so your calls run our
                standard model until it is — ask your Calevate team to enable it.</>
              )}
              {inForceSurchargeInr !== null ? (
                // WHAT IT ADDS TO THEIR BILL, in words for the zero case, because "₹0.00
                // a minute" is a rupee amount of nothing and "no extra charge" is the
                // answer to the question they asked.
                compareRates(inForceSurchargeInr, "0") === "same" ? (
                  <> It adds nothing to what you are charged for a minute.</>
                ) : (
                  <>
                    {" "}
                    It adds {formatRupeeRate(inForceSurchargeInr)} to every minute you are
                    charged for.
                  </>
                )
              ) : (
                // The catalogue does not price what is in force — a model withdrawn from
                // the list, or an older API. Saying so beats printing a number we do not
                // have, and beats saying nothing at all on a screen about a price.
                <> We cannot show its price from here; your account manager can.</>
              )}
            </p>
          </NoticeBox>

          <RestrictionNote reason={write.reason} />
          {/* The server's own refusal, with its remediation — never a generic toast. An
              unknown model and a model this plan does not include are different answers
              and only the API knows which one this was. */}
          {save.error != null && <ProblemNotice error={save.error} />}

          <ModelPicker
            name="organization-llm-default"
            legend="Model for all your agents"
            hint="Figures are what a model adds to every minute you are charged for."
            choices={choices}
            value={selected}
            baselineSurcharge={inForceSurchargeInr}
            disabled={!write.allowed || save.isPending}
            onChange={(next) => setPicked({ model: next })}
          />

          <div className="flex flex-wrap items-center gap-3">
            {/* Shared ActionButton: it carries the spinner while the save is in flight
                (`loading`) so the panel no longer spells "Saving…" itself, and it disables
                during the request the same way the old button did (`disabled || loading`).
                The accessible name is the children and does NOT change with `loading`, so
                `clientLlmModel.test.tsx`'s `getByRole(button, /Save model/)` — and a screen
                reader — keeps pointing at the same control mid-save. */}
            <ActionButton
              type="submit"
              loading={save.isPending}
              disabled={!write.allowed || !changed}
              title={write.reason ?? undefined}
            >
              <Save aria-hidden className="h-4 w-4" />
              Save model
            </ActionButton>
            {!changed && !save.isPending && (
              <span className="text-xs text-ink-muted">Nothing has been changed yet.</span>
            )}
          </div>
          <span className={FIELD_HINT}>
            This takes effect on the next call. Calls already running finish on the model
            they started on.
          </span>
        </form>
      </Card>

      <Card title="What this does and does not change">
        <ul className="space-y-2 text-sm text-ink-muted">
          <li className="flex gap-2">
            <Sparkles aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            It is the model that decides what your agent SAYS. The voice your callers hear
            is a separate setting, and changing the model does not change it.
          </li>
          <li className="flex gap-2">
            <IndianRupee aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            {/* A SURCHARGE, not a replacement rate, and the sentence says so: your plan's
                per-minute rate is unchanged and this is added to it. That is the whole
                shape of `plans.llm_model_surcharge`, and a client who reads it as "the new
                price of a minute" would expect the wrong number on their statement. */}
            {/* The <li> is a FLEX CONTAINER, so it gets exactly two children: the icon and
                one span holding the whole sentence. Left loose, each text node and the
                <Link> were separate flex ITEMS — the link was laid out as its own ragged
                column with `gap-2` on both sides of it, which is what the founder
                screenshotted. Inside the span it is inline text again and `gap-2` does the
                one job it was written for: the space after the icon. */}
            <span>
              A model&apos;s figure is ADDED to your plan&apos;s per-minute rate, for the
              minutes your agents run it — your plan&apos;s own rate does not change. It
              appears on your statement as its own line, naming the model. What you are
              actually billed for the month is on the{" "}
              <Link
                href={href(`/c/${slug}/billing?tab=usage`)}
                className="font-medium underline underline-offset-2 hover:text-ink"
              >
                Usage tab of Credits &amp; billing
              </Link>
              .
            </span>
          </li>
          <li className="flex gap-2">
            <Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              One agent can be put on a different model from the rest — open it from{" "}
              <Link
                href={href(`/c/${slug}/agents`)}
                className="font-medium underline underline-offset-2 hover:text-ink"
              >
                Agents
              </Link>{" "}
              and choose there. An agent with its own model ignores this setting until you
              put it back on the default.
            </span>
          </li>
        </ul>
      </Card>
    </>
  );
}
