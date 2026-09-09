"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft, CheckCircle2, KeyRound, Mail, Send, Trash2 } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import {
  useInvite,
  useResendTenantInvitation,
  useRevokeTenantInvitation,
  useTenant,
  useTenantInvitations,
  type PendingInviteOut,
} from "@/lib/api/admin";
import { ROLE_COPY } from "@/lib/api/members";
import { lookup } from "@/lib/lookup";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { useAdminAccess } from "@/app/admin/access";

/**
 * The keys to one client's account — who holds one, since when, and re-cutting it (D-546).
 *
 * The founder's ask was a RE-SEND, not a send: *"the invite link can be re-sent via the
 * admin panel for a client business until that mail sets up their business correctly."*
 * Every part of that shipped with D-538 — the list, the revoke, the resend that rotates
 * the token, the address correction — and the only console caller was the new-client
 * wizard, which an operator can never return to. So a client who mistyped their address at
 * signup was unreachable: every self-service recovery mails the mailbox that does not work.
 *
 * ## WHY THIS IS A STATE SCREEN AND NOT A BUTTON
 *
 * "They still have not signed up" is not a decision until you know WHEN the last link went
 * and HOW MANY have gone. A link sent four minutes ago is not yet a problem; one sent five
 * times to an address that never answers is a telephone call rather than a sixth click.
 * `invited_at` is the MINT and `last_sent_at` is the SEND — after a resend they differ, and
 * reading the wrong one tells an operator to wait when they need not.
 *
 * ## THE RESEND ROTATES THE TOKEN; IT DOES NOT MINT A SECOND INVITATION
 *
 * The previous link dies in the same statement that cuts the new one, so two live keys to
 * one account cannot exist by construction. That is why this is safe to click twice, why
 * the list must be refetched after it (`expires_at`, `last_sent_at` and `send_count` all
 * move), and why "resend" is not spelled "revoke, then invite again" anywhere.
 *
 * ## NO TOKEN IS EVER ON THIS SCREEN
 *
 * The link is mailed by the server and never handed back (D-198): `InviteOut` and
 * `ResendInviteOut` carry no token at all, so there is nothing here to be shouted into a
 * screenshot or a log. What an operator gets is the address it went to, which is what they
 * read back to the client on the telephone.
 */
export default function TenantInvitationsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const invitations = useTenantInvitations(tenantId);
  const write = useAdminAccess("admin:tenants", "issue or re-send an invitation");

  /*
   * INVITATIONS TO ONE ACCOUNT, DECLARED TO THE SCREEN ASSISTANT.
   *
   * COUNTS AND TIMES, NEVER ADDRESSES. Every address on this screen is a person's email,
   * and volunteering one to a model is a disclosure nobody asked for — the operator is
   * looking straight at them, so nothing is lost. NO FIELDS: the address box on this
   * screen mints a live credential to a client's account, and a machine-drafted value in
   * it is not something this console should offer.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/invitations",
    title: "Invitations",
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
            ? invitations.data
                .map((invite) => invite.last_sent_at)
                .sort()
                .slice(-1)[0]!
            : "never, or none outstanding",
      },
      {
        key: "may_invite",
        label: "May this operator issue or re-send an invitation",
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
        <h1 className="mt-1 text-xl font-semibold text-ink">Invitations</h1>
        <p className="text-sm text-ink-muted">
          The keys to this account that are sitting in somebody&apos;s inbox right now.
          Re-sending cuts a fresh link and kills the previous one in the same movement, so
          it is safe to press twice and two live links for one address can never exist. The
          link itself is emailed and never shown here.
        </p>
      </div>

      <Card title="Outstanding invitations">
        {invitations.isLoading ? (
          <Skeleton rows={3} />
        ) : invitations.error ? (
          /* §52: "no invitation is outstanding" is the exact claim this screen exists to
             make actionable, and it must never be made about a read that failed — an
             operator who believes it issues a second link to an address that already
             holds one. */
          <ProblemNotice error={invitations.error} onRetry={() => invitations.refetch()} />
        ) : (invitations.data?.length ?? 0) === 0 ? (
          <EmptyState
            title="Nobody is holding a key to this account"
            hint="No invitation to this client is outstanding. Either everyone invited has signed up, or nobody has been invited yet."
          />
        ) : (
          <ul className="divide-y divide-line">
            {invitations.data!.map((invite) => (
              <InviteRow
                key={invite.id}
                tenantId={tenantId}
                invite={invite}
                write={write}
              />
            ))}
          </ul>
        )}
      </Card>

      <InviteForm tenantId={tenantId} write={write} />
    </div>
  );
}

/** One live key: who holds it, when it was cut, when it dies, and the two ways to act. */
function InviteRow({
  tenantId,
  invite,
  write,
}: {
  tenantId: string;
  invite: PendingInviteOut;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const resend = useResendTenantInvitation();
  const revoke = useRevokeTenantInvitation();
  // The address CORRECTION is a second control behind a disclosure, never the default: it
  // is an operator ATTESTATION about a mailbox nothing verified, and one click away from
  // an ordinary resend is one click away from re-addressing a client's credential.
  const [correcting, setCorrecting] = useState(false);
  const [email, setEmail] = useState("");
  const [attestation, setAttestation] = useState("");

  const busy = resend.isPending || revoke.isPending;
  const correctionMalformed = !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  const correctionBlocked = correctionMalformed || attestation.trim().length < 3;

  return (
    <li className="space-y-3 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-medium text-ink">
            <Mail className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden />
            {/* Same rule as the operator directory: two invitations to one domain are
                told apart by the local part, which is the half a truncation eats. */}
            <span title={invite.email} className="truncate">
              {invite.email}
            </span>
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">
            {lookup(ROLE_COPY, invite.role)?.label ?? invite.role} · issued{" "}
            {formatIST(invite.invited_at)}{" "}
            · expires {formatIST(invite.expires_at)}
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">
            {/* The two facts that turn "they have not signed up" into a decision. */}
            Link last sent {formatIST(invite.last_sent_at)} · sent {invite.send_count}{" "}
            time{invite.send_count === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <ActionButton
            type="button"
            loading={resend.isPending}
            disabled={busy || !write.allowed}
            onClick={() => resend.mutate({ tenantId, invitationId: invite.id })}
          >
            <Send className="mr-1.5 h-4 w-4" aria-hidden />
            Send the link again
          </ActionButton>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={busy || !write.allowed}
            onClick={() => setCorrecting((open) => !open)}
            aria-expanded={correcting}
          >
            Wrong address?
          </button>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={busy || !write.allowed}
            onClick={() => revoke.mutate({ tenantId, invitationId: invite.id })}
          >
            <Trash2 className="mr-1.5 h-4 w-4" aria-hidden />
            Cancel it
          </button>
        </div>
      </div>

      <RestrictionNote reason={write.reason} />

      {correcting && (
        <div className="space-y-3 rounded-md border border-line bg-surface-muted p-3">
          <p className="text-xs text-ink-muted">
            Sends the link to a DIFFERENT address on the same invitation. Use it when the
            address on file cannot receive mail — a client who mistyped it at signup can be
            reached no other way, because every self-service recovery mails that same
            mailbox. This records what you assert, not a verified address: nothing has
            proved this new mailbox, and it does not become proved by the link being used.
          </p>
          <div>
            <label htmlFor={`resend-email-${invite.id}`} className={FIELD_LABEL}>
              Send it to
            </label>
            <input
              id={`resend-email-${invite.id}`}
              type="email"
              value={email}
              maxLength={254}
              onChange={(event) => {
                setEmail(event.target.value);
                resend.reset();
              }}
              className={FIELD}
            />
          </div>
          <div>
            <label htmlFor={`resend-attestation-${invite.id}`} className={FIELD_LABEL}>
              How you established it
            </label>
            <textarea
              id={`resend-attestation-${invite.id}`}
              rows={2}
              maxLength={500}
              value={attestation}
              onChange={(event) => {
                setAttestation(event.target.value);
                resend.reset();
              }}
              className={FIELD}
            />
            <span className={FIELD_HINT}>
              Required, and recorded in the audit log as your attestation — &quot;confirmed
              on a call with the owner&quot;, &quot;from the signed order form&quot;. An
              assertion with no stated ground is a claim rather than a record.
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <ActionButton
              type="button"
              loading={resend.isPending}
              disabled={correctionBlocked || busy || !write.allowed}
              onClick={() =>
                resend.mutate({
                  tenantId,
                  invitationId: invite.id,
                  email: email.trim(),
                  attestation: attestation.trim(),
                })
              }
            >
              Send to the corrected address
            </ActionButton>
            {correctionBlocked && (
              <span className="text-xs text-amber-700 dark:text-amber-400">
                {correctionMalformed
                  ? "That does not look like an email address."
                  : "Say how you established this address."}
              </span>
            )}
          </div>
        </div>
      )}

      {resend.error != null && <ProblemNotice error={resend.error} />}
      {revoke.error != null && <ProblemNotice error={revoke.error} />}
      {resend.data != null && (
        <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
          <p className="text-xs">
            A fresh link is on its way to {resend.data.email}, and the previous one stopped
            working the moment it was cut. It expires {formatIST(resend.data.expires_at)} —
            send {resend.data.send_count} for this invitation.
          </p>
        </NoticeBox>
      )}
    </li>
  );
}

/**
 * Issuing a NEW invitation, for the case the list above cannot serve: nobody at this
 * client holds a key at all, because the first one was redeemed by somebody who has since
 * left, or was cancelled, or expired.
 *
 * A SECOND live token for one address is refused by the API (`invitation_already_pending`),
 * which is exactly why the list sits above this form rather than below it — the refusal is
 * only actionable if the operator can see and cancel the invitation causing it.
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
    <Card title="Invite somebody to this account">
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
            The link is emailed straight to them and is never shown here — it is a live key
            to this client&apos;s account, and a key on a screen is a key in a screenshot.
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
          <ActionButton
            type="submit"
            loading={invite.isPending}
            disabled={malformed || !write.allowed}
          >
            <KeyRound className="mr-1.5 h-4 w-4" aria-hidden />
            Send the invitation
          </ActionButton>
          {malformed && (
            <span className="text-xs text-amber-700 dark:text-amber-400">
              Enter the address the link should go to.
            </span>
          )}
        </div>
      </form>

      {invite.error != null && <ProblemNotice error={invite.error} />}
      {invite.data != null && (
        <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
          <p className="text-xs">
            The invitation is queued for delivery and the link is good for{" "}
            {invite.data.expires_in_hours} hours. It appears in the list above, where it can
            be re-sent or cancelled.
          </p>
        </NoticeBox>
      )}
    </Card>
  );
}
