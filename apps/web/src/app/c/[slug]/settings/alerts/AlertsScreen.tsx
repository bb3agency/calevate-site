"use client";

import { DesktopAlerts } from "./DesktopAlerts";


import { useActionFeedback } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { ServiceLogo } from "@/components/console/serviceLogo";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import {
  Disclosure,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
  formatISTStamp,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useMyAlertOptIn, useRecordMyAlertOptIn } from "@/lib/api/whatsappAlerts";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { GrantControl, WithdrawControl } from "./consentControls";

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
export function AlertsScreen() {
  const session = useClientSession();
  const state = useMyAlertOptIn(session);
  const record = useRecordMyAlertOptIn(session);
  const recordFeedback = useActionFeedback(record, { errorDisplay: "inline" });
  /**
   * `org:manage` — the permission that already governs the account's own settings, and
   * the one only the `owner` role holds. Agreeing to receive WhatsApp about your own
   * business is exactly that decision, and a staff member cannot make it on the owner's
   * behalf: the subject of an opt-in is the only person who can give it.
   */
  const write = useWriteAccess(session, "org:manage", "turn WhatsApp alerts on or off");

  const current = state.data;

  /*
   * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * NOTHING IS WRITABLE, and on this screen that is a rule rather than a shrug: the one
   * act here is a CONSENT, recorded against a person and a notice version, and "the
   * subject of an opt-in is the only person who can give it" is the sentence the
   * permission comment above already makes. An assistant that could flip it would be
   * manufacturing consent on somebody's behalf.
   *
   * The consent NOTICE TEXT is not sent either — it is a versioned legal string, and the
   * version identifier says everything an answer here needs.
   */
  useCopilotSurface({
    route: "/c/{slug}/settings/alerts",
    title: "Hot-lead alerts",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: current
          ? "the alert settings below have loaded"
          : state.error != null
            ? "the settings failed to load — this is NOT evidence that alerts are off"
            : "still loading",
      },
      ...(current
        ? [
            {
              key: "messageable",
              label: "Are hot-lead alerts going to this person's WhatsApp?",
              value: current.messageable ? "yes" : "no",
            },
            { key: "opt_in_status", label: "Recorded consent status", value: current.status },
            { key: "channel", label: "Channel the consent was given on", value: current.channel ?? "none recorded" },
            { key: "captured_at", label: "When it was recorded (IST)", value: formatISTStamp(current.captured_at, "never") },
            {
              key: "delivery_available",
              label: "Can we deliver WhatsApp at all right now?",
              value: current.delivery_available
                ? "yes"
                : `no — ${current.delivery_unavailable_reason ?? "no reason given"}`,
            },
          ]
        : []),
      {
        key: "may_change",
        label: "May this session turn alerts on or off?",
        value: write.allowed ? "yes" : `no — ${write.reason ?? "no reason given"}`,
      },
    ],
    apply: noFill,
  });

  return (
    <div className="max-w-2xl space-y-10 pb-12">
      <PageHeader
        description={
          <>
            Hot leads always reach you by email. WhatsApp is optional.{" "}
            <InfoTip label="hot-lead alerts" className="-my-3">
              <p>
                When a call produces a hot lead, we message the account owner within two
                minutes. The email always goes out; WhatsApp only goes out if you have
                agreed to receive it here.
              </p>
            </InfoTip>
          </>
        }
      />

      <RestrictionNote reason={write.reason} />

      {state.error != null && (
        <ProblemNotice error={state.error} onRetry={() => state.refetch()} />
      )}

      {state.isLoading ? (
        <Skeleton rows={3} label="Checking your alert settings" />
      ) : !current ? null : (
        <>
          {/* Above the row it explains, so the dead "I agree" below reads as ours to fix. */}
          {!current.delivery_available && (
            <NoticeBox tone="warn" title="We cannot send WhatsApp messages yet">
              <p>This is on our side, not yours. Email alerts are unaffected.</p>
            </NoticeBox>
          )}

          <section className="border-y border-line">
            <SettingRows>
              <SettingRow
                label="WhatsApp alerts"
                icon={<ServiceLogo service="whatsapp" className="h-5 w-5" />}
                hint={
                  current.messageable ? (
                    <>
                      Sent to the mobile number on your profile, which we never show here.
                      {current.captured_at && (
                        <> You agreed on {formatIST(current.captured_at)}.</>
                      )}
                    </>
                  ) : current.status === "withdrawn" ? (
                    "You turned these off. Email alerts continue."
                  ) : (
                    "Nobody on this account has agreed to them yet."
                  )
                }
                value={<AlertStatePill on={current.messageable} />}
              />
              {/* The consent controls sit under the row, in full: granting is an agreement to
                  the server's own notice text, so it is that text and a button naming the
                  act — never a switch that records consent without the notice being read. */}
              <div className="py-4">
                {record.error != null && <ProblemNotice error={record.error} />}
                {current.messageable ? (
                  <WithdrawControl
                    allowed={write.allowed}
                    reason={write.reason}
                    status={recordFeedback.status}
                    onWithdraw={() =>
                      record.mutate({
                        status: "withdrawn",
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
                        : "Nothing to agree to until we can send them.")
                    }
                    status={recordFeedback.status}
                    onGrant={() =>
                      record.mutate({
                        status: "granted",
                        noticeVersion: current.current_notice_version,
                      })
                    }
                  />
                )}
              </div>
            </SettingRows>
          </section>

          <Disclosure
            variant="inline"
            headingLevel={2}
            title="What we send, and what we never send"
            subtitle="One message per hot lead, to you only. Never marketing, and never to your customers."
          >
            <ul className="space-y-2 text-body text-ink-muted">
              <li>
                One message per hot lead, to the owner. Never marketing, and never to your
                customers. This setting is about messages to you.
              </li>
              <li>
                Whether your agents may message your customers is a different question with
                its own record, on the Messaging consent screen.
              </li>
              <li>
                Turning this off is a new entry, not a deletion: we keep the record that
                you agreed and the record that you withdrew, which is what lets us show
                anyone asking exactly what was on when.
              </li>
            </ul>
          </Disclosure>
        </>
      )}
      <DesktopAlerts />
    </div>
  );
}

/** On or off, in words; the colour is the second channel (WCAG 1.4.1). */
function AlertStatePill({ on }: { on: boolean }) {
  return (
    <span
      className={`text-body font-medium ${on ? "text-brand-strong dark:text-brand-bright" : "text-ink-muted"}`}
    >
      {on ? "On" : "Off"}
    </span>
  );
}
