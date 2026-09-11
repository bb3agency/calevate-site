"use client";

import { useState } from "react";

import {
  Card,
  EmptyState,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import { useActAccess, useMe } from "@/lib/api/hooks";
import {
  ROLE_COPY,
  useMembers,
  usePendingInvitations,
  useRemoveMember,
  useRevokeInvitation,
  useSetMemberRole,
  type Member,
  type MemberRole,
} from "@/lib/api/members";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { ROLES } from "./roles";
import { InviteForm } from "./InviteForm";
import { InvitationRow, MemberRow } from "./teamRows";

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

export function TeamScreen() {
  const session = useClientSession();
  const me = useMe(session);
  const members = useMembers(session);
  const invitations = usePendingInvitations(session);

  /**
   * `org:manage` — the permission the API requires for every write on this surface.
   * Reading the team is `org:read`, so a support session keeps the list and loses the
   * buttons, which is exactly the split the endpoints implement. ⚠ THE REASON FOR THAT
   * SPLIT CHANGED: it used to be D-22 refusing `org:manage` to an impersonating operator;
   * it is now the named act below, because the permission itself came back.
   */
  // `useActAccess`, NOT `useWriteAccess`: a view-as operator KEEPS `org:manage`
  // (D-587 made it writable), and the server then refuses `org.membership` inside it —
  // an invitation is an access grant that outlives the session. Asking only the
  // permission rendered working Invite and Remove buttons that the API refused.
  const write = useActAccess(
    session,
    "org:manage",
    "org.membership",
    "change who is on this team",
  );

  const changeRole = useSetMemberRole(session);
  const remove = useRemoveMember(session);
  const revoke = useRevokeInvitation(session);

  /*
   * THE ADDRESS AND THE ROLE ARE HELD HERE, not in `InviteForm`, because the copilot
   * declaration below reads both — an assistant told "the invite box is empty" while it
   * is filled in has been handed a fact about the screen that is not true of the screen.
   */
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<MemberRole>("staff");

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
        options: ROLES.map((value) => ({
          value,
          label: ROLE_COPY[value].label,
        })),
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
      {
        key: "members",
        label: "People on the account",
        value: people ? String(people.length) : "not known",
      },
      {
        key: "role_split",
        label: "How many hold each role",
        value: people
          ? ROLES.map(
              (value) =>
                `${value}: ${people.filter((member) => member.role === value).length}`,
            ).join(", ")
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
        value: write.allowed
          ? "yes"
          : `no — ${write.reason ?? "no reason given"}`,
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
        Everyone who can sign in to this account.
      </p>

      <RestrictionNote reason={write.reason} />

      {write.allowed && (
        <InviteForm
          email={email}
          setEmail={setEmail}
          role={role}
          setRole={setRole}
        />
      )}

      <Card
        title="People"
        action={
          /* No count until the server has sent a list. "1 person" while the request is
             in flight is a statement about who has access to this business, made on no
             evidence. */
          people ? (
            <span className="text-xs text-ink-faint">
              {formatCount(people.length)}{" "}
              {people.length === 1 ? "person" : "people"}
            </span>
          ) : undefined
        }
        bodyClassName="p-2"
      >
        {/* A removal refusal belongs inside the dialog while it is open — see below. */}
        {(changeRole.error != null ||
          (remove.error != null && removing == null)) && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice error={changeRole.error ?? remove.error} />
          </div>
        )}
        {members.error != null && (
          <div className="mb-3 px-4 pt-2">
            <ProblemNotice
              error={members.error}
              onRetry={() => members.refetch()}
            />
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
                  (changeRole.isPending &&
                    changeRole.variables?.userId === member.id) ||
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
                    remove.data.leads_still_assigned === 1
                      ? "lead is"
                      : "leads are"
                  } still assigned to them. Those leads were not touched — reassign them from the Leads screen so somebody picks them up.`
                : "They had no leads assigned, so nothing needs reassigning."}
            </NoticeBox>
          </div>
        )}

        <p className="px-4 pb-3 pt-1 text-xs text-ink-faint">
          An account always keeps at least one owner: the last one cannot be
          removed or moved to staff. Nobody can change their own role — ask
          another owner.
        </p>
      </Card>

      <Card
        title="Pending invites"
        action={
          pending ? (
            <span className="text-xs text-ink-faint">
              {formatCount(pending.length)} unused{" "}
              {pending.length === 1 ? "link" : "links"}
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
            <ProblemNotice
              error={invitations.error}
              onRetry={() => invitations.refetch()}
            />
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
            They will be signed out and will not be able to sign in to this
            account again unless you invite them back.
          </p>
          {/* Said BEFORE the click. The `Access removed` notice on the list already
              reports this afterwards, which is the wrong moment to learn it. */}
          <p>
            Any leads assigned to them stay assigned to them and are not
            reassigned — you would pick those up from the Leads screen.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
