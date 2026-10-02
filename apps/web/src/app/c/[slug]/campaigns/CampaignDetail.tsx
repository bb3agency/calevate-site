"use client";

import { ListPlus, Pause, Play } from "lucide-react";

import { PageHeader } from "@/components/console/pageHeader";
import { ProgressBar } from "@/components/interior/progress-bar";
import {
  Card,
  Disclosure,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  formatCount,
  formatIST,
  formatPhone,
} from "@/components/ui";
import type {
  CampaignSummary,
  useAddContacts,
  useCampaignProgress,
  useLaunchCampaign,
  useLaunchCheck,
  usePauseCampaign,
  useScheduleCampaign,
  useSetRecurrence,
  useUnscheduleCampaign,
} from "@/lib/api/campaigns";
import { lookup } from "@/lib/lookup";

import { ArmingForms } from "./ArmingForms";
import { LaunchGate } from "./LaunchGate";
import { ContactEditor } from "./ContactEditor";
import { ScheduleCards } from "./ScheduleCards";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";
import { CampaignStatusPill } from "./campaignStatus";

/**
 * ONE CAMPAIGN: its state in the header, then the one thing its state asks for.
 *
 * A draft's job is the launch checklist (`LaunchGate`), with the delayed start and the
 * weekly repeat disclosed under it: both are the Launch button on a calendar, and the
 * gate runs again when they fire. A running campaign's job is its progress and Pause.
 *
 * Every figure is the server's or is not shown (§52): while progress is loading the
 * header carries no counts, and a failed read is the notice at the top of the screen.
 */
export function CampaignDetail({
  campaignId,
  campaign,
  form,
  scheduleForm,
  progress,
  check,
  addContacts,
  launch,
  setStatus,
  schedule,
  unschedule,
  repeat,
  canWrite,
  writeReason,
  refusal,
  onBack,
}: {
  campaignId: string;
  /** The list's row for this campaign: its name lives there, not on the progress read. */
  campaign: CampaignSummary | undefined;
  form: CampaignFormState;
  scheduleForm: ScheduleFormState;
  progress: ReturnType<typeof useCampaignProgress>;
  check: ReturnType<typeof useLaunchCheck>;
  addContacts: ReturnType<typeof useAddContacts>;
  launch: ReturnType<typeof useLaunchCampaign>;
  setStatus: ReturnType<typeof usePauseCampaign>;
  schedule: ReturnType<typeof useScheduleCampaign>;
  unschedule: ReturnType<typeof useUnscheduleCampaign>;
  repeat: ReturnType<typeof useSetRecurrence>;
  canWrite: boolean;
  writeReason: string | null;
  refusal: string | undefined;
  onBack: () => void;
}) {
  // Null, not "draft", until the server says: a default would render the launch card
  // over a campaign that is already running.
  const status = progress.data?.status ?? null;
  const counts = progress.data?.contacts ?? {};
  const live = status === "running" || status === "paused";

  /**
   * Would this ALREADY-ARMED schedule be refused if it came due now? Only for `scheduled`
   * (on a running campaign the gate's own `status` blocker is not about the next run),
   * only from a launch check that answered, and only until the server has actually
   * refused, after which its own record of which rules refused is the stronger statement.
   */
  const armedScheduleWouldRefuse =
    status === "scheduled" &&
    check.data !== undefined &&
    !check.data.ready &&
    (progress.data?.schedule_blocked_rules?.length ?? 0) === 0;

  const hours = progress.data?.calling_hours;
  const facts = progress.data
    ? [
        `${formatCount(progress.data.total)} ${progress.data.total === 1 ? "contact" : "contacts"}`,
        progress.data.number_e164 ? `from ${formatPhone(progress.data.number_e164)}` : "no number of its own",
        hours ? `${hours.start}–${hours.end} IST` : "9am–9pm IST",
        `up to ${formatCount(progress.data.concurrency)} at once`,
      ].join(" · ")
    : undefined;

  return (
    <div className="space-y-5">
      <div>
        <PageHeader
          back={{ onClick: onBack, label: "All campaigns" }}
          title={campaign?.name ?? "Campaign"}
          status={status ? <CampaignStatusPill status={status} /> : undefined}
          description={facts}
          actions={
            live ? (
              <button
                type="button"
                title={refusal}
                disabled={!canWrite || setStatus.isPending}
                onClick={() => setStatus.mutate(status === "running" ? "pause" : "resume")}
                className={SECONDARY_BUTTON}
              >
                {status === "running" ? (
                  <Pause aria-hidden className="h-3.5 w-3.5" />
                ) : (
                  <Play aria-hidden className="h-3.5 w-3.5" />
                )}
                {status === "running" ? "Pause" : "Resume"}
              </button>
            ) : undefined
          }
        />
      </div>

      {progress.isLoading && <Skeleton rows={3} />}

      {/* The list stays editable until launch. After a create whose upload failed, the
          list is still in the editor (cleared only on success), so this button is
          the retry. */}
      {(status === "draft" || status === "scheduled") && (
        <ContactsCard
          form={form}
          addContacts={addContacts}
          canWrite={canWrite}
          refusal={refusal}
        />
      )}

      <ScheduleCards
        status={status}
        progress={progress}
        unschedule={unschedule}
        armedScheduleWouldRefuse={armedScheduleWouldRefuse}
        canWrite={canWrite}
        refusal={refusal}
      />

      <LaunchGate
        campaignId={campaignId}
        status={status}
        check={check}
        progress={progress}
        launch={launch}
        canWrite={canWrite}
        writeReason={writeReason}
        refusal={refusal}
      />

      {(status === "draft" || status === "scheduled") && check.data && (
        <Disclosure
          title="Start later or repeat"
          subtitle="Set a start time or a weekly repeat. The same checks run again when it starts."
        >
          <ArmingForms
            status={status}
            check={check}
            schedule={schedule}
            repeat={repeat}
            scheduleForm={scheduleForm}
            canWrite={canWrite}
            refusal={refusal}
          />
        </Disclosure>
      )}

      {launch.data && (
        <p role="status" className="text-sm text-ink-muted">
          Calling {formatCount(launch.data.dialable)}{" "}
          {launch.data.dialable === 1 ? "person" : "people"}.
          {launch.data.dnc_scrubbed > 0 &&
            ` ${formatCount(launch.data.dnc_scrubbed)} were on the do-not-call list and won't be called.`}
        </p>
      )}

      {progress.data && status !== null && ["running", "paused", "completed"].includes(status) && (
        <Card title="Progress">
          {progress.data.total ? (
            <div className="space-y-5">
              <ProgressBar
                label="Connected"
                value={lookup(counts, "connected") ?? 0}
                max={progress.data.total}
              />
              {/* `contacts` is a complete GROUP BY over this campaign's rows, so a key the
                  response omits genuinely means zero — honest HERE and only here. */}
              <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                {Object.entries(counts).map(([key, value]) => (
                  <div key={key}>
                    {/* The server's own contact-status words, humanised but not renamed. */}
                    <dt className="text-xs capitalize text-ink-faint">{key.replace(/_/g, " ")}</dt>
                    <dd className="mt-0.5 text-lg font-semibold tabular-nums text-ink">
                      {formatCount(value)}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="text-xs text-ink-faint">
                Launched {formatIST(progress.data.launched_at)} · Not called:{" "}
                {formatCount(lookup(counts, "dnc_blocked") ?? 0)} on the do-not-call list
              </p>
            </div>
          ) : (
            <p className="text-sm text-ink-muted">No contacts yet.</p>
          )}
        </Card>
      )}
    </div>
  );
}

/** The contact list, editable until launch. */
function ContactsCard({
  form,
  addContacts,
  canWrite,
  refusal,
}: {
  form: CampaignFormState;
  addContacts: ReturnType<typeof useAddContacts>;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const { contacts, setContacts, checked } = form;
  const result = addContacts.data;
  const ready = checked.ready.length;
  return (
    <Disclosure
      title="Contacts"
      subtitle="Add more numbers to this campaign any time before it launches."
      defaultOpen={contacts.length > 0 || addContacts.isError}
    >
      <div className="space-y-3">
        {addContacts.error && <ProblemNotice error={addContacts.error} />}
        <ContactEditor entries={contacts} onChange={setContacts} label="Contacts to add" />
        <button
          type="button"
          title={refusal}
          disabled={!canWrite || addContacts.isPending || ready === 0 || checked.refusal !== null}
          onClick={() => addContacts.mutate(checked.ready, { onSuccess: () => setContacts([]) })}
          className={SECONDARY_BUTTON}
        >
          <ListPlus aria-hidden className="h-4 w-4" />
          {addContacts.isPending ? "Adding…" : "Add contacts"}
        </button>
        {result && (
          <p role="status" className="text-xs text-ink-muted">
            Added {formatCount(result.added)}.{" "}
            {result.duplicate > 0 &&
              `${formatCount(result.duplicate)} ${result.duplicate === 1 ? "was" : "were"} already on the list. `}
            {result.malformed > 0 &&
              `${formatCount(result.malformed)} ${result.malformed === 1 ? "number" : "numbers"} couldn't be read and ${
                result.malformed === 1 ? "was" : "were"
              } skipped.`}
          </p>
        )}
      </div>
    </Disclosure>
  );
}
