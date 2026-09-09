"use client";

import {
  Activity,
  ArrowLeft,
  ListPlus,
  Pause,
  PhoneCall,
  PhoneOff,
  Play,
  Users,
} from "lucide-react";

import {
  Card,
  EmptyState,
  SECONDARY_BUTTON,
  Skeleton,
  StatTile,
  formatCount,
  formatIST,
} from "@/components/ui";
import { lookup } from "@/lib/lookup";
import type {
  useAddContacts,
  useCampaignProgress,
  useLaunchCampaign,
  useLaunchCheck,
  usePauseCampaign,
  useScheduleCampaign,
  useSetRecurrence,
  useUnscheduleCampaign,
} from "@/lib/api/campaigns";

import { LaunchGate } from "./LaunchGate";
import { ScheduleCards } from "./ScheduleCards";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";

/**
 * ONE CAMPAIGN, once it exists — what it holds, when it dials, and how it is going.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). The bands are UX-DOCTRINE §5's: what state
 * it is in (the tiles), what it will call (the contact list), when it will call
 * (Repeats / Scheduled), the gate that decides whether it may (`LaunchGate`), and what it
 * did (Progress). Every figure here is the server's or is not shown — §52 — and none of
 * it was reworded in the move.
 */
export function CampaignDetail({
  campaignId,
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
  onStartAnother,
}: {
  campaignId: string;
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
  onStartAnother: () => void;
}) {
  const { csv, setCsv, parsed } = form;
  // Null, not "draft", until the server says: defaulting to draft renders the
  // contact-upload and launch cards over a campaign that is already running.
  const status = progress.data?.status ?? null;
  const counts = progress.data?.contacts ?? {};

  /**
   * Would this ALREADY-ARMED schedule be refused if it came due right now?
   *
   * The armed cards below used to say nothing about a refusal until the tick had tried
   * and failed at least once (`schedule_blocked_rules`), so between arming and the first
   * attempt a doomed schedule read as "Starts Monday, 10:00 IST" and nothing else. That
   * is the same discovery-by-silence the arming forms now avoid, one moment later.
   *
   * Three conditions, each load-bearing:
   *
   * - `status === "scheduled"` — the only status `due_schedules` reads. On a RUNNING
   *   campaign `launch_blockers` correctly reports its own `status` blocker ("already
   *   launched"), which is true and is NOT a statement about the next occurrence; a
   *   repeat card that read it as one would warn about a campaign that is dialling fine.
   * - `check.data !== undefined` — an unanswered launch check has no verdict, and a
   *   warning derived from one we do not have is §52's defect rather than its remedy.
   * - no `schedule_blocked_rules` — once the server has actually refused, its own record
   *   of WHICH rules refused is the stronger statement and says so in its own words.
   */
  const armedScheduleWouldRefuse =
    status === "scheduled" &&
    check.data !== undefined &&
    !check.data.ready &&
    (progress.data?.schedule_blocked_rules?.length ?? 0) === 0;

  return (
    <>
          {/* EVERY FIGURE HERE IS THE SERVER'S OR IS NOT SHOWN.
              These four used to render unconditionally with `?? 0` and, for the contact
              count, `?? parsed.length` — so a campaign whose progress request was still
              in flight, or had failed, was described as "Contacts 0 · Connected 0 · Not
              called 0". On this screen that is not a cosmetic zero: a client reading it
              during an outage concludes their campaign dialled nobody. Loading is a
              skeleton, failure is the notice above and nothing else. */}
          {progress.isLoading ? (
            <Card>
              <Skeleton rows={3} />
            </Card>
          ) : progress.data ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatTile
                label="Status"
                value={progress.data.status.replace(/_/g, " ")}
                icon={<Activity className="h-5 w-5" />}
              />
              <StatTile
                label="Contacts"
                value={formatCount(progress.data.total)}
                icon={<Users className="h-5 w-5" />}
              />
              {/* `contacts` is a complete GROUP BY over this campaign's rows, so a key
                  the response omits genuinely means zero — unlike the leads board, where
                  an absent stage means the server did not say. That is the whole reason
                  `?? 0` is honest HERE and only inside this branch. */}
              <StatTile
                label="Connected"
                value={formatCount(lookup(counts, "connected") ?? 0)}
                hint="calls answered"
                icon={<PhoneCall className="h-5 w-5" />}
              />
              <StatTile
                label="Not called"
                value={formatCount(lookup(counts, "dnc_blocked") ?? 0)}
                hint="on the do-not-call list"
                icon={<PhoneOff className="h-5 w-5" />}
              />
            </div>
          ) : null}

          {status === "draft" && (
            <Card title="Contact list">
              <div className="space-y-3">
                <textarea
                  rows={6}
                  value={csv}
                  onChange={(e) => setCsv(e.target.value)}
                  aria-label="Contact list, as CSV"
                  placeholder={"phone,name\n9876543210,Priya\n9876501234,Ravi"}
                  className="w-full rounded-md border border-line bg-surface px-3 py-2 font-mono text-xs text-ink placeholder:text-ink-faint"
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-ink-faint">
                    {parsed.length > 0
                      ? `${formatCount(parsed.length)} rows ready. Numbers we can't read are counted and skipped — never guessed.`
                      : "Paste your CSV, or one number per line."}
                  </p>
                  <button
                    type="button"
                    title={refusal}
                    disabled={
                      !canWrite ||
                      addContacts.isPending ||
                      parsed.length === 0
                    }
                    onClick={() =>
                      addContacts.mutate(parsed, {
                        onSuccess: () => setCsv(""),
                      })
                    }
                    className={SECONDARY_BUTTON}
                  >
                    <ListPlus aria-hidden className="h-4 w-4" />
                    {addContacts.isPending ? "Adding…" : "Add contacts"}
                  </button>
                </div>
                {addContacts.data && (
                  <p className="rounded-md border border-line bg-app p-2 text-xs text-ink-muted">
                    Added {formatCount(addContacts.data.added)}.{" "}
                    {addContacts.data.duplicate > 0 &&
                      `${formatCount(addContacts.data.duplicate)} ${
                        addContacts.data.duplicate === 1 ? "was" : "were"
                      } already on the list. `}
                    {addContacts.data.malformed > 0 &&
                      `${formatCount(addContacts.data.malformed)} ${
                        addContacts.data.malformed === 1 ? "number" : "numbers"
                      } couldn't be read and ${
                        addContacts.data.malformed === 1 ? "was" : "were"
                      } skipped.`}
                  </p>
                )}
              </div>
            </Card>
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
            schedule={schedule}
            repeat={repeat}
            scheduleForm={scheduleForm}
            canWrite={canWrite}
            writeReason={writeReason}
            refusal={refusal}
          />

          {launch.data && (
            <Card title="Launched">
              <p className="text-sm text-ink-muted">
                Calling {formatCount(launch.data.dialable)}{" "}
                {launch.data.dialable === 1 ? "person" : "people"}.
                {launch.data.dnc_scrubbed > 0 &&
                  ` ${formatCount(launch.data.dnc_scrubbed)} were on the do-not-call list and won't be called.`}
              </p>
            </Card>
          )}

          {status !== null &&
            ["running", "paused", "completed"].includes(status) && (
              <Card
                title="Progress"
                action={
                  status !== "completed" ? (
                    <button
                      type="button"
                      title={refusal}
                      disabled={!canWrite || setStatus.isPending}
                      onClick={() =>
                        setStatus.mutate(
                          status === "running" ? "pause" : "resume",
                        )
                      }
                      className={SECONDARY_BUTTON}
                    >
                      {status === "running" ? (
                        <Pause aria-hidden className="h-3.5 w-3.5" />
                      ) : (
                        <Play aria-hidden className="h-3.5 w-3.5" />
                      )}
                      {status === "running" ? "Pause" : "Resume"}
                    </button>
                  ) : null
                }
              >
                {progress.data?.total ? (
                  <>
                  <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                    {Object.entries(counts).map(([key, value]) => (
                      <div key={key}>
                        {/* The server's own contact-status vocabulary, humanised but not
                          renamed: inventing a label here would make the campaign screen
                          and the API disagree about what a row is called. */}
                        <dt className="text-[11px] uppercase tracking-wider text-ink-faint">
                          {key.replace(/_/g, " ")}
                        </dt>
                        <dd className="mt-0.5 text-lg font-semibold tabular-nums text-ink">
                          {formatCount(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  {/* Prose, so OUTSIDE the <dl>: a bare <div> of text as a direct child
                      of a definition list is the axe violation f944a67 fixed on the
                      call-detail screen — this was its sibling. */}
                  <p className="mt-4 text-xs text-ink-faint">
                    Launched {formatIST(progress.data.launched_at)} · up to{" "}
                    {formatCount(progress.data.concurrency)} calls at a time
                  </p>
                  </>
                ) : (
                  <EmptyState title="No contacts yet" />
                )}
              </Card>
            )}


          <button
            type="button"
            onClick={onStartAnother}
            className={SECONDARY_BUTTON}
          >
            <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
            Start another campaign
          </button>
    </>
  );
}
