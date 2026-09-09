"use client";

import Link from "next/link";
import { AlertTriangle } from "lucide-react";

import { NoticeBox } from "@/components/ui";
import { holdRule } from "@/lib/api/holds";

/**
 * What is holding this account, at the top of its own page.
 *
 * `TenantSummary.holds` is `read_tenant_holds` — the blockers themselves — so this says
 * the same thing as the work list and as the client's refusal, in the same vocabulary. It
 * is here because the panels below (numbers, templates, registrations) all read as "this
 * client is nearly ready", and an account whose dialling is refused outright should not
 * have to be inferred from a screen full of green.
 *
 * Renders nothing when nothing holds them: an operator opening a healthy account should
 * not be shown a box saying so.
 */
export function HoldsBanner({ tenantId, holds }: { tenantId: string; holds: string[] }) {
  if (holds.length === 0) return null;
  return (
    <NoticeBox
      tone="warn"
      icon={<AlertTriangle className="h-5 w-5" />}
      title="This account is waiting on us."
    >
      <ul className="mt-2 space-y-2 text-xs">
        {holds.map((rule) => {
          const copy = holdRule(rule);
          return (
            <li key={rule} className="flex flex-wrap items-baseline gap-2">
              <span className="font-medium">{copy?.label ?? rule}</span>
              <span className="opacity-80">
                {copy?.blocks ??
                  "We do not have a plain description for this hold, but the check that set it does."}
              </span>
              {copy && (
                <Link href={copy.screen(tenantId)} className="font-medium underline">
                  {copy.cta}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </NoticeBox>
  );
}
