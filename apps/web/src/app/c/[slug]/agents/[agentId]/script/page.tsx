import { redirectToAgentTab } from "../tabRedirect";

/**
 * `/c/{slug}/agents/{id}/script` was the script builder's own route; the builder is the agent
 * page's Script tab since D-825. Links in the app point at the tab directly.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string; agentId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return redirectToAgentTab(params, searchParams, "script");
}
