"use client";

import { useState } from "react";
import { CheckCircle2, Send } from "lucide-react";

import { ActionButton } from "@/components/actionButton";
import { Drawer } from "@/components/console/drawer";
import { RowMenu } from "@/components/console/rowMenu";
import { FIELD, FIELD_HINT, FIELD_LABEL, NoticeBox, ProblemNotice, formatIST } from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  useResendTenantInvitation,
  useRevokeTenantInvitation,
  type PendingInviteOut,
} from "@/lib/api/admin";
import { ROLE_COPY } from "@/lib/api/members";
import { lookup } from "@/lib/lookup";

const EMAIL_SHAPE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * One live key to this account: who holds it, when it was cut, when it dies, and how many
 * times it has gone — the two facts that turn "they have not signed up" into a decision.
 * `invited_at` is the MINT and `last_sent_at` is the SEND; after a resend they differ.
 *
 * Re-sending ROTATES the token: the previous link dies in the statement that cuts the new
 * one, so two live keys for one address cannot exist and the button is safe to press twice.
 *
 * The address CORRECTION is behind the row menu, never the default: it is an operator
 * ATTESTATION about a mailbox nothing verified, recorded in the audit log as such.
 */
export function InviteRow({
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
  const [correcting, setCorrecting] = useState(false);
  const [email, setEmail] = useState("");
  const [attestation, setAttestation] = useState("");

  const busy = resend.isPending || revoke.isPending;
  const correctionMalformed = !EMAIL_SHAPE.test(email.trim());
  const correctionBlocked = correctionMalformed || attestation.trim().length < 3;

  return (
    <li className="space-y-2 px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-56">
          {/* Two invitations to one domain are told apart by the local part, which is the
              half a truncation eats — so the full address is in the title. */}
          <p className="truncate text-sm font-medium text-ink" title={invite.email}>
            {invite.email}
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">
            {lookup(ROLE_COPY, invite.role)?.label ?? invite.role} · issued{" "}
            {formatIST(invite.invited_at)} · expires {formatIST(invite.expires_at)}
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">
            Link last sent {formatIST(invite.last_sent_at)} · sent {invite.send_count} time
            {invite.send_count === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 max-sm:w-full">
          <ActionButton
            type="button"
            loading={resend.isPending}
            disabled={busy || !write.allowed}
            onClick={() => resend.mutate({ tenantId, invitationId: invite.id })}
          >
            <Send aria-hidden className="h-4 w-4" />
            Send the link again
          </ActionButton>
          <RowMenu
            label={invite.email}
            items={[
              {
                id: "correct",
                label: "Wrong address?",
                disabled: busy || !write.allowed,
                hint: write.allowed ? undefined : (write.reason ?? undefined),
                onSelect: () => {
                  resend.reset();
                  setCorrecting(true);
                },
              },
              {
                id: "cancel",
                label: "Cancel it",
                tone: "danger",
                disabled: busy || !write.allowed,
                hint: write.allowed ? undefined : (write.reason ?? undefined),
                onSelect: () => revoke.mutate({ tenantId, invitationId: invite.id }),
              },
            ]}
          />
        </div>
      </div>

      {resend.error != null && !correcting && <ProblemNotice error={resend.error} />}
      {revoke.error != null && <ProblemNotice error={revoke.error} />}
      {resend.data != null && !correcting && <ResentNotice data={resend.data} />}

      <Drawer
        open={correcting}
        onClose={() => setCorrecting(false)}
        title="Send it to a different address"
        description={`The invitation for ${invite.email}.`}
      >
        <div className="space-y-4">
          <p className="text-sm text-ink-muted">
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
              <span className="text-xs text-warn">
                {correctionMalformed
                  ? "That does not look like an email address."
                  : "Say how you established this address."}
              </span>
            )}
          </div>
          {resend.error != null && <ProblemNotice error={resend.error} />}
          {resend.data != null && <ResentNotice data={resend.data} />}
        </div>
      </Drawer>
    </li>
  );
}

function ResentNotice({
  data,
}: {
  data: NonNullable<ReturnType<typeof useResendTenantInvitation>["data"]>;
}) {
  return (
    <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
      <p className="text-xs">
        A fresh link is on its way to {data.email}, and the previous one stopped working the
        moment it was cut. It expires {formatIST(data.expires_at)} — send {data.send_count} for
        this invitation.
      </p>
    </NoticeBox>
  );
}
