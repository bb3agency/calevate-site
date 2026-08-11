"use client";

import Link from "next/link";
import { use } from "react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  Skeleton,
  StatusBadge,
  formatDuration,
  formatIST,
} from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { useCall, useCallBack, useCallbackEligibility } from "@/lib/api/hooks";

export default function CallDetailPage({
  params,
}: {
  params: Promise<{ slug: string; callId: string }>;
}) {
  const { slug, callId } = use(params);
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const call = useCall(session, callId);
  const eligibility = useCallbackEligibility(session, callId);
  const callback = useCallBack(session, callId);

  if (call.isLoading) return <Skeleton rows={8} />;
  if (call.error) return <ProblemNotice error={call.error} onRetry={() => call.refetch()} />;
  if (!call.data) return <EmptyState title="Call not found" />;

  const detail = call.data;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link href={href(`/c/${slug}/calls`)} className="text-sm text-sky-700 hover:underline">
          ← Calls
        </Link>
        <StatusBadge value={detail.status} kind="call" />
        <span className="text-sm text-slate-500">
          {formatIST(detail.started_at)} · {formatDuration(detail.duration_s)} ·{" "}
          {detail.caller_masked ?? "—"}
        </span>
      </div>

      {callback.error && <ProblemNotice error={callback.error} />}

      {/* D-21 M2. Rendered whenever the API has an opinion — disabled WITH the reason
          rather than hidden, so "why can't I follow this up?" is answered on screen.
          The refusals are mostly protective (we have already followed up twice; the
          call is a fortnight old), and a client who cannot see them assumes a bug. */}
      {eligibility.data && (
        <Card title="Follow up">
          {callback.data?.status === "queued" ? (
            <p className="text-sm text-emerald-700 dark:text-emerald-400">
              Calling back now — follow-up #{callback.data.follow_up_number}. It will
              appear in your calls list in a moment.
            </p>
          ) : callback.data?.status === "blocked" ? (
            /* A refusal by the compliance gate comes back 200 with a reason, not as an
               error. Falling through to the enabled button rendered it as a no-op: the
               client presses "Call back", nothing visibly happens, and they press it
               again. The server has already recorded the answer against this call, so
               it says why instead of offering another attempt. */
            <p className="text-sm text-amber-700 dark:text-amber-400">
              {callback.data.blocked_reason ?? "This follow-up call was not allowed."}
              {callback.data.blocked_rule ? ` (${callback.data.blocked_rule})` : ""}
            </p>
          ) : eligibility.data.eligible ? (
            <div className="space-y-2">
              <p className="text-sm text-slate-600 dark:text-slate-400">
                Our agent will call back and pick up where this conversation stopped.
              </p>
              <button
                type="button"
                disabled={callback.isPending}
                onClick={() => callback.mutate()}
                className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
              >
                {callback.isPending ? "Calling…" : "Call back with AI"}
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {eligibility.data.reason}
              </p>
              <button
                type="button"
                disabled
                className="cursor-not-allowed rounded-md bg-slate-200 px-4 py-1.5 text-sm font-medium text-slate-500 dark:bg-slate-800"
              >
                Call back with AI
              </button>
            </div>
          )}
        </Card>
      )}

      {detail.summary && (
        <Card title="Summary">
          <p className="text-sm text-slate-700 dark:text-slate-300">{detail.summary}</p>
          <div className="mt-3 flex gap-4 text-xs text-slate-500">
            {detail.sentiment && <span>Sentiment: {detail.sentiment}</span>}
            {detail.outcome_tag && <span>Outcome: {detail.outcome_tag.replace(/_/g, " ")}</span>}
            {detail.lead_id && (
              <Link href={href(`/c/${slug}/leads`)} className="text-sky-700 hover:underline">
                View lead
              </Link>
            )}
          </div>
        </Card>
      )}

      {Object.keys(detail.extraction ?? {}).length > 0 && (
        <Card title="Captured details">
          {/* These keys are the agent's extraction schema (TRD §7) — the same
              definition that becomes the Leads table columns and the CSV export. */}
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {Object.entries(detail.extraction as Record<string, unknown>).map(([key, value]) => (
              <div key={key} className="flex justify-between gap-4 text-sm">
                <dt className="capitalize text-slate-500">{key.replace(/_/g, " ")}</dt>
                <dd className="font-medium text-slate-800 dark:text-slate-200">
                  {formatValue(value)}
                </dd>
              </div>
            ))}
          </dl>
          {!detail.extraction_valid && (
            <p className="mt-3 text-xs text-amber-700 dark:text-amber-400">
              Some fields could not be captured cleanly from this call.
            </p>
          )}
        </Card>
      )}

      <Card
        title="Transcript"
        action={
          // Hard rule 5 surfaced in the UI: the default view is redacted, and the
          // client should know it rather than wonder why a number looks odd.
          <span className="text-xs text-slate-500">
            Personal numbers are hidden. Ask your account manager for the full transcript.
          </span>
        }
      >
        {detail.transcript?.length ? (
          <ol className="space-y-3">
            {detail.transcript.map((turn) => (
              <li key={turn.idx} className="flex gap-3">
                <span
                  className={
                    turn.speaker === "agent"
                      ? "mt-0.5 w-16 shrink-0 text-xs font-medium text-sky-700"
                      : "mt-0.5 w-16 shrink-0 text-xs font-medium text-slate-500"
                  }
                >
                  {turn.speaker === "agent" ? "Agent" : "Caller"}
                </span>
                <p className="text-sm text-slate-700 dark:text-slate-300">{turn.text}</p>
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState
            title="No transcript yet"
            hint="Transcripts arrive a couple of minutes after the call ends."
          />
        )}
      </Card>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}
