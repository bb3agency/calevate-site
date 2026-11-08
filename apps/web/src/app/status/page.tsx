import type { Metadata } from "next";

import { Providers } from "@/app/providers";
import { MarketingPage } from "@/components/marketing/pageShell";
import { publicPageMetadata } from "@/lib/seo/metadata";

import { StatusScreen } from "./StatusScreen";

/**
 * The public status page, meant for status.calevate.tech; until that host is served
 * (OPERATIONS §2 gate H-2: DNS, certificate and the nginx block in `runbooks/auto-healer.md`
 * §5) it is live at calevate.tech/status only. It reads one unauthenticated endpoint and
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
      {/* StatusScreen reads through React Query; the marketing shell mounts no client. */}
      <Providers>
        <StatusScreen />
      </Providers>
    </MarketingPage>
  );
}
