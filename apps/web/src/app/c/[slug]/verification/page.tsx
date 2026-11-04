import { redirectWithin } from "@/lib/routeRedirect";

/**
 * Retired route (D-875): what we hold about the business is on Verify your business now,
 * beside the steps that change it.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await redirectWithin(params, searchParams, "/verify-business");
}
