"use client";

import { useState } from "react";
import {
  CheckCircle2,
  CircleHelp,
  Lock,
  PackageOpen,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import {
  Card,
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ScrollRegion,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useReplayOutbox } from "@/lib/api/admin";

import type { OpsAccess } from "./opsAccess";
import type { DeadLetterState } from "./opsSurfaceState";

/** `""` = the operator has not chosen yet; `"*"` = every job. Neither can collide with a
 *  real job name, which the API bounds to `^[a-z][a-z0-9_]*$`. */
const EVERY_JOB = "*";

/**
 * The outbox dead-letter queue: how deep it is, and its one lever —
 * `POST /v1/ops/outbox/replay`.
 *
 * `runbooks/webhook-delivery-failures.md` §3 and `campaign-escalation-refused.md` both end
 * at this endpoint with the instruction "never by hand", and until recently the only way
 * to reach it was by hand. It is cross-tenant: `replay_dead_letters` has no tenant
 * predicate at all (`outbox_messages` carries no `tenant_id`), so one click moves other
 * people's clients' messages.
 *
 * THE BLAST RADIUS IS REDELIVERY, not the flip. Every message it moves back to `pending`
 * gets a fresh attempt budget and will be delivered again — and a message can dead-letter
 * *after* its side effect landed, so "delivered twice" is the outcome to be sure about
 * before clicking, not the flag in the row.
 *
 * ## The depth, and why the panel changed shape around it
 *
 * This panel used to say, in its own words, that there was no count to show before the
 * click because no endpoint published one. So an operator confirmed a redelivery of
 * unknown size, unknown mix and unknown age — every other confirmation on this router
 * binds to something visible (a tenant id, a target mode, a direction), and this one named
 * an action whose scope was whatever the queue happened to hold. A confirmation you cannot
 * size is a habit, not a control.
 *
 * `GET /v1/ops/platform` now carries `outbox_dead_letters`, so the depth, the per-`job`
 * breakdown and the age of the oldest message are on screen BEFORE the confirmation. Four
 * consequences, each deliberate:
 *
 * 1. **A depth we could not read is not a zero.** The panel refuses to state one and says
 *    the confirmation is unsized — and the button STAYS ENABLED, because the lever must
 *    not disappear when the platform is behaving strangely. That is the same rule the
 *    gating already followed (this control is gated on the permission, never on the
 *    platform row); riding that read costs a NUMBER here, never the control.
 * 2. **A depth of 0 disables the button, with the reason beside it.** The objection is the
 *    load-shed panel's, one step earlier: the server would accept an empty replay and
 *    write an `ops.outbox_replay` audit row for a redelivery nobody performed. It is the
 *    console's guard alone — the API cannot refuse an empty queue without lying about the
 *    race between the check and the claim.
 * 3. **The panel still renders when the queue is empty.** The runbook sends operators here
 *    by name ("Console: Operations — /admin/ops → Dead-lettered outbox messages"), and a
 *    panel that vanished would make "the runbook is wrong" indistinguishable from "there
 *    is nothing parked".
 * 4. **The scope is chosen, not defaulted.** See the select below.
 */
export function OutboxReplayPanel({
  access,
  queue,
}: {
  access: OpsAccess;
  queue: DeadLetterState;
}) {
  const replay = useReplayOutbox();
  const [confirm, setConfirm] = useState("");
  // Opens on NO CHOICE, for the load-shed panel's reason applied to a bigger blast
  // radius: a select preloaded with "every job" would make "click the obvious button" a
  // cross-tenant redelivery of everything, chosen by nobody.
  const [scope, setScope] = useState("");

  const sized = queue.status === "read" ? queue.queue : null;
  const job = scope === "" || scope === EVERY_JOB ? null : scope;
  // Nothing to choose FROM when the queue could not be read, and nothing to choose
  // BETWEEN when it is empty — so in both cases the choice is not withheld and this term
  // stands aside. That is not tidiness: while it also covered the empty queue, two
  // independent guards produced one dead button, `replayable` was doing no work, and a
  // test asserting the empty-queue rule passed with that rule deleted (it was really
  // asserting the scope rule). One condition, one reason, one sentence under the button.
  const scopeChosen = sized === null || sized.depth === 0 || scope !== "";
  const replayable = queue.status === "unreadable" || (sized !== null && sized.depth > 0);
  // The permission is part of `ready` here rather than a second term at the button,
  // because the sentence under the button explains whichever condition is unmet and
  // "ready" must therefore mean the same thing as "the button is alive".
  const ready = access.allowed && replayable && scopeChosen && confirm === "REPLAY";

  const scopedDepth =
    job === null ? sized?.depth : sized?.by_job.find((entry) => entry.job === job)?.depth;

  // WHY the control is dead, in the order the operator can act on: their permission, then
  // ours to answer, then the queue's own answer. Rendered BESIDE the button — a reason a
  // screenful away from the control it explains is the defect §52 found on three screens.
  const deadReason = !access.allowed
    ? access.reason
    : queue.status === "loading"
      ? "Checking how many messages are stuck. The button unlocks once we know the size of the resend."
      : sized !== null && sized.depth === 0
        ? // THE ALL-CLEAR LIVES IN TWO PLACES, and only one of them was fixed first: the
          // green box above became conditional on `deferred` while this sentence — the one
          // physically next to the button, which is where an operator actually reads — went
          // on saying "nothing is stuck" during an outage. Caught by
          // `apps/web/tests/ops.test.tsx`, and worth the note: a panel with two voices needs
          // both of them changed, and the one beside the control is the one that counts.
          sized.deferred > 0
          ? `No message has failed yet, so there is nothing to resend — but ${formatCount(sized.deferred)} ` +
            "are waiting to retry on their own (shown above). Resending only helps messages that " +
            "have already failed; these need the queue to come back."
          : "Nothing is stuck, so there is nothing to resend. Running it anyway would record a " +
            "resend in the activity log that never actually happened."
        : !scopeChosen
          ? "Choose what to resend first. There is no default, because the default would be " +
            "the biggest possible action."
          : null;

  return (
    <Card title="Stuck outbound messages">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Messages that failed to send after several tries and are now stuck — things like
          a lead sent to a client&apos;s own system, or a hot-lead alert. Resending puts
          them back in line to be tried again, for every client at once, oldest first, up
          to 100 at a time.
        </p>

        {queue.status === "loading" && <Skeleton rows={2} />}

        {/* The refusal. NOT "0 parked" and NOT a hidden panel: an operator who cannot see
            the queue is exactly the one who must be told that the confirmation below is
            unsized, rather than reassured by a number nobody sent. */}
        {queue.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We do not know how many messages are stuck"
          >
            <p className="mt-1">
              The count is read together with the platform state, and that read failed — so
              this screen will not tell you nothing is stuck, and it will not tell you how
              large a resend would be. The error above says what stopped it.
            </p>
            <p className="mt-2">
              The button below still works. It will resend{" "}
              <span className="font-semibold">every type</span> — up to 100, oldest first.
            </p>
          </NoticeBox>
        )}

        {/* THE ALL-CLEAR, AND THE CASE THAT IS NOT ONE.
            `depth === 0` used to render "Nothing is dead-lettered" unconditionally, and
            during a queue outage that sentence was TRUE and the screen it produced was a
            lie: `defer_outbox_claim` holds a failing batch as `pending` with a lease into
            the future, so for the whole five minutes of tolerated downtime the DLQ really
            is empty while the backlog grows behind it. An operator opening this screen
            mid-incident read a green box. `deferred` is the same aggregate's answer to
            "and how many are waiting", so the tone follows the queue's actual health
            rather than the one state this panel happens to act on. */}
        {sized !== null && sized.depth === 0 && sized.deferred === 0 && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Nothing is stuck"
          >
            <p className="mt-1">
              No outbound message has failed, so there is nothing to resend and the button
              below is disabled. Refreshes every 30 seconds.
            </p>
          </NoticeBox>
        )}

        {/* Deferred messages are NOT this panel's lever — replay acts on `failed` rows
            only and would move none of them — so this box states the situation and
            explicitly says not to click, rather than implying the button is the answer. */}
        {sized !== null && sized.deferred > 0 && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title={`${formatCount(sized.deferred)} messages are waiting to retry on their own`}
          >
            <p className="mt-1">
              These are not stuck — the system will retry them by itself in a short while.
              A number here that keeps climbing means the whole queue is unreachable, not
              that any one message is bad; that&apos;s a separate alert, covered by the
              webhook-delivery runbook.
            </p>
            <p className="mt-2">
              Resending does nothing for these — it only acts on messages that have already
              failed. If they run out of automatic retries before the queue recovers, they
              become stuck, and then resending will apply.
            </p>
          </NoticeBox>
        )}

        {/* THE SIZE OF THE ACT, before the confirmation. The breakdown is the half a total
            cannot give: 142 CRM webhooks and 142 hot-lead emails are different things to
            re-send, and the oldest timestamp is what separates a retry from a client's CRM
            receiving a lead they closed last week. Counts and job names only — outbox
            payloads are JSONB carrying phone numbers and extraction output (hard rule 6),
            and the API publishes none of it. */}
        {sized !== null && sized.depth > 0 && (
          <NoticeBox
            tone="warn"
            icon={<PackageOpen aria-hidden className="h-5 w-5" />}
            title={`${formatCount(sized.depth)} messages are stuck`}
          >
            <p className="mt-1">
              Oldest: <span className="font-semibold">{formatIST(sized.oldest_at)}</span>.
              Resending sends them again; an old one may reach a client who has already
              dealt with it another way.
            </p>
            {/* The scroll container every other table in this repo already has. Its
                three columns (a job name, a count, an IST timestamp) do not fit 320px,
                and inside the shell's `overflow-hidden` the excess was CLIPPED rather
                than scrollable — the "Oldest" column was simply unreachable. */}
            <ScrollRegion label="Stuck message types" className="mt-3">
            <table className="w-full text-left text-xs">
              <thead className="text-ink-faint">
                <tr>
                  <th className="pb-1 font-medium">Type</th>
                  <th className="pb-1 text-right font-medium">Stuck</th>
                  <th className="pb-1 text-right font-medium">Oldest</th>
                </tr>
              </thead>
              <tbody>
                {sized.by_job.map((entry) => (
                  <tr key={entry.job}>
                    <td className="py-0.5 pr-2 font-mono">{entry.job}</td>
                    <td className="py-0.5 text-right tabular-nums">
                      {formatCount(entry.depth)}
                    </td>
                    <td className="py-0.5 pl-2 text-right">{formatIST(entry.oldest_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </ScrollRegion>
          </NoticeBox>
        )}

        {replay.error && <WriteFailure error={replay.error} actionLabel="Resend stuck messages" />}

        {/* The SERVER's count, rendered as the result it is. A toast would put the one
            number this control produces on a timer. */}
        {replay.data && (
          <NoticeBox
            tone={replay.data.replayed > 0 ? "ok" : "neutral"}
            icon={<RefreshCw aria-hidden className="h-5 w-5" />}
            title={
              replay.data.replayed > 0
                ? `${formatCount(replay.data.replayed)} messages queued to resend`
                : "Nothing was stuck"
            }
          >
            <p className="mt-1">
              {replay.data.replayed > 0
                ? "Each one gets a fresh set of attempts. Keep an eye on the count above rather than assuming they all land — the webhook-delivery runbook covers the follow-up."
                : "No message had failed, so nothing was resent."}
            </p>
            {/* The scope the SERVER applied, not the one this form thinks it sent: a
                `replayed: 0` under a mistyped job is an operator's typo, and reading it
                back is what makes that visible rather than "the queue was empty". */}
            <p className="mt-2 text-xs">
              Resent: <span className="font-mono">{replay.data.job ?? "every type"}</span>
            </p>
            {/* The run is capped at 100 (`replay_dead_letters`), so a full batch is the
                one result that does NOT mean the queue is now empty. */}
            {replay.data.replayed === 100 && (
              <p className="mt-2 font-semibold">
                That is the per-run limit, so there may be more waiting. Run it again.
              </p>
            )}
          </NoticeBox>
        )}

        <form
          className="space-y-3"
          // No constraint attributes here: the scope select and the typed word are gates,
          // not answers a rule can be read off. `noValidate` all the same, so no later
          // edit hands this form back to the browser.
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            replay.mutate(job, { onSuccess: () => setConfirm("") });
          }}
        >
          {/* THE SCOPE, offered only when we can enumerate it.
              `outbox_messages` has no `tenant_id` (infra table — the ids live inside the
              JSONB payload), so per-client scoping is impossible without a migration and
              `job` is the only bound available. It is not a consolation prize: the run
              takes the 100 OLDEST rows, so an operator recovering a client's webhooks out
              of a queue full of dead-lettered emails replays 100 emails, reads "100 moved"
              as success, and leaves every webhook parked. */}
          {sized !== null && sized.depth > 0 && (
            <label className="block">
              <span className={FIELD_LABEL}>What to resend</span>
              <select
                value={scope}
                onChange={(e) => {
                  setScope(e.target.value);
                  // The confirmation authorises THIS scope — the header carries it
                  // (`outboxReplayConfirmation`) — so a word typed for one selection must
                  // not survive a change of selection and submit against another.
                  setConfirm("");
                }}
                disabled={!access.allowed}
                className={FIELD}
              >
                <option value="">— choose —</option>
                <option value={EVERY_JOB}>
                  Every type — all {formatCount(sized.depth)} stuck messages
                </option>
                {sized.by_job.map((entry) => (
                  <option key={entry.job} value={entry.job}>
                    {entry.job} — {formatCount(entry.depth)} stuck
                  </option>
                ))}
              </select>
              <span className={FIELD_HINT}>
                Choosing a type limits what gets resent. It does not limit WHOSE — every
                type covers all clients at once, because these messages aren&apos;t split
                by client.
              </span>
            </label>
          )}

          <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
            <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
            <div className="min-w-0">
              <p className="font-semibold text-ink">
                This resends stuck messages for EVERY client, not one
              </p>
              <p className="mt-1 text-ink-muted">
                A message that actually reached its destination before it got stuck will be
                sent a second time — a duplicate WhatsApp alert, or a duplicate delivery to
                a client&apos;s own system. This can&apos;t be undone from here.
              </p>
              {/* What THIS submission will send, in numbers, immediately above the
                  confirmation it is asking for. */}
              {scopedDepth !== undefined && scopeChosen && (
                <p className="mt-1 font-semibold text-ink">
                  About to resend up to {formatCount(Math.min(scopedDepth, 100))} of the{" "}
                  {formatCount(scopedDepth)} stuck{" "}
                  {job !== null && (
                    <>
                      <span className="font-mono">{job}</span>{" "}
                    </>
                  )}
                  messages, oldest first.
                </p>
              )}
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the activity log with how many were resent and which type. The
                word you type below is also sent to confirm this exact action, so it
                can&apos;t be triggered from outside this form.
              </p>
            </div>
          </div>

          <label className="block">
            <span className={FIELD_LABEL}>Type REPLAY to confirm</span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed}
              placeholder="REPLAY"
              className={`${FIELD} font-mono`}
            />
          </label>

          <button
            type="submit"
            title={deadReason ?? undefined}
            disabled={!ready || replay.isPending}
            className={DANGER_BUTTON}
          >
            <RefreshCw aria-hidden className="h-4 w-4" />
            {replay.isPending ? "Resending…" : "Resend stuck messages"}
          </button>

          {deadReason && !ready && (
            <p className="flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {deadReason}
            </p>
          )}
        </form>
      </div>
    </Card>
  );
}
