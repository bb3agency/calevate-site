"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, KeyRound, UserMinus, Users } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  TypedConfirmation,
  confirmationMatches,
  formatIST,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useAdminAccess } from "@/app/admin/access";
import { useTenant } from "@/lib/api/admin";
import { ROLE_COPY } from "@/lib/api/members";
import {
  useRemoveTenantMember,
  useSetTenantMemberRole,
  useTenantMembers,
  type TenantMember,
  type TenantMemberRole,
} from "@/lib/api/tenantMembers";
import { lookup } from "@/lib/lookup";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

/**
 * Who can sign in to one client's account, and taking that away (D-602).
 *
 * The screen the Invitations page stops at. An invitation is a key in somebody's inbox;
 * this is a key that has been USED, and until now the console lost sight of a person the
 * moment they redeemed one. The support case it exists for is the one this business meets
 * first: the client's only owner has left the company, nobody there can sign in as an
 * owner, and every client-realm control needs a live owner — so the client cannot fix it
 * and, until this screen, neither could we. Inviting a replacement was already possible;
 * taking the departed person's access away was not.
 *
 * ## WHY REMOVAL AND ROLE CHANGE LOOK SO DIFFERENT HERE
 *
 * The role control is a select and a button. The removal is behind a disclosure, wants a
 * typed word, and says out loud how much work the person is carrying. That asymmetry is
 * the API's — see `admin/members_routes.py` — and the line is NOT "destructive", it is
 * whether the operator who was wrong can put it back. A role change is one click back on
 * this same screen. A removal is not undoable by us at all: the way back is a fresh
 * invitation the person themselves has to receive and redeem, and an operator who removes
 * the wrong owner has handed the repair to somebody who can no longer sign in.
 *
 * THE TYPED WORD IS NOT THE GUARD, and the difference matters (the closure screen makes
 * the same note). The guard is the `X-Confirm-Action` header the API demands and the
 * `admin:tenants` permission it checks first; a dialog that exists only in this component
 * is absent from curl. What the typing buys is that the request cannot be sent by a
 * mis-click, and that the operator has read the sentence describing what it costs.
 *
 * ## THE LEAD COUNT IS ON THE ROW, NOT ONLY IN THE ANSWER
 *
 * Removing somebody does NOT unassign their work — `tenancy/members.remove_member` argues
 * why at length, and the short version is that clearing it would erase the answer to "who
 * was working this?" from every lead at once. So the number that decides the act is beside
 * the person before the decision, and restated afterwards from inside the removing
 * transaction.
 *
 * ## WHAT THIS SCREEN DELIBERATELY DOES NOT OFFER
 *
 * Adding somebody — that is an invitation, one screen away, and a membership with no
 * redeemed token behind it would be an access grant nobody can account for. And
 * deactivating the PERSON: `users` is global and crosses tenants, so a switch for it under
 * one client's heading would be the wrong scope printed over the right button.
 */
export default function TenantMembersPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const members = useTenantMembers(tenantId);
  const write = useAdminAccess("admin:tenants", "change or remove somebody's access");

  /*
   * THIS CLIENT'S TEAM, DECLARED TO THE SCREEN ASSISTANT.
   *
   * COUNTS AND ROLES, NEVER ADDRESSES OR NAMES. Every address on this screen belongs to a
   * person, and volunteering one to a model is a disclosure nobody asked for — the
   * operator is looking straight at the list, so nothing is lost by withholding it. NO
   * FIELDS: the only inputs here are a role select that changes who can do what, and a
   * confirmation box whose whole purpose is that a human typed it.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/members",
    title: "Who holds this account",
    realm: "admin",
    fields: [],
    facts: [
      { key: "tenant_id", label: "Tenant id", value: tenantId },
      {
        key: "client",
        label: "Client",
        value: tenantQuery.data?.name ?? "could not be read",
      },
      {
        key: "members",
        label: "People who can sign in (names and addresses are not sent)",
        value: members.data
          ? String(members.data.length)
          : members.error
            ? "could not be read"
            : "still loading",
      },
      {
        key: "owners",
        label: "How many of them are owners",
        value: members.data
          ? String(members.data.filter((row) => row.role === "owner").length)
          : "not known",
      },
      {
        key: "deactivated",
        label: "How many hold a membership but are deactivated platform-wide",
        value: members.data
          ? String(members.data.filter((row) => row.deactivated).length)
          : "not known",
      },
      {
        key: "may_write",
        label: "May this operator change or remove somebody's access",
        value: write.allowed ? "yes" : "no",
      },
    ],
    apply: noFill,
  });

  const name = tenantQuery.data?.name ?? "this client";

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {name}
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">Who holds this account</h1>
        <p className="text-sm text-ink-muted">
          Everyone who can sign in to this client&apos;s account right now. Removing somebody
          takes effect on their very next request and cannot be undone from here — the way
          back is a fresh invitation they have to redeem themselves. Their leads stay
          assigned to them either way.
        </p>
      </div>

      <Card title="Members">
        {members.isLoading ? (
          <Skeleton rows={3} />
        ) : members.error ? (
          /* A read that FAILED must never render as "nobody has access" — an operator who
             believed that would hand out a new owner invitation to an account that already
             has one, or conclude the client is locked out when they are not. */
          <ProblemNotice error={members.error} onRetry={() => members.refetch()} />
        ) : (members.data?.length ?? 0) === 0 ? (
          <EmptyState
            title="Nobody has signed in to this account yet"
            hint="Every invitation to this client is either outstanding, cancelled or expired. The Invitations screen is where a key is cut."
          />
        ) : (
          <ul className="divide-y divide-line">
            {members.data!.map((member) => (
              <MemberRow
                key={member.user_id}
                tenantId={tenantId}
                member={member}
                owners={members.data!.filter((row) => row.role === "owner").length}
                write={write}
              />
            ))}
          </ul>
        )}
      </Card>

      <p className="text-xs text-ink-faint">
        Nobody is added here.{" "}
        <Link
          href={`/admin/tenants/${tenantId}/invitations`}
          className="font-medium text-brand-strong hover:underline"
        >
          <KeyRound className="mr-1 inline h-3 w-3" aria-hidden />
          Invitations
        </Link>{" "}
        is where a key to this account is cut, re-sent or cancelled — somebody becomes a
        member by redeeming one.
      </p>
    </div>
  );
}

/** One person: who they are, what they hold, and the two things an operator may do. */
function MemberRow({
  tenantId,
  member,
  owners,
  write,
}: {
  tenantId: string;
  member: TenantMember;
  /**
   * How many owners this account has. Used ONLY to explain the server's refusal before it
   * happens — the rule itself is enforced in one place, under a row lock, because a count
   * read in a browser is exactly the read-then-write the API's `lock_owner_ids` exists to
   * refuse.
   */
  owners: number;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const setRole = useSetTenantMemberRole(tenantId);
  const remove = useRemoveTenantMember(tenantId);
  const [removing, setRemoving] = useState(false);
  const [typed, setTyped] = useState("");

  const busy = setRole.isPending || remove.isPending;
  const lastOwner = member.role === "owner" && owners === 1;
  const wordMissing = !confirmationMatches(typed, "REMOVE");

  return (
    <li className="space-y-3 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-medium text-ink">
            <Users className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden />
            {/* NOT falling back to the address when the name is null: a fallback that
                leaks is not a fallback, and the address is printed beneath anyway. */}
            {member.name ?? "Unnamed member"}
          </p>
          <p className="mt-0.5 truncate text-xs text-ink-muted" title={member.email}>
            {member.email}
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">
            {lookup(ROLE_COPY, member.role)?.label ?? member.role} · joined{" "}
            {formatIST(member.joined_at)} ·{" "}
            {member.leads_assigned === 0
              ? "no leads assigned"
              : `${member.leads_assigned} lead${member.leads_assigned === 1 ? "" : "s"} assigned`}
          </p>
          {!member.email_verified && (
            <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">
              This address has never been verified by them — our notices may not be reaching
              it.
            </p>
          )}
          {member.deactivated && (
            <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">
              This person is deactivated platform-wide, so they are refused at sign-in. They
              still hold a membership here, and it still counts as an owner.
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor={`role-${member.user_id}`}>
            Role for {member.name ?? member.email}
          </label>
          <select
            id={`role-${member.user_id}`}
            // The value the ROW is showing, which is also what is sent as `expected_role`
            // — so the compare-and-swap guards the picture the operator actually read,
            // not one re-derived at submit time.
            value={member.role}
            disabled={busy || !write.allowed}
            className={FIELD}
            onChange={(event) => {
              setRole.reset();
              setRole.mutate({
                userId: member.user_id,
                role: event.target.value as TenantMemberRole,
                expectedRole: member.role as TenantMemberRole,
              });
            }}
          >
            {Object.entries(ROLE_COPY).map(([value, copy]) => (
              <option key={value} value={value}>
                {copy.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={busy || !write.allowed}
            onClick={() => {
              setRemoving((open) => !open);
              setTyped("");
              remove.reset();
            }}
            aria-expanded={removing}
          >
            <UserMinus className="mr-1.5 h-4 w-4" aria-hidden />
            Remove access
          </button>
        </div>
      </div>

      <RestrictionNote reason={write.reason} />
      <p className="text-xs text-ink-faint">{lookup(ROLE_COPY, member.role)?.can}</p>

      {setRole.error != null && <ProblemNotice error={setRole.error} />}

      {removing && (
        <div className="space-y-3 rounded-md border border-line bg-surface-muted p-3">
          {lastOwner ? (
            <NoticeBox tone="stop" icon={<AlertTriangle className="h-5 w-5" />}>
              <p className="text-xs">
                This is the only owner on the account, so their access cannot be removed —
                an account with no owner can never invite anybody, change a role or manage
                its own settings again. Make somebody else an owner first, or invite a new
                one and remove this person once they have signed in.
              </p>
            </NoticeBox>
          ) : (
            <>
              <p className="text-xs text-ink-muted">
                They stop being able to sign in to this account on their very next request.
                Their user account, their leads and every timeline entry naming them all
                survive —{" "}
                {member.leads_assigned === 0
                  ? "they are carrying no leads"
                  : `the ${member.leads_assigned} lead${member.leads_assigned === 1 ? "" : "s"} assigned to them stay${member.leads_assigned === 1 ? "s" : ""} assigned to them, and will show as owned by somebody no longer on the account`}
                . <span className="font-semibold">There is no undo on our side:</span> to
                give the access back you issue a fresh invitation, which only they can
                redeem.
              </p>
              <TypedConfirmation
                phrase="REMOVE"
                binding={`Bound to ${member.name ?? member.email}. Nobody else on this list is affected.`}
                value={typed}
                onChange={setTyped}
                disabled={!write.allowed}
              />
              <div className="flex flex-wrap items-center gap-3">
                <ActionButton
                  type="button"
                  loading={remove.isPending}
                  disabled={wordMissing || busy || !write.allowed}
                  onClick={() => remove.mutate(member.user_id)}
                >
                  Remove their access
                </ActionButton>
                {wordMissing && (
                  <span className="text-xs text-amber-700 dark:text-amber-400">
                    Type REMOVE above to confirm.
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* Through `WriteFailure` rather than `ProblemNotice` because this write SENDS a
          confirmation header: a `step_up_required` here cannot mean "you forgot to
          confirm", only that this console and the API disagree about the string, and
          `reauthentication_required` needs the prompt rather than a red box. */}
      {remove.error != null && (
        <WriteFailure error={remove.error} actionLabel="Remove their access" />
      )}
      {remove.data != null && (
        <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
          <p className="text-xs">
            Their access to this account is gone.{" "}
            {remove.data.leads_still_assigned === 0
              ? "They were carrying no leads."
              : `${remove.data.leads_still_assigned} lead${remove.data.leads_still_assigned === 1 ? " is" : "s are"} still assigned to them and will show as owned by somebody no longer on the account — reassign from the client's own leads screen.`}
          </p>
        </NoticeBox>
      )}
    </li>
  );
}
