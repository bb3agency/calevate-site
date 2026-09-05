"use client";

import { useState } from "react";
import { KeyRound, Mail, ShieldCheck, Trash2, UserMinus, UserPlus } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  PRIMARY_BUTTON_SM,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import { useFormValidation } from "@/components/formValidation";
import { useMe, useWriteAccess } from "@/lib/api/hooks";
import { lookup } from "@/lib/lookup";
import {
  ROLE_COPY,
  useInviteMember,
  useMembers,
  usePendingInvitations,
  useRemoveMember,
  useRevokeInvitation,
  useSetMemberRole,
  type CreatedInvitation,
  type Member,
  type MemberRole,
  type PendingInvitation,
} from "@/lib/api/members";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

/**
 * Team — who has access to this account, and who may change that (ROADMAP M3).
 *
 * Until this screen existed, adding a colleague or taking someone's access away was a
 * support ticket that ended with a Calevate operator running SQL. Three things about it
 * are decisions rather than layout:
 *
 * 1. **Every refusal is explained WHERE the control is.** A `staff` member sees the
 *    people list with no buttons and one sentence saying why; an impersonating operator
 *    (D-22) sees the same list and a different sentence. `useWriteAccess` is the one
 *    place in this app that answers "may this session write", and it distinguishes
 *    "you may not" from "we could not find out" — which matters here more than anywhere,
 *    because a dead Remove button on a permissions screen reads as a broken product and
 *    gets filed as one.
 * 2. **§52's rule, on a screen where the empty state is a security claim.** "You are the
 *    only person on this account" printed over a FAILED request is an invitation to
 *    re-invite people who already have access — and, worse, a quiet answer of "nobody
 *    else has access" to somebody who came here to check exactly that. Loading is a
 *    skeleton, failure is the refusal notice and nothing else, and the empty state is
 *    reachable only through a list the server actually sent.
 * 3. **The invite link is shown once and is never cached.** The API returns the raw
 *    token in the create response and cannot produce it again (only its SHA-256 is
 *    stored). It lives in component state until the page is left.
 *
 * Two API rules the screen renders rather than re-derives: you cannot change your own
 * role or remove yourself (the row says so instead of offering a control the server
 * refuses), and the last owner cannot be demoted or removed (the API is the authority;
 * the note under the list says the rule out loud so it is not discovered as an error).
 */

const ROLES: MemberRole[] = ["owner", "staff"];

export default function TeamPage() {
  const session = useClientSession();
  const me = useMe(session);
  const members = useMembers(session);
  const invitations = usePendingInvitations(session);

  /**
   * `org:manage` — the permission the API requires for every write on this surface, and
   * the one D-22 refuses to an impersonating operator. Reading the team is `org:read`,
   * so a support session keeps the list and loses the buttons, which is exactly the
   * split the endpoints implement.
   */
  const write = useWriteAccess(session, "org:manage", "change who is on this team");

  const invite = useInviteMember(session);
  const changeRole = useSetMemberRole(session);
  const remove = useRemoveMember(session);
  const revoke = useRevokeInvitation(session);

  const [email, setEmail] = useState("");
  const valid = useFormValidation();
  const [role, setRole] = useState<MemberRole>("staff");
  /* Held here, never in the query cache: this is a credential, and the API cannot
     reissue it. Cleared when another invitation is created. */
  const [issued, setIssued] = useState<CreatedInvitation | null>(null);

  /**
   * The colleague an owner has asked to remove, held until they confirm it.
   *
   * "Remove" used to revoke a person's access to the whole account on one click, from a
   * button styled `SECONDARY_BUTTON_SM` — the same visual class as a benign action, which
   * is the pairing NN/g names as dangerous UX. The page then reported how many leads were
   * left stranded, which is a consequence disclosed AFTER the fact; the dialog says it
   * before.
   *
   * The whole member, so the dialog can name the person. "Remove this member?" confirms
   * that a removal was intended and says nothing about whose.
   */
  const [removing, setRemoving] = useState<Member | null>(null);

  /* `.data`, never `.data ?? []` — the difference between "the server said none" and
     "the server did not answer" is this screen's whole honesty (§52). */
  const people = members.data;
  const pending = invitations.data;
  const myId = me.data?.user_id ?? null;

  /*
   * THE TEAM, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * ## Not one colleague's name or address
   *
   * Every row on this screen is a real person and their email. The counts and the ROLE
   * SPLIT are what answer the questions this screen is opened with — "who can change
   * billing", "why can my receptionist not export leads" — and they name nobody.
   *
   * ## The invite address is declared, and is neither writable nor sent
   *
   * It is `personal: "email"`, so it leaves as `«EMAIL_1»` (D-127 G-2), and it is
   * `writable: false` because inviting somebody into a business's account is a decision
   * about a specific human being; an assistant that invented an address would be handing
   * a stranger the client's CRM. The ROLE beside it IS writable: it is a two-value enum,
   * it is the half people actually get wrong, and it grants nothing on its own — nobody
   * is invited until the owner presses the button.
   */
  useCopilotSurface({
    route: "/c/{slug}/settings/team",
    title: "Who is on this team",
    realm: "client",
    fields: [
      {
        id: "team-invite-email",
        label: "Email address to invite",
        type: "text",
        value: email,
        writable: false,
        personal: "email",
        help: "Typed by the owner. The assistant is told whether it is filled in, never what it says.",
      },
      {
        id: "team-invite-role",
        label: "What the invited person may do",
        type: "select",
        value: role,
        options: ROLES.map((value) => ({ value, label: ROLE_COPY[value].label })),
        help: "Owner can change billing and settings; staff works the leads.",
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: people
          ? "the team below has loaded"
          : members.error
            ? "the team failed to load, so nobody is listed"
            : "still loading",
      },
      { key: "members", label: "People on the account", value: people ? String(people.length) : "not known" },
      {
        key: "role_split",
        label: "How many hold each role",
        value: people
          ? ROLES.map((value) => `${value}: ${people.filter((member) => member.role === value).length}`).join(", ")
          : "not known",
      },
      {
        key: "pending_invitations",
        label: "Invitations sent and not yet accepted",
        value: pending ? String(pending.length) : "not known",
      },
      {
        key: "may_change",
        label: "May this session invite, re-role or remove anyone?",
        value: write.allowed ? "yes" : `no — ${write.reason ?? "no reason given"}`,
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id !== "team-invite-role") continue;
        const next = ROLES.find((value) => value === asText(item.value));
        if (next !== undefined) setRole(next);
      }
    },
  });

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Everyone who can sign in to this account. Owners can invite people, change roles
        and remove access; staff can work leads, calls and agents but cannot see billing
        or change this list.
      </p>

      <RestrictionNote reason={write.reason} />

      {write.allowed && (
        <Card title="Invite a colleague">
          <form
            className="mt-1 flex flex-wrap items-end gap-3"
            noValidate
            onSubmit={valid.onSubmit(() => {
              invite.mutate(
                { email: email.trim(), role },
                {
                  onSuccess: (created) => {
                    setIssued(created);
                    setEmail("");
                  },
                },
              );
            })}
          >
            {/* The message sits OUTSIDE the wrapping label on purpose: a `<label>` that
                encloses it would fold the refusal into the field's accessible NAME, so a
                screen reader would read it back on every subsequent visit to the field.
                `aria-describedby` is the association that belongs to a message. */}
            <div>
              <label className="block">
                <span className={FIELD_LABEL}>Their email address</span>
                <input
                  {...valid.field("email", "Enter their email address.")}
                  required
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="off"
                  placeholder="priya@yourbusiness.in"
                  aria-label="Email address to invite"
                  className={`${FIELD} mt-1 w-72`}
                />
              </label>
              {valid.error("email")}
            </div>
            <label className="block">
              <span className={FIELD_LABEL}>Role</span>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as MemberRole)}
                aria-label="Role for the invitation"
                className={`${FIELD} mt-1`}
              >
                {ROLES.map((value) => (
                  <option key={value} value={value}>
                    {ROLE_COPY[value].label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              disabled={invite.isPending || email.trim().length < 3}
              className={PRIMARY_BUTTON_SM}
            >
              <UserPlus className="h-4 w-4" />
              {invite.isPending ? "Creating…" : "Create invite link"}
            </button>
          </form>

          <p className="mt-2 text-xs text-ink-faint">{ROLE_COPY[role].can}</p>

          {invite.error != null && (
            <div className="mt-3">
              <ProblemNotice error={invite.error} />
            </div>
          )}

          {issued && <IssuedInvite invitation={issued} />}
        </Card>
      )}

      <Card
        title="People"
        action={
          /* No count until the server has sent a list. "1 person" while the request is
             in flight is a statement about who has access to this business, made on no
             evidence. */
          people ? (
            <span className="text-xs text-ink-faint">
              {formatCount(people.length)} {people.length === 1 ? "person" : "people"}
            </span>
          ) : undefined
        }
        bodyClassName="p-2"
      >
        {/* A removal refusal belongs inside the dialog while it is open — see below. */}
        {(changeRole.error != null || (remove.error != null && removing == null)) && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={changeRole.error ?? remove.error} />
          </div>
        )}
        {members.error != null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={members.error} onRetry={() => members.refetch()} />
          </div>
        )}

        {/* Loading is a skeleton; a failure is the notice above and NOTHING else. There
            is deliberately no "you are the only member" fallback: that sentence, wrong,
            sends an owner off to re-invite people who already have access — and reads as
            an assurance that nobody else can see this account. */}
        {members.isLoading ? (
          <div className="p-4">
            <Skeleton rows={4} />
          </div>
        ) : !people ? null : people.length ? (
          <ul className="divide-y divide-line">
            {people.map((member) => (
              <MemberRow
                key={member.id}
                member={member}
                isMe={member.id === myId}
                canManage={write.allowed}
                restriction={write.reason}
                busy={
                  (changeRole.isPending && changeRole.variables?.userId === member.id) ||
                  (remove.isPending && remove.variables === member.id)
                }
                onRole={(next) =>
                  changeRole.mutate({
                    userId: member.id,
                    role: next,
                    // The CAS guard: the role this row was RENDERING, so a change made
                    // by another owner in the meantime is reported, not overwritten.
                    expectedRole: member.role as MemberRole,
                  })
                }
                onRemove={() => setRemoving(member)}
              />
            ))}
          </ul>
        ) : (
          <EmptyState
            title="Nobody is on this account yet"
            hint="That is unusual — an account always has at least one owner. Reload the page, and tell us if it stays empty."
          />
        )}

        {remove.data && (
          <div className="px-4 pb-3 pt-1">
            <NoticeBox tone="warn" title="Access removed">
              {remove.data.leads_still_assigned > 0
                ? `${formatCount(remove.data.leads_still_assigned)} ${
                    remove.data.leads_still_assigned === 1 ? "lead is" : "leads are"
                  } still assigned to them. Those leads were not touched — reassign them from the Leads screen so somebody picks them up.`
                : "They had no leads assigned, so nothing needs reassigning."}
            </NoticeBox>
          </div>
        )}

        <p className="px-4 pb-3 pt-1 text-xs text-ink-faint">
          An account always keeps at least one owner: the last one cannot be removed or
          moved to staff. Nobody can change their own role — ask another owner.
        </p>
      </Card>

      <Card
        title="Pending invites"
        action={
          pending ? (
            <span className="text-xs text-ink-faint">
              {formatCount(pending.length)} unused {pending.length === 1 ? "link" : "links"}
            </span>
          ) : undefined
        }
        bodyClassName="p-2"
      >
        {revoke.error != null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={revoke.error} />
          </div>
        )}
        {invitations.error != null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={invitations.error} onRetry={() => invitations.refetch()} />
          </div>
        )}

        {/* Same rule, and the same reason it matters twice: "no pending invites" over a
            failed request tells an owner that no unused key to their account exists. */}
        {invitations.isLoading ? (
          <div className="p-4">
            <Skeleton rows={2} />
          </div>
        ) : !pending ? null : pending.length ? (
          <ul className="divide-y divide-line">
            {pending.map((invitation) => (
              <InvitationRow
                key={invitation.id}
                invitation={invitation}
                canManage={write.allowed}
                busy={revoke.isPending && revoke.variables === invitation.id}
                onRevoke={() => revoke.mutate(invitation.id)}
              />
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No unused invites"
            hint="Invite links expire after 72 hours and can only be used once, by the person they were sent to."
          />
        )}
      </Card>

      {/* Closes only on success. A refused removal (the last owner, a stale row) leaves
          the person on the account, and closing the dialog would say otherwise. */}
      {removing && (
        <ConfirmDialog
          title={`Remove ${removing.name ?? "this member"} from this account?`}
          confirmLabel="Remove their access"
          pendingLabel="Removing…"
          cancelLabel="Keep their access"
          pending={remove.isPending}
          error={remove.error}
          onCancel={() => {
            remove.reset();
            setRemoving(null);
          }}
          onConfirm={() =>
            remove.mutate(removing.id, { onSuccess: () => setRemoving(null) })
          }
        >
          <p>
            They will be signed out and will not be able to sign in to this account again
            unless you invite them back.
          </p>
          {/* Said BEFORE the click. The `Access removed` notice on the list already
              reports this afterwards, which is the wrong moment to learn it. */}
          <p>
            Any leads assigned to them stay assigned to them and are not reassigned —
            you would pick those up from the Leads screen.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

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
function IssuedInvite({ invitation }: { invitation: CreatedInvitation }) {
  return (
    <div className="mt-4">
      <NoticeBox tone="ok" title={`Invitation sent to ${invitation.email}`}>
        <p>
          We have emailed them a link. It works once, only from that address, and stops
          working {formatIST(invitation.expires_at)}.
        </p>
        <p className="mt-2 text-xs">
          If it does not arrive, ask them to check their spam folder. We cannot show or
          re-send the link — it is stored only as a fingerprint, so revoke the invite below
          and create a new one instead.
        </p>
      </NoticeBox>
    </div>
  );
}

function MemberRow({
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

function InvitationRow({
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
