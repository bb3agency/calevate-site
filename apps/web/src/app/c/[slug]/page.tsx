"use client";

import Link from "next/link";
import { use } from "react";
import {
  CheckCircle2,
  Clock,
  Flame,
  Moon,
  PhoneCall,
  Sparkles,
  Users,
} from "lucide-react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  Skeleton,
  StatTile,
  StatusBadge,
  formatCount,
  formatDuration,
  formatINR,
  formatIST,
} from "@/components/ui";
import { useCalls, useDashboard, useUsage } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/**
 * The client's home screen.
 *
 * EVERY NUMBER ON THIS PAGE COMES FROM THE API OR IS NOT SHOWN. That is the rule the
 * design pass has to survive, and it is not a style preference: the mock this was
 * built from carried a hardcoded "3,482 successful calls", a "$0.042 cost per call",
 * a seven-day chart of invented bars and an activity feed of American phone numbers,
 * and the previous wiring fell back to `?? 5430` when the request failed — so a
 * client whose calls had STOPPED would have seen a healthy dashboard. A number that
 * is sometimes real and sometimes decorative is worse than a blank: it teaches the
 * owner to trust the screen, and then lies to them on the one day it matters.
 *
 * The tiles the design asked for that the API cannot answer are ABSENT rather than
 * approximated — cost per call, active campaigns, booked appointments, conversion
 * rate, and the "+18.4% vs last week" deltas under every figure. Each is a real
 * question and each needs an endpoint; `docs/BUILD-LOG.md` records which.
 */
export default function DashboardPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const { session, href } = useClientRealm();
  const dashboard = useDashboard(session);
  const usage = useUsage(session);
  const recent = useCalls(session, { limit: 6 });

  if (dashboard.isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton rows={4} />
        <Skeleton rows={8} />
      </div>
    );
  }

  if (dashboard.error) {
    return <ProblemNotice error={dashboard.error} onRetry={() => void dashboard.refetch()} />;
  }

  const data = dashboard.data;

  return (
    <div className="space-y-6 pb-12">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Calls today"
          value={formatCount(data?.calls_today)}
          icon={<PhoneCall className="h-5 w-5" />}
          hint={`${formatCount(data?.calls_7d)} in the last 7 days`}
        />
        <StatTile
          label="Average call length"
          value={formatDuration(data?.avg_duration_s)}
          icon={<Clock className="h-5 w-5" />}
          hint="Completed calls only"
        />
        <StatTile
          label="New leads (7 days)"
          value={formatCount(data?.leads_new_7d)}
          icon={<Users className="h-5 w-5" />}
          hint={
            <Link href={href(`/c/${slug}/leads`)} className="underline hover:text-ink">
              Open leads
            </Link>
          }
        />
        <StatTile
          label="Hot leads waiting"
          value={formatCount(data?.hot_leads_open)}
          icon={<Flame className="h-5 w-5" />}
          tone="strong"
          hint="Interested and not yet won or lost"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <Card title="Where the calls went" bodyClassName="p-6">
            <OutcomeBreakdown outcomes={data?.outcome_split ?? {}} total={data?.calls_7d ?? 0} />
          </Card>
        </div>

        <div className="flex flex-col gap-4 lg:col-span-4">
          <StatTile
            label="Captured after hours"
            value={formatCount(data?.after_hours_captured_7d)}
            icon={<Moon className="h-5 w-5" />}
            hint={
              /* WHICH definition produced the number, straight from the field the API
                 added for exactly this reason. A tile that renders "14 captured after
                 hours" identically from a fact and from a 09:00–21:00 guess invites an
                 owner to trust a number we did not earn. */
              data?.after_hours_basis === "business_hours"
                ? "Using your recorded opening hours"
                : "Using 9am–9pm IST — add your opening hours for a real figure"
            }
          />
          <StatTile
            label="Spend this month"
            value={formatINR(usage.data?.overage_cost_inr)}
            icon={<Sparkles className="h-5 w-5" />}
            hint={
              usage.data
                ? `${usage.data.minutes_used} min used of ${formatCount(usage.data.included_minutes)} included`
                : undefined
            }
          />
          <SentimentSplit split={data?.sentiment_split ?? {}} />
        </div>
      </div>

      <Card
        title="Latest calls"
        action={
          <Link
            href={href(`/c/${slug}/calls`)}
            className="rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
          >
            View all
          </Link>
        }
        bodyClassName="p-2"
      >
        {recent.error ? (
          <ProblemNotice error={recent.error} onRetry={() => void recent.refetch()} />
        ) : recent.isLoading ? (
          <Skeleton rows={5} />
        ) : !recent.data?.length ? (
          <EmptyState
            title="No calls yet"
            hint="They appear here within a couple of minutes of the call ending."
          />
        ) : (
          <ul className="divide-y divide-line">
            {recent.data.map((call) => (
              <li key={call.id}>
                <Link
                  href={href(`/c/${slug}/calls/${call.id}`)}
                  className="flex items-center gap-4 rounded-lg px-4 py-3 hover:bg-black/[0.02] dark:hover:bg-white/[0.03]"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
                    {call.status === "completed" ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      <PhoneCall className="h-4 w-4" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    {/* MASKED, always. `caller_masked` is what the API sends and the
                        only thing this screen is allowed to render (hard rule 6) —
                        the mock printed full numbers here. */}
                    <span className="block truncate text-[13px] font-semibold text-ink">
                      {call.caller_masked ?? "Unknown number"}
                    </span>
                    <span className="block truncate text-[12px] text-ink-muted">
                      {call.agent_name ?? "—"} · {call.direction}
                    </span>
                  </span>
                  <span className="hidden sm:block">
                    <StatusBadge value={call.status} kind="call" />
                  </span>
                  <span className="w-20 shrink-0 text-right">
                    <span className="block text-[11px] font-medium text-ink-muted">
                      {formatDuration(call.duration_s)}
                    </span>
                    <span className="block text-[11px] text-ink-faint">
                      {formatIST(call.started_at)}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/**
 * The outcome mix, drawn as bars in the order the API sent.
 *
 * A bar per outcome rather than the design's seven-day stacked column chart, because
 * a day-by-day series is a different question and `/v1/dashboard` answers this one:
 * `outcome_split` is already a map of outcome to count over the same 7 days as every
 * other figure on this screen. Bars are drawn from the count, and each row prints its
 * own number beside the bar, so the chart is checkable rather than decorative.
 */
function OutcomeBreakdown({ outcomes, total }: { outcomes: Record<string, number>; total: number }) {
  const rows = Object.entries(outcomes).sort((a, b) => b[1] - a[1]);
  if (!rows.length) {
    return (
      <EmptyState
        title="No tagged outcomes in the last 7 days"
        hint="Every completed call is tagged automatically once its transcript is processed."
      />
    );
  }
  const largest = Math.max(...rows.map(([, count]) => count));
  return (
    <div className="space-y-3">
      <p className="text-[13px] text-ink-muted">
        {formatCount(total)} calls in the last 7 days.
      </p>
      {rows.map(([outcome, count]) => (
        <div key={outcome} className="flex items-center gap-3">
          <span className="w-40 shrink-0 truncate text-[13px] font-medium capitalize text-ink">
            {outcome.replace(/_/g, " ")}
          </span>
          <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-brand-soft dark:bg-white/5">
            <span
              className="block h-full rounded-full bg-brand"
              style={{ width: `${largest > 0 ? Math.round((count / largest) * 100) : 0}%` }}
            />
          </span>
          <span className="w-12 shrink-0 text-right text-[13px] font-semibold tabular-nums text-ink">
            {formatCount(count)}
          </span>
        </div>
      ))}
    </div>
  );
}

const SENTIMENT_TONES: Record<string, string> = {
  positive: "bg-brand",
  neutral: "bg-slate-300 dark:bg-slate-600",
  negative: "bg-rose-500",
};

function SentimentSplit({ split }: { split: Record<string, number> }) {
  const rows = Object.entries(split);
  const total = rows.reduce((sum, [, count]) => sum + count, 0);
  return (
    <Card title="How callers sounded" bodyClassName="p-5">
      {total === 0 ? (
        <p className="text-[13px] text-ink-muted">No scored calls in the last 7 days yet.</p>
      ) : (
        <div className="space-y-2">
          {rows.map(([mood, count]) => (
            <div key={mood} className="flex items-center gap-3">
              {/* `lookup`, not `SENTIMENT_TONES[mood]`: `mood` is a server-chosen
                  string, and a bare index reaches Object.prototype (src/lib/lookup.ts).
                  The type-aware guard in tests/wireLookupGuard.test.ts failed this line
                  as written, which is the guard doing its job on new code. */}
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${lookup(SENTIMENT_TONES, mood) ?? "bg-slate-300"}`}
              />
              <span className="flex-1 text-[13px] capitalize text-ink-muted">{mood}</span>
              <span className="text-[13px] font-semibold tabular-nums text-ink">
                {formatCount(count)}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
