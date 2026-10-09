"use client";

import Link from "next/link";
import { UserPlus } from "lucide-react";

import { NoticeBox } from "@/components/ui";
import { useUnfinishedOnboardings } from "@/lib/api/onboarding";

/**
 * Accounts nobody can sign in to and nobody has been invited into (D-695), each linking to
 * its page, where the invite is. Left over from when creating an account and inviting its
 * owner were separate steps; new accounts are always created with their invitation.
 *
 * Renders nothing while loading, on a failed read, or when there are none: the directory
 * below is the screen's job, and this list is a nudge on top of it.
 */
export function NoOwnerAccounts() {
  const unfinished = useUnfinishedOnboardings();
  if (!unfinished.data) return null;
  const orphans = unfinished.data.filter((row) => !row.owner_present && !row.invite_pending);
  if (orphans.length === 0) return null;
  return (
    <NoticeBox
      tone="warn"
      icon={<UserPlus aria-hidden className="h-5 w-5" />}
      title={orphans.length === 1 ? "1 account has no owner invited yet" : `${orphans.length} accounts have no owner invited yet`}
    >
      <ul className="mt-1 space-y-1">
        {orphans.map((row) => (
          <li key={row.tenant_id} className="min-w-0 truncate">
            <Link
              href={`/admin/tenants/${row.tenant_id}`}
              className="font-medium underline-offset-2 hover:underline"
            >
              {row.name}
            </Link>{" "}
            — invite the owner
          </li>
        ))}
      </ul>
    </NoticeBox>
  );
}
