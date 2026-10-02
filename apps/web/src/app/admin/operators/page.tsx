"use client";

import { adminAccess, identityAnswerPending, useAdminMe } from "@/app/admin/access";
import { WithheldPanel } from "@/app/admin/withheld";
import { Skeleton } from "@/components/ui";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { OperatorsScreen } from "./OperatorsScreen";

/**
 * Admin accounts — who may sign in to this console, and in which tier.
 *
 * Every route behind it is `admin:operators`, which only `superadmin` holds
 * (`core/rbac.py`), and the READ carries it too, so a refused session is shown a withheld
 * panel rather than a list with dead buttons. Every act is audited and step-up confirmed
 * by the API; this screen adds the consequence before the click and a typed phrase bound to
 * the role (on add) or the account (on the row actions). A super admin cannot demote or
 * revoke themselves: the API refuses it (`operator_self_administration`), which is what
 * keeps a live super admin in existence, and the row says so where its controls would be.
 */
export default function OperatorsPage() {
  /**
   * ONE identity read for the whole screen, passed down. A second observer on a query in
   * the ERROR state triggers `retryOnMount`, and `identityAnswerPending` decides whether the
   * body mounts — together they once looped `/v1/admin/me` (~45 requests in 300ms).
   */
  const me = useAdminMe();
  const access = adminAccess(me, "admin:operators", "manage who may use this console");
  const pending = identityAnswerPending(me);

  // The outer declaration keeps the assistant on screen for the identity-pending and
  // refused renders; the list's own richer declaration wins once it mounts (innermost).
  useCopilotSurface({
    route: "/admin/operators",
    title: "Admin accounts",
    realm: "admin",
    fields: [],
    facts: [
      {
        key: "may_manage",
        label: "May this operator manage who may use the console",
        value: pending ? "still checking" : access.refused ? "no" : "yes",
      },
      {
        key: "screen",
        label: "What is on screen",
        value: pending
          ? "the permission check has not answered yet"
          : access.refused
            ? "a withheld panel — this account may not see who may sign in"
            : "the list of admin accounts",
      },
    ],
    apply: noFill,
  });

  // Mounting the list for an unknown session fires a GET that can only 403 for a normal
  // admin, and the operator would watch it populate and then be replaced by a refusal.
  if (pending) {
    return (
      <div className="max-w-3xl">
        <Skeleton rows={4} label="Checking whether you may manage admin accounts…" />
      </div>
    );
  }

  if (access.refused) {
    return (
      <div className="max-w-3xl">
        <WithheldPanel
          title="Admin accounts"
          reason={access.reason ?? "Your admin account cannot manage who may use this console."}
          subject="This screen would list who may sign in to this console and in which tier."
        />
      </div>
    );
  }

  return (
    <OperatorsScreen
      viewerId={me.data?.user_id ?? null}
      // A control FAILS CLOSED: `AdminAccess` has a paused state (offline) with no data, no
      // error and no sentence, and a bare `access.reason` would read that as "you may".
      restriction={
        access.allowed
          ? null
          : (access.reason ??
            "The console has not been able to establish what you may do here — you may be offline. The controls stay closed until it can.")
      }
    />
  );
}
