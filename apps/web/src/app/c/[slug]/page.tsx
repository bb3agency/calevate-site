"use client";

import Link from "next/link";
import { use } from "react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  Skeleton,
  StatTile,
  StatusBadge,
  formatDuration,
  formatIST,
} from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { useCalls, useDashboard } from "@/lib/api/hooks";

export default function DashboardPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const dashboard = useDashboard(session);
  const recent = useCalls(session, { limit: 8 });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Dashboard</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Live figures for the last 7 days. Updates automatically.
        </p>
      </div>

      {dashboard.error && <ProblemNotice error={dashboard.error} onRetry={() => dashboard.refetch()} />}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Calls today" value={dashboard.data?.calls_today} />
        <StatTile label="Calls (7d)" value={dashboard.data?.calls_7d} />
        <StatTile label="New leads (7d)" value={dashboard.data?.leads_new_7d} />
        <StatTile
          label="Hot leads open"
          value={dashboard.data?.hot_leads_open}
          hint="Owner is alerted within 2 minutes"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile
          label="Avg call length"
          value={formatDuration(dashboard.data?.avg_duration_s)}
        />
        {/* The after-hours number is the inbound receptionist's whole sales argument
            (D-38): calls the business would simply have missed. */}
        <StatTile
          label="Captured after hours"
          value={dashboard.data?.after_hours_captured_7d}
          hint="Outside 9:00–21:00 IST"
        />
        <StatTile
          label="Minutes this month"
          value={dashboard.data?.minutes_used_month ?? "—"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* `loading` is passed through rather than folded into the empty case: an
            absent split during the first fetch is "we don't know yet", and printing
            "No completed calls yet" for it is a claim about the business. */}
        <Card title="Sentiment (7d)">
          <Split
            data={dashboard.data?.sentiment_split}
            loading={dashboard.isLoading}
            empty="No completed calls yet."
          />
        </Card>
        <Card title="Outcomes (7d)">
          <Split
            data={dashboard.data?.outcome_split}
            loading={dashboard.isLoading}
            empty="No outcomes recorded yet."
          />
        </Card>
      </div>

      <Card
        title="Recent calls"
        action={
          <Link href={href(`/c/${slug}/calls`)} className="text-xs font-medium text-sky-700 hover:underline">
            View all
          </Link>
        }
      >
        {recent.isLoading ? (
          <Skeleton rows={4} />
        ) : recent.data?.length ? (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {recent.data.map((call) => (
              <li key={call.id} className="flex items-center gap-3 py-2 text-sm">
                <StatusBadge value={call.status} kind="call" />
                <Link
                  href={href(`/c/${slug}/calls/${call.id}`)}
                  className="flex-1 truncate text-slate-700 hover:underline dark:text-slate-300"
                >
                  {call.summary ?? `${call.direction} call`}
                </Link>
                <span className="tabular-nums text-xs text-slate-500">
                  {call.caller_masked ?? "—"}
                </span>
                <span className="w-24 text-right text-xs text-slate-500">
                  {formatIST(call.started_at)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No calls yet"
            hint="Calls appear here within two minutes of hanging up."
          />
        )}
      </Card>
    </div>
  );
}

function Split({
  data,
  loading,
  empty,
}: {
  data?: Record<string, number>;
  loading: boolean;
  empty: string;
}) {
  if (loading) return <Skeleton rows={3} />;
  const entries = Object.entries(data ?? {});
  if (!entries.length) return <EmptyState title={empty} />;
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  return (
    <ul className="space-y-2">
      {entries.map(([key, count]) => (
        <li key={key} className="text-sm">
          <div className="flex justify-between">
            <span className="capitalize text-slate-700 dark:text-slate-300">
              {key.replace(/_/g, " ")}
            </span>
            <span className="tabular-nums text-slate-500">{count}</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800">
            <div
              className="h-1.5 rounded-full bg-sky-500"
              style={{ width: `${Math.round((count / total) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
