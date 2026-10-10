"use client";

import Link from "next/link";
import { useState } from "react";
import { Info, IndianRupee, Save, Sparkles } from "lucide-react";

import { Disclosure, FIELD_HINT, ProblemNotice, RestrictionNote } from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { SavedTick } from "@/components/console/savedTick";
import { ModelPicker, type ModelChoice } from "@/components/llmModelPicker";
import { useWriteAccess } from "@/lib/api/hooks";
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
  // Transient confirmation of the write; the refetched list is what proves the new state.
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

  // One row per tier. The default tier's row IS "follow Calevate's default" (`null` on the
  // wire); pinning that same tier is the box under it, not a second row. An older API that
  // names no default keeps the separate inherit row, since there is no row to fold it into.
  const tiers = defaults.available.map<ModelChoice>((option) => ({
    value: option.tier,
    label: option.label,
    detail: option.description,
    surcharge: option.client_surcharge_inr_per_minute,
    baseline: option.tier === defaults.effective_tier,
    unavailable: tierUnavailableReason(option),
  }));
  const choices: ModelChoice[] = platformDefault
    ? tiers
    : [
        {
          value: null,
          label: "Calevate's default",
          detail: "Whatever tier we run by default, including after we change it.",
          surcharge: "0",
        },
        ...tiers,
      ];

  return (
    <>
      <form
        className="space-y-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!changed) return;
          save.mutate({ default_llm_tier: selected });
        }}
      >
        {/* The tier marked as running is the one we INTEND to run; this says when it is not
            the one answering yet. A warning, not help text: it changes what a call runs on. */}
        {!defaults.effective_is_available && (
          <p className="rounded-md border border-warn-line bg-warn-soft px-3 py-2 text-body text-ink">
            {defaults.effective_tier_label} is not switched on for your account yet, so your
            calls run our standard model until it is — ask your Calevate team to enable it.
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
          followDefault={
            platformDefault
              ? {
                  value: platformDefault.tier,
                  badge: "Default",
                  keepLabel: `Keep ${platformDefault.label} even if Calevate changes the default`,
                }
              : undefined
          }
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
          <SavedTick at={save.isSuccess ? save.submittedAt : 0} />
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
        <ul className="space-y-2 text-body text-ink-muted">
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
