import { redirectToAgentTab } from "../tabRedirect";

/**
 * `/c/{slug}/agents/{id}/script` was the script builder's own route, then the Script tab
 * (D-825). The agent has no script of its own since D-997, so the address opens Overview,
 * which says where scripts are written now.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string; agentId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return redirectToAgentTab(params, searchParams, "overview");
}
