"use client";

import Link from "next/link";
import { use, useState } from "react";

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
import { useCalls } from "@/lib/api/hooks";

const STATUSES = ["completed", "in_progress", "no_answer", "failed"] as const;

export default function CallsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const [status, setStatus] = useState<string | undefined>(undefined);
  const calls = useCalls(session, { status, limit: 100 });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Calls</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Caller numbers are masked here; open a call to see its details.
          </p>
        </div>
        <div className="flex gap-1">
          <FilterChip label="All" active={!status} onClick={() => setStatus(undefined)} />
          {STATUSES.map((s) => (
            <FilterChip
              key={s}
              label={s.replace(/_/g, " ")}
              active={status === s}
              onClick={() => setStatus(s)}
            />
          ))}
        </div>
      </div>

      {calls.error && <ProblemNotice error={calls.error} onRetry={() => calls.refetch()} />}

      <Card>
        {calls.isLoading ? (
          <Skeleton rows={6} />
        ) : calls.data?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800">
                  <th className="py-2 pr-3 font-medium">When</th>
                  <th className="py-2 pr-3 font-medium">Caller</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Length</th>
                  <th className="py-2 pr-3 font-medium">Outcome</th>
                  <th className="py-2 font-medium">Summary</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {calls.data.map((call) => (
                  <tr key={call.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <td className="whitespace-nowrap py-2 pr-3 text-xs text-slate-500">
                      {formatIST(call.started_at)}
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 tabular-nums text-slate-700 dark:text-slate-300">
                      {call.caller_masked ?? "—"}
                    </td>
                    <td className="py-2 pr-3">
                      <StatusBadge value={call.status} kind="call" />
                    </td>
                    <td className="py-2 pr-3 tabular-nums text-slate-600 dark:text-slate-400">
                      {formatDuration(call.duration_s)}
                    </td>
                    <td className="py-2 pr-3 text-slate-600 dark:text-slate-400">
                      {call.outcome_tag?.replace(/_/g, " ") ?? "—"}
                    </td>
                    <td className="max-w-md py-2">
                      <Link
                        href={href(`/c/${slug}/calls/${call.id}`)}
                        className="line-clamp-1 text-slate-700 hover:underline dark:text-slate-300"
                      >
                        {call.summary ?? "Open call"}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : calls.error ? null : (
          <EmptyState title="No calls match this filter" />
        )}
      </Card>
    </div>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? "rounded-full bg-slate-900 px-3 py-1 text-xs font-medium capitalize text-white dark:bg-slate-100 dark:text-slate-900"
          : "rounded-full border border-slate-200 px-3 py-1 text-xs font-medium capitalize text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
      }
    >
      {label}
    </button>
  );
}
