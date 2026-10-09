"use client";

import Link from "next/link";
import { useState } from "react";
import { BrainCircuit, RotateCcw, Save } from "lucide-react";

import {
  Disclosure,
  FIELD_HINT,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
} from "@/components/ui";
import { ModelPicker, type ModelChoice } from "@/components/llmModelPicker";
import { isDeleted } from "@/lib/agentState";
import { useUpdateAgent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  agentInForceSurcharge,
  agentLlmView,
  agentModelPatch,
  tierOption,
  tierUnavailableReason,
  useOrganizationLlmDefaults,
  type AgentLlmView,
  type AgentWithLlm,
  type ClientLlmDefaults,
  type LlmModelSource,
  type LlmTier,
} from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/**
 * ONE AGENT'S AI MODEL TIER — inherited from the organisation, or overridden here.
 *
 * ## Inheritance is the thing this panel has to make legible
 *
 * An agent runs on a tier it was given, or on the one its organisation chose, or on the one
 * Calevate runs by default — and from the outside those three look identical. Changing the
 * organisation default moves the first two and not the third, so a client who cannot tell
 * which they are looking at cannot predict what their own change will do.
 * `llm_tier_source` is the server's answer and is read as a WIRE STRING through `lookup`.
 *
 * ## A tier, never a model (D-679, D-680)
 *
 * Which model answers each tier is ours and is not on the wire. The figure shown is what the
 * CLIENT pays (`client_surcharge_inr_per_minute`, D-455); whether this agent's minutes carry
 * it is the server's `llm_surcharged`, because an agent following a level it did not choose
 * is never surcharged.
 *
 * A catalogue read that FAILS leaves the agent's own facts on screen and replaces only the
 * picker with the refusal.
 */
export function AgentModel({ agent, slug }: { agent: AgentWithLlm; slug: string }) {
  const session = useClientSession();
  const view = agentLlmView(agent);
  const catalogue = useOrganizationLlmDefaults(session);

  return (
    /* DISCLOSED, not a Card (UX-DOCTRINE §3): an owner picks a tier at most once, and the
       consequence is a bounded, reversible price per minute. The closed state still names
       the tier in force, so the FACT survives the disclosure. */
    <Disclosure
      title="The model it thinks with"
      subtitle={`Currently ${view.label}. Changing it changes what a minute of this agent's calls costs you.`}
      icon={<BrainCircuit className="h-4 w-4" />}
    >
      <div className="space-y-5">
        <Inheritance view={view} slug={slug} />

        {catalogue.error != null && (
          <ProblemNotice error={catalogue.error} onRetry={() => void catalogue.refetch()} />
        )}

        {isDeleted(agent) ? (
          <p className="text-sm text-ink-muted">
            This agent is deleted, so its settings are kept exactly as they were — they are
            part of the record of what it did. Bring it back first if you want to change
            them.
          </p>
        ) : catalogue.isLoading ? (
          <Skeleton rows={4} label="Loading the models you can choose from" />
        ) : !catalogue.data ? null : (
          <ModelForm agent={agent} view={view} catalogue={catalogue.data} />
        )}
      </div>
    </Disclosure>
  );
}

/** Where this agent's tier comes from, in one line. A wire string chooses between them. */
const SOURCE_LINE: Record<LlmModelSource, string> = {
  agent: "This agent has its own model, and ignores your organisation default.",
  organization: "This agent follows your organisation default.",
  platform: "This agent follows Calevate's default, because neither it nor your organisation has picked one.",
};

/**
 * Where the tier came from, as one line: the tier and its price are on the rows below, so
 * this does not repeat them.
 */
function Inheritance({ view, slug }: { view: AgentLlmView; slug: string }) {
  const { href } = useClientRealm();
  return (
    <p className="text-sm text-ink-muted">
      {lookup(SOURCE_LINE, view.source) ?? `This agent runs on ${view.label}.`}
      {view.source === "organization" || view.source === "platform" ? (
        <>
          {" "}
          <Link
            href={href(`/c/${slug}/settings/models`)}
            className="font-medium underline underline-offset-2"
          >
            Change it for every agent
          </Link>
        </>
      ) : null}
    </p>
  );
}

/**
 * The override itself. Sends ONLY `llm_tier`: `null` reads as "follow the organisation",
 * OMITTING the field means "leave this agent alone", so the body is built by
 * `agentModelPatch`. `useUpdateAgent` rather than a mutation of this panel's own, so one
 * route has one list of cache keys.
 */
function ModelForm({
  agent,
  view,
  catalogue,
}: {
  agent: AgentWithLlm;
  view: AgentLlmView;
  catalogue: ClientLlmDefaults;
}) {
  const session = useClientSession();
  const save = useUpdateAgent(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change this agent's model");

  const [picked, setPicked] = useState<{ tier: LlmTier | null } | null>(null);
  const selected = picked ? picked.tier : view.chosen;
  const changed = selected !== view.chosen;

  const baselineSurcharge = agentInForceSurcharge(view, catalogue);
  const organizationTier = tierOption(catalogue.available, catalogue.effective_tier);

  // One row per tier. The organisation's tier IS "follow my organisation" (`null`);
  // pinning that same tier is the box under it, never a second look-alike row.
  const inForce = view.chosen ?? catalogue.effective_tier;
  const tiers = catalogue.available.map<ModelChoice>((option) => ({
    value: option.tier,
    label: option.label,
    detail: option.description,
    surcharge: option.client_surcharge_inr_per_minute,
    baseline: option.tier === inForce,
    unavailable: tierUnavailableReason(option),
  }));
  const choices: ModelChoice[] = organizationTier
    ? tiers
    : [
        {
          value: null,
          label: "Follow my organisation",
          detail: "If you change your organisation default, this agent follows.",
          surcharge: catalogue.in_force_surcharge_inr_per_minute,
        },
        ...tiers,
      ];

  return (
    <form
      className="space-y-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!changed) return;
        save.mutate(agentModelPatch(selected));
      }}
    >
      <RestrictionNote reason={write.reason} />
      {/* The server's own words: only the API can say why a tier is refused. */}
      {save.error != null && <ProblemNotice error={save.error} />}

      <ModelPicker
        name={`agent-llm-model-${agent.id}`}
        legend="Model for this agent"
        hint="Figures are what a tier adds to every minute you are charged for."
        choices={choices}
        value={selected}
        baselineSurcharge={baselineSurcharge}
        disabled={!write.allowed || save.isPending}
        // Narrowed through the server's own rows rather than asserted.
        onChange={(next) => setPicked({ tier: tierOption(catalogue.available, next)?.tier ?? null })}
        audience="client"
        followDefault={
          organizationTier
            ? {
                value: organizationTier.tier,
                badge: "Organisation default",
                keepLabel: `Keep ${organizationTier.label} even if the organisation default changes`,
              }
            : undefined
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={!write.allowed || !changed || save.isPending}
          title={write.reason ?? undefined}
          className={PRIMARY_BUTTON}
        >
          {selected === null ? (
            <RotateCcw aria-hidden className="h-4 w-4" />
          ) : (
            <Save aria-hidden className="h-4 w-4" />
          )}
          {save.isPending
            ? "Saving…"
            : selected === null
              ? "Go back to the organisation default"
              : "Save model"}
        </button>
        {!changed && !save.isPending && (
          <span className="text-xs text-ink-muted">Nothing has been changed yet.</span>
        )}
      </div>
      <span className={FIELD_HINT}>
        This takes effect on this agent&apos;s next call. Calls already running finish on the
        model they started on.
      </span>
    </form>
  );
}
