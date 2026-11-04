import { EXISTING_SECTION } from "@/lib/phoneNumbersSection";
import { redirectWithin } from "@/lib/routeRedirect";

/**
 * Retired route: forwarding the client's existing number is the "Your existing number"
 * section of Phone numbers now, beside the numbers it forwards to.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await redirectWithin(params, searchParams, "/phone-number", { section: EXISTING_SECTION });
}
