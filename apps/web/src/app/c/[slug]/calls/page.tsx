"use client";

import Link from "next/link";
import { use, useState } from "react";
import { CheckCircle2, PhoneCall, PhoneMissed, XCircle } from "lucide-react";

import {
  Card,
  EmptyState,
  FilterChip,
  ProblemNotice,
  Skeleton,
  StatusBadge,
  formatCount,
  formatDuration,
  formatIST,
} from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { useCalls } from "@/lib/api/hooks";
import { lookup } from "@/lib/lookup";

/**
 * The call log — every call the agents took or placed, newest first.
 *
 * Restyled to the console's design language (globals.css tokens, `Card`, lucide
 * medallions) without changing what it fetches or what it filters on. Three things
 * that were wrong under the old styling and are fixed here rather than carried over:
 *
 * - It rendered its own `<h1>Calls</h1>`, and the app shell now renders the page title
 *   from the nav list. Two headings saying the same word is the visible half of a
 *   drift: rename the nav entry and the screen keeps arguing with it.
 * - The count of what you are looking at was nowhere on screen, so a filter that
 *   matched nothing and a filter that matched everything looked the same until you
 *   read the rows.
 * - The status filter offered four statuses out of the eight `calls.status` actually
 *   holds, with `busy`, `voicemail`, `queued` and `ringing` unreachable — a client
 *   looking for the calls that went to voicemail could not ask for them.
 *
 * WHAT IS NOT HERE, deliberately: any figure the API did not send. The summary column
 * shows `summary` as the API redacted it, the caller column shows `caller_e164` in
 * full, and a call with neither shows a dash rather than something invented to fill
 * the cell. The number and the summary are governed differently and always were: the
 * number is the client's own contact data (D-436), the summary is transcript-derived
 * prose and stays redacted.
 */

/**
 * The filter chips, and the icon each status wears in the row medallion.
 *
 * Grouped the way the dashboard's chart groups them and the way `StatusBadge` colours
 * them, so the three places a status appears on this product agree: a conversation
 * happened, the dial reached the network but not a person, the dial itself broke, or
 * it is still running.
 */
/** One page of the log — and the honesty threshold for the header count (CL1). */
const CALLS_PAGE_SIZE = 100;

const STATUS_FILTERS = [
  { value: "completed", label: "Completed" },
  { value: "no_answer", label: "No answer" },
  { value: "busy", label: "Busy" },
  { value: "voicemail", label: "Voicemail" },
  { value: "failed", label: "Failed" },
  { value: "in_progress", label: "In progress" },
] as const;

const STATUS_ICONS: Record<string, typeof PhoneCall> = {
  completed: CheckCircle2,
  no_answer: PhoneMissed,
  busy: PhoneMissed,
  voicemail: PhoneMissed,
  failed: XCircle,
};

const STATUS_MEDALLIONS: Record<string, string> = {
  // `text-brand-strong`, like the other thirty `bg-brand-soft` sites. `--brand` on
  // `--brand-soft` measures 3.08:1 and this pill carries TEXT, so AA wants 4.5:1;
  // `--brand-strong` gives 6.01:1 on the same ground. `tests/contrastTokens.test.ts`
  // pins the pairing so the next status colour cannot reintroduce it.
  completed: "bg-brand-soft text-brand-strong",
  no_answer: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400",
  busy: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400",
  voicemail: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400",
  failed: "bg-rose-50 text-rose-600 dark:bg-rose-950 dark:text-rose-400",
};

export default function CallsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const [status, setStatus] = useState<string | undefined>(undefined);
  const calls = useCalls(session, { status, limit: CALLS_PAGE_SIZE });

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          Open a call to see the transcript, recording and the details we captured.
        </p>
        {/* The denominator, so an empty screen is legibly "nothing matched this
            filter" rather than possibly "nothing loaded". Only once the query has
            answered — a count rendered from `data ?? []` while loading says 0 and
            then jumps, which reads as calls disappearing. */}
        {calls.data &&
          /* A full page is a statement about OUR QUERY, not their business: an account
             past 100 calls would read "100 calls" forever — the exact defect the leads
             screen's docstring names as the thing it fixed. Below the cap the length IS
             the total, so the plain count is honest there (ux-audit CL1). */
          (calls.data.length >= CALLS_PAGE_SIZE ? (
            <p className="text-sm text-ink-muted">
              Showing the{" "}
              <span className="font-semibold tabular-nums text-ink">
                {formatCount(calls.data.length)}
              </span>{" "}
              most recent{status ? ` matching “${status.replace(/_/g, " ")}”` : ""}
            </p>
          ) : (
            <p className="text-sm text-ink-muted">
              <span className="font-semibold tabular-nums text-ink">
                {formatCount(calls.data.length)}
              </span>{" "}
              {status ? `matching “${status.replace(/_/g, " ")}”` : "calls"}
            </p>
          ))}
      </div>

      <div className="flex flex-wrap gap-1.5">
        <FilterChip label="All" active={!status} onClick={() => setStatus(undefined)} />
        {STATUS_FILTERS.map((s) => (
          <FilterChip
            key={s.value}
            label={s.label}
            active={status === s.value}
            onClick={() => setStatus(s.value)}
          />
        ))}
      </div>

      {calls.error && <ProblemNotice error={calls.error} onRetry={() => void calls.refetch()} />}

      <Card bodyClassName="p-2">
        {calls.isLoading ? (
          <div className="p-4">
            <Skeleton rows={6} />
          </div>
        ) : /* `calls.error ? null` was the whole non-answer branch, and it left one non-
               answer uncovered: a query TanStack has PAUSED because the browser is offline
               reports `isLoading === false` AND `error === null` with no data, so the
               ternary walked past both arms and printed "No calls yet" to a client whose
               phone had lost signal. `!calls.data` is the test that separates an empty
               list the server sent from a list we never asked for. `null` still, not a
               notice: the `ProblemNotice` above this Card is this screen's whole refusal
               and a second one inside it would say the same thing twice — but under a
               PAUSE there is no error above, so this arm renders the sentence itself. */
        calls.error ? null : !calls.data ? (
          <div className="p-4">
            <ProblemNotice
              error={new Error("Your calls did not load.")}
              onRetry={() => void calls.refetch()}
            />
          </div>
        ) : calls.data.length ? (
          <ul className="divide-y divide-line">
            {calls.data.map((call) => {
              const Icon = lookup(STATUS_ICONS, call.status) ?? PhoneCall;
              return (
                <li key={call.id}>
                  <Link
                    href={href(`/c/${slug}/calls/${call.id}`)}
                    className="flex items-start gap-4 rounded-lg px-4 py-3 hover:bg-black/[0.02] dark:hover:bg-white/[0.03]"
                  >
                    <span
                      className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
                        // `lookup`, never `STATUS_MEDALLIONS[call.status]`: the status is
                        // a server-chosen string and a bare index reaches
                        // Object.prototype (src/lib/lookup.ts).
                        lookup(STATUS_MEDALLIONS, call.status) ??
                        "bg-black/5 text-ink-muted dark:bg-white/10"
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        {/* IN FULL. Ringing this person back is the only action this
                            row leads to, and a number nobody can read is not one
                            (D-436). NULL means the engine gave us no number for the
                            leg — not that we withheld it. */}
                        <span className="truncate text-sm font-semibold tabular-nums text-ink">
                          {call.caller_e164 ?? "Unknown number"}
                        </span>
                        <StatusBadge value={call.status} kind="call" />
                        {call.outcome_tag && (
                          <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[11px] font-semibold capitalize text-brand-strong">
                            {call.outcome_tag.replace(/_/g, " ")}
                          </span>
                        )}
                      </span>
                      {/* The summary as the API redacted it — `text_redacted`'s
                          treatment applies to derived prose too (crm/schemas.py). */}
                      <span className="mt-0.5 block truncate text-[13px] text-ink-muted">
                        {call.summary ?? "No summary yet"}
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-ink-faint">
                        {call.agent_name ?? "—"} · {call.direction}
                      </span>
                    </span>

                    <span className="shrink-0 text-right">
                      <span className="block text-[12px] font-medium tabular-nums text-ink-muted">
                        {formatDuration(call.duration_s)}
                      </span>
                      <span className="block whitespace-nowrap text-[11px] text-ink-faint">
                        {formatIST(call.started_at)}
                      </span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState
            title={status ? "No calls match this filter" : "No calls yet"}
            hint={
              status
                ? "Clear the filter to see everything."
                : "A call appears here within a couple of minutes of the caller hanging up."
            }
          />
        )}
      </Card>
    </div>
  );
}
