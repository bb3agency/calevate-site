"use client";

import { useState } from "react";
import { KeyRound, Mail, ShieldCheck, Trash2, UserMinus } from "lucide-react";

import {
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  SECONDARY_BUTTON_SM,
  formatIST,
} from "@/components/ui";
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
 * The three rows this screen is made of: the confirmation an invitation was sent, one
 * person on the account, and one unused invite link. One subject — a row about a human
 * being — kept out of the screen that decides what may be done to them.
 */

/**
 * Confirmation that the invitation was sent — NOT the link.
 *
 * This panel used to print the raw invite token and tell the owner to forward it, because
 * the client realm had no mailer. It has had one since D-170, and the printed token was
 * the last half of D-185's finding: a token anyone but the invitee can see is a token
 * that can be redeemed by anyone but the invitee, which let an owner squat a stranger's
 * address (D-190 removed the field from the response entirely, so there is nothing left
 * here to print).
 *
 * The copy says what actually happened — queued, not delivered. The outbox dispatches it
 * within seconds, but "we emailed them" would be a claim about a vendor's behaviour that
 * this screen has no way to observe, and the sentence a client needs when it does not
 * arrive is "check the spam folder, or revoke and re-invite", not a link to paste.
 */
export function IssuedInvite({ invitation }: { invitation: CreatedInvitation }) {
  return (
    <div className="mt-4">
      <NoticeBox tone="ok" title={`Invitation sent to ${invitation.email}`}>
        <p>
          We have emailed them a link. It works once, only from that address, and stops
          working {formatIST(invitation.expires_at)}.
        </p>
        <p className="mt-2 text-xs">
          If it does not arrive, ask them to check their spam folder. We cannot show or
          re-send the link — revoke the invite below and create a new one instead.
        </p>
      </NoticeBox>
    </div>
  );
}

export function MemberRow({
  member,
  isMe,
  canManage,
  restriction,
  busy,
  onRole,
  onRemove,
}: {
  member: Member;
  isMe: boolean;
  canManage: boolean;
  restriction: string | null;
  busy: boolean;
  onRole: (role: MemberRole) => void;
  onRemove: () => void;
}) {
  // `lookup()`, not `ROLE_COPY[...]`: `member.role` is a WIRE string, and indexing a
  // literal with one walks the prototype chain — a role of `constructor` resolves to
  // the `Object` function instead of missing. See src/lib/lookup.ts.
  const copy = lookup(ROLE_COPY, member.role);
  const who = member.name ?? "this member";
  /**
   * The role chosen in the dropdown but NOT yet saved, or null while it matches the
   * server's. No effect resets it: once the write lands, `member.role` becomes the staged
   * value and `pendingRole` below goes null on its own, so the button and its sentence
   * disappear because the change has happened rather than because a timer said so.
   */
  const [staged, setStaged] = useState<MemberRole | null>(null);
  const pendingRole = staged && staged !== member.role ? staged : null;
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
        aria-hidden
      >
        {member.role === "owner" ? (
          <ShieldCheck className="h-4 w-4" />
        ) : (
          <Mail className="h-4 w-4" />
        )}
      </span>
      {/* `name` is nullable and there is deliberately no email to fall back to — a
          fallback that leaks is not a fallback (see `MemberOut` on the API). */}
      <span className="text-ink">{member.name ?? "Unnamed member"}</span>
      {isMe && <span className="text-xs text-ink-faint">(you)</span>}
      <span className="text-xs text-ink-muted">{copy?.label ?? member.role}</span>

      <span className="ml-auto flex items-center gap-2">
        {isMe ? (
          /* The reason where the control would have been, rather than a disabled
             control with no explanation — the API refuses self-directed changes so
             that a mis-click cannot cost somebody their own access. */
          <span className="text-xs text-ink-faint">
            You cannot change your own access — ask another owner.
          </span>
        ) : canManage ? (
          <>
            <label className="sr-only" htmlFor={`role-${member.id}`}>
              Role for {who}
            </label>
            {/*
             * The select STAGES the choice; a second, named press commits it.
             *
             * It used to mutate straight out of `onChange`, so one stray scroll wheel over
             * a focused dropdown granted a colleague `billing:read` and `org:manage` —
             * including the power to remove the person who granted it — with no
             * are-you-sure moment anywhere in the interaction. This file's own comment
             * three lines up says the API refuses self-directed changes "so that a
             * mis-click cannot cost somebody their own access"; the rule was right and was
             * being applied to exactly one row.
             *
             * Staged rather than a modal, deliberately, and NOT because a modal was too
             * much work: the consequence here is a sentence about capabilities, and
             * GOV.UK's check-answers pattern is about seeing what you are about to commit
             * rather than being interrupted. The sentence renders beside the control, in
             * the row it concerns, and the button says which change it makes — so the
             * confirmation carries target as well as intent. Removal, which destroys
             * access rather than changing it, gets the dialog.
             */}
            <select
              id={`role-${member.id}`}
              value={staged ?? member.role}
              disabled={busy}
              onChange={(e) => setStaged(e.target.value as MemberRole)}
              className={`${FIELD} py-1 text-xs`}
            >
              {ROLES.map((value) => (
                <option key={value} value={value}>
                  {ROLE_COPY[value].label}
                </option>
              ))}
            </select>
            {pendingRole && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onRole(pendingRole)}
                aria-label={`Save ${who} as ${ROLE_COPY[pendingRole].label}`}
                className={PRIMARY_BUTTON_SM}
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                {busy ? "Saving…" : "Save role"}
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={onRemove}
              // Named for the row: a list of identical "Remove" buttons is a list of
              // identical announcements to a screen reader.
              aria-label={`Remove ${who} from this account`}
              className={SECONDARY_BUTTON_SM}
            >
              <UserMinus className="h-3.5 w-3.5" />
              {busy ? "Working…" : "Remove"}
            </button>
            {/* What the staged change actually does, said BEFORE it is made rather than
                discovered afterwards. `basis-full` so it takes its own line under the
                controls instead of squeezing them. */}
            {pendingRole && (
              <span className="basis-full text-xs text-ink-muted">
                {pendingRole === "owner"
                  ? `${who} will be able to see your invoice, invite and remove people — including you.`
                  : `${who} will lose access to billing and will no longer be able to change who is on this team.`}
              </span>
            )}
          </>
        ) : (
          <span className="text-xs text-ink-faint">
            {restriction ?? "Only an account owner can change this."}
          </span>
        )}
      </span>
    </li>
  );
}

export function InvitationRow({
  invitation,
  canManage,
  busy,
  onRevoke,
}: {
  invitation: PendingInvitation;
  canManage: boolean;
  busy: boolean;
  onRevoke: () => void;
}) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-black/5 text-ink-muted dark:bg-white/10"
        aria-hidden
      >
        <KeyRound className="h-4 w-4" />
      </span>
      {/* The whole address (D-436): an owner has to be able to see that the address
          they typed is the one they meant, and to tell two invites at one domain apart. */}
      <span className="font-mono text-ink">{invitation.email}</span>
      <span className="text-xs text-ink-muted">
        {lookup(ROLE_COPY, invitation.role)?.label ?? invitation.role}
      </span>
      <span className="ml-auto whitespace-nowrap text-xs text-ink-faint">
        expires {formatIST(invitation.expires_at)}
      </span>
      {canManage && (
        <button
          type="button"
          disabled={busy}
          onClick={onRevoke}
          aria-label={`Revoke the invitation for ${invitation.email}`}
          className={SECONDARY_BUTTON_SM}
        >
          <Trash2 className="h-3.5 w-3.5" />
          {busy ? "Revoking…" : "Revoke"}
        </button>
      )}
    </li>
  );
}
