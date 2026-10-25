"use client";

import Link from "next/link";

import { useActionFeedback } from "@/components/arc/feedback";
import { ModelTierSetting } from "@/components/modelTierSetting";
import { Disclosure, NoticeBox } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  platformDefaultTier,
  useSetOrganizationLlmDefault,
  type ClientLlmDefaults,
} from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";

/**
 * The account's model tier, given defaults that ARRIVED: the shared `ModelTierSetting` in its
 * organisation mode, plus how the tier is billed.
 *
 * Takes the payload rather than the query envelope: every sentence below is a claim about this
 * client's account, and a component that cannot see `undefined` cannot make one out of it.
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
  // `ModelTierSetting` draws the save bar's faces and the refusal beside it, so a failure
  // stays inline. The bar closes on success; the summary row's `SavedTick` says it, not a toast.
  const feedback = useActionFeedback(save, { errorDisplay: "inline" });
  /**
   * `org:manage` — the owner's own permission, the one that already governs the account's
   * settings and its spending limit. An operator in view-as holds it too (D-587).
   */
  const write = useWriteAccess(
    session,
    "org:manage",
    "change which AI model your agents use",
  );
  const platformDefault = platformDefaultTier(defaults.available);

  return (
    <div className="space-y-10">
      <ModelTierSetting
        mode="organisation"
        name="organization-llm-default"
        catalogue={defaults}
        saved={defaults.default_llm_tier}
        inForceLabel={defaults.effective_tier_label}
        source={
          defaults.default_llm_tier === null
            ? "Follows Calevate's default."
            : "Chosen for your account."
        }
        followLabel={platformDefault?.label ?? defaults.effective_tier_label}
        followSurcharge={
          platformDefault?.client_surcharge_inr_per_minute ?? "0"
        }
        baselineSurcharge={defaults.in_force_surcharge_inr_per_minute}
        write={write}
        status={feedback.status}
        error={save.error}
        savedAt={save.isSuccess ? save.submittedAt : 0}
        onSave={(tier, done) =>
          save.mutate({ default_llm_tier: tier }, { onSuccess: done })
        }
        // The tier marked as running is the one we INTEND to run; this says when it is not
        // the one answering yet. It changes what a call runs on, so it is a notice.
        notice={
          defaults.effective_is_available ? undefined : (
            <NoticeBox tone="warn">
              {defaults.effective_tier_label} is not on for your account yet, so
              calls use our standard model. Ask your Calevate team to turn it
              on.
            </NoticeBox>
          )
        }
      />

      {/* Nothing to choose and nothing extra to bill where the model is included (D-750). */}
      {defaults.tier_choosable !== false && (
        <Disclosure
          title="How the model is billed"
          subtitle="A tier's figure is added to your plan's per-minute rate, as its own line on your statement."
        >
          <ul className="space-y-2 text-body text-ink-muted">
            <li>Changing the model does not change the voice your callers hear.</li>
            <li>
              {/* A SURCHARGE, not a replacement rate: the plan's per-minute rate is unchanged
                and this is added to it (`plans.llm_model_surcharge`). One span inside the
                flex <li>, so the link stays inline text rather than its own flex item. */}
              <span>
                A tier&apos;s figure is ADDED to your plan&apos;s per-minute
                rate for the minutes your agents run it, as its own line naming
                the tier; your plan&apos;s own rate does not change. What you are
                actually billed for the month is on the{" "}
                <Link
                  href={href(`/c/${slug}/billing?tab=usage`)}
                  className="font-medium underline underline-offset-2 hover:text-ink touch:py-3.5"
                >
                  Usage tab of Credits &amp; billing
                </Link>
                .
              </span>
            </li>
            <li>
              <span>
                One agent can be put on a different tier from the rest: open it
                from{" "}
                <Link
                  href={href(`/c/${slug}/agents`)}
                  className="font-medium underline underline-offset-2 hover:text-ink touch:py-3.5"
                >
                  Agents
                </Link>{" "}
                and choose on its Model section. It then ignores this setting
                until you put it back on the organisation default.
              </span>
            </li>
          </ul>
        </Disclosure>
      )}
    </div>
  );
}
