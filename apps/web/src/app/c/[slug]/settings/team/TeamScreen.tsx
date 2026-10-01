"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";

import { DataTable } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import {
  NoticeBox,
  PRIMARY_BUTTON,
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
  useTeamMembers,
  type Member,
  type MemberRole,
} from "@/lib/api/members";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { ROLES } from "./roles";
import { InviteDrawer } from "./InviteForm";
import { teamColumns, type TeamRow } from "./teamRows";

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
  const [inviting, setInviting] = useState(false);

  /* Colleagues' email addresses are owner-only (`org:manage`), so the roster is not even
     requested for a session that may not read it, or while `/v1/me` has not said. The
     column appears only when the roster arrived; a failed read says so under the table
     rather than passing for a team with no addresses. */
  const mayReadRoster =
    me.data !== undefined && me.data.permissions.includes("org:manage");
  const roster = useTeamMembers(session, { enabled: mayReadRoster });
  const emailById = new Map<string, string>();
  if (roster.data) for (const person of roster.data) emailById.set(person.id, person.email);

  /* `.data`, never `.data ?? []` — the difference between "the server said none" and
     "the server did not answer" is this screen's whole honesty (§52). */
  const people = members.data;
  // `Array.isArray`, not a cast: a list endpoint answering with anything else is no list.
  const pending = Array.isArray(invitations.data) ? invitations.data : undefined;
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

  const rows: TeamRow[] = [
    ...(people ?? []).map((member) => ({
      kind: "member" as const,
      id: `member-${member.id}`,
      member,
      email: emailById.get(member.id) ?? null,
    })),
    ...(pending ?? []).map((invitation) => ({
      kind: "invite" as const,
      id: `invite-${invitation.id}`,
      invitation,
    })),
  ];
  const columns = teamColumns({
    myId,
    canManage: write.allowed,
    restriction: write.reason,
    showEmail: roster.data !== undefined,
    busyMember:
      changeRole.isPending
        ? (changeRole.variables?.userId ?? null)
        : remove.isPending
          ? (remove.variables ?? null)
          : null,
    busyInvite: revoke.isPending ? (revoke.variables ?? null) : null,
    onRole: (member, next) =>
      changeRole.mutate({
        userId: member.id,
        role: next,
        // The CAS guard: the role this row was RENDERING, so a change made by another
        // owner in the meantime is reported, not overwritten.
        expectedRole: member.role as MemberRole,
      }),
    onRemove: (member) => setRemoving(member),
    onRevoke: (invitation) => revoke.mutate(invitation.id),
  });

  return (
    <div className="space-y-5 pb-12">
      <PageHeader
        description="Everyone who can sign in to this account."
        actions={
          write.allowed ? (
            <button
              type="button"
              onClick={() => setInviting(true)}
              className={PRIMARY_BUTTON}
            >
              <UserPlus aria-hidden className="h-4 w-4" />
              Invite
            </button>
          ) : undefined
        }
      />

      <RestrictionNote reason={write.reason} />

      {/* A removal refusal belongs inside the dialog while it is open — see below. */}
      {(changeRole.error != null || (remove.error != null && removing == null)) && (
        <ProblemNotice error={changeRole.error ?? remove.error} />
      )}
      {revoke.error != null && <ProblemNotice error={revoke.error} />}
      {members.error != null && (
        <ProblemNotice error={members.error} onRetry={() => members.refetch()} />
      )}
      {invitations.error != null && (
        <ProblemNotice error={invitations.error} onRetry={() => invitations.refetch()} />
      )}

      {remove.data && (
        <NoticeBox tone="warn" title="Access removed">
          {remove.data.leads_still_assigned > 0
            ? `${formatCount(remove.data.leads_still_assigned)} ${
                remove.data.leads_still_assigned === 1 ? "lead is" : "leads are"
              } still assigned to them. Those leads were not touched — reassign them from the Leads screen so somebody picks them up.`
            : "They had no leads assigned, so nothing needs reassigning."}
        </NoticeBox>
      )}

      {/* Loading is a skeleton; a failure is the notice above and NOTHING else. There is
          deliberately no "you are the only member" fallback: wrong, it sends an owner off to
          re-invite people who already have access. */}
      {members.isLoading ? (
        <Skeleton rows={4} label="Loading your team" />
      ) : !people ? null : people.length === 0 ? (
        <EmptyState
          className="rounded-card border border-line bg-surface"
          message={
            <>
              <span className="block font-medium text-ink">Nobody is on this account yet</span>
              <span className="mt-1 block">
                That is unusual — an account always has at least one owner. Reload the page,
                and tell us if it stays empty.
              </span>
            </>
          }
        />
      ) : (
        <section className="space-y-2">
          {/* Counts only from lists the server actually sent: "1 person" while a request is
              in flight, or "0 unused links" over a failed one, is a claim about who has
              access to this business made on no evidence. */}
          <p className="text-[13px] text-ink-muted">
            {formatCount(people.length)} {people.length === 1 ? "person" : "people"}
            {pending && pending.length > 0
              ? ` · ${formatCount(pending.length)} unused ${pending.length === 1 ? "link" : "links"}`
              : ""}
          </p>
          <DataTable
            label="People who can sign in, and unused invitations"
            columns={columns}
            rows={rows}
            getRowId={(row) => row.id}
            className="rounded-card border border-line bg-surface"
          />
        </section>
      )}

      {roster.isError && (
        <p className="text-[13px] text-ink-muted">
          We could not load your colleagues&apos; email addresses, so they are not shown.{" "}
          <button
            type="button"
            onClick={() => void roster.refetch()}
            className="font-medium text-ink underline underline-offset-2 touch:min-h-11"
          >
            Try again
          </button>
        </p>
      )}

      {/* Only from a list the server actually sent empty: over a failed read this sentence
          would tell an owner no unused key to their account exists. */}
      {pending && pending.length === 0 && (
        <p className="text-[13px] text-ink-muted">
          <span className="font-medium text-ink">No unused invites.</span> Invite links expire
          after 72 hours and can only be used once, by the person they were sent to.
        </p>
      )}

      <InviteDrawer
        open={inviting}
        onClose={() => setInviting(false)}
        email={email}
        setEmail={setEmail}
        role={role}
        setRole={setRole}
      />

      {/* Closes only on success. A refused removal (the last owner, a stale row) leaves the
          person on the account, and closing the dialog would say otherwise. */}
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
          onConfirm={() => remove.mutate(removing.id, { onSuccess: () => setRemoving(null) })}
        >
          <p>
            They will be signed out and will not be able to sign in to this account again
            unless you invite them back.
          </p>
          {/* Said BEFORE the click; the "Access removed" notice reports it afterwards,
              which is the wrong moment to learn it. */}
          <p>
            Any leads assigned to them stay assigned to them and are not reassigned — you
            would pick those up from the Leads screen.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
