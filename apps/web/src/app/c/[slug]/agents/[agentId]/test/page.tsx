import { redirectToAgentTab } from "../tabRedirect";

/** `/c/{slug}/agents/{id}/test` was the Test section (D-748); testing is in Training (D-825). */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string; agentId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return redirectToAgentTab(params, searchParams, "training");
}
