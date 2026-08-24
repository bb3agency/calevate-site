"use client";

import { BellOff, BellRing, CircleAlert, Info, Lock, ShieldCheck } from "lucide-react";

import {
  Card,
  DANGER_BUTTON,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useMyAlertOptIn, useRecordMyAlertOptIn } from "@/lib/api/whatsappAlerts";

/**
 * WhatsApp alerts for hot leads — the client's own opt-in.
 *
 * ## Why this screen exists
 *
 * FLOWS §6 promises a WhatsApp and an email to the owner within two minutes of a hot
 * lead, and only the email has ever been sent. Not because the transport is missing —
 * `notify_hot_lead_whatsapp` refuses with `recipient_not_opted_in`, correctly, because
 * Meta's policy requires the business owner to have opted in to receive messages from us.
 * The ledger that records that opt-in shipped with an API and no screen, so the ONE
 * person who is allowed to give it (the account owner, in the first person — a CHECK
 * constraint enforces it) had no way to.
 *
 * ## What this screen must never do, and the API is shaped to stop it
 *
 * 1. **Show its own copy of the notice.** The exact sentence is
 *    `whatsapp_optin.ALERT_NOTICE_TEXT`, delivered on every response with its version,
 *    and it is rendered from there. A `notice_version` in a database row is only evidence
 *    if the wording it names can be reproduced years later, and a string that lives in a
 *    React component cannot be. The version this screen SHOWS is the version it sends
 *    back, so a cached build agreeing to last quarter's text is refused
 *    (`alert_optin_notice_out_of_date`) rather than recorded.
 * 2. **Offer an opt-in for a channel nothing can send on.** `delivery_available` is a
 *    different question from consent: no WhatsApp Business account exists yet (D-91), and
 *    a tick-box that quietly records an agreement to receive messages this deployment
 *    cannot deliver is the "looks finished" failure the WhatsApp seam was built to avoid.
 *    So the grant is withheld with its reason while the channel is unavailable — and
 *    WITHDRAWING never is. Taking consent back must not depend on our vendor situation.
 * 3. **Decide for itself whether alerts are on.** `messageable` is the server's verdict,
 *    computed from the same read the hot-lead worker runs. A screen that re-derived it
 *    would eventually show a tick beside an alert that is never sent.
 *
 * §52 governs the rest: the read is a skeleton while it is in flight and a refusal when
 * it fails, and neither is "alerts are off" — which is the one wrong answer here, because
 * a client who reads it turns on something that is already on, or stops waiting for a
 * message that is coming.
 *
 * NO `<h1>`: the app shell renders the page title from the nav list it also renders.
 */
export default function AlertsPage() {
  const session = useClientSession();
  const state = useMyAlertOptIn(session);
  const record = useRecordMyAlertOptIn(session);
  /**
   * `org:manage` — the permission that already governs the account's own settings, and
   * the one only the `owner` role holds. Agreeing to receive WhatsApp about your own
   * business is exactly that decision, and a staff member cannot make it on the owner's
   * behalf: the subject of an opt-in is the only person who can give it.
   */
  const write = useWriteAccess(session, "org:manage", "turn WhatsApp alerts on or off");

  const current = state.data;

  return (
    <div className="max-w-2xl space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        When a call produces a hot lead, we message the account owner within two minutes so
        somebody can ring them back while they are still interested. The email always goes
        out; WhatsApp only goes out if you have agreed to receive it here.
      </p>

      <RestrictionNote reason={write.reason} />

      {state.error != null && (
        <ProblemNotice error={state.error} onRetry={() => state.refetch()} />
      )}

      {/* Loading is a skeleton, failure is the refusal above and nothing else. "Alerts are
          off" over a failed read is the sentence that makes a client turn on something
          that is already on. */}
      {state.isLoading ? (
        <Card>
          <Skeleton rows={4} />
        </Card>
      ) : !current ? null : (
        <>
          <Card title="WhatsApp alerts">
            <div className="space-y-4">
              <NoticeBox
                tone={current.messageable ? "ok" : "neutral"}
                icon={
                  current.messageable ? (
                    <BellRing aria-hidden className="h-5 w-5" />
                  ) : (
                    <BellOff aria-hidden className="h-5 w-5" />
                  )
                }
                title={
                  current.messageable
                    ? "Hot-lead alerts are on for your WhatsApp"
                    : "Hot-lead alerts are not going to your WhatsApp"
                }
              >
                {current.messageable ? (
                  <p className="mt-1">
                    We message the mobile number on your profile. We do not need it typed
                    here and we never show it back to you.
                    {current.captured_at && (
                      <> You agreed on {formatIST(current.captured_at)}.</>
                    )}
                  </p>
                ) : (
                  <p className="mt-1">
                    {current.status === "withdrawn"
                      ? "You turned these off. Hot leads still reach you by email and are on your dashboard."
                      : "Nobody has agreed to receive them on this account yet. Hot leads still reach you by email and are on your dashboard."}
                  </p>
                )}
              </NoticeBox>

              {/* The channel's own readiness, said separately from consent — they are
                  different questions and collapsing them would either hide this control
                  until a vendor account exists or promise a message nothing can send. */}
              {!current.delivery_available && (
                <NoticeBox
                  tone="warn"
                  icon={<CircleAlert aria-hidden className="h-5 w-5" />}
                  title="We cannot send WhatsApp messages yet"
                >
                  <p className="mt-1">
                    This is on our side, not yours: the WhatsApp business connection is not
                    live yet
                    {current.delivery_unavailable_reason && (
                      <>
                        {" "}
                        (<MonoValue>{current.delivery_unavailable_reason}</MonoValue>)
                      </>
                    )}
                    . Agreeing now would record your consent for something we cannot do, so
                    the control is held back until it works. Email alerts are unaffected.
                  </p>
                </NoticeBox>
              )}

              {record.error != null && <ProblemNotice error={record.error} />}

              {current.messageable ? (
                <WithdrawControl
                  allowed={write.allowed}
                  reason={write.reason}
                  pending={record.isPending}
                  onWithdraw={() =>
                    record.mutate({
                      status: "withdrawn",
                      // Sent for shape only: the server records no notice version against
                      // a withdrawal, because taking consent back is not an agreement to
                      // anything.
                      noticeVersion: current.current_notice_version,
                    })
                  }
                />
              ) : (
                <GrantControl
                  notice={current.current_notice_text}
                  allowed={write.allowed && current.delivery_available}
                  reason={
                    write.reason ??
                    (current.delivery_available
                      ? null
                      : "We cannot send WhatsApp messages yet, so there is nothing to agree to.")
                  }
                  pending={record.isPending}
                  onGrant={() =>
                    record.mutate({
                      status: "granted",
                      // The version THIS screen is showing, not a constant in the bundle:
                      // a build showing older wording must be refused, not recorded.
                      noticeVersion: current.current_notice_version,
                    })
                  }
                />
              )}
            </div>
          </Card>

          <Card title="What we send, and what we never send">
            <ul className="space-y-2 text-sm text-ink-muted">
              <li className="flex gap-2">
                <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
                One message per hot lead, to the owner. Never marketing, and never to your
                customers — this setting is about messages to YOU.
              </li>
              <li className="flex gap-2">
                <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
                Whether your agents may message your customers is a different question with
                its own record, on the Messaging consent screen.
              </li>
              <li className="flex gap-2">
                <Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
                Turning this off is a new entry, not a deletion: we keep the record that
                you agreed and the record that you withdrew, which is what lets us show
                anyone asking exactly what was on when.
              </li>
            </ul>
            <p className="mt-3 text-xs text-ink-faint">
              Wording in force:{" "}
              <MonoValue>{current.current_notice_version}</MonoValue>
              {current.notice_version && current.notice_version !== current.current_notice_version && (
                <> · you agreed to <MonoValue>{current.notice_version}</MonoValue></>
              )}
            </p>
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * The agreement itself: the server's exact sentence, and a button that means it.
 *
 * A tick-box plus a separate Save was the alternative and is worse here — it produces a
 * screen state where the box is ticked and nothing is recorded, which looks exactly like
 * consent to the person who ticked it and is nothing at all to the ledger.
 */
function GrantControl({
  notice,
  allowed,
  reason,
  pending,
  onGrant,
}: {
  notice: string;
  allowed: boolean;
  reason: string | null;
  pending: boolean;
  onGrant: () => void;
}) {
  return (
    <div className="space-y-3">
      <p className="rounded-card border border-line bg-surface p-4 text-sm text-ink">{notice}</p>
      {/* Shared ActionButton: the spinner rides `loading` while the opt-in is recorded, and
          the disabled logic is unchanged (`disabled || loading`). The accessible name stays
          "I agree…" through the write, so `whatsappAlerts.test.tsx`'s `/I agree/` — and a
          screen reader — never lose the control. */}
      <ActionButton type="button" loading={pending} disabled={!allowed} onClick={onGrant}>
        <BellRing aria-hidden className="h-4 w-4" />
        I agree — send me WhatsApp alerts
      </ActionButton>
      {!allowed && reason && (
        <p className="flex items-start gap-2 text-xs text-ink-muted">
          <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {reason}
        </p>
      )}
    </div>
  );
}

/**
 * Withdrawing — offered whenever alerts are on, and never gated on the channel working.
 *
 * The asymmetry with the grant is deliberate: consent that can be given more easily than
 * it can be taken back is not consent, and "our vendor connection is down" is our problem
 * rather than a reason to keep messaging somebody who has asked us to stop.
 */
function WithdrawControl({
  allowed,
  reason,
  pending,
  onWithdraw,
}: {
  allowed: boolean;
  reason: string | null;
  pending: boolean;
  onWithdraw: () => void;
}) {
  return (
    <div className="space-y-3">
      <button
        type="button"
        disabled={!allowed || pending}
        onClick={onWithdraw}
        className={DANGER_BUTTON}
      >
        <BellOff aria-hidden className="h-4 w-4" />
        {pending ? "Saving…" : "Stop sending me WhatsApp alerts"}
      </button>
      <p className="text-xs text-ink-faint">
        Hot leads keep reaching you by email and on your dashboard. You can turn WhatsApp
        back on here whenever you like.
      </p>
      {!allowed && reason && (
        <p className="flex items-start gap-2 text-xs text-ink-muted">
          <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {reason}
        </p>
      )}
    </div>
  );
}
