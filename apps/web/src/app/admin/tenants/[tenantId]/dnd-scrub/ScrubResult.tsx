"use client";

import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { NoticeBox, formatIST, formatWholeCount } from "@/components/ui";
import { Metric } from "@/components/console/metric";
import type { PreferenceScrubOut } from "@/lib/api/preferenceScrub";

/** What the recording did — whether the gate is now satisfied, and the counts. */
export function ScrubResult({ result }: { result: PreferenceScrubOut }) {
  return (
    <NoticeBox
      tone={result.is_current ? "ok" : "warn"}
      icon={
        result.is_current ? <CheckCircle2 className="h-5 w-5" /> : <AlertTriangle className="h-5 w-5" />
      }
      title={
        result.is_current
          ? "Recorded — this campaign may launch"
          : "Recorded, but it does NOT open the gate"
      }
    >
      <p className="mt-1 text-xs opacity-90">
        {/* A REPLAY is neither a failure nor a second run: `recorded: false` means this
            provider and reference were already on file. Either extreme sends the operator
            the wrong way — to record it again, or to believe they filed a second piece of
            evidence. */}
        {result.recorded
          ? "This run is now on file."
          : "That provider and reference were already on file, so nothing new was written — the suppression was re-applied to be sure."}{" "}
        {result.is_current ? (
          <>
            Valid until <span className="font-medium">{formatIST(result.expires_at)}</span> —
            midnight IST. The campaign keeps dialling past that moment, so a run recorded
            today does not cover tomorrow&apos;s dialling, and the dispatch tick will hold it
            again in the morning.
          </>
        ) : (
          <>
            It was run on <span className="font-medium">{formatIST(result.scrubbed_at)}</span>{" "}
            and expired at <span className="font-medium">{formatIST(result.expires_at)}</span>.
            It is kept as the historical record it is, and the campaign stays held: ask the
            provider for a scrub run TODAY and record that one.
          </>
        )}
      </p>
      {/* `submitted` is the SERVER's count of contacts pending when the run was recorded,
          never a figure typed off the provider's report. */}
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="On the list" value={formatWholeCount(String(result.submitted))} />
        <Metric label="Suppressed" value={formatWholeCount(String(result.suppressed))} />
        <Metric label="Not on this list" value={formatWholeCount(String(result.unmatched))} />
        <Metric label="Unreadable" value={formatWholeCount(String(result.malformed))} />
      </div>
      {result.malformed > 0 && (
        <p className="mt-2 text-xs opacity-90">
          {formatWholeCount(String(result.malformed))} of the numbers you pasted could not be
          read as phone numbers, so they suppressed nothing. Check the report for a header row
          or a truncated column, and record the remainder under a second reference.
        </p>
      )}
      {result.unmatched > 0 && (
        <p className="mt-2 text-xs opacity-90">
          {formatWholeCount(String(result.unmatched))} were readable but are not pending on this
          campaign — already dialled, or on a different list. That is ordinary; it is shown so
          the totals add up.
        </p>
      )}
    </NoticeBox>
  );
}
