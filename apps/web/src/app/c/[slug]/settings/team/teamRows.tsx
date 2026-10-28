"use client";

import { useState } from "react";

import type { DataColumn } from "@/components/console/dataTable";
import { InfoTip } from "@/components/console/infoTip";
import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { RowMenu } from "@/components/arc/menu";
import { TEXT_ACTION_DANGER } from "@/components/console/section";
import { FIELD_INLINE, NoticeBox, formatIST } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import {
  ROLE_COPY,
  type CreatedInvitation,
  type Member,
  type MemberRole,
  type PendingInvitation,
} from "@/lib/api/members";

import { ROLES } from "./roles";

/**
 * The team table: one row per person on the account, then one per unused invitation.
 * A row is about a human being, so it is kept out of the screen that decides what may be
 * done to them.
 */
export type TeamRow =
  | { kind: "member"; id: string; member: Member; email: string | null }
  | { kind: "invite"; id: string; invitation: PendingInvitation };

type RowStatus = { id: string; status: FeedbackStatus };

function statusFor(row: RowStatus | null, id: string): FeedbackStatus {
  return row?.id === id ? row.status : "idle";
}

export type TeamTableContext = {
  myId: string | null;
  canManage: boolean;
  restriction: string | null;
  /** Shown only when the owner-only roster loaded; staff never see colleagues' addresses. */
  showEmail: boolean;
  busyMember: string | null;
  busyInvite: string | null;
  /** The invitation being sent again. */
  resendingInvite: string | null;
  /** Each action's button face, for the row it was last pressed on. */
  roleStatus: RowStatus | null;
  resendStatus: RowStatus | null;
  revokeStatus: RowStatus | null;
  onRole: (member: Member, role: MemberRole) => void;
  onRemove: (member: Member) => void;
  onRevoke: (invitation: PendingInvitation) => void;
  onResend: (invitation: PendingInvitation) => void;
};

/**
 * Confirmation that the invitation was sent — NOT the link.
 *
 * A token anyone but the invitee can see can be redeemed by anyone but the invitee
 * (D-185, D-190 removed it from the response), so there is nothing to print. The copy
 * says what happened — queued, not delivered — and what to do if it does not arrive.
 */
export function IssuedInvite({ invitation }: { invitation: CreatedInvitation }) {
  return (
    <NoticeBox
      tone="ok"
      title={`Invitation sent to ${invitation.email}`}
      info="Sending again mails a new link, and the one in the earlier email stops working."
      infoLabel="sending an invitation again"
    >
      <p>Works once, until {formatIST(invitation.expires_at)}.</p>
      <p>Not there? Check spam, or Send again below.</p>
    </NoticeBox>
  );
}

function roleLabel(role: string): string {
  // `lookup()`, not `ROLE_COPY[role]`: a wire string indexing a literal walks the
  // prototype chain (src/lib/lookup.ts).
  return lookup(ROLE_COPY, role)?.label ?? role;
}

/**
 * The role control for one colleague. The select STAGES the choice and a second, named
 * press commits it: mutating straight from `onChange` let one stray scroll wheel grant
 * `org:manage` — including the power to remove the person who granted it. The staged
 * sentence says what the change does before it is made (GOV.UK's check-answers shape);
 * removal, which destroys access, gets the dialog instead.
 */
function RoleControl({
  member,
  busy,
  status,
  onRole,
}: {
  member: Member;
  busy: boolean;
  status: FeedbackStatus;
  onRole: (role: MemberRole) => void;
}) {
  const who = member.name ?? "this member";
  const [staged, setStaged] = useState<MemberRole | null>(null);
  // Once the write lands `member.role` becomes the staged value, so this goes null on its
  // own: the Save button disappears because the change happened, not because of a timer.
  const pendingRole = staged && staged !== member.role ? staged : null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="sr-only" htmlFor={`role-${member.id}`}>
        Role for {who}
      </label>
      <select
        id={`role-${member.id}`}
        value={staged ?? member.role}
        disabled={busy}
        onChange={(e) => setStaged(e.target.value as MemberRole)}
        className={`${FIELD_INLINE} w-28 sm:w-36`}
      >
        {ROLES.map((value) => (
          <option key={value} value={value}>
            {ROLE_COPY[value].label}
          </option>
        ))}
      </select>
      {pendingRole && (
        <>
          <ActionButton
            variant="primary-sm"
            status={status}
            onClick={() => onRole(pendingRole)}
            aria-label={`Save ${who} as ${ROLE_COPY[pendingRole].label}`}
            successLabel="Saved"
          >
            Save role
          </ActionButton>
          <span className="basis-full text-meta text-ink-muted">
            {pendingRole === "owner"
              ? `${who} gets billing and can remove anyone, including you.`
              : `${who} loses billing and team access.`}
          </span>
        </>
      )}
    </div>
  );
}

function NameCell({ row, ctx }: { row: TeamRow; ctx: TeamTableContext }) {
  if (row.kind === "invite") {
    // The whole address (D-436): an owner must be able to see the address they typed is
    // the one they meant, and to tell two invites at one domain apart.
    return (
      <span className="block min-w-0">
        <span className="break-all font-mono text-ink">{row.invitation.email}</span>
        <span className="block text-meta text-ink-muted">
          Invited · expires {formatIST(row.invitation.expires_at)}
        </span>
      </span>
    );
  }
  const isMe = ctx.myId !== null && row.member.id === ctx.myId;
  return (
    <span className="block min-w-0">
      <span className="text-ink">{row.member.name ?? "Unnamed member"}</span>
      {isMe && <span className="ml-1.5 text-meta text-ink-faint">(you)</span>}
      {ctx.showEmail && row.email && (
        <span className="block truncate text-meta text-ink-muted md:hidden">{row.email}</span>
      )}
    </span>
  );
}

function RoleCell({ row, ctx }: { row: TeamRow; ctx: TeamTableContext }) {
  if (row.kind === "invite") {
    return <span className="text-ink-muted">{roleLabel(row.invitation.role)}</span>;
  }
  const isMe = ctx.myId !== null && row.member.id === ctx.myId;
  if (isMe) {
    // The reason where the control would have been: the API refuses self-directed changes
    // so a mis-click cannot cost somebody their own access.
    return (
      <span className="block">
        <span className="text-ink-muted">{roleLabel(row.member.role)}</span>
        <span className="block text-meta text-ink-faint">
          Only another owner can change yours.
        </span>
      </span>
    );
  }
  if (ctx.canManage) {
    return (
      <RoleControl
        member={row.member}
        busy={ctx.busyMember === row.member.id}
        status={statusFor(ctx.roleStatus, row.member.id)}
        onRole={(role) => ctx.onRole(row.member, role)}
      />
    );
  }
  return (
    <span className="block">
      <span className="text-ink-muted">{roleLabel(row.member.role)}</span>
      <span className="block text-meta text-ink-faint">
        {ctx.restriction ?? "Only an account owner can change this."}
      </span>
    </span>
  );
}

function ActionsCell({ row, ctx }: { row: TeamRow; ctx: TeamTableContext }) {
  if (!ctx.canManage) return null;
  if (row.kind === "invite") {
    // Both actions in view rather than behind a menu from `sm` up: an unanswered invitation
    // has only these two next steps, and the owner came to this row to take one of them.
    // Below `sm` the two buttons are wider than the column a phone can give them, so they
    // sit behind the row's ⋯ like a member's; the outcome is the resend's toast and the
    // refusal notice above the table, since a closed menu has no face to show it on.
    const revoking = ctx.busyInvite === row.invitation.id;
    const sending = ctx.resendingInvite === row.invitation.id;
    const who = row.invitation.email;
    return (
      <>
        <RowMenu
          label={`the invitation to ${who}`}
          className="sm:hidden"
          items={[
            {
              id: "resend",
              label: "Send again",
              disabled: sending || revoking,
              hint: sending ? "Sending…" : undefined,
              onSelect: () => ctx.onResend(row.invitation),
            },
            {
              id: "revoke",
              label: "Cancel invitation",
              tone: "danger",
              disabled: sending || revoking,
              hint: revoking ? "Cancelling…" : undefined,
              onSelect: () => ctx.onRevoke(row.invitation),
            },
          ]}
        />
        <InviteButtons row={row} ctx={ctx} revoking={revoking} sending={sending} who={who} />
      </>
    );
  }
  if (ctx.myId !== null && row.member.id === ctx.myId) return null;
  const busy = ctx.busyMember === row.member.id;
  return (
    <RowMenu
      label={row.member.name ?? "this member"}
      items={[
        {
          id: "remove",
          label: "Remove from account",
          tone: "danger",
          disabled: busy,
          onSelect: () => ctx.onRemove(row.member),
        },
      ]}
    />
  );
}

function InviteButtons({
  row,
  ctx,
  revoking,
  sending,
  who,
}: {
  row: Extract<TeamRow, { kind: "invite" }>;
  ctx: TeamTableContext;
  revoking: boolean;
  sending: boolean;
  who: string;
}) {
  return (
    <span className="hidden flex-wrap items-center justify-end gap-2 sm:flex">
      <ActionButton
        variant="secondary-sm"
        status={statusFor(ctx.resendStatus, row.invitation.id)}
        disabled={revoking}
        onClick={() => ctx.onResend(row.invitation)}
        aria-label={`Send the invitation to ${who} again`}
        successLabel="Sent"
        className="whitespace-nowrap"
      >
        Send again
      </ActionButton>
      <button
        type="button"
        disabled={sending || revoking}
        aria-busy={revoking || undefined}
        onClick={() => ctx.onRevoke(row.invitation)}
        aria-label={`Cancel the invitation to ${who}`}
        className={TEXT_ACTION_DANGER}
      >
        {revoking ? "Cancelling…" : statusFor(ctx.revokeStatus, row.invitation.id) === "error" ? "Try again" : "Cancel"}
      </button>
    </span>
  );
}

export function teamColumns(ctx: TeamTableContext): DataColumn<TeamRow>[] {
  return [
    { id: "name", header: "Name", cell: (row) => <NameCell row={row} ctx={ctx} /> },
    ...(ctx.showEmail
      ? [
          {
            id: "email",
            header: "Email",
            hideBelow: "md" as const,
            cell: (row: TeamRow) =>
              row.kind === "member" ? (
                <span className="text-ink-muted">{row.email ?? "—"}</span>
              ) : null,
          },
        ]
      : []),
    {
      id: "role",
      header: "Role",
      renderHeader: () => (
        <span className="inline-flex items-center gap-1">
          Role
          <InfoTip label="roles">
            <p>
              An account always keeps at least one owner: the last one cannot be removed or
              moved to staff. Nobody can change their own role. Ask another owner.
            </p>
          </InfoTip>
        </span>
      ),
      cell: (row) => <RoleCell row={row} ctx={ctx} />,
    },
    {
      id: "actions",
      header: "Actions",
      align: "right",
      cell: (row) => <ActionsCell row={row} ctx={ctx} />,
    },
  ];
}
