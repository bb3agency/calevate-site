"use client";

import Link from "next/link";
import { AlertTriangle, PauseCircle } from "lucide-react";

import { NoticeBox } from "@/components/ui";

/**
 * "This account is stopped", at the top of its own page.
 *
 * `organizations.status` was on this screen already — as one lowercase word in the grey
 * subtitle, between the slug and the vertical template. Everything under it reads as a
 * healthy account: agents, spend, a margin, a campaign setup card. So the screen an
 * operator opens to answer "why is this client not dialling" could answer it in a word
 * they were not looking at, on a page of green. `HoldsBanner` beside this one exists for
 * exactly that reason on the gates; the lifecycle state is the other half, and it is the
 * half that outranks them — a suspended account is refused before any hold is reached
 * (`compliance/service.py::check_dispatch` asks the account state first).
 *
 * ## What it does NOT print, and why that is deliberate
 *
 * **No erasure countdown.** `days_remaining` is computed server-side on one clock and
 * belongs beside the button that acts on it, on the Closing screen. A deadline printed on
 * two screens is a deadline that will disagree with itself — `lifecycle/page.tsx` made
 * the same call for the same reason, and this banner links there rather than racing it.
 *
 * **Nothing at all for a live account.** `prospect` and `onboarding` are ordinary states
 * on the way in, not stops, and `active` is the expected case: an operator opening a
 * healthy client should not be shown a box telling them it is healthy.
 */
export function AccountStateBanner({ tenantId, status }: { tenantId: string; status: string }) {
  if (status === "suspended") {
    return (
      <NoticeBox
        tone="warn"
        icon={<PauseCircle className="h-5 w-5" />}
        title="This account is suspended."
      >
        <p className="mt-1 text-xs opacity-90">
          Its outbound dialling is refused at the next dial — campaigns included. Inbound
          answering is deliberately untouched: their own customers still get through.
          Reactivating is one click on{" "}
          <Link
            href={`/admin/tenants/${tenantId}/lifecycle`}
            className="font-medium underline"
          >
            Account state
          </Link>
          , where the reason it was suspended was recorded.
        </p>
      </NoticeBox>
    );
  }

  if (status === "churned") {
    return (
      <NoticeBox
        tone="stop"
        icon={<AlertTriangle className="h-5 w-5" />}
        title="This account is closed."
      >
        <p className="mt-1 text-xs opacity-90">
          Nobody at the client can sign in, no call or campaign runs, and no agent can be
          published. Whether their records have been erased yet — and the date they go —
          is on{" "}
          <Link href={`/admin/tenants/${tenantId}/closure`} className="font-medium underline">
            Closing the account
          </Link>
          , which is also the one way to reopen it while nothing has been deleted.
        </p>
      </NoticeBox>
    );
  }

  return null;
}
