import { redirect } from "next/navigation";

/**
 * Retired route (D-875): what we hold about the business is on Verify your business now,
 * beside the steps that change it. The file stays so a bookmark, an email we already sent or
 * an old link still lands there; every query parameter rides along, `view` included, so an
 * operator's view-as session survives the hop (the same reason `lib/billingRedirect.ts`
 * carries them).
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
    if (value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item);
  }
  const carried = query.toString();
  redirect(`/c/${encodeURIComponent(slug)}/verify-business${carried ? `?${carried}` : ""}`);
}
