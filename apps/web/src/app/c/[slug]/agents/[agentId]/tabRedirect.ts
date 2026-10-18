import { redirect } from "next/navigation";

/**
 * An agent address that used to be its own page and is now a tab of the agent page (D-748's
 * `/test`, D-825's `/script`): answered with a redirect, the way the retired billing routes
 * are (`lib/billingRedirect.ts`), with every other query parameter (an operator's `view_as`)
 * carried and `section` set.
 */
export async function redirectToAgentTab(
  params: Promise<{ slug: string; agentId: string }>,
  searchParams: Promise<Record<string, string | string[] | undefined>>,
  tab: string,
): Promise<never> {
  const { slug, agentId } = await params;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (key === "section" || value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item);
  }
  query.set("section", tab);
  redirect(`/c/${slug}/agents/${agentId}?${query.toString()}`);
}
