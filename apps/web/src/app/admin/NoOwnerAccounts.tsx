"use client";

import { ChecklistRows } from "@/components/console/checklist";
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
    <ChecklistRows
      heading={orphans.length === 1 ? "1 account has no owner invited yet" : `${orphans.length} accounts have no owner invited yet`}
      tone="warn"
      rows={orphans.map((row) => ({
        id: row.tenant_id,
        label: row.name,
        status: "not_started",
        statusText: "No owner",
        link: { href: `/admin/tenants/${row.tenant_id}`, label: "Invite" },
      }))}
    />
  );
}
