"use client";

import Link from "next/link";
import { use } from "react";
import { ArrowLeft } from "lucide-react";

import { useClientRealm } from "@/lib/api/session";

import { BuildAgent } from "./BuildAgent";

/**
 * Build an agent (D-440) — the route module, and almost nothing else.
 *
 * Everything about the form lives in `./BuildAgent.tsx` (UX-DOCTRINE §6: a Next route
 * module may export only `default` and route-segment fields (D-196), so it cannot be split
 * by extraction and the answer is to keep almost nothing in it).
 */
export default function NewAgentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const { href } = useClientRealm();

  return (
    <div className="space-y-5 pb-12">
      <Link
        href={href(`/c/${slug}/agents`)}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        All agents
      </Link>

      <BuildAgent slug={slug} />
    </div>
  );
}
