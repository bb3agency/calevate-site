"use client";

import Link from "next/link";
import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { StatusPill } from "@/components/console/statusPill";
import {
  CALLER_ID_COPY,
  CARRIER_LABEL,
  CONCURRENCY_COPY,
  LINE_KIND_LABEL,
  STATUS_COPY,
  modeSummary,
} from "@/components/forwarding/copy";
import { ForwardingCodes } from "@/components/forwarding/ForwardingCodes";
import { ModeChoice } from "@/components/forwarding/ModeChoice";
import { TestPanel } from "@/components/forwarding/TestPanel";
import {
  Disclosure,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
  ToggleSwitch,
  formatPhone,
} from "@/components/ui";
import type { Session } from "@/lib/api/client";
import {
  DEFAULT_RING_SECONDS,
  useChangeLine,
  useForwarding,
  useRemoveLine,
  useSaveNumberSwitch,
  useSetSaveNumber,
  type ForwardedLine,
  type ForwardingMode,
} from "@/lib/api/forwarding";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

/**
 * SETTINGS > PHONE NUMBERS (D-746): the number callers already know, how its calls reach
 * the agent, the codes for the client's own phone, the test, and the "save our number"
 * message. Primary job: see that the forward works, and fix it when it does not.
 */
export function PhoneNumbersScreen() {
  const { session, href } = useClientRealm();
  const slug = session.orgSlug;
  const forwarding = useForwarding(session);
  const write = useWriteAccess(session, "org:manage", "change how your number forwards");
  const guide = href(`/c/${slug}/setup/existing-number`);
  const data = forwarding.data;

  return (
    <div className="max-w-2xl space-y-10 pb-12">
      <PageHeader description="The number your callers know, and how its calls reach your agent." />
      <RestrictionNote reason={write.reason} />
      <Section
        title="Your existing number"
        action={
          data && data.lines.length > 0 && data.lines.length < data.max_lines ? (
            <Link href={guide} className={TEXT_ACTION}>
              Add another
            </Link>
          ) : undefined
        }
      >
        {forwarding.isLoading ? (
          <Skeleton rows={4} label="Loading your numbers" />
        ) : forwarding.error || !data ? (
          <ProblemNotice error={forwarding.error ?? new Error("Your numbers did not load.")} onRetry={() => void forwarding.refetch()} />
        ) : data.lines.length === 0 ? (
          <EmptyState
            align="start"
            message="No existing number set up."
            hint="Keep the number your callers know and forward its calls to your agent."
            action={
              data.calevate_numbers.length > 0 ? (
                <Link href={guide} className={`${PRIMARY_BUTTON} w-full justify-center sm:w-auto`}>
                  Set it up
                </Link>
              ) : (
                <Link href={href(`/c/${slug}/phone-number`)} className={TEXT_ACTION}>
                  Get your Calevate number first
                </Link>
              )
            }
          />
        ) : (
          <div className="divide-y divide-line">
            {data.lines.map((line) => (
              <LineSettings
                key={line.id}
                session={session}
                line={line}
                allowed={write.allowed}
                testingAvailable={data.testing_available}
              />
            ))}
          </div>
        )}
      </Section>
      <SaveNumber session={session} />
    </div>
  );
}

function LineSettings({
  session,
  line,
  allowed,
  testingAvailable,
}: {
  session: Session;
  line: ForwardedLine;
  allowed: boolean;
  testingAvailable: boolean;
}) {
  const change = useChangeLine(session, line.id);
  const changeFeedback = useActionFeedback(change, { errorDisplay: "inline" });
  const remove = useRemoveLine(session);
  // The dialog shows a refusal inside itself; on success the line leaves the page, so the
  // outcome is said in a toast.
  const removeFeedback = useActionFeedback(remove, {
    errorDisplay: "inline",
    successToast: `${formatPhone(line.e164)} removed`,
  });
  const [editing, setEditing] = useState(false);
  const [mode, setMode] = useState<ForwardingMode>(line.mode);
  const [seconds, setSeconds] = useState<number>(line.ring_seconds || DEFAULT_RING_SECONDS);
  const [confirming, setConfirming] = useState(false);
  const status = STATUS_COPY[line.status];
  const target = line.calevate_number_e164;

  return (
    <div className="space-y-6 py-6 first:pt-0">
      {line.quiet_since && (
        <NoticeBox tone="warn" title="No calls from this number for three days." role="status">
          The forward on your phone may be off. Run the test again.
        </NoticeBox>
      )}
      <SettingRows>
        <SettingRow
          label="Your number"
          value={<span className="font-mono tabular-nums">{formatPhone(line.e164)}</span>}
        />
        <SettingRow
          label="Line"
          value={
            line.line_kind === "mobile"
              ? `${LINE_KIND_LABEL.mobile} · ${CARRIER_LABEL[line.carrier]}`
              : LINE_KIND_LABEL[line.line_kind]
          }
        />
        <SettingRow
          label="Forwards to"
          value={target ? <span className="font-mono tabular-nums">{formatPhone(target)}</span> : "No Calevate number"}
        />
        <SettingRow
          label="Calls"
          value={modeSummary(line.mode, line.ring_seconds)}
          action={
            editing ? undefined : (
              <button type="button" className={TEXT_ACTION} disabled={!allowed} onClick={() => setEditing(true)}>
                Change
              </button>
            )
          }
        />
        <SettingRow label="Forwarding" value={<StatusPill tone={status.tone}>{status.text}</StatusPill>} />
        {line.caller_id_finding && (
          <SettingRow label="Caller's number" value={CALLER_ID_COPY[line.caller_id_finding]} />
        )}
        {line.concurrency_finding && (
          <SettingRow label="Two calls at once" value={CONCURRENCY_COPY[line.concurrency_finding]} />
        )}
      </SettingRows>

      {editing && (
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            change.mutate(
              {
                line_kind: line.line_kind,
                carrier: line.carrier,
                mode,
                ring_seconds: mode === "all_calls" ? 0 : seconds,
                calevate_number_id: line.calevate_number_id,
              },
              { onSuccess: () => setEditing(false) },
            );
          }}
        >
          <ModeChoice
            idPrefix={`line-${line.id}`}
            mode={mode}
            seconds={seconds}
            disabled={!allowed || change.isPending}
            onChange={(nextMode, nextSeconds) => {
              setMode(nextMode);
              if (nextSeconds > 0) setSeconds(nextSeconds);
            }}
          />
          <p className="text-meta text-ink-muted">After saving, dial the new codes on your phone, then test again.</p>
          {change.error != null && <ProblemNotice error={change.error} />}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" className={SECONDARY_BUTTON} onClick={() => setEditing(false)}>
              Cancel
            </button>
            <ActionButton type="submit" status={changeFeedback.status} successLabel="Saved" disabled={!allowed}>
              Save
            </ActionButton>
          </div>
        </form>
      )}

      {target && (
        <Disclosure title="Codes for your phone" subtitle="Switch the forward on or off" variant="inline" headingLevel={3}>
          <ForwardingCodes
            session={session}
            carrier={line.carrier}
            lineKind={line.line_kind}
            mode={line.mode}
            seconds={line.ring_seconds}
            calevateNumber={target}
            headingLevel={3}
          />
        </Disclosure>
      )}

      <TestPanel session={session} line={line} allowed={allowed} available={testingAvailable} />

      <button type="button" className={TEXT_ACTION_DANGER} disabled={!allowed} onClick={() => setConfirming(true)}>
        Stop using this number
      </button>
      {confirming && (
        <ConfirmDialog
          title={`Stop using ${formatPhone(line.e164)}`}
          confirmLabel="Stop using it"
          pendingLabel="Removing…"
          status={removeFeedback.status}
          error={remove.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() => remove.mutate(line.id, { onSuccess: () => setConfirming(false) })}
        >
          Switch the forward off on your phone too, with the codes for your phone, or callers keep reaching your
          agent.
        </ConfirmDialog>
      )}
    </div>
  );
}

function SaveNumber({ session }: { session: Session }) {
  const state = useSaveNumberSwitch(session);
  const set = useSetSaveNumber(session);
  // The switch itself shows the new state; a refusal is drawn under it.
  useActionFeedback(set, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change the save-our-number message");
  return (
    <Section
      title="Ask callers to save your number"
      info="Sent once to each caller on WhatsApp, only to callers who agreed to messages and are not on your do-not-call list, in their language. It names your business and the number your agent calls from. We pay for it."
    >
      {state.isLoading ? (
        <Skeleton rows={1} label="Loading the setting" />
      ) : state.error || !state.data ? (
        <ProblemNotice error={state.error ?? new Error("This setting did not load.")} onRetry={() => void state.refetch()} />
      ) : (
        <div className="space-y-2">
          <ToggleSwitch
            label="Send one message after a booking"
            hint="When your agent makes a booking or arranges a call back, the caller is asked to save the number reminders come from."
            checked={state.data.enabled}
            disabled={!write.allowed || set.isPending}
            onChange={(next) => set.mutate(next)}
          />
          {set.error != null && <ProblemNotice error={set.error} />}
        </div>
      )}
    </Section>
  );
}
