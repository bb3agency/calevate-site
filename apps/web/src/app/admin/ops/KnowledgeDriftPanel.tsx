"use client";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import {
  MonoValue,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { lookup } from "@/lib/lookup";
import { useKbOrphanCheck, type KbOrphanReport } from "@/lib/api/opsKbOrphans";

import type { KbDriftState } from "./opsSurfaceState";

/**
 * What the voice platform is ANSWERING FROM, versus what a human approved (D-158).
 *
 * ## Why this is a second panel and not two more rows on the first
 *
 * `EngineDriftPanel` above answers "is the agent configured as we published" — prompt,
 * greeting, voice. This answers a different question about a different object: which
 * knowledge bases the agent can retrieve from. An agent can be perfectly in sync on the
 * first and be reading out a price list somebody pasted into the platform's own console,
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
    <section aria-labelledby="kb-drift-heading" className="space-y-3">
      <div className="flex items-center gap-1">
        <h3 id="kb-drift-heading" className="text-body font-semibold text-ink">
          What it is answering from
        </h3>
        <InfoTip label="Knowledge drift">
          <p>
            Every hour a sweep reads live agents&apos; knowledge bases back off the voice
            platform and compares them with what was approved and published. It only ever
            reads &mdash; whatever knowledge is on the platform now is still there after the
            sweep.
          </p>
        </InfoTip>
      </div>
      <div className="space-y-3">

        {drift.status === "loading" && <Skeleton rows={2} />}

        {/* The refusal. NOT "0 drifted": an operator who cannot see this number is the one
            who most needs telling that nobody has checked. */}
        {drift.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            title="We do not know what knowledge the voice platform is holding"
          >
            <p>Sync is unknown, not confirmed. The error above says why.</p>
          </NoticeBox>
        )}

        {/* THE ENGINE HAS NO KNOWLEDGE BASE — checked BEFORE "nothing has been swept",
            because the two produce identical data and only one of them is a problem.
            `sweep_kb_drift` returns on its first line when the engine lacks the
            capability, so on such an engine it records nothing on every run, for ever, by
            design. Every engine `Settings.engine` can name declares one today
            (`calevate_shared.config.EngineName` — `thinnest`, `fake`; each adapter's
            `*_CAPABILITIES.knowledge_base` is `True`), so this notice is currently
            unreachable. It STAYS rather than being deleted:
            the field is on the wire precisely so the screen reads the engine's own answer
            instead of a value typed here, and a capability that flipped True once can flip
            back. Before the field existed, the warning below
            told an operator "the reconciliation job is not running" — permanently, about
            a job running hourly at :23 and doing exactly the right thing. Found by
            walking the console: the panel had counts and a null pulse, which is the same
            shape a dead cron makes, and no way to tell them apart until the API grew
            `engine_supports_knowledge_base`. */}
        {read !== null && !read.engine_supports_knowledge_base && (
          <NoticeBox
            tone="neutral"
            title="This engine has no built-in knowledge base"
          >
            <p>The counts below stay at zero. The configuration check beside this one watches the prompt.</p>
          </NoticeBox>
        )}

        {read !== null && read.engine_supports_knowledge_base && !swept && (
          <NoticeBox
            tone="warn"
            title="No agent's knowledge has been checked yet"
          >
            <p>The counts below are not evidence yet. After an hour, the knowledge check has stopped running.</p>
          </NoticeBox>
        )}

        {read !== null && read.out_of_sync > 0 && (
          <NoticeBox
            tone="warn"
            title={`${formatCount(read.out_of_sync)} of ${formatCount(read.live_agents)} live agents hold knowledge we did not publish`}
          >
            <p className="mt-1">
              Oldest divergence: <span className="font-semibold">{formatIST(read.oldest_drift_at)}</span>.
              Open each agent&apos;s knowledge tab.{" "}
              <InfoTip label="drifted knowledge">
                Either the platform serves text that never went through approval, or a version we
                approved is gone. Removing a document from here deletes it at the vendor, and if
                it was added on their console that is the only copy.
              </InfoTip>
            </p>
          </NoticeBox>
        )}

        {read !== null && swept && read.out_of_sync === 0 && (
          <NoticeBox
            tone="ok"
            title="Every checked agent is answering from what we published"
          >
            <p className="mt-1">
              {read.undetermined > 0
                ? `${formatCount(read.undetermined)} could not be decided: the platform did not answer, or listed no knowledge for an agent that should have some. A vendor question, not a drifted client.`
                : "No divergence found."}
            </p>
          </NoticeBox>
        )}

        {read !== null && (
          <table className="w-full text-left text-meta">
            <caption className="sr-only">Live agents by knowledge check</caption>
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

        <AccountKnowledgeCheck />
      </div>
    </section>
  );
}

/** What each finding means, in the words `engine_kb_orphans_detected`'s runbook row uses. */
const ORPHAN_VERDICTS: Record<string, string> = {
  unrecorded: "Named like ours, but no record of ours claims it (a publish that rolled back)",
  unclaimed: "Nothing attributes it (a hand-made upload, or older than our naming)",
  stranded: "We believe it is live and the platform does not hold it (needs a republish)",
};

/**
 * The account-level cross-check (`GET /v1/ops/kb-orphans`), run only when asked: it walks
 * the voice platform's whole account, so it never runs on mount or on a poll. Read-only,
 * like the sweep above: nothing here deletes anything, and the runbook row for
 * `engine_kb_orphans_detected` says how to decide each finding.
 */
function AccountKnowledgeCheck() {
  const check = useKbOrphanCheck();
  const checkFeedback = useActionFeedback(check, { errorDisplay: "inline" });
  const report = check.data;

  return (
    <div className="space-y-2 border-t border-line pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-meta text-ink-muted">
          Knowledge the platform account holds that no client of ours claims.
        </p>
        <ActionButton
          variant="secondary-sm"
          status={checkFeedback.status}
          pendingLabel="Checking…"
          successLabel="Checked"
          onClick={() => checkFeedback.run()}
        >
          {report ? "Check again" : "Check the account"}
        </ActionButton>
      </div>
      {check.error && <ProblemNotice error={check.error} onRetry={() => checkFeedback.run()} />}
      {check.isPending && <Skeleton rows={2} />}
      {report && !check.isPending && <OrphanReport report={report} />}
    </div>
  );
}

function OrphanReport({ report }: { report: KbOrphanReport }) {
  if (!report.supported) {
    return (
      <p className="text-meta text-ink-muted">
        This engine keeps no account-level knowledge store, so there is nothing to walk.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {!report.listing_complete && (
        <NoticeBox
          tone="warn"
          title="The platform's listing could not be read to the end"
        >
          <p className="mt-1">
            The unclaimed and stranded counts below cannot be trusted.
            {report.listing_incomplete_reason ? ` Reason: ${report.listing_incomplete_reason}.` : ""}
          </p>
        </NoticeBox>
      )}
      <table className="w-full text-left text-meta">
        <caption className="sr-only">Platform account knowledge check</caption>
        <tbody>
          {(
            [
              ["Accounted for", report.accounted],
              ["Unrecorded", report.unrecorded],
              ["Unclaimed", report.unclaimed],
              ["Stranded", report.stranded],
            ] as const
          ).map(([label, value]) => (
            <tr key={label}>
              <td className="py-0.5 text-ink-muted">{label}</td>
              <td className="py-0.5 text-right tabular-nums">{formatCount(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {report.rows.length === 0 ? (
        <p className="text-meta text-ink-muted">No findings.</p>
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {report.rows.map((row, index) => (
            <li key={`${row.verdict}:${row.handle ?? row.source_id ?? index}`} className="py-2.5">
              <p className="text-meta font-medium capitalize text-ink">{row.verdict}</p>
              <p className="text-meta text-ink-muted">
                {lookup(ORPHAN_VERDICTS, row.verdict) ?? row.verdict}
              </p>
              <dl className="mt-1 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 text-meta">
                {row.handle && (
                  <>
                    <dt className="text-ink-muted">Handle</dt>
                    <dd className="min-w-0 break-all">
                      <MonoValue>{row.handle}</MonoValue>
                    </dd>
                  </>
                )}
                {row.tenant_id && (
                  <>
                    <dt className="text-ink-muted">Client</dt>
                    <dd className="min-w-0 break-all">
                      <MonoValue>{row.tenant_id}</MonoValue>
                    </dd>
                  </>
                )}
                {row.source_id && (
                  <>
                    <dt className="text-ink-muted">Source</dt>
                    <dd className="min-w-0 break-all">
                      <MonoValue>{row.source_id}</MonoValue>
                    </dd>
                  </>
                )}
                {row.created_at && (
                  <>
                    <dt className="text-ink-muted">Created</dt>
                    <dd>{formatIST(row.created_at)}</dd>
                  </>
                )}
              </dl>
            </li>
          ))}
        </ul>
      )}
      {report.truncated && (
        <p className="text-meta text-ink-muted">
          Showing the first {formatCount(report.rows.length)} of {formatCount(report.findings)}{" "}
          findings. The counts above are exact.
        </p>
      )}
    </div>
  );
}
