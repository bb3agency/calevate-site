"use client";

import Link from "next/link";
import { use } from "react";
import { ArrowLeft } from "lucide-react";

import { useClientRealm } from "@/lib/api/session";

import { ScriptBuilder } from "./ScriptBuilder";

/**
 * The script builder screen for one agent (client realm).
 *
 * A dedicated route rather than a section on the agent detail page: the builder is a full
 * authoring surface (steps, FAQ, AI assist, compiled-prompt preview) and deserves its own
 * space, the way the KB and campaigns do. The agent detail page links here.
 */
export default function AgentScriptPage({
  params,
}: {
  params: Promise<{ slug: string; agentId: string }>;
}) {
  const { slug, agentId } = use(params);
  const { href } = useClientRealm();

  return (
    <div className="space-y-5 pb-12">
      <Link
        href={href(`/c/${slug}/agents/${agentId}`)}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        Back to the agent
      </Link>
      <h1 className="text-xl font-semibold text-ink">Script builder</h1>
      <ScriptBuilder agentId={agentId} />
    </div>
  );
}
