"use client";

/**
 * ONE AGENT'S HOME — six tabs (redesign 28 Nov 2026, PLAN.md §2; four under D-997, seven
 * under D-825, a twelve-section menu under D-657).
 *
 * A slim header (name, the On/Off switch, Try it, Put it live while a draft is waiting, and
 * "Calls (n)"), then What it says · What it knows · Actions · What it notes · Voice ·
 * Settings (`sections/agentSections.tsx`). Each tab is complete on its own and is visited
 * rather than read in order, which is the case UX-DOCTRINE §3 allows tabs for.
 *
 * The agent is the staff member and has no script of its own (D-997): scripts are written on
 * an inbound line or a campaign. What it says lists those jobs with their first words and a
 * link to each, so an agent's words are found from the agent without being stored on it.
 *
 * ## What may not move out of What it says
 *
 * The truthful-answer guarantee and the two opening notices under it. What it says is the
 * tab that opens first, so neither is ever behind a switch (doctrine §8 rule 7, hard rule 5).
 * The header carries the publish state on every tab.
 *
 * ## Where everything went
 *
 * Overview's checklist, notices and pending changes are What it says; its latest calls are
 * the header's "Calls (n)". Training is What it knows. What it notes and Voice were sections
 * of Settings. `/script` and `/test` redirect here, and old `?section=` values resolve
 * through `LEGACY_SECTIONS`.
 *
 * ## A deleted agent is a different screen
 *
 * Read-only, with one move: bring it back. The history is the reason the server archives
 * rather than erases, so what it was and its model stay on the page as a record; every
 * control that would write is gone.
 */

import dynamic from "next/dynamic";
import { useEffect } from "react";

import { ProblemNotice, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { SettingsLayout } from "@/components/console/settingsLayout";
import { isDeleted } from "@/lib/agentState";
import { useAgent, type Agent } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AgentHeader } from "./sections/agentHeader";
import { AGENT_TABS_LABEL, LEGACY_SECTIONS, useAgentSections, type AgentTab } from "./sections/agentSections";
import { WhatItSays } from "./sections/whatItSays";
import { AgentTour } from "./tour/AgentTour";

/*
 * Only the open tab's code is in the page's first load. What it says opens first and carries
 * the truthful-answer guarantee, so it stays static; the other five tabs and the
 * deleted-agent body are their own chunks. Bundled together they made this page about 450 KB
 * of JavaScript, most of it tabs nobody had opened, which is seconds on a slow phone network.
 *
 * Server rendering is unchanged (`next/dynamic` keeps `ssr`), and the chunks are fetched
 * once the page is idle so a tab tap rarely waits on the network.
 */
const loadKnowledge = () => import("./sections/training");
const loadActions = () => import("../actions/Actions");
const loadNotes = () => import("./sections/notesTab");
const loadVoice = () => import("./sections/voiceTab");
const loadSettings = () => import("./sections/settingsTab");
const loadDeleted = () => import("./sections/deletedAgent");

const tabLoading = () => <Skeleton rows={6} />;
const TrainingTab = dynamic(() => loadKnowledge().then((m) => m.TrainingTab), { loading: tabLoading });
const Actions = dynamic(() => loadActions().then((m) => m.Actions), { loading: tabLoading });
const NotesTab = dynamic(() => loadNotes().then((m) => m.NotesTab), { loading: tabLoading });
const VoiceTab = dynamic(() => loadVoice().then((m) => m.VoiceTab), { loading: tabLoading });
const SettingsTab = dynamic(() => loadSettings().then((m) => m.SettingsTab), { loading: tabLoading });
const DeletedAgentBody = dynamic(() => loadDeleted().then((m) => m.DeletedAgentBody), { loading: tabLoading });

/** Warms the other tabs' chunks once the browser is idle, after the open tab has drawn. */
function usePrefetchTabs(): void {
  useEffect(() => {
    const warm = () => {
      void loadKnowledge();
      void loadActions();
      void loadNotes();
      void loadVoice();
      void loadSettings();
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

  if (isDeleted(agent)) {
    return (
      <div className="space-y-8">
        <AgentHeader agent={agent} slug={slug} />
        <p className="max-w-prose text-sm text-ink-muted">
          Read-only while deleted. It comes back switched off.
        </p>
        <DeletedAgentBody agent={agent} slug={slug} />
      </div>
    );
  }

  return <LiveAgent agent={agent} slug={slug} />;
}

function LiveAgent({ agent, slug }: { agent: Agent; slug: string }) {
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
          switch (id as AgentTab) {
            case "knowledge":
              return <TrainingTab agent={agent} slug={slug} />;
            case "actions":
              return <ActionsTab agentId={agent.id} />;
            case "notes":
              return <NotesTab agent={agent} slug={slug} />;
            case "voice":
              return <VoiceTab agent={agent} slug={slug} />;
            case "settings":
              return <SettingsTab agent={agent} slug={slug} />;
            default:
              return <WhatItSays agent={agent} slug={slug} />;
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
