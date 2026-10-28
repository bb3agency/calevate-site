"use client";

import Link from "next/link";

import { useActionFeedback } from "@/components/arc/feedback";
import { ModelTierSetting } from "@/components/modelTierSetting";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import { isDeleted } from "@/lib/agentState";
import { useUpdateAgent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  agentInForceSurcharge,
  agentLlmView,
  agentModelPatch,
  useOrganizationLlmDefaults,
  type AgentLlmView,
  type AgentWithLlm,
  type LlmModelSource,
} from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

/**
 * ONE AGENT'S MODEL TIER, the agent page's Model section: inherited from the organisation,
 * or set here (D-680). `llm_tier_source` is the server's answer to where the tier came from
 * and is read as a wire string through `lookup`; the screen never derives it.
 *
 * Whether this agent's minutes carry the surcharge is the server's `llm_surcharged`, because
 * an agent following a level it did not choose is never surcharged. A catalogue read that
 * fails leaves the agent's own facts on screen and replaces only the options with the refusal.
 */
export function AgentModel({ agent, slug }: { agent: AgentWithLlm; slug: string }) {
  const session = useClientSession();
  const view = agentLlmView(agent);
  const catalogue = useOrganizationLlmDefaults(session);
  const save = useUpdateAgent(session, agent.id);
  // `ModelTierSetting` draws the save bar's faces and the refusal beside it, so a failure
  // stays inline. The bar closes on success; the summary row's `SavedTick` says it, not a toast.
  const feedback = useActionFeedback(save, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change this agent's model");

  useCopilotSurface(
    isDeleted(agent)
      ? null
      : {
          route: "/c/{slug}/agents/{id}",
          title: "Agent: model",
          realm: "client",
          fields: [],
          facts: [
            { key: "agent_id", label: "Agent id", value: agent.id },
            { key: "tier", label: "The model tier this agent runs on", value: view.label },
            {
              key: "source",
              label: "Where that tier comes from",
              value: lookup(SOURCE_LINE, view.source) ?? "not stated",
            },
            ...(catalogue.data && catalogue.data.tier_choosable !== false
              ? [
                  {
                    key: "options",
                    label: "Tiers on offer, and what each adds per minute (INR)",
                    value: catalogue.data.available
                      .map(
                        (option) =>
                          `${option.label}: ${option.client_surcharge_inr_per_minute} per minute${
                            option.is_available === false ? ", not switched on for this account" : ""
                          }`,
                      )
                      .join("; "),
                  },
                ]
              : []),
          ],
          // A per-minute charge on every call: chosen by the owner behind Save, never filled.
          apply: noFill,
        },
  );

  const source = <SourceLine view={view} slug={slug} />;

  if (catalogue.error != null) {
    return (
      <div className="space-y-4">
        <p className="text-body text-ink">{view.label}</p>
        {source}
        <ProblemNotice error={catalogue.error} onRetry={() => void catalogue.refetch()} />
      </div>
    );
  }
  if (catalogue.isLoading || !catalogue.data) {
    return <Skeleton rows={4} label="Loading the models you can choose from" />;
  }
  const data = catalogue.data;

  return (
    <ModelTierSetting
      mode="agent"
      name={`agent-llm-model-${agent.id}`}
      catalogue={data}
      saved={view.chosen}
      inForceLabel={view.label}
      source={source}
      followLabel={data.effective_tier_label}
      followSurcharge={data.in_force_surcharge_inr_per_minute}
      baselineSurcharge={agentInForceSurcharge(view, data)}
      write={write}
      status={feedback.status}
      error={save.error}
      savedAt={save.isSuccess ? save.submittedAt : 0}
      // Sends ONLY `llm_tier`: `null` follows the organisation, an omitted field leaves the
      // agent alone, so the body is built by `agentModelPatch`.
      onSave={(tier, done) => save.mutate(agentModelPatch(tier), { onSuccess: done })}
      readOnly={
        isDeleted(agent) ? (
          <p className="text-body text-ink-muted">
            Deleted. Bring it back to change its model.
          </p>
        ) : undefined
      }
    />
  );
}

/** Where this agent's tier comes from, in one line. A wire string chooses between them. */
const SOURCE_LINE: Record<LlmModelSource, string> = {
  agent: "Set for this agent. The default does not change it.",
  organization: "Follows your organisation default.",
  platform: "Follows the standard default.",
};

function SourceLine({ view, slug }: { view: AgentLlmView; slug: string }) {
  const { href } = useClientRealm();
  return (
    <span>
      {lookup(SOURCE_LINE, view.source) ?? `This agent runs on ${view.label}.`}{" "}
      <Link href={href(`/c/${slug}/settings/models`)} className={TEXT_ACTION}>
        Change it for every agent
      </Link>
    </span>
  );
}
