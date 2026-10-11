import { redirect } from "next/navigation";

/**
 * `/c/{slug}/agents/{id}/test` is the agent's Test section (D-748). The agent's sections live
 * on one route under `?section=` (D-657), so this address answers with a redirect there, the
 * way the retired billing routes do (`lib/billingRedirect.ts`): no flash, and every other
 * query parameter (an operator's `view_as`) carried, `section` set.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string; agentId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { slug, agentId } = await params;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (key === "section" || value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item);
  }
  query.set("section", "test");
  redirect(`/c/${slug}/agents/${agentId}?${query.toString()}`);
}
