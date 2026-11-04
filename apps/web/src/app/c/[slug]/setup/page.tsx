import { STEPS_MODE } from "@/lib/businessProfileMode";
import { redirectWithin } from "@/lib/routeRedirect";

/**
 * Retired route: Business setup is the business profile asked one question at a time, a
 * mode of Business profile now. A `step` the old link named rides along.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await redirectWithin(params, searchParams, "/settings/business", { mode: STEPS_MODE });
}
