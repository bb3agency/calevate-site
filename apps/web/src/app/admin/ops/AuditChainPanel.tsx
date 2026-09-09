"use client";

import { CheckCircle2, FileSearch, Lock, ShieldAlert } from "lucide-react";

import {
  Card,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useVerifyAuditChain } from "@/lib/api/admin";

import type { OpsAccess } from "./opsAccess";

/**
 * The audit hash chain, verified on demand — `GET /v1/ops/audit/verify`.
 *
 * Three things make this panel different from every other control on the screen:
 *
 * 1. **It writes nothing, so it takes no typed confirmation.** The confirmations here
 *    exist to stop an accidental CHANGE; demanding one to run a read would be friction
 *    whose only lesson is that confirmations are things you type past.
 * 2. **A failure is an INCIDENT and is rendered as one.** `audit_log` is INSERT-only
 *    (hard rule 4) and each row's hash covers the previous one, so a broken link means a
 *    row was edited, deleted or reordered — evidence of tampering, or of a writer that
 *    bypassed `write_audit`. That does not belong in a toast that fades: it stays on
 *    screen, in the stop palette, naming the entry.
 * 3. **What it does NOT prove is on screen too.** The verdict now travels with its
 *    SCOPE — `entries_checked`, the `at` range, and `complete`, which is true only when
 *    the walk reached the end of the log. This copy used to hard-code "the oldest 1,000
 *    entries" because the route walked a fixed limit and published no scope, so the
 *    console had to compensate in prose. That prose outlived the limit and became false
 *    in the other direction, which is the argument for rendering the server's own
 *    numbers rather than a sentence about them: a fixed string cannot track a fix.
 *
 * The verdict is stamped with the moment it was asked for, because a verification carries
 * an implicit "as of", and one left on screen while an operator works elsewhere is
 * otherwise indistinguishable from a live one.
 */
/**
 * The weakly-attested era, rendered beside the verdict rather than under it.
 *
 * `entries_under_retired_key` is NOT a break and is not a component of `ok` — those
 * entries hash correctly. What they lack is attestation STRENGTH: on most deployments
 * they are the rows written before `AUDIT_CHAIN_SECRET` was required, when the chain
 * was signed with a constant that was printed in the source, so anyone who could read
 * the repository could have produced a row that verifies. That distinction only matters
 * at one moment — when an operator exports this log as evidence — and a caveat that
 * lives in a runbook reaches nobody at that moment.
 *
 * It renders on the intact verdict AND on the failed one, because the two facts are
 * independent: a log can be unbroken and still partly weakly attested, and a log with a
 * break has the same era question about everything either side of it.
 */
function WeaklyAttestedNote({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <p className="mt-2">
      <span className="font-semibold">
        {formatCount(count)} {count === 1 ? "entry" : "entries"} verified under a retired
        signing key.
      </span>{" "}
      Those rows are intact — they are not tampered with — but they were signed before this
      deployment had its own private signing key, when the key was a value anyone with the
      source code could read. Treat them as weaker evidence than the rest: if you are
      exporting this log for a dispute or an audit, say where that earlier period ends.
    </p>
  );
}

export function AuditChainPanel({ access }: { access: OpsAccess }) {
  const verify = useVerifyAuditChain();
  const asOf = verify.data ? formatIST(new Date(verify.submittedAt).toISOString()) : null;

  return (
    <Card title="Activity-log tamper check">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Every entry in the activity log is sealed against the one before it, so any entry
          that was edited, deleted or reordered shows up as a broken seal. This re-checks
          the whole log and reports every break, not just the first — it&apos;s the check
          behind the quarterly compliance review, and the one to run when a client disputes
          a record.
        </p>

        {verify.error && <ProblemNotice error={verify.error} />}

        {/* `ok === false` is not a failed REQUEST — the request succeeded and the answer
            is bad. Rendering it as an error notice would file it under "try again". */}
        {verify.data && !verify.data.ok && (
          <NoticeBox
            tone="stop"
            icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
            title="TAMPER CHECK FAILED"
          >
            <p className="mt-1">
              {verify.data.breaks_found === 1
                ? "The seal is broken in one place."
                : `The seal is broken in ${formatCount(verify.data.breaks_found)} places.`}{" "}
              The check did not stop at the first — it carried on to the end, so what follows
              covers the whole log, not just the part before the earliest break.
            </p>
            {/* Every break, dated and typed. A single line naming only the first is how a
                historical break — which an append-only ledger can never repair — hides
                tonight's, and how an attacker buys silence on the recent past by damaging
                something old. `at` is what lets an operator tell those two apart. */}
            {verify.data.breaks.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {verify.data.breaks.map((entry) => (
                  <li key={entry.entry_id} className="text-sm">
                    <span className="font-mono font-semibold">{entry.entry_id}</span>
                    {" — "}
                    {entry.kind === "content"
                      ? "its own fields no longer hash to its recorded hash (edited)"
                      : "it names the wrong predecessor (deleted or reordered)"}
                    {", "}
                    {formatIST(entry.at)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2">
                The server reported a break at{" "}
                <span className="font-mono font-semibold">
                  {verify.data.first_bad_entry_id ?? "an entry it did not name"}
                </span>{" "}
                without listing it.
              </p>
            )}
            {verify.data.breaks_found > verify.data.breaks.length && (
              <p className="mt-2">
                Only the first {formatCount(verify.data.breaks.length)} are listed;{" "}
                {formatCount(verify.data.breaks_found - verify.data.breaks.length)} more
                were found. At this scale the count matters more than the individual rows —
                query the activity log directly.
              </p>
            )}
            <p className="mt-2">
              <span className="font-semibold">Treat this as an incident.</span> The activity
              log is add-only — entries are never meant to change — so a broken seal means an
              entry was edited, deleted or reordered in the database. Do not re-run and move
              on: note the entry IDs above, and do not let anyone &quot;repair&quot; the
              rows — the break itself is the evidence.
            </p>
            <WeaklyAttestedNote count={verify.data.entries_under_retired_key} />
            <p className="mt-2 text-xs">
              {verify.data.complete
                ? `Whole log checked — ${formatCount(verify.data.entries_checked)} entries. Checked at ${asOf}.`
                : `Covers ${formatCount(verify.data.entries_checked)} entries only, so there may be more beyond them. Checked at ${asOf}.`}
            </p>
          </NoticeBox>
        )}

        {verify.data?.ok && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="No tampering found in the entries checked"
          >
            <p className="mt-1">
              Every seal checked out, so nothing in that range was edited, deleted or
              reordered.
            </p>
            {/* The scope, beside the green box rather than in a tooltip: this is what
                stops "verified" being read as "the whole log is verified". It is the
                server's own count and range — an incomplete walk must never be allowed
                to read like a full audit. */}
            <p className="mt-2">
              {verify.data.complete
                ? `Whole log checked — ${formatCount(verify.data.entries_checked)} entries, from the first row to the last.`
                : `This covers ${formatCount(verify.data.entries_checked)} entries only, so it says nothing about the rest of the log.`}
            </p>
            <WeaklyAttestedNote count={verify.data.entries_under_retired_key} />
            <p className="mt-2 text-xs">Checked at {asOf}.</p>
          </NoticeBox>
        )}

        <div>
          <button
            type="button"
            title={access.reason ?? undefined}
            disabled={!access.allowed || verify.isPending}
            onClick={() => verify.mutate()}
            className={SECONDARY_BUTTON}
          >
            <FileSearch aria-hidden className="h-4 w-4" />
            {verify.isPending ? "Checking…" : "Run the tamper check"}
          </button>
          <p className="mt-2 text-xs text-ink-faint">
            This only reads and reports — it changes nothing.
          </p>
          {!access.allowed && access.reason && (
            <p className="mt-2 flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {access.reason}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
