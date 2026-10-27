import { permanentRedirect } from "next/navigation";

import { OPEN_SETTINGS } from "@/lib/openAgentSettings";

/**
 * Retired route (founder, 27 Oct 2026): call handling is set on each agent's Settings, for
 * that agent or for all of them, so this account page is gone. The file stays so a bookmark
 * or an old link lands on the agents list, which opens the only agent's Settings straight
 * away when there is just one (`OPEN_SETTINGS`). Every query parameter rides along, `view`
 * included, so an operator's view-as session survives the hop.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { slug } = await params;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (value === undefined || key === OPEN_SETTINGS.param) continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item);
  }
  query.set(OPEN_SETTINGS.param, OPEN_SETTINGS.callHandling);
  permanentRedirect(`/c/${encodeURIComponent(slug)}/agents?${query.toString()}`);
}
