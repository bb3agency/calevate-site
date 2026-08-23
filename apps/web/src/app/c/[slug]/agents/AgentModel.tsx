"use client";

import Link from "next/link";
import { useState } from "react";
import { BrainCircuit, RotateCcw, Save } from "lucide-react";

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
import { ARCHIVED_STATUS } from "@/lib/agentState";
import { useUpdateAgent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  agentInForceSurcharge,
  agentLlmView,
  agentModelPatch,
  inForceSurcharge,
  modelOption,
  unavailableReason,
  useOrganizationLlmDefaults,
  type AgentLlmView,
  type AgentWithLlm,
  type LlmModelSource,
  type OrganizationLlmDefaults,
} from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { compareRates } from "@/lib/llmRates";
import { lookup } from "@/lib/lookup";

/**
 * ONE AGENT'S MODEL — inherited from the organisation, or overridden here.
 *
 * ## Inheritance is the thing this panel has to make legible
 *
 * An agent runs on a model it was given, or on the one its organisation chose, or on the
 * one Calevate runs by default — and from the outside those three look identical: a model
 * name on a screen. They are not identical. Changing the organisation default moves the
 * first two agents and not the third, so a client who cannot tell which they are looking
 * at cannot predict what their own change will do.
 *
 * `llm_model_source` is the server's answer to exactly that question and it is read as a
 * WIRE STRING through `lookup` (src/lib/lookup.ts) rather than derived from
 * `llm_model === null`. The two agree today; a fourth source — a campaign-level choice, a
 * per-lane override — would make the derived version say "your organisation default"
 * about something that is not it, on the screen where a client checks precisely that.
 *
 * ## Why the price is here too
 *
 * Because an override is a per-agent price. A busy inbound receptionist on a dearer model
 * costs more than a rarely-used outbound one, which is a legitimate thing to want and an
 * expensive thing to do by accident. Same catalogue, same figures, same exact-decimal
 * comparison as the settings screen — one read, one cache entry, one answer
 * (`lib/api/llmModels.ts`).
 *
 * **THE FIGURE IS WHAT THE CLIENT PAYS, AND THAT IS A CORRECTION (D-455).** This panel
 * used to say "Running it costs us ₹x a minute — your own rate is set by your plan and
 * does not change with the model", which was true and was the defect: the dearer model
 * cost Calevate 2.7x and earned nothing. `plans.llm_model_surcharge` prices the upgrade
 * now, so the sentence is false and the figure is `client_surcharge_inr_per_minute`. OUR
 * cost stays on the operator's console, where publishing it is not publishing a margin to
 * the account it is a margin on (`apps/api/billing/rates.py`).
 *
 * **AN AGENT FOLLOWING A LEVEL IT DID NOT CHOOSE IS NOT SURCHARGED FOR IT.** The server's
 * rule is `llm_model_source`: `agent` and `organization` are the client choosing,
 * `platform` is not, so an agent inheriting the platform default carries no surcharge
 * however dear that default becomes. `agentInForceSurcharge` holds that once.
 *
 * ## What this panel does when it cannot say
 *
 * It disappears. `agentLlmView` returns `null` when the API build does not report a
 * model, and a missing fact is honest while an invented one is not — `panels.tsx
 * ::VoiceFacts` makes the same call for the same reason. A catalogue read that FAILS is a
 * different case: the agent's own state is still known, so the facts stay and only the
 * picker is replaced by the refusal.
 */
export function AgentModel({ agent, slug }: { agent: AgentWithLlm; slug: string }) {
  const session = useClientSession();
  const view = agentLlmView(agent);
  // The catalogue is only worth fetching if there is a panel to put it in — see the hook.
  // `view` is a pure function of the agent already on screen, so this decision is
  // available before the query starts rather than after it has been paid for.
  const catalogue = useOrganizationLlmDefaults(session, view !== null);

  // Nothing to say, so nothing is said. Not a skeleton and not an empty card: this is an
  // API that does not carry the field, which is neither a load nor a failure.
  if (view === null) return null;

  return (
    <Card title="The model it thinks with">
      <div className="space-y-5">
        <Inheritance view={view} catalogue={catalogue.data} slug={slug} />

        {catalogue.error != null && (
          <ProblemNotice error={catalogue.error} onRetry={() => void catalogue.refetch()} />
        )}

        {agent.status === ARCHIVED_STATUS ? (
          <p className="text-sm text-ink-muted">
            This agent is archived, so its settings are kept exactly as they were — they are
            part of the record of what it did. Bring it back first if you want to change
            them.
          </p>
        ) : catalogue.isLoading ? (
          <Skeleton rows={4} label="Loading the models you can choose from" />
        ) : !catalogue.data ? null : (
          <ModelForm agent={agent} view={view} catalogue={catalogue.data} />
        )}
      </div>
    </Card>
  );
}

/** What each source means, in the client's words. A wire string chooses between them. */
const SOURCE_COPY: Record<LlmModelSource, { title: string; body: string }> = {
  agent: {
    title: "This agent has its own model",
    body: "It ignores your organisation default until you put it back on it.",
  },
  organization: {
    title: "Using your organisation default",
    body: "Every agent that has not been given its own model runs on it.",
  },
  platform: {
    title: "Using the Calevate default",
    body: "Neither this agent nor your organisation has picked a model, so it runs on the one we use by default.",
  },
};

/**
 * Where this agent's model came from, and what it costs — said before any control.
 *
 * The order is deliberate and is `OpeningNotices`': the FACT first, the control under it.
 * A picker with the current state only inferable from which radio is filled in makes the
 * reader work out the answer from the widget, and inheritance is exactly the thing they
 * came here to read.
 */
function Inheritance({
  view,
  catalogue,
  slug,
}: {
  view: AgentLlmView;
  /** `undefined` while the catalogue is in flight or after it failed — see below. */
  catalogue: OrganizationLlmDefaults | undefined;
  slug: string;
}) {
  const { href } = useClientRealm();
  const copy = lookup(SOURCE_COPY, view.source);
  // WHAT THE MODEL IN FORCE ADDS TO THEIR BILL. `null` covers both "the catalogue has not
  // arrived" and "the catalogue cannot price this model", and the sentence below says
  // nothing at all rather than printing a figure for either — a screen that guessed
  // ₹0.00 here would be telling an owner an upgrade is free.
  const surcharge = catalogue ? agentInForceSurcharge(view, catalogue.available) : null;

  return (
    <NoticeBox
      tone="neutral"
      icon={<BrainCircuit aria-hidden className="h-5 w-5" />}
      title={`${copy?.title ?? "The model in use"}: ${view.effective}`}
    >
      <p className="mt-1">
        {copy?.body}
        {surcharge === null ? null : compareRates(surcharge, "0") === "same" ? (
          <> It adds nothing to what you are charged for a minute.</>
        ) : (
          <>
            {" "}
            It adds {formatRupeeRate(surcharge)} to every minute this agent is charged for,
            on top of your plan&apos;s own rate.
          </>
        )}
      </p>
      {view.source === "organization" || view.source === "platform" ? (
        <p className="mt-2">
          <Link
            href={href(`/c/${slug}/settings/models`)}
            className="font-medium underline underline-offset-2"
          >
            Change it for every agent
          </Link>
        </p>
      ) : null}
    </NoticeBox>
  );
}

/**
 * The override itself.
 *
 * Sends ONLY `llm_model`, which is what makes going back to inheriting expressible at
 * all: `null` is a value the API reads as "follow the organisation", while OMITTING the
 * field means "leave this agent alone". They are one keystroke apart and they are opposite
 * requests, which is why the body is built by `agentModelPatch` rather than written inline
 * (`lib/api/llmModels.ts`).
 *
 * `useUpdateAgent` rather than a mutation of this panel's own: it is the same
 * `PATCH /v1/agents/{id}` the identity form already uses, and it already invalidates the
 * roster, the archive, this agent and its publishing state. A second hook on one route
 * would be a second list of cache keys, and the second list is always the one that forgets
 * a key (`agents.ts`).
 */
function ModelForm({
  agent,
  view,
  catalogue,
}: {
  agent: AgentWithLlm;
  view: AgentLlmView;
  catalogue: OrganizationLlmDefaults;
}) {
  const session = useClientSession();
  const save = useUpdateAgent(session, agent.id);
  /**
   * `org:manage`, NOT `agents:write` — `agents.ts` argues it in full: `agents:write` is
   * admin-only and neither client role holds it, so gating this on it would disable the
   * control for the owner it exists for.
   */
  const write = useWriteAccess(session, "org:manage", "change this agent's model");

  // Wrapped for `settings/models`' reason: `null` is a real choice here ("follow my
  // organisation"), so it cannot double as "nothing picked yet".
  const [picked, setPicked] = useState<{ model: string | null } | null>(null);
  const selected = picked ? picked.model : view.chosen;
  const changed = selected !== view.chosen;

  // The "follow my organisation" row's own cost: what the ACCOUNT's choice is surcharged
  // at, which is nothing when the account is itself following the platform default.
  const organizationSurcharge = inForceSurcharge(catalogue);
  // Everything is compared against what this agent runs TODAY.
  const baselineSurcharge = agentInForceSurcharge(view, catalogue.available);

  /**
   * A model this agent is pinned to that the catalogue no longer offers — the same real
   * state the settings screen handles, argued there. Without the row the picker would
   * show nothing selected on an agent that is definitely running on something.
   */
  const retired =
    view.chosen !== null && modelOption(catalogue.available, view.chosen) === undefined
      ? view.chosen
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
      label: "Follow my organisation",
      detail: `Today that is ${catalogue.effective_default}. If you change your organisation default, this agent follows.`,
      surcharge: organizationSurcharge,
      badge: view.chosen === null ? "in use" : undefined,
      baseline: view.chosen === null,
    },
    ...catalogue.available.map<ModelChoice>((option) => ({
      value: option.model,
      label: option.model,
      // Provider is the group heading (D-456); the row's note is model-specific only.
      provider: option.provider,
      detail: option.model === catalogue.effective_default ? "Your organisation default" : "",
      surcharge: option.client_surcharge_inr_per_minute,
      badge: view.chosen === option.model ? "in use" : undefined,
      baseline: view.chosen !== null && view.effective === option.model,
      // SHOWN, PRICED AND NOT SELECTABLE. `PATCH /v1/agents/{id}` refuses a model this
      // platform has no deployment for (`llm_model_not_deployed`) — the same predicate
      // that decides whether the agent could be PUBLISHED on it — so offering the row
      // would show a client a price and then answer their click with a 422.
      unavailable: unavailableReason(option),
    })),
  ];

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!changed) return;
        save.mutate(agentModelPatch(selected));
      }}
    >
      <RestrictionNote reason={write.reason} />
      {/* The server's own words. A model this plan does not include and a model that does
          not exist are different refusals, and only the API can tell them apart. */}
      {save.error != null && <ProblemNotice error={save.error} />}

      <ModelPicker
        name={`agent-llm-model-${agent.id}`}
        legend="Model for this agent"
        hint="Figures are what a model adds to every minute you are charged for."
        choices={choices}
        value={selected}
        baselineSurcharge={baselineSurcharge}
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
