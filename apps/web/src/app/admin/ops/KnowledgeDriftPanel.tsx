"use client";

import { CheckCircle2, CircleHelp, TriangleAlert } from "lucide-react";

import { Card, NoticeBox, Skeleton, formatCount, formatIST } from "@/components/ui";

import type { KbDriftState } from "./opsSurfaceState";

/**
 * What the voice platform is ANSWERING FROM, versus what a human approved (D-158).
 *
 * ## Why this is a second panel and not two more rows on the first
 *
 * `EngineDriftPanel` above answers "is the agent configured as we published" — prompt,
 * greeting, voice. This answers a different question about a different object at the
 * vendor: which knowledge bases the agent can retrieve from. An agent can be perfectly in
 * sync on the first and be reading out a price list somebody pasted into Bolna's console,
 * and the two are measured by two sweeps on two schedules. Each therefore carries its OWN
 * `oldest_checked_at`: folding them would let a healthy agent sweep's timestamp vouch for
 * a knowledge sweep that had died, which is the exact lying-by-omission the pulse exists
 * to prevent.
 *
 * ## Why the approval gate makes this the more serious of the two
 *
 * FLOWS §7 puts a human in front of every word a knowledge base contains, because a client
 * editing what their agent says is a client editing a legal instrument — the agent speaks
 * on their behalf under their PE registration. Text added at the vendor has been through
 * no gate at all, and the agent will read it to callers.
 *
 * ## `undetermined` carries more weight here than on the agent panel
 *
 * An EMPTY knowledge listing is ambiguous between "the documents are gone" and "the
 * vendor's listing does not attribute rows to agents at all" (pilot gate 8, still open),
 * and the sweep refuses to guess. So a large `undetermined` here is a real, actionable
 * signal about the VENDOR — go and settle gate 8 — rather than a count of drifted clients.
 *
 * ## No lever, and the reason is stronger than on the panel above
 *
 * There is deliberately no "fix it" button. The repair a knowledge drift superficially
 * invites is a detach — an irreversible DELETE at the vendor of a document our tables, by
 * hypothesis, cannot describe. One click from a platform-wide summary would destroy the
 * only copy of text somebody added by hand, plausibly during an incident.
 */
export function KnowledgeDriftPanel({ drift }: { drift: KbDriftState }) {
  const read = drift.status === "read" ? drift.drift : null;
  // A platform whose sweep has never run is NOT the same as one whose sweep is healthy and
  // found nothing, and the difference is `oldest_checked_at`. True even when `live_agents`
  // is 0: an empty platform has nothing to sweep, and saying "no knowledge has drifted"
  // there is accurate and says nothing about whether the job is alive.
  const swept = read !== null && read.oldest_checked_at !== null;

  return (
    <Card title="What the voice platform is answering from">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Every hour a sweep reads live agents&apos; knowledge bases back off the voice
          platform and compares them with what was approved and published. It only ever
          reads — knowledge added on the vendor&apos;s own console stays exactly where it is.
        </p>

        {drift.status === "loading" && <Skeleton rows={2} />}

        {/* The refusal. NOT "0 drifted": an operator who cannot see this number is the one
            who most needs telling that nobody has checked. */}
        {drift.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We do not know what knowledge the voice platform is holding"
          >
            <p className="mt-1">
              This is read with the platform state, and that read failed — so this screen
              will not tell you every agent&apos;s knowledge is in sync. The error above
              says what stopped it.
            </p>
          </NoticeBox>
        )}

        {/* THE ENGINE HAS NO KNOWLEDGE BASE — checked BEFORE "nothing has been swept",
            because the two produce identical data and only one of them is a problem.
            `sweep_kb_drift` returns on its first line when the engine lacks the
            capability, so on Bolna (`BOLNA_CAPABILITIES.knowledge_base` is False, D-354)
            it records nothing on every run, for ever, by design. The warning below then
            told an operator "the reconciliation job is not running" — permanently, about
            a job running hourly at :23 and doing exactly the right thing. Found by
            walking the console: the panel had counts and a null pulse, which is the same
            shape a dead cron makes, and no way to tell them apart until the API grew
            `engine_supports_knowledge_base`. */}
        {read !== null && !read.engine_supports_knowledge_base && (
          <NoticeBox
            tone="neutral"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="This engine has no built-in knowledge base"
          >
            <p className="mt-1">
              There is nothing here for the sweep to watch, so it records nothing and the
              counts below stay at zero. Agents answer from the prompt they were published
              with, and the panel above is what watches that.
            </p>
          </NoticeBox>
        )}

        {read !== null && read.engine_supports_knowledge_base && !swept && (
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
            title="No agent's knowledge has been checked yet"
          >
            <p className="mt-1">
              Nothing below is evidence: the counts are what the last check recorded, and it
              has not recorded anything. If this lasts more than an hour, the knowledge check
              has stopped running and nobody is watching what the agents answer from.
            </p>
          </NoticeBox>
        )}

        {read !== null && read.out_of_sync > 0 && (
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
            title={`${formatCount(read.out_of_sync)} of ${formatCount(read.live_agents)} live agents hold knowledge we did not publish`}
          >
            <p className="mt-1">
              Oldest divergence: <span className="font-semibold">{formatIST(read.oldest_drift_at)}</span>.
              Either the platform is serving text that never went through approval, or a
              version we approved is no longer there. Open each agent&apos;s knowledge tab —
              removing a document from here would delete it at the vendor, and if it was
              added on their console this is the only copy.
            </p>
          </NoticeBox>
        )}

        {read !== null && swept && read.out_of_sync === 0 && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Every checked agent is answering from what we published"
          >
            <p className="mt-1">
              {read.undetermined > 0
                ? `${formatCount(read.undetermined)} could not be decided — either the voice platform did not answer, or it reported no knowledge for an agent that should have some and nothing proved its listing is per-agent. That is a question about the vendor, not a drifted client.`
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
                <td className="py-0.5 text-ink-muted">Holding what we published</td>
                <td className="py-0.5 text-right tabular-nums">{formatCount(read.in_sync)}</td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Holding something else</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.out_of_sync)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Could not be decided</td>
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
