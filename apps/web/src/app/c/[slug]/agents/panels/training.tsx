"use client";

/**
 * WHAT THE AGENT KNOWS — a pointer to the business's knowledge, not a copy of it.
 *
 * Knowledge belongs to the business and every agent answers from it (D-689), so this agent
 * has no knowledge of its own to list or add to. A per-agent form here would read as
 * teaching THIS agent while in fact teaching all of them, so the panel says what is true
 * and sends the owner to `/c/<slug>/knowledge`, the one place knowledge is added.
 *
 * It renders a bare block rather than its own `Card`: the screen that mounts it decides
 * its container (UX-DOCTRINE §1 — never nest a Card inside a Card).
 */

import Link from "next/link";
import { BookOpen } from "lucide-react";

import { SECONDARY_BUTTON } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";

export function TrainingPanel({ agent }: { agent: Agent }) {
  const { href, session } = useClientRealm();

  return (
    <div>
      <p className="text-sm text-ink-muted">
        {agent.name} uses your business knowledge — the opening hours, prices, documents
        and web pages that every one of your agents answers from. Add to it or change it in
        one place, and all your agents pick it up.
      </p>
      <Link
        href={href(`/c/${session.orgSlug}/knowledge`)}
        className={`${SECONDARY_BUTTON} mt-4`}
      >
        <BookOpen aria-hidden className="h-4 w-4" />
        Open your business knowledge
      </Link>
    </div>
  );
}
