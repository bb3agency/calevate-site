import { redirectWithin } from "@/lib/routeRedirect";

/** Retired route: the existing-number guide lives under Phone numbers now. */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await redirectWithin(params, searchParams, "/phone-number/existing-number");
}
