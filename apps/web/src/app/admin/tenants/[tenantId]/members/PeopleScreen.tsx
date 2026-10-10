"use client";

import { EmptySketch } from "@/components/console/emptySketch";
import { useState } from "react";
import { CheckCircle2, KeyRound, UserPlus } from "lucide-react";

import { ActionButton } from "@/components/actionButton";
import { Drawer } from "@/components/console/drawer";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { HAIRLINE_LIST } from "@/components/admin/kit";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatISTStamp,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import { useInvite, useTenant, useTenantInvitations } from "@/lib/api/admin";
import { ROLE_COPY } from "@/lib/api/members";
import { useTenantMembers } from "@/lib/api/tenantMembers";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

import { WhatsAppAlertsPanel } from "../WhatsAppAlertsPanel";
import { InviteRow } from "./InviteRow";
import { MemberRow } from "./MemberRow";

/**
 * EVERYONE WITH A KEY TO ONE CLIENT'S ACCOUNT (D-602, D-546, D-661): the people who have
 * signed in, the invitations still sitting in somebody's inbox, and the owner's WhatsApp
 * consent — one page, the way the client's own Team screen shows it.
 *
 * Primary job: *make sure the right people can sign in.* The support case it exists for is
 * the one this business meets first: the client's only owner has left, nobody there can
 * sign in as an owner, and every client-realm control needs one — so the fix is ours.
 *
 * Nobody is ADDED except by an invitation they redeem: a membership with no redeemed token
 * behind it would be an access grant nobody can account for. Deactivating the PERSON is not
 * here either — `users` crosses tenants, so a switch for it under one client's heading would
 * be the wrong scope printed over the right button.
 *
 * No invitation link is ever on this screen: `InviteOut` and `ResendInviteOut` carry no
 * token (D-198), so there is nothing here to be caught in a screenshot.
 */
export function PeopleScreen({ tenantId }: { tenantId: string }) {
  const tenant = useTenant(tenantId).data;
  const members = useTenantMembers(tenantId);
  const invitations = useTenantInvitations(tenantId);
  const write = useAdminAccess("admin:tenants", "change or remove somebody's access");
  const inviteWrite = useAdminAccess("admin:tenants", "issue or re-send an invitation");
  const [inviting, setInviting] = useState(false);

  /*
   * THIS CLIENT'S PEOPLE, DECLARED TO THE SCREEN ASSISTANT: counts, roles and times, never
   * addresses or names. Every address here is a person's, the operator is looking straight
   * at them, and volunteering one to a model is a disclosure nobody asked for. NO FIELDS:
   * the inputs here change who can do what, mint a live credential, or are a confirmation
   * whose whole purpose is that a human typed it.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/members",
    title: "People",
    realm: "admin",
    fields: [],
    facts: [
      { key: "tenant_id", label: "Tenant id", value: tenantId },
      { key: "client", label: "Client", value: tenant?.name ?? "could not be read" },
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
        key: "outstanding",
        label: "Invitations outstanding (addresses are not sent)",
        value: invitations.data
          ? String(invitations.data.length)
          : invitations.error
            ? "could not be read"
            : "still loading",
      },
      {
        key: "last_sent_at",
        label: "When a link was last sent to anybody at this account",
        value:
          invitations.data && invitations.data.length > 0
            ? formatISTStamp(
                invitations.data
                  .map((invite) => invite.last_sent_at)
                  .sort()
                  .slice(-1)[0],
              )
            : "never, or none outstanding",
      },
      {
        key: "may_write",
        label: "May this operator change, remove or invite somebody",
        value: write.allowed ? "yes" : "no",
      },
    ],
    apply: noFill,
  });

  const owners = members.data?.filter((row) => row.role === "owner").length ?? 0;
  const inviteAction = (
    <button
      type="button"
      className={PRIMARY_BUTTON}
      disabled={!inviteWrite.allowed}
      onClick={() => setInviting(true)}
    >
      <UserPlus aria-hidden className="h-4 w-4" />
      Invite somebody
    </button>
  );

  return (
    <div className="max-w-4xl space-y-10">
      <PageHeader
        title="People"
        description="Who can sign in to this account, and the invitations still waiting."
        actions={inviteAction}
      />

      <RestrictionNote reason={write.reason} />

      <Section
        title="Members"
        info={
          <>
            {Object.values(ROLE_COPY).map((copy) => (
              <p key={copy.label}>
                <span className="font-medium text-ink">{copy.label}</span> — {copy.can}
              </p>
            ))}
            <p>
              Removing somebody takes effect on their very next request and cannot be undone
              from here. Their leads stay assigned to them.
            </p>
          </>
        }
      >
        {members.isLoading ? (
          <div>
            <Skeleton rows={3} />
          </div>
        ) : members.error || !members.data ? (
          /* A read that FAILED must never render as "nobody has access" — an operator who
             believed that would hand out a new owner invitation to an account that already
             has one, or conclude the client is locked out when they are not. */
          <div>
            <ProblemNotice
              error={members.error ?? new Error("The member list did not load.")}
              onRetry={() => members.refetch()}
            />
          </div>
        ) : members.data.length === 0 ? (
          // No button here: "Invite somebody" in the header is this page's one action.
          <EmptyState
            message="Nobody has signed in to this account yet."
            illustration={
              <EmptySketch kind="leads" />
            }
          />
        ) : (
          <ul aria-label="Members" className={HAIRLINE_LIST}>
            {members.data.map((member) => (
              <MemberRow
                key={member.user_id}
                tenantId={tenantId}
                member={member}
                owners={owners}
                write={write}
              />
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Waiting to sign up"
        info="A link sits in somebody's inbox until they redeem it. Re-sending cuts a fresh link and kills the previous one in the same movement, so it is safe to press twice. The link itself is emailed and never shown here."
      >
        {invitations.isLoading ? (
          <div>
            <Skeleton rows={2} />
          </div>
        ) : invitations.error || !invitations.data ? (
          /* §52: "no invitation is outstanding" must never be said about a read that
             failed — an operator who believes it issues a second link to an address that
             already holds one. */
          <div>
            <ProblemNotice
              error={invitations.error ?? new Error("The invitation list did not load.")}
              onRetry={() => invitations.refetch()}
            />
          </div>
        ) : invitations.data.length === 0 ? (
          <EmptyState message="Nobody is holding a key to this account: no invitation is outstanding." />
        ) : (
          <ul aria-label="Waiting to sign up" className={HAIRLINE_LIST}>
            {invitations.data.map((invite) => (
              <InviteRow key={invite.id} tenantId={tenantId} invite={invite} write={inviteWrite} />
            ))}
          </ul>
        )}
      </Section>

      {/* The owner's WhatsApp consent is a fact about a person on this account, recorded
          here when it was given off-screen (onboarding call, signed form). */}
      <WhatsAppAlertsPanel tenantId={tenantId} />

      <Drawer
        open={inviting}
        onClose={() => setInviting(false)}
        title="Invite somebody"
        description="The link is emailed to them and never shown here."
      >
        <InviteForm tenantId={tenantId} write={inviteWrite} />
      </Drawer>
    </div>
  );
}

/**
 * A NEW invitation. A second live token for one address is refused by the API
 * (`invitation_already_pending`), which is only actionable because the list of outstanding
 * invitations is on the page behind this drawer, where the one causing it can be cancelled.
 */
function InviteForm({
  tenantId,
  write,
}: {
  tenantId: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const invite = useInvite();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("owner");
  const malformed = !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());

  return (
    <div className="space-y-4">
      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          invite.mutate({ tenantId, email: email.trim(), role });
        }}
      >
        <RestrictionNote reason={write.reason} />
        <div>
          <label htmlFor="invite-email" className={FIELD_LABEL}>
            Their email address
          </label>
          <input
            id="invite-email"
            type="email"
            value={email}
            maxLength={254}
            disabled={!write.allowed}
            onChange={(event) => {
              setEmail(event.target.value);
              invite.reset();
            }}
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            A live key to this client&apos;s account, so it goes straight to their inbox.
          </span>
        </div>
        <div>
          <label htmlFor="invite-role" className={FIELD_LABEL}>
            What they may do
          </label>
          <select
            id="invite-role"
            value={role}
            disabled={!write.allowed}
            onChange={(event) => {
              setRole(event.target.value);
              invite.reset();
            }}
            className={FIELD}
          >
            {Object.entries(ROLE_COPY).map(([value, copy]) => (
              <option key={value} value={value}>
                {copy.label}
              </option>
            ))}
          </select>
          <span className={FIELD_HINT}>{lookup(ROLE_COPY, role)?.can}</span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ActionButton type="submit" loading={invite.isPending} disabled={malformed || !write.allowed}>
            <KeyRound aria-hidden className="h-4 w-4" />
            Send the invitation
          </ActionButton>
          {malformed && (
            <span className="text-meta text-warn">Enter the address the link should go to.</span>
          )}
        </div>
      </form>

      {invite.error != null && <ProblemNotice error={invite.error} />}
      {invite.data != null && (
        <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
          <p>
            The invitation is queued for delivery and the link is good for{" "}
            {invite.data.expires_in_hours} hours. It appears under Waiting to sign up, where it
            can be re-sent or cancelled.
          </p>
        </NoticeBox>
      )}
    </div>
  );
}
