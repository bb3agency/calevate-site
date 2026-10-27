"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import type { Agent } from "@/lib/api/agents";
import { OPEN_SETTINGS } from "@/lib/openAgentSettings";

/**
 * With `OPEN_SETTINGS` asked for and one agent there is nothing to choose, so the list steps
 * aside to that agent's Settings, where call handling is; with several, the list is the
 * choice.
 */
export function useOpenOnlyAgentSettings(
  agents: readonly Pick<Agent, "id">[] | undefined,
  slug: string,
  href: (path: string) => string,
): void {
  const params = useSearchParams();
  const router = useRouter();
  const asked = params.get(OPEN_SETTINGS.param) === OPEN_SETTINGS.callHandling;
  const only = agents?.length === 1 ? agents[0] : undefined;
  useEffect(() => {
    if (!asked || !only) return;
    // No `#call-handling`: `href` appends the view-as marker after it. Call handling opens
    // the Settings tab, so the tab alone lands on it.
    router.replace(href(`/c/${slug}/agents/${only.id}?section=settings`));
  }, [asked, only, slug, href, router]);
}
