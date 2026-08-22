"use client";

import Link from "next/link";
import { use, useState } from "react";
import { BrainCircuit, Info, IndianRupee, Save, Sparkles } from "lucide-react";

import {
  Card,
  FIELD_HINT,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatRupeeRate,
} from "@/components/ui";
import { ModelPicker, type ModelChoice } from "@/components/llmModelPicker";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  modelOption,
  platformDefaultOption,
  unavailableReason,
  useOrganizationLlmDefaults,
  useSetOrganizationLlmDefault,
  type OrganizationLlmDefaults,
} from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";

/**
 * THE AI MODEL A CLIENT'S AGENTS THINK WITH — the organisation-wide default.
 *
 * ## Why a client decides this
 *
 * Because they pay for it. Every option carries `platform_cost_inr_per_minute` — what a minute
 * of a five-minute call costs on that model — and the difference between the cheapest and
 * the dearest is the difference between two phone bills. D-21 reserves what an agent SAYS
 * and what it CAPTURES because both need a regression run against real calls; a price is
 * neither, and the same argument that gives a client their own spending limit
 * (`/c/[slug]/usage`) and their own disclosure switches (D-163) gives them this.
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

  return (
    <div className="max-w-2xl space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Your agents use an AI model to understand a caller and decide what to say next. The
        model you pick here is the one they all use, unless a particular agent has been
        given its own. A dearer model costs us more to run and can answer harder questions;
        what you are charged for a call does not change when you switch, because your plan
        prices a minute of conversation rather than the model behind it.
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

  const inForce = modelOption(defaults.available, defaults.effective_default);
  const platformDefault = platformDefaultOption(defaults.available);

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
            rate: null,
            badge: "in use",
            baseline: true,
          } satisfies ModelChoice,
        ]),
    {
      value: null,
      label: "Use the Calevate default",
      detail: platformDefault
        ? `Today that is ${platformDefault.model}. If we change it, your agents follow.`
        : "Whatever model we run by default, including after we change it.",
      rate: platformDefault?.platform_cost_inr_per_minute ?? null,
      badge: defaults.default_llm_model === null ? "in use" : undefined,
      baseline: defaults.default_llm_model === null,
    },
    ...defaults.available.map<ModelChoice>((option) => ({
      value: option.model,
      label: option.model,
      detail: option.is_platform_default
        ? `${option.provider} · the model we run by default`
        : option.provider,
      rate: option.platform_cost_inr_per_minute,
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
          onSubmit={(event) => {
            event.preventDefault();
            if (!changed) return;
            save.mutate({ default_llm_model: selected });
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
              {inForce ? (
                <>
                  {" "}
                  It costs {formatRupeeRate(inForce.platform_cost_inr_per_minute)} a minute on a
                  five-minute call.
                </>
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
            hint="Prices are per minute, on a five-minute call."
            choices={choices}
            value={selected}
            baselineRate={inForce?.platform_cost_inr_per_minute ?? null}
            disabled={!write.allowed || save.isPending}
            onChange={(next) => setPicked({ model: next })}
          />

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={!write.allowed || !changed || save.isPending}
              title={write.reason ?? undefined}
              className={PRIMARY_BUTTON}
            >
              <Save aria-hidden className="h-4 w-4" />
              {save.isPending ? "Saving…" : "Save model"}
            </button>
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
            {/* The five-minute qualifier is not decoration and the server states why: the
                model is sent the whole conversation again on every turn, so cost per
                minute RISES with call length. A bare "per minute" would be a figure that
                is only true for one call length, unlabelled. */}
            Prices are quoted per minute of a five-minute call. A longer call costs a
            little more per minute — the agent re-reads the whole conversation each time it
            answers — so every model is priced at the same call length to make them
            comparable. What you are actually billed for the month is on your{" "}
            <Link
              href={href(`/c/${slug}/usage`)}
              className="font-medium underline underline-offset-2 hover:text-ink"
            >
              Usage
            </Link>{" "}
            screen.
          </li>
          <li className="flex gap-2">
            <Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            One agent can be put on a different model from the rest — open it from{" "}
            <Link
              href={href(`/c/${slug}/agents`)}
              className="font-medium underline underline-offset-2 hover:text-ink"
            >
              Agents
            </Link>{" "}
            and choose there. An agent with its own model ignores this setting until you
            put it back on the default.
          </li>
        </ul>
      </Card>
    </>
  );
}
