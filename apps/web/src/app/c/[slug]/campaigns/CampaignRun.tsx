"use client";

import Link from "next/link";
import { PhoneCall } from "lucide-react";

import { useElapsedSeconds } from "@/components/console/liveCallPanel";
import { LiveDot } from "@/components/console/liveCalls";
import { FlashValue } from "@/components/console/valueFlash";
import { InfoTip } from "@/components/console/infoTip";
import { ProgressBar } from "@/components/interior/progress-bar";
import { TaskSteps } from "@/components/interior/task-steps";
import { SECONDARY_BUTTON_SM, formatCount, formatDuration, formatIST, formatPhone } from "@/components/ui";
import { useCallingNow, type CampaignProgress, type ContactResult } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";

import { AtOnceHint } from "./CampaignSettings";
import { campaignRun, runSentence } from "./campaignProgress";

/**
 * THE LIVE PANEL OF A LAUNCHED CAMPAIGN: what it is doing this minute, how far through the
 * list it is, and who is on the phone right now (UX-DOCTRINE §1: while a campaign runs the
 * screen answers "is it working, and how far has it got").
 *
 * Four facts sit under the bar because they are the questions an owner asks of a running
 * dialler, in this order: how many calls are going out at once against the most allowed,
 * when the next try is, who has not been rung yet, and who has spoken to the agent. The
 * people on a call are named under them with their own clock and a way into the call.
 * The steps stay on the panel (founder, 15 Oct 2026), at its foot and beside the calls on
 * a wide screen: they say which part of the run this is, which the sentence at the top
 * already says in words, so they come after the facts rather than before them.
 *
 * Everything is the progress read (polled, and refetched by the live stream on every
 * campaign change, D-774), except the names on a call, which are the people list filtered
 * to `calling` on a faster poll of their own.
 */
export function CampaignRun({ progress, campaignId }: { progress: CampaignProgress; campaignId: string }) {
  const run = campaignRun(progress);
  const running = progress.status === "running";
  const live = running || progress.status === "paused";
  const calling = run.hold === undefined && running && run.onCallNow > 0;
  const onCall = running && run.onCallNow > 0;

  return (
    <section
      aria-labelledby="campaign-run"
      className="space-y-5 rounded-card border border-line bg-surface p-4 shadow-card sm:p-5"
    >
      <div>
        <h2 id="campaign-run" className="flex items-center gap-2 text-[13px] font-medium text-ink-muted">
          {calling ? <LiveDot /> : null}
          {live ? "Right now" : "Progress"}
        </h2>
        <p role="status" className="mt-1 text-body font-medium text-ink">
          {/* The one "working now" line on this screen gets the shimmer, and only while
              calls are actually in progress; a pause or a wait is plain text. */}
          <span className={calling ? "text-shimmer" : undefined}>{runSentence(progress, run)}</span>
        </p>
      </div>

      <div className="space-y-2">
        <p className="flex flex-wrap items-baseline gap-x-2 text-ink">
          <FlashValue value={String(run.called)} className="text-[2.25rem] font-semibold leading-none tracking-tight tabular-nums">
            {formatCount(run.called)}
          </FlashValue>
          <span className="text-body text-ink-muted">
            of {formatCount(run.callable)} {run.callable === 1 ? "person" : "people"} called
          </span>
        </p>
        <ProgressBar
          value={run.called}
          max={Math.max(run.callable, 1)}
          label="Called at least once"
          completeLabel="Everyone has been called"
        />
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-t border-line pt-4 md:grid-cols-4">
        {live ? (
          <>
            <LinesInUse progress={progress} onCallNow={run.onCallNow} />
            <Fact
              label="Next try"
              value={run.retriesWaiting > 0 && run.nextRetryAt ? formatIST(run.nextRetryAt) : "None due"}
              hint={
                run.retriesWaiting > 0
                  ? `${formatCount(run.retriesWaiting)} waiting to be tried again`
                  : "Nobody is waiting for another try"
              }
              flash={run.nextRetryAt ?? ""}
            />
            <Fact label="Not called yet" value={formatCount(run.notCalled)} flash={String(run.notCalled)} />
            <Fact label="Spoke to your agent" value={formatCount(run.spoke)} flash={String(run.spoke)} />
          </>
        ) : (
          <>
            <Fact label="Spoke to your agent" value={formatCount(run.spoke)} />
            <Fact label="Never reached" value={formatCount(Math.max(0, run.callable - run.spoke))} />
            <Fact label="Started" value={formatIST(progress.launched_at)} />
          </>
        )}
      </dl>

      <div className={`grid grid-cols-1 gap-x-10 gap-y-5 border-t border-line pt-4 ${onCall ? "lg:grid-cols-2" : ""}`}>
        {onCall ? <OnACallNow campaignId={campaignId} count={run.onCallNow} /> : null}
        <div className="min-w-0">
          <h3 className="mb-1 text-[13px] font-medium text-ink-muted">Steps</h3>
          <TaskSteps size="md" steps={run.steps} current={run.current} hold={run.hold} label="Where this campaign is" />
        </div>
      </div>
    </section>
  );
}

function Fact({ label, value, hint, flash }: { label: string; value: string; hint?: string; flash?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[13px] text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-body font-semibold tabular-nums text-ink">
        {flash === undefined ? value : <FlashValue value={flash}>{value}</FlashValue>}
        {hint ? <span className="block text-meta font-normal text-ink-muted">{hint}</span> : null}
      </dd>
    </div>
  );
}

/**
 * Calls going out now against the most this campaign may have at once
 * (`effective_concurrency`: its own setting under the plan's ceiling, the lines kept free
 * for callers and the account's call lines). One slot per allowed call, so a full row reads as "at the limit"
 * without a number; the number is there too, because the slots are not read aloud.
 */
function LinesInUse({ progress, onCallNow }: { progress: CampaignProgress; onCallNow: number }) {
  const allowed = Math.max(0, progress.effective_concurrency);
  const filled = Math.min(onCallNow, allowed);
  const limited = progress.effective_concurrency < progress.concurrency;
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-[13px] text-ink-muted">
        Calls at once
        {limited ? (
          <InfoTip label="Calls at once" align="start">
            <AtOnceHint progress={progress} className="block" />
          </InfoTip>
        ) : null}
      </dt>
      <dd className="mt-0.5 text-body font-semibold tabular-nums text-ink">
        <FlashValue value={String(onCallNow)}>
          {formatCount(onCallNow)} of {formatCount(allowed)}
        </FlashValue>
        {allowed > 0 ? (
          <span aria-hidden className="mt-1.5 flex max-w-[10rem] gap-1">
            {Array.from({ length: allowed }, (_, slot) => (
              <span
                key={slot}
                className={`h-1.5 flex-1 rounded-full transition-colors duration-(--duration-fast) ${
                  slot < filled ? "bg-brand" : "bg-ink/[0.08]"
                }`}
              />
            ))}
          </span>
        ) : null}
      </dd>
    </div>
  );
}

/** Who is on the phone now, each with how long the call has run and a way into it. */
function OnACallNow({ campaignId, count }: { campaignId: string; count: number }) {
  const { session } = useClientRealm();
  const now = useCallingNow(session, campaignId, true);
  // The list is a moment behind the count; it says so rather than showing an empty box.
  if (now.error || !now.data || now.data.items.length === 0) {
    return (
      <div className="min-w-0 space-y-1">
        <h3 className="text-[13px] font-medium text-ink-muted">On a call now</h3>
        <p className="text-meta text-ink-muted">{now.error ? "Couldn't load who is on a call." : "Connecting…"}</p>
      </div>
    );
  }
  const people = now.data.items;
  return (
    <div className="min-w-0 space-y-1">
      <h3 className="text-[13px] font-medium text-ink-muted">On a call now</h3>
      <ul className="divide-y divide-line">
        {people.map((person) => (
          <OnACallRow key={person.id} person={person} />
        ))}
      </ul>
      {count > people.length ? (
        <p className="text-meta text-ink-muted">and {formatCount(count - people.length)} more</p>
      ) : null}
    </div>
  );
}

function OnACallRow({ person }: { person: ContactResult }) {
  const { session, href } = useClientRealm();
  const elapsed = useElapsedSeconds(person.last_attempt_at);
  const who = person.name?.trim() || formatPhone(person.phone_e164);
  return (
    <li className="flex items-center gap-3 py-2">
      <LiveDot />
      <div className="min-w-0 flex-1">
        <p className="truncate text-body font-medium text-ink">{who}</p>
        <p className="text-meta tabular-nums text-ink-muted">
          {person.name?.trim() ? `${formatPhone(person.phone_e164)} · ` : ""}
          {elapsed === null ? "Calling" : formatDuration(elapsed)}
        </p>
      </div>
      {person.call_id ? (
        <Link
          href={href(`/c/${session.orgSlug}/calls/${person.call_id}`)}
          className={SECONDARY_BUTTON_SM}
          aria-label={`Open the call with ${who}`}
        >
          <PhoneCall aria-hidden className="h-3.5 w-3.5" />
          Open call
        </Link>
      ) : null}
    </li>
  );
}
