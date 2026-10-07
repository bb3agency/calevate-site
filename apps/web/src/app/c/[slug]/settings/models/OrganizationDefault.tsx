"use client";

import Link from "next/link";
import { useState } from "react";
import { BrainCircuit, Info, IndianRupee, Save, Sparkles } from "lucide-react";

import {
  Disclosure,
  FIELD_HINT,
  ProblemNotice,
  RestrictionNote,
  formatRupeeRate,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { useToast } from "@/components/interior/toaster";
import { ModelPicker, type ModelChoice } from "@/components/llmModelPicker";
import { useWriteAccess } from "@/lib/api/hooks";
import { compareRates } from "@/lib/llmRates";
import {
  platformDefaultTier,
  tierOption,
  tierUnavailableReason,
  useSetOrganizationLlmDefault,
  type ClientLlmDefaults,
  type LlmTier,
} from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";

/**
 * The screen, given defaults that ARRIVED.
 *
 * Takes the payload rather than the query envelope for `AgentDetail`'s reason: every
 * sentence below is a claim about this client's account, and a component that cannot see
 * `undefined` cannot make one out of it.
 *
 * Every row is a TIER (D-680). Which model answers each one is Calevate's and is not on the
 * wire, so nothing here can name a model or the company behind it (D-679).
 */
export function OrganizationDefault({
  defaults,
  slug,
}: {
  defaults: ClientLlmDefaults;
  slug: string;
}) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const save = useSetOrganizationLlmDefault(session);
  // Transient confirmation of the write; the "In force now" panel that refetches is what
  // proves the new state.
  const { toast } = useToast();
  /**
   * `org:manage` — the owner's own permission, the one that already governs the account's
   * settings and its spending limit. An operator in view-as holds it too (D-587).
   */
  const write = useWriteAccess(session, "org:manage", "change which AI model your agents use");

  /**
   * The choice, WRAPPED, because `null` is a real value here: "nothing picked yet" and
   * "picked: use Calevate's default" are both spelled `null` on the wire.
   */
  const [picked, setPicked] = useState<{ tier: LlmTier | null } | null>(null);
  const selected = picked ? picked.tier : defaults.default_llm_tier;
  const changed = selected !== defaults.default_llm_tier;

  const platformDefault = platformDefaultTier(defaults.available);
  const inForceSurchargeInr = defaults.in_force_surcharge_inr_per_minute;

  const choices: ModelChoice[] = [
    {
      value: null,
      label: "Use the Calevate default",
      detail: !platformDefault
        ? "Whatever tier we run by default, including after we change it."
        : tierUnavailableReason(platformDefault) !== null
          ? `Today that is ${platformDefault.label}, and it is not switched on for your account yet — your agents run our standard model until it is.`
          : `Today that is ${platformDefault.label}. If we change it, your agents follow.`,
      surcharge: "0",
      badge: defaults.default_llm_tier === null ? "in use" : undefined,
      baseline: defaults.default_llm_tier === null,
    },
    ...defaults.available.map<ModelChoice>((option) => ({
      value: option.tier,
      label: option.label,
      detail: option.is_platform_default
        ? `${option.description} The tier we run by default.`
        : option.description,
      surcharge: option.client_surcharge_inr_per_minute,
      badge: defaults.default_llm_tier === option.tier ? "in use" : undefined,
      baseline: defaults.default_llm_tier === option.tier,
      unavailable: tierUnavailableReason(option),
    })),
  ];

  return (
    <>
      <form
        className="space-y-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!changed) return;
          save.mutate(
            { default_llm_tier: selected },
            { onSuccess: () => toast({ tone: "success", title: "AI model saved" }) },
          );
        }}
      >
        <div className="border-y border-line py-3.5">
          <p className="flex items-center gap-1.5 text-[15px] font-semibold text-ink">
            <BrainCircuit aria-hidden className="h-4 w-4 shrink-0 text-ink-faint" />
            {`In force now: ${defaults.effective_tier_label}`}
          </p>
          <p className="mt-0.5 text-[13px] text-ink-muted">
            {defaults.default_llm_tier === null
              ? "You have not picked a tier, so your agents run on the one Calevate uses by default."
              : "You picked this tier for your account."}
            {compareRates(inForceSurchargeInr, "0") === "same" ? (
              <> It adds nothing to what you are charged for a minute.</>
            ) : (
              <>
                {" "}
                It adds {formatRupeeRate(inForceSurchargeInr)} to every minute you are
                charged for.
              </>
            )}
          </p>
        </div>
        {/* The tier named above is the one we INTEND to run; this says when it is not the
            one answering yet. A warning, not help text: it changes what a call runs on. */}
        {!defaults.effective_is_available && (
          <p className="rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-sm text-ink">
            It is not switched on for your account yet, so your calls run our standard model
            until it is — ask your Calevate team to enable it.
          </p>
        )}

        <RestrictionNote reason={write.reason} />
        {/* The server's own refusal, with its remediation — never a generic toast. */}
        {save.error != null && <ProblemNotice error={save.error} />}

        <ModelPicker
          name="organization-llm-default"
          legend="Model for all your agents"
          hint="Figures are what a tier adds to every minute you are charged for."
          choices={choices}
          value={selected}
          baselineSurcharge={inForceSurchargeInr}
          disabled={!write.allowed || save.isPending}
          // Narrowed through the server's own rows rather than asserted: a value the list
          // does not carry is the inherit row.
          onChange={(next) => setPicked({ tier: tierOption(defaults.available, next)?.tier ?? null })}
          audience="client"
        />

        <div className="flex flex-wrap items-center gap-3">
          {/* The accessible name is the children and does NOT change while saving, so a
              screen reader (and `clientLlmModel.test.tsx`) keeps the same control. */}
          <ActionButton
            type="submit"
            loading={save.isPending}
            disabled={!write.allowed || !changed}
            title={write.reason ?? undefined}
          >
            <Save aria-hidden className="h-4 w-4" />
            Save model
          </ActionButton>
          <span className={FIELD_HINT}>
            This takes effect on the next call. Calls already running finish on the model
            they started on.
          </span>
        </div>
      </form>

      <Disclosure
        title="How the model is billed"
        subtitle="A tier's figure is added to your plan's per-minute rate, as its own line on your statement."
      >
        <ul className="space-y-2 text-sm text-ink-muted">
          <li className="flex gap-2">
            <Sparkles aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            The voice your callers hear is a separate setting, and changing the model does
            not change it.
          </li>
          <li className="flex gap-2">
            <IndianRupee aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            {/* A SURCHARGE, not a replacement rate: the plan's per-minute rate is unchanged
                and this is added to it (`plans.llm_model_surcharge`). One span inside the
                flex <li>, so the link stays inline text rather than its own flex item. */}
            <span>
              A tier&apos;s figure is ADDED to your plan&apos;s per-minute rate, for the
              minutes your agents run it — your plan&apos;s own rate does not change. It
              appears on your statement as its own line, naming the tier. What you are
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
              One agent can be put on a different tier from the rest — open it from{" "}
              <Link
                href={href(`/c/${slug}/agents`)}
                className="font-medium underline underline-offset-2 hover:text-ink"
              >
                Agents
              </Link>{" "}
              and choose there. An agent with its own tier ignores this setting until you
              put it back on the default.
            </span>
          </li>
        </ul>
      </Disclosure>
    </>
  );
}
