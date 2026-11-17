"use client";

/**
 * ONE AGENT'S WORKSPACE — four plain tabs (D-997, founder 16 Nov 2026; seven under D-825, a
 * twelve-section menu under D-657).
 *
 * A slim header (name, the On/Off switch, Try it, and Put it live while a draft is
 * waiting), then Overview · Actions · Settings · Training (`sections/agentSections.tsx`).
 * Each tab is complete on its own and is visited rather than read in order, which is the
 * case UX-DOCTRINE §3 allows tabs for.
 *
 * The agent is the staff member and has no script of its own: scripts are written on an
 * inbound line or a campaign, and Overview links to both. The script builder is no longer
 * on this page; `/script` and `?section=script` open Overview.
 *
 * ## What may not move out of Overview
 *
 * The truthful-answer guarantee, the two opening-notice switches under it, and the
 * publish state. Overview is the tab that opens first, so none of them is ever behind a
 * switch (doctrine §8 rule 7). The header carries the publish state on every tab.
 *
 * ## Where everything went
 *
 * Calls are Overview's latest calls; the voice, what it notes, call handling, the model and
 * the link to the business-wide leads and calling hours are in Settings; knowledge, the old
 * Test section and the try-it chat are Training. `/script` and `/test` redirect here, and
 * old `?section=` values resolve through `LEGACY_SECTIONS`.
 *
 * ## A deleted agent is a different screen
 *
 * Read-only, with one move: bring it back. The history is the reason the server archives
 * rather than erases, so what it captured, what it was and its model stay on the page as
 * a record; every control that would write is gone.
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, type ReactNode } from "react";

import { ProblemNotice, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { SettingsLayout } from "@/components/console/settingsLayout";
import { isDeleted } from "@/lib/agentState";
import { useAgent, type Agent } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AgentHeader } from "./sections/agentHeader";
import { AGENT_TABS_LABEL, LEGACY_SECTIONS, useAgentSections } from "./sections/agentSections";
import { Overview } from "./sections/overview";
import { AgentTour } from "./tour/AgentTour";

/*
 * Only the open tab's code is in the page's first load. Overview opens first and carries the
 * truthful-answer guarantee, so it stays static; the other three tabs and the deleted-agent
 * body are their own chunks. Bundled together they made this page about 450 KB of
 * JavaScript, most of it tabs nobody had opened, which is seconds on a slow phone network.
 *
 * Server rendering is unchanged (`next/dynamic` keeps `ssr`), and the chunks are fetched
 * once the page is idle so a tab tap rarely waits on the network.
 */
const loadTraining = () => import("./sections/training");
const loadSettings = () => import("./sections/settingsTab");
const loadActions = () => import("../actions/Actions");
const loadDeleted = () => import("./sections/deletedAgent");

const tabLoading = () => <Skeleton rows={6} />;
const TrainingTab = dynamic(() => loadTraining().then((m) => m.TrainingTab), { loading: tabLoading });
const SettingsTab = dynamic(() => loadSettings().then((m) => m.SettingsTab), { loading: tabLoading });
const Actions = dynamic(() => loadActions().then((m) => m.Actions), { loading: tabLoading });
const DeletedAgentBody = dynamic(() => loadDeleted().then((m) => m.DeletedAgentBody), { loading: tabLoading });

/** Warms the other tabs' chunks once the browser is idle, after the open tab has drawn. */
function usePrefetchTabs(): void {
  useEffect(() => {
    const warm = () => {
      void loadTraining();
      void loadSettings();
      void loadActions();
    };
    if (typeof window.requestIdleCallback === "function") {
      const id = window.requestIdleCallback(warm, { timeout: 4000 });
      return () => window.cancelIdleCallback(id);
    }
    const id = window.setTimeout(warm, 1500);
    return () => window.clearTimeout(id);
  }, []);
}

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
        <DeletedAgentBody agent={agent} slug={slug} leadsLink={leadsLink} />
      </div>
    );
  }

  return <LiveAgent agent={agent} slug={slug} leadsLink={leadsLink} />;
}

function LiveAgent({ agent, slug, leadsLink }: { agent: Agent; slug: string; leadsLink: ReactNode }) {
  const sections = useAgentSections(agent);
  usePrefetchTabs();
  return (
    <div className="space-y-6">
      <SettingsLayout
        label={AGENT_TABS_LABEL}
        menu="tabs"
        // Inside the layout so its links to a tab ("Try it", "Delete…") take the
        // unsaved-edits guard the tabs themselves take.
        header={<AgentHeader agent={agent} slug={slug} tour={<AgentTour />} />}
        sections={sections}
        aliases={LEGACY_SECTIONS}
        renderSection={(id) => {
          switch (id) {
            case "training":
              return <TrainingTab agent={agent} slug={slug} />;
            case "actions":
              return <ActionsTab agentId={agent.id} />;
            case "settings":
              return <SettingsTab agent={agent} slug={slug} leadsLink={leadsLink} />;
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
