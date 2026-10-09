import type { Metadata } from "next";

import { MarketingPage } from "@/components/marketing/pageShell";
import { publicPageMetadata } from "@/lib/seo/metadata";

import { StatusScreen } from "./StatusScreen";

/**
 * The public status page, served on status.calevate.tech (the edge rewrites that host to
 * this path; `infra/nginx/status.conf.template`). It reads one unauthenticated endpoint and
 * names no client: only what an operator or the outage playbook chose to post (D-701).
 */
export const metadata: Metadata = publicPageMetadata({
  path: "/status",
  title: "Service status — Calevate",
  description:
    "Whether Calevate's phone calls, phone numbers, dashboard and assistant are working " +
    "right now, and the problems posted in the last ninety days.",
});

export default function StatusPage() {
  return (
    <MarketingPage>
      <StatusScreen />
    </MarketingPage>
  );
}
