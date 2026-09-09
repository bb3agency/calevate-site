"use client";

import { use } from "react";

import { DashboardScreen } from "./DashboardScreen";

/**
 * The route is chrome and nothing else (UX-DOCTRINE §6): a page module may export only
 * `default` (D-196), so the screen it mounts is where the work lives.
 */
export default function DashboardPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  return <DashboardScreen slug={slug} />;
}
