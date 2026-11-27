"use client";

/**
 * VOICE — how it sounds: the voice picker (its insides are `panels/delivery.tsx`), and the
 * languages it speaks.
 *
 * The languages are shown here and changed in Settings, What it is: the main language is one
 * field of that form, and a main-language change rewrites the opening notices through it
 * (`AgentIdentity`'s offer, D-838). A second language control here would be two writers of
 * one field.
 */

import Link from "next/link";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { useSectionLink } from "@/components/console/settingsLayout";
import type { Agent } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";
import { CopilotSurfaceScope } from "@/lib/copilot/registry";
import { LANGUAGE_NAMES } from "@/lib/languageNames";
import { lookup } from "@/lib/lookup";

import { VoiceSection } from "./deliverySections";
import { WHAT_IT_IS_ANCHOR } from "./agentSections";

export function VoiceTab({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const settings = useSectionLink("settings");
  const name = (code: string) => lookup(LANGUAGE_NAMES, code) ?? code;
  const also = agent.reply_languages.slice(1).map(name);
  const settingsHref = `${settings?.href ?? href(`/c/${slug}/agents/${agent.id}?section=settings`)}#${WHAT_IT_IS_ANCHOR}`;
  return (
    <CopilotSurfaceScope
      route="/c/{slug}/agents/{id}"
      title={`Agent: voice (${agent.name})`}
      realm="client"
      facts={[
        { key: "agent_id", label: "Agent id", value: agent.id },
        { key: "language_primary", label: "Main language", value: name(agent.language_primary) },
        { key: "also_speaks", label: "Also replies in", value: also.length ? also.join(", ") : "no other language" },
      ]}
    >
      <div className="space-y-12">
        {/* No heading of its own: the tab's label is this part's heading. */}
        <VoiceSection agent={agent} />

        <Section
          headingLevel={3}
          title="Languages"
          action={
            <Link href={settingsHref} onClick={settings?.onClick} scroll={false} className={TEXT_ACTION}>
              Change
            </Link>
          }
        >
          <dl className="divide-y divide-line border-y border-line">
            <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3">
              <dt className="text-body text-ink">First language</dt>
              <dd className="text-body text-ink-muted">{name(agent.language_primary)}</dd>
            </div>
            <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3">
              <dt className="text-body text-ink">Also speaks</dt>
              <dd className="text-body text-ink-muted">{also.length ? also.join(", ") : "No other language"}</dd>
            </div>
          </dl>
        </Section>
      </div>
    </CopilotSurfaceScope>
  );
}
