"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, UserMinus } from "lucide-react";

import { ActionButton } from "@/components/actionButton";
import { Drawer } from "@/components/console/drawer";
import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import {
  FIELD_INLINE,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  formatIST,
} from "@/components/ui";
import { WriteFailure } from "@/app/admin/writeFailure";
import type { useAdminAccess } from "@/app/admin/access";
import { ROLE_COPY } from "@/lib/api/members";
import {
  useRemoveTenantMember,
  useSetTenantMemberRole,
  type TenantMember,
  type TenantMemberRole,
} from "@/lib/api/tenantMembers";
import { lookup } from "@/lib/lookup";

/**
 * One person who can sign in: who they are, what they hold, and the two things an operator
 * may do about it.
 *
 * WHY REMOVAL AND ROLE CHANGE LOOK SO DIFFERENT. The role is a select on the row because a
 * wrong one is one click back on this same screen. Removal opens a drawer, wants a typed
 * word and says how much work the person is carrying, because it is not undoable by us at
 * all: the way back is a fresh invitation the person has to redeem themselves
 * (`admin/members_routes.py`). The typed word is not the guard — the `X-Confirm-Action`
 * header and `admin:tenants` are — it is what stops a mis-click and makes the operator read
 * the cost.
 *
 * The lead count is on the row, not only in the answer: removing somebody does NOT
 * unassign their work (`tenancy/members.remove_member`), so the number that decides the act
 * is beside the person before the decision.
 */
export function MemberRow({
  tenantId,
  member,
  owners,
  write,
}: {
  tenantId: string;
  member: TenantMember;
  /**
   * How many owners this account has. Used ONLY to explain the server's refusal before it
   * happens — the rule is enforced under a row lock (`lock_owner_ids`), because a count read
   * in a browser is exactly the read-then-write that lock exists to refuse.
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
  const who = member.name ?? member.email;

  return (
    <li className="space-y-2 px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-56">
          {/* NOT falling back to the address when the name is null: the address is printed
              beneath anyway, and a fallback that duplicates it reads as two people. */}
          <p className="text-sm font-medium text-ink">{member.name ?? "Unnamed member"}</p>
          <p className="truncate text-xs text-ink-muted" title={member.email}>
            {member.email}
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">
            Joined {formatIST(member.joined_at)} ·{" "}
            {member.leads_assigned === 0
              ? "no leads assigned"
              : `${member.leads_assigned} lead${member.leads_assigned === 1 ? "" : "s"} assigned`}
          </p>
          {!member.email_verified && (
            <p className="mt-0.5 text-xs text-warn">
              This address has never been verified by them — our notices may not be reaching
              it.
            </p>
          )}
          {member.deactivated && (
            <p className="mt-0.5 text-xs text-warn">
              This person is deactivated platform-wide, so they are refused at sign-in. They
              still hold a membership here, and it still counts as an owner.
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 max-sm:w-full">
          <label className="sr-only" htmlFor={`role-${member.user_id}`}>
            Role for {who}
          </label>
          <select
            id={`role-${member.user_id}`}
            // The value the ROW is showing is also what is sent as `expected_role`, so the
            // compare-and-swap guards the picture the operator actually read.
            value={member.role}
            disabled={busy || !write.allowed}
            title={lookup(ROLE_COPY, member.role)?.can}
            className={`${FIELD_INLINE} max-sm:flex-1`}
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
              setRemoving(true);
              setTyped("");
              remove.reset();
            }}
          >
            <UserMinus aria-hidden className="h-4 w-4" />
            Remove access
          </button>
        </div>
      </div>

      {setRole.error != null && <ProblemNotice error={setRole.error} />}

      <Drawer
        open={removing}
        onClose={() => setRemoving(false)}
        title={`Remove ${who}'s access`}
        description="Takes effect on their very next request."
      >
        <div className="space-y-4">
          {lastOwner ? (
            <NoticeBox tone="stop" icon={<AlertTriangle className="h-5 w-5" />}>
              <p className="text-xs">
                This is the only owner on the account, so their access cannot be removed —
                an account with no owner can never invite anybody, change a role or manage
                its own settings again. Make somebody else an owner first, or invite a new
                one and remove this person once they have signed in.
              </p>
            </NoticeBox>
          ) : remove.data != null ? (
            <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
              <p className="text-xs">
                Their access to this account is gone.{" "}
                {remove.data.leads_still_assigned === 0
                  ? "They were carrying no leads."
                  : `${remove.data.leads_still_assigned} lead${remove.data.leads_still_assigned === 1 ? " is" : "s are"} still assigned to them and will show as owned by somebody no longer on the account — reassign from the client's own leads screen.`}
              </p>
            </NoticeBox>
          ) : (
            <>
              <p className="text-sm text-ink-muted">
                They stop being able to sign in to this account on their very next request.
                Their user account, their leads and every timeline entry naming them all
                survive —{" "}
                {member.leads_assigned === 0
                  ? "they are carrying no leads"
                  : `the ${member.leads_assigned} lead${member.leads_assigned === 1 ? "" : "s"} assigned to them stay${member.leads_assigned === 1 ? "s" : ""} assigned to them, and will show as owned by somebody no longer on the account`}
                . <span className="font-semibold text-ink">There is no undo on our side:</span>{" "}
                to give the access back you issue a fresh invitation, which only they can
                redeem.
              </p>
              <TypedConfirmation
                phrase="REMOVE"
                hint={`Bound to ${who}. Nobody else on this list is affected.`}
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
                  <span className="text-xs text-warn">Type REMOVE above to confirm.</span>
                )}
              </div>
              {/* `WriteFailure`, not `ProblemNotice`: this write SENDS a confirmation header,
                  so `step_up_required` means this console and the API disagree about the
                  string, and `reauthentication_required` needs the prompt, not a red box. */}
              {remove.error != null && (
                <WriteFailure error={remove.error} actionLabel="Remove their access" />
              )}
            </>
          )}
        </div>
      </Drawer>
    </li>
  );
}
