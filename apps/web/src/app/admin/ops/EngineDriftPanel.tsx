"use client";

import { CheckCircle2, CircleHelp, TriangleAlert } from "lucide-react";

import { Card, NoticeBox, Skeleton, formatCount, formatIST } from "@/components/ui";

import type { EngineDriftState } from "./opsSurfaceState";

/**
 * What the voice platform is ACTUALLY running, versus what we published (D-123).
 *
 * ## Why this panel exists at all
 *
 * `publish_agent` reads the agent back and refuses a proven mismatch, so at the moment of
 * publishing, "live" means something. Two divergences appear AFTERWARDS and neither
 * involves any code of ours running: somebody edits the agent in the vendor's own
 * dashboard, or a publish fails on our side after the vendor committed. Both leave every
 * table we own agreeing with itself and wrong, and until the half-hourly sweep existed
 * they were found only by whoever thought to open one agent's screen.
 *
 * ## Three numbers, not one, and the middle one is the point
 *
 * `out_of_sync` is a PROVEN mismatch and is the only one that is an alarm. `undetermined`
 * is "we could not read the answer" — a vendor having a slow afternoon — and folding it
 * into the alarm would report a fleet of agents speaking unapproved scripts every time
 * the platform was briefly unreachable, which is a number an operator learns to ignore
 * inside a week. `never_checked` is the third: an agent nobody has swept must not be
 * counted as one we swept and liked.
 *
 * ## And the pulse, which is what stops this panel lying by omission
 *
 * If the cron dies, every count freezes and `out_of_sync: 0` reads as "all clear" forever.
 * `oldest_checked_at` is the only field here that can say "nobody is watching", so the
 * panel leads with it whenever it is missing or old rather than burying it in a footnote.
 *
 * ## No lever
 *
 * There is deliberately no "re-publish" button. Re-publishing over a drift overwrites
 * whatever the vendor's console was used to change — plausibly the correct emergency edit,
 * made while ours was the thing that was down — and offering that as one click from a
 * platform-wide summary is the worst possible way to make that decision. The route from
 * here is the agent's own screen, which carries the sentence saying what actually differs.
 */
export function EngineDriftPanel({ drift }: { drift: EngineDriftState }) {
  const read = drift.status === "read" ? drift.drift : null;
  // A platform whose sweep has never run is NOT the same as one whose sweep is healthy
  // and found nothing, and the difference is `oldest_checked_at`. Note this is true even
  // when `live_agents` is 0 — an empty platform has nothing to sweep, and saying "no
  // agent has drifted" there is accurate but says nothing about whether the job is alive.
  const swept = read !== null && read.oldest_checked_at !== null;

  return (
    <Card title="What the voice platform is running">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Every half hour a sweep reads live agents back off the voice platform and
          compares them with what we published. It only ever reads — an agent edited on the
          vendor&apos;s own console stays exactly as they left it.
        </p>

        {drift.status === "loading" && <Skeleton rows={2} />}

        {/* The refusal. NOT "0 drifted": an operator who cannot see this number is the one
            who most needs telling that nobody has checked. */}
        {drift.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We do not know what the voice platform is running"
          >
            <p className="mt-1">
              This is read with the platform state, and that read failed — so this screen
              will not tell you every agent is in sync. The error above says what stopped
              it.
            </p>
          </NoticeBox>
        )}

        {read !== null && !swept && (
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
            title="No agent has been checked yet"
          >
            <p className="mt-1">
              Nothing below is evidence: the counts are what the last check recorded, and it
              has not recorded anything. If this lasts more than half an hour, the check has
              stopped running and no agent on the platform is being watched.
            </p>
          </NoticeBox>
        )}

        {read !== null && read.out_of_sync > 0 && (
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
            title={`${formatCount(read.out_of_sync)} of ${formatCount(read.live_agents)} live agents are running something else`}
          >
            <p className="mt-1">
              Oldest divergence: <span className="font-semibold">{formatIST(read.oldest_drift_at)}</span>.
              These agents are answering callers with a script, greeting or voice other
              than the one we published. Open each agent to see what differs — publishing
              again from here would overwrite whatever was changed on the vendor&apos;s
              console.
            </p>
          </NoticeBox>
        )}

        {read !== null && swept && read.out_of_sync === 0 && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Every checked agent is running what we published"
          >
            <p className="mt-1">
              {read.undetermined > 0
                ? `${formatCount(read.undetermined)} could not be read back — that is the voice platform not answering, not a drifted agent, and it will be retried on the next sweep.`
                : "No divergence found."}
            </p>
          </NoticeBox>
        )}

        {read !== null && (
          <table className="w-full text-left text-xs">
            <tbody>
              <tr>
                <td className="py-0.5 text-ink-muted">Live agents</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.live_agents)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Running what we published</td>
                <td className="py-0.5 text-right tabular-nums">{formatCount(read.in_sync)}</td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Running something else</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.out_of_sync)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Could not be read back</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.undetermined)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Not yet checked</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.never_checked)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Oldest check</td>
                <td className="py-0.5 text-right">
                  {swept ? formatIST(read.oldest_checked_at) : "never"}
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}
