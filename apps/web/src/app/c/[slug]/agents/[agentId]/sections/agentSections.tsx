"use client";

/**
 * THE AGENT PAGE'S MENU, ordered by what an owner comes to do, with one line of state each.
 *
 * Script comes straight after Overview because it is the screen's main job. Knowledge,
 * Actions and the call log follow; then what it notes, the business's leads and calling
 * hours, its voice and call handling; Settings last. The call log and Leads & hours live on
 * their own pages (the call list, and the business-wide calling setup, which is per client
 * and not per agent), so their entries link out rather than open in place.
 *
 * The state lines are read from what the page already loads; nothing here adds a request
 * the sections do not make anyway.
 */

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import type { SettingsSection } from "@/components/console/settingsLayout";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import type { Agent } from "@/lib/api/agents";
import { useScript } from "@/lib/api/script";

import { hasUnpublished, workingCopy } from "../script/scriptDraft";

export function useAgentSections(agent: Agent, slug: string): SettingsSection[] {
  const session = useClientSession();
  const { href } = useClientRealm();
  const script = useScript(session, agent.id);
  const working = agent.published && agent.status === "live";

  let scriptLine = "";
  if (script.data) {
    const copy = workingCopy(script.data).script;
    const count = copy.stages?.length ?? 0;
    const shape =
      copy.raw_override !== null
        ? "Written by hand"
        : script.data.version === null && count === 0
          ? "Not written yet"
          : `${count} ${count === 1 ? "section" : "sections"}`;
    scriptLine = hasUnpublished(script.data, copy) ? `${shape} · changes waiting` : shape;
  }

  return [
    { id: "overview", label: "Overview", detail: working ? "Taking calls" : "Not taking calls" },
    { id: "script", label: "Script", detail: scriptLine },
    { id: "knowledge", label: "Knowledge", detail: "Shared by all your agents" },
    { id: "actions", label: "Actions", detail: "What it can do on a call" },
    {
      id: "call-log",
      label: "Calls",
      detail: "Every call it handled",
      href: href(`/c/${slug}/calls?agent_id=${agent.id}`),
    },
    { id: "captured", label: "What it notes", detail: "Details it writes down" },
    {
      id: "leads-hours",
      label: "Leads & hours",
      detail: "For your whole business",
      href: href(`/c/${slug}/lead-sources`),
    },
    { id: "voice", label: "Voice", detail: "How it sounds" },
    { id: "calls", label: "Call handling", detail: "Hand-over, call length, memory" },
    { id: "advanced", label: "Settings", detail: "What it is, its model, delete" },
  ];
}

/** The menu as rows, for the bottom of Overview on a phone. */
export function SectionRows({ sections }: { sections: SettingsSection[] }) {
  const { href } = useClientRealm();
  return (
    <nav aria-label="Everything about this agent" className="mt-10 lg:hidden">
      <ul className="divide-y divide-line border-y border-line">
        {sections.map((section) => (
          <li key={section.id}>
            <Link
              href={section.href ?? href(`?section=${section.id}`)}
              scroll={section.href ? undefined : false}
              className="flex min-h-14 items-center gap-3 py-2.5 hover:bg-ink/[0.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
            >
              <span className="min-w-0 flex-1">
                <span className="block text-body font-medium text-ink">{section.label}</span>
                {section.detail && <span className="block truncate text-meta text-ink-muted">{section.detail}</span>}
              </span>
              <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-ink-faint" />
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
