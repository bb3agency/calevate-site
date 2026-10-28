"use client";

/**
 * ONE AGENT'S WORKSPACE — seven plain tabs (D-825, founder 19 Oct 2026; was the D-657
 * twelve-section menu).
 *
 * A slim header (name, the On/Off switch, Try it, and Put it live while the script has
 * changes), then Overview · Script · Training · Actions · What it notes · Voice · Settings
 * (`sections/agentSections.tsx`). Each tab is complete on its own and is visited rather
 * than read in order, which is the case UX-DOCTRINE §3 allows tabs for; the decision is
 * D-825.
 *
 * ## What may not move out of Overview
 *
 * The truthful-answer guarantee, the two opening-notice switches under it, and the
 * publish state. Overview is the tab that opens first, so none of them is ever behind a
 * switch (doctrine §8 rule 7). The header carries the publish state on every tab.
 *
 * ## Where everything went
 *
 * Every control the twelve sections had is still here and still writes to the same
 * endpoint. Calls are Overview's latest calls; call handling, the model and the link to the
 * business-wide leads and calling hours are in Settings; knowledge, the old Test section
 * and the try-it chat are Training. The script builder, which had its own route, is the
 * Script tab, and `/script` and `/test` now redirect here. Old `?section=` values resolve
 * through `LEGACY_SECTIONS`.
 *
 * ## A deleted agent is a different screen
 *
 * Read-only, with one move: bring it back. The history is the reason the server archives
 * rather than erases, so what it captured, what it was and its model stay on the page as
 * a record; every control that would write is gone.
 */

import Link from "next/link";
import type { ReactNode } from "react";
import { useSearchParams } from "next/navigation";

import { NoticeBox, ProblemNotice, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { SettingsLayout, useActiveSection } from "@/components/console/settingsLayout";
import { isDeleted } from "@/lib/agentState";
import { useAgent, type Agent } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AgentIdentity } from "../AgentIdentity";
import { AgentModel } from "../AgentModel";
import { Actions } from "../actions/Actions";
import { ExtractionList } from "../panels/extraction";
import { ScriptBuilder } from "./script/ScriptBuilder";
import { AgentHeader } from "./sections/agentHeader";
import { AGENT_TABS_LABEL, LEGACY_SECTIONS, useAgentSections } from "./sections/agentSections";
import { VoiceSection } from "./sections/deliverySections";
import { Overview } from "./sections/overview";
import { SettingsTab } from "./sections/settingsTab";
import { TrainingTab } from "./sections/training";
import { AgentTour } from "./tour/AgentTour";

/** The screen, from the route's params. Loading, failure and the agent are three branches. */
export function AgentWorkspace({ slug, agentId }: { slug: string; agentId: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const agent = useAgent(session, agentId);

  // Declared only while there is no agent: once it arrives, the mounted tab's own surface
  // (e.g. the capture columns) is the one the assistant should see.
  useCopilotSurface(
    agent.data
      ? null
      : {
          route: "/c/{slug}/agents/{id}",
          title: "Agent",
          realm: "client",
          fields: [],
          facts: [
            { key: "agent_id", label: "Agent id", value: agentId },
            {
              key: "state",
              label: "What is on screen",
              value: agent.error
                ? "the agent failed to load, so none of its settings are on screen"
                : "still loading",
            },
          ],
          apply: noFill,
        },
  );

  if (agent.error && !agent.data) {
    // The way back stays: a 404 on a bookmarked agent is when a person most needs it.
    return (
      <div className="space-y-4">
        <PageHeader back={{ href: href(`/c/${slug}/agents`), label: "All agents" }} />
        <ProblemNotice error={agent.error} onRetry={() => void agent.refetch()} />
      </div>
    );
  }
  if (agent.isLoading || !agent.data) return <Skeleton rows={8} />;
  // A failed REFRESH keeps the page mounted under the refusal: TanStack keeps the last
  // answer, and unmounting it threw away whatever the owner was typing in its forms.
  return (
    <>
      {agent.error && (
        <div className="mb-4">
          <ProblemNotice error={agent.error} onRetry={() => void agent.refetch()} />
        </div>
      )}
      <AgentDetail agent={agent.data} slug={slug} />
    </>
  );
}

function AgentDetail({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const leadsLink = (
    <Link
      href={href(`/c/${slug}/leads`)}
      className="font-medium underline underline-offset-2 hover:text-ink"
    >
      Leads
    </Link>
  );

  if (isDeleted(agent)) {
    return (
      <div className="space-y-8">
        <AgentHeader agent={agent} slug={slug} />
        <p className="max-w-prose text-sm text-ink-muted">
          Read-only while deleted. It comes back switched off.
        </p>
        <ExtractionList agent={agent} leadsHref={leadsLink} />
        <section aria-labelledby="deleted-identity-heading">
          <h3 id="deleted-identity-heading" className="mb-2 text-heading text-ink">
            What it is
          </h3>
          <AgentIdentity agent={agent} />
        </section>
        <AgentModel agent={agent} slug={slug} />
      </div>
    );
  }

  return <LiveAgent agent={agent} slug={slug} leadsLink={leadsLink} />;
}

function LiveAgent({ agent, slug, leadsLink }: { agent: Agent; slug: string; leadsLink: ReactNode }) {
  const sections = useAgentSections(agent);
  const active = useActiveSection(sections, undefined, LEGACY_SECTIONS);
  const { href } = useClientRealm();
  return (
    // The Script tab's flow picture and the editor beside it use the width a desktop has,
    // so the shell takes the wide rail while that tab is open.
    <div className="space-y-6">
      <SettingsLayout
        label={AGENT_TABS_LABEL}
        menu="tabs"
        // Inside the layout so its links to a tab ("Try it", "Delete…") take the
        // unsaved-edits guard the tabs themselves take.
        header={
          <AgentHeader
            agent={agent}
            slug={slug}
            onScriptTab={active === "script"}
            tour={<AgentTour />}
          />
        }
        sections={sections}
        aliases={LEGACY_SECTIONS}
        renderSection={(id) => {
          switch (id) {
            case "script":
              return (
                <>
                  <StarterDraftNotice agent={agent} />
                  <ScriptBuilder
                    agentId={agent.id}
                    knowledgeHref={href(`/c/${slug}/knowledge`)}
                    trainingHref={href(`/c/${slug}/agents/${agent.id}?section=training`)}
                  />
                </>
              );
            case "training":
              return <TrainingTab agent={agent} slug={slug} />;
            case "actions":
              return <ActionsTab agentId={agent.id} />;
            case "captured":
              return <ExtractionList agent={agent} leadsHref={leadsLink} />;
            case "voice":
              return <VoiceSection agent={agent} />;
            case "settings":
              return <SettingsTab agent={agent} slug={slug} />;
            default:
              return <Overview agent={agent} slug={slug} />;
          }
        }}
      />
    </div>
  );
}

function ActionsTab({ agentId }: { agentId: string }) {
  const session = useClientSession();
  return <Actions agentId={agentId} session={session} />;
}

/**
 * Just made from a job (`/agents/new`, `?from=starter`): the script below is the ready-made
 * one, saved but not live. Said once, above it, until the agent is published.
 */
function StarterDraftNotice({ agent }: { agent: Agent }) {
  const params = useSearchParams();
  if (params.get("from") !== "starter" || agent.published) return null;
  return (
    <NoticeBox tone="neutral" className="mb-6">
      Your agent is a draft. Review the script, then put it live.
    </NoticeBox>
  );
}
