"use client";

import { useState } from "react";
import { KeyRound, Mail, TriangleAlert } from "lucide-react";

import { ActionButton } from "@/components/actionButton";
import { useFormValidation } from "@/components/formValidation";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import {
  useInvite,
  useResendTenantInvitation,
  useRevokeTenantInvitation,
  useTenantInvitations,
} from "@/lib/api/admin";
import { ApiProblem } from "@/lib/api/client";

import { refusalReason } from "@/app/admin/new/shared";

/**
 * Invite the owner of an account nobody has been invited into (D-695: the leftovers from
 * when creating an account and inviting its owner were separate steps). The link is mailed
 * to the owner and never shown; their name and mobile travel with it.
 */
export function OwnerInvitePanel({ created }: { created: { id: string; slug: string } }) {
  const invite = useInvite();
  const revoke = useRevokeTenantInvitation();
  // THE FOUNDER'S OWN ASK, and until now the only route in D-538 with no caller: *"the
  // invite link can be re-sent via the admin panel ... until that mail sets up their
  // business"*. The endpoint, the rotation, the rate limit and the audit row all shipped;
  // the operator staring at `invitation_already_pending` could only CANCEL, which throws
  // away a live key to fix a mail that simply never arrived. Resending is the answer to
  // that refusal far more often than cancelling is, so it stands beside it.
  const resend = useResendTenantInvitation();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  // WAS the raw token, rendered on screen. D-198 removed it from the response and put the
  // link in the invitee's mailbox instead, so what is remembered here is the ADDRESS it was
  // sent to — the one thing an operator still needs to see, and not a credential. Cleared
  // at every submit so a send to one address can never sit under a refusal for another.
  const [sentTo, setSentTo] = useState<string | null>(null);
  const refusal = refusalReason(invite.error);
  const inviteValid = useFormValidation();
  // THE EXIT FROM THE SERVER'S OWN REFUSAL, and the reason it needs its own state.
  //
  // A second live token for one address is refused (`invitation_already_pending`), which
  // is right — two keys to a client's account in one inbox, only one of them revocable —
  // but on its own it leaves an operator whose first token was lost with nothing to do
  // for 72 hours: the revoke that already existed is client-realm, and this invite is
  // minted before anybody can sign in.
  //
  // `invite.data` cannot carry the id: a mutation clears `data` when the next attempt
  // fails, and the attempt that fails is exactly the one where the cancel is needed. So
  // the mint is remembered here — WITH ITS ADDRESS, which is the part that must not be
  // dropped. Minting for A and then being refused for B is a refusal about B's pending
  // invitation, and offering a button that silently cancels A's would revoke a live
  // credential the operator never asked about. The control appears only when the address
  // in the box is the one we hold.
  const [minted, setMinted] = useState<{ id: string; email: string } | null>(null);
  const blockedByPending =
    invite.error instanceof ApiProblem && invite.error.code === "invitation_already_pending";
  const cancellable =
    blockedByPending && minted && minted.email === email.trim().toLowerCase() ? minted.id : null;
  // The case the remembered mint cannot cover: the first link was issued by a colleague,
  // or from another tab, so this component never saw its id. Fetched only once the server
  // has actually refused — a list of live credentials is not something to put on screen
  // for every operator who opens the wizard.
  const pending = useTenantInvitations(blockedByPending && !cancellable ? created.id : "");

  return (
    <Section
      title="Invite the owner"
      description="We send the owner a single-use link that is valid for 72 hours. We only keep a fingerprint of it, so it is never shown here and cannot be recovered."
    >
        <div className="space-y-4">

          <form
            className="max-w-sm space-y-4"
            noValidate
            onSubmit={inviteValid.onSubmit(() => {
              // A previous confirmation must not survive this attempt: "sent to …" left
              // over from an earlier address is a claim about mail nobody sent.
              setSentTo(null);
              // No placeholder fallback: an invite is a single-use credential for a real
              // inbox, and minting one for `owner@example.com` because the billing-email
              // field was left blank is a token nobody can use and a membership row
              // nobody asked for.
              invite.mutate(
                {
                  tenantId: created.id,
                  email: email.trim(),
                  role: "owner",
                  name: name.trim() || null,
                  phone: phone.trim() || null,
                },
                {
                  onSuccess: (data) => {
                    setSentTo(email.trim());
                    setMinted({ id: data.id, email: email.trim().toLowerCase() });
                  },
                },
              );
            })}
          >
            <label className="block">
              <span className={FIELD_LABEL}>Owner&apos;s name</span>
              <input
                value={name}
                maxLength={200}
                autoComplete="off"
                onChange={(e) => setName(e.target.value)}
                className={FIELD}
              />
            </label>
            <label className="block">
              <span className={FIELD_LABEL}>Owner&apos;s mobile</span>
              <input
                value={phone}
                inputMode="tel"
                placeholder="+919876543210"
                autoComplete="off"
                onChange={(e) => setPhone(e.target.value)}
                className={`${FIELD} font-mono`}
              />
            </label>
            <label className="block">
              <span className={FIELD_LABEL}>Owner&apos;s email</span>
              <input
                {...inviteValid.field("email", "Enter the owner's email address.")}
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="owner@business.com"
                className={FIELD}
              />
              {inviteValid.error("email")}
            </label>
            <ActionButton
              type="submit"
              title={refusal ?? undefined}
              loading={invite.isPending}
              /* Emptiness is answered at the field now. `refusal` is a permission or a
                 lifecycle gate and stays. */
              disabled={Boolean(refusal)}
            >
              <Mail aria-hidden className="h-4 w-4" />
              Create invite
            </ActionButton>
          </form>

          {invite.error && <ProblemNotice error={invite.error} />}
          {refusal && <p className="text-meta text-ink-muted">{refusal}</p>}
          {revoke.error && <ProblemNotice error={revoke.error} />}
          {resend.error && <ProblemNotice error={resend.error} />}
          {resend.data && (
            <p className="text-meta text-ink-muted">
              A new link is on its way to {resend.data.email}. The previous one has stopped
              working, and this one expires {formatIST(resend.data.expires_at)}.
            </p>
          )}

          {blockedByPending && !cancellable && (
            <div className="space-y-2">
              {/* §52 on a panel that appears only inside a refusal: while the list is in
                  flight it is a skeleton, and a failed read is the read's own refusal —
                  never "there are no pending invites", which would contradict the 409
                  that put this panel on screen. */}
              {pending.isLoading ? (
                <Skeleton rows={2} />
              ) : pending.error || !pending.data ? (
                /* `|| !pending.data` because a paused query — what TanStack does with
                   every read while the browser is offline — has `isLoading === false` and
                   `error === null`, so both arms above were skipped and `?? []` rendered
                   "no pending invites" against the 409 that put this panel on screen. */
                <ProblemNotice
                  error={pending.error ?? new Error("The pending invitations did not load.")}
                  onRetry={() => void pending.refetch()}
                />
              ) : (
                pending.data.map((row) => (
                  <div key={row.id} className="flex flex-wrap items-center gap-2 border-y border-line py-2.5 text-meta">
                    <MonoValue className="text-ink">{row.email}</MonoValue>
                    <span className="text-ink-muted">
                      {row.role} · expires {formatIST(row.expires_at)}
                    </span>
                    <button
                      type="button"
                      disabled={resend.isPending}
                      className={SECONDARY_BUTTON_SM}
                      onClick={() =>
                        resend.mutate({ tenantId: created.id, invitationId: row.id })
                      }
                    >
                      Send this invite again
                    </button>
                    <button
                      type="button"
                      disabled={revoke.isPending}
                      className={SECONDARY_BUTTON_SM}
                      onClick={() =>
                        revoke.mutate({ tenantId: created.id, invitationId: row.id })
                      }
                    >
                      Cancel this invite
                    </button>
                  </div>
                ))
              )}
            </div>
          )}

          {cancellable && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={resend.isPending}
                className={SECONDARY_BUTTON_SM}
                onClick={() => {
                  // The old confirmation goes: "sent to …" described a link this rotation
                  // has just killed, and leaving it beside the new one is two claims about
                  // one mailbox.
                  setSentTo(null);
                  resend.mutate({ tenantId: created.id, invitationId: cancellable });
                }}
              >
                Send it again
              </button>
              <button
                type="button"
                disabled={revoke.isPending}
                className={SECONDARY_BUTTON_SM}
                onClick={() => {
                  // The confirmation goes with the invitation it described — leaving "sent
                  // to …" beside a cancelled link is a claim about a link that no longer
                  // opens anything.
                  setSentTo(null);
                  revoke.mutate(
                    { tenantId: created.id, invitationId: cancellable },
                    {
                      onSuccess: () => {
                        // The row is gone, so the handle must go with it: a second click
                        // would 404 and read as the cancel having failed.
                        setMinted(null);
                        invite.reset();
                      },
                    },
                  );
                }}
              >
                {revoke.isPending ? "Cancelling…" : "Cancel the unused invite"}
              </button>
              <span className="text-meta text-ink-muted">
                Cancels the link this wizard already issued, so a fresh one can be sent to
                the same address. It does nothing to an invite somebody has already used.
              </span>
            </div>
          )}

          {sentTo && (
            <NoticeBox
              tone="ok"
              icon={<KeyRound aria-hidden className="h-5 w-5" />}
              title="Invitation sent"
            >
              <p className="mt-1">
                The link is on its way to <MonoValue>{sentTo}</MonoValue>. It is not shown
                here and cannot be read again — only a fingerprint of it is stored.
              </p>
              <p className="mt-2 flex items-start gap-2">
                <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                Whoever opens it becomes an owner of{" "}
                <MonoValue>/c/{created.slug}</MonoValue>. If it went to the wrong address,
                cancel the invitation rather than sending a second one.
              </p>
            </NoticeBox>
          )}
        </div>
    </Section>
  );
}
