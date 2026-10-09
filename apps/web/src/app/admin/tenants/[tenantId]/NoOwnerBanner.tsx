"use client";

import Link from "next/link";
import { UserPlus } from "lucide-react";

import { NoticeBox } from "@/components/ui";
import { useOwnerStatus } from "@/lib/api/onboarding";

import { OwnerInvitePanel } from "./OwnerInvitePanel";

/**
 * "No owner invited yet": an account nobody can sign in to and nobody has been invited
 * into, with the invite right here (D-695). Such accounts were left when creating an
 * account and inviting its owner were separate steps. While an invitation is out and
 * unused, a quieter line says so instead.
 *
 * Renders nothing while loading or on a failed read: the tenant page carries on without it.
 */
export function NoOwnerBanner({ tenantId, slug }: { tenantId: string; slug: string }) {
  const status = useOwnerStatus(tenantId);
  if (status.isPending) return null;
  if (status.isError) {
    return (
      <p className="text-sm text-ink-muted">
        We could not check whether anybody can sign in to this account.
      </p>
    );
  }
  if (status.data.owner_present) return null;
  if (status.data.invite_pending) {
    return (
      <p className="text-sm text-ink-muted">
        The owner has been invited and has not joined yet.{" "}
        <Link
          href={`/admin/tenants/${tenantId}/invitations`}
          className="font-medium text-brand-strong hover:underline"
        >
          See the invitation
        </Link>
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <NoticeBox
        tone="warn"
        icon={<UserPlus aria-hidden className="h-5 w-5" />}
        title="No owner invited yet"
      >
        <p className="mt-1">
          Nobody can sign in to this account. Invite the owner below; their voice workspace is
          set up when they first sign in.
        </p>
      </NoticeBox>
      <OwnerInvitePanel created={{ id: tenantId, slug }} />
    </div>
  );
}
