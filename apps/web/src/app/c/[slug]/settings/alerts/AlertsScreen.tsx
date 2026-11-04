"use client";

import Link from "next/link";

import { DailySummary } from "./DailySummary";
import { DesktopAlerts } from "./DesktopAlerts";
import { TeamList } from "./TeamList";

import { useActionFeedback } from "@/components/arc/feedback";
import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { ServiceLogo } from "@/components/console/serviceLogo";
import {
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
  formatISTStamp,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useMyAlertOptIn, useRecordMyAlertOptIn } from "@/lib/api/whatsappAlerts";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { GrantControl, WithdrawControl } from "./consentControls";

/**
 * WHO HEARS ABOUT HOT LEADS (D-967): one list. The owner is its first row (email always, to
 * the account email; WhatsApp once they agree here), the team addresses are the rest
 * (`TeamList`). Everyone on it hears about the same calls, once per person per channel per
 * call. What counts is set on each agent: an outcome that makes a lead hot, plus anything its
 * own rule adds.
 *
 * The owner's WhatsApp is a CONSENT, and three things about it are the server's, never this
 * screen's:
 *
 * 1. The notice text and its version (`whatsapp_optin.ALERT_NOTICE_TEXT`), shown and sent back
 *    as given, so a cached build agreeing to an old text is refused rather than recorded.
 * 2. Whether the channel can deliver at all (`delivery_available`): the grant is withheld with
 *    its reason while it cannot. Withdrawing never is.
 * 3. Whether alerts are on (`messageable`), computed from the read the worker runs.
 *
 * A read in flight is a skeleton and a failed one a refusal; neither is "alerts are off".
 *
 * NO `<h1>`: the app shell renders the page title from the nav list it also renders.
 */
export function AlertsScreen() {
  const { session, href } = useClientRealm();
  const state = useMyAlertOptIn(session);
  const record = useRecordMyAlertOptIn(session);
  const recordFeedback = useActionFeedback(record, { errorDisplay: "inline" });
  // One mutation drives both controls, and the refetch after it swaps Grant for Withdraw
  // inside the success hold: each control shows the feedback only for its own act, or the
  // new button reads "Stopped" right after the owner agreed.
  const feedbackFor = (act: "granted" | "withdrawn") =>
    record.variables?.status === act ? recordFeedback.status : "idle";
  /**
   * `org:manage`, which only the owner holds: agreeing to receive WhatsApp is the owner's own
   * consent, and choosing who else receives a caller's full number is the owner's decision.
   */
  const write = useWriteAccess(session, "org:manage", "change who hears about hot leads");

  const current = state.data;

  /*
   * NOTHING IS WRITABLE BY THE ASSISTANT HERE: the owner's WhatsApp is a consent recorded
   * against a person and a notice version, and team addresses are confirmed by a code typed
   * here. Pip adds or removes team emails through its own `team_alert_contact` action.
   */
  useCopilotSurface({
    route: "/c/{slug}/settings/alerts",
    title: "Who hears about hot leads",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: current
          ? "the hot-lead list below has loaded"
          : state.error != null
            ? "the settings failed to load — this is NOT evidence that alerts are off"
            : "still loading",
      },
      ...(current
        ? [
            {
              key: "messageable",
              label: "Are hot-lead alerts going to the owner's WhatsApp?",
              value: current.messageable ? "yes" : "no",
            },
            { key: "opt_in_status", label: "Recorded consent status", value: current.status },
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
        label: "May this session change who hears?",
        value: write.allowed ? "yes" : `no — ${write.reason ?? "no reason given"}`,
      },
    ],
    apply: noFill,
  });

  return (
    <div className="max-w-2xl space-y-10 pb-12">
      <PageHeader description="Who hears about hot leads, and your daily summary." />

      <RestrictionNote reason={write.reason} />

      <Section
        title="Who hears about hot leads"
        description="Each person once per hot lead, within two minutes."
        info={
          <p>
            You get the caller&apos;s name and a link. Your team gets their full number too,
            so they can call back.
          </p>
        }
      >
        <ul className="divide-y divide-line border-y border-line">
          <li className="space-y-3 py-4">
            <div>
              <p className="text-body font-medium text-ink">You</p>
              <p className="text-meta text-ink-muted">Email to your account email · Always on</p>
            </div>
            {state.error != null ? (
              <ProblemNotice error={state.error} onRetry={() => state.refetch()} />
            ) : !current ? (
              <Skeleton rows={1} label="Checking your WhatsApp alerts" />
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="flex items-center gap-2 text-body text-ink">
                    <ServiceLogo service="whatsapp" className="h-5 w-5" />
                    WhatsApp
                    <span className="text-meta text-ink-muted">
                      {current.messageable
                        ? current.captured_at
                          ? `On since ${formatIST(current.captured_at)}`
                          : "On"
                        : "Off"}
                    </span>
                  </p>
                </div>
                {!current.delivery_available && !current.messageable ? (
                  <NoticeBox tone="warn" title="WhatsApp is not ready yet">
                    <p>Our side, not yours. Email still works.</p>
                  </NoticeBox>
                ) : null}
                {record.error != null && <ProblemNotice error={record.error} />}
                {current.messageable ? (
                  <WithdrawControl
                    allowed={write.allowed}
                    reason={write.reason}
                    status={feedbackFor("withdrawn")}
                    onWithdraw={() =>
                      record.mutate({
                        status: "withdrawn",
                        noticeVersion: current.current_notice_version,
                      })
                    }
                  />
                ) : (
                  // The agreement is the server's own sentence and a button that means it,
                  // never a switch that records consent without the notice on screen.
                  <GrantControl
                    notice={current.current_notice_text}
                    allowed={write.allowed && current.delivery_available}
                    reason={write.reason ?? (current.delivery_available ? null : "Opens once WhatsApp is ready.")}
                    status={feedbackFor("granted")}
                    onGrant={() =>
                      record.mutate({
                        status: "granted",
                        noticeVersion: current.current_notice_version,
                      })
                    }
                  />
                )}
              </div>
            )}
          </li>
          <TeamList canWrite={write.allowed} reason={write.reason} />
        </ul>
        <p className="mt-3 flex flex-wrap items-center gap-x-3 text-meta text-ink-muted">
          <span>What counts as hot is set on each agent.</span>
          <Link href={href(`/c/${session.orgSlug}/agents`)} className={TEXT_ACTION}>
            Open agents
          </Link>
        </p>
      </Section>

      <DailySummary />
      <DesktopAlerts />
    </div>
  );
}
