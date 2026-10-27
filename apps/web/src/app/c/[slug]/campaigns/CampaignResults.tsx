"use client";

import Link from "next/link";

import { Metric, MetricRow } from "@/components/console/metric";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice, Skeleton, StatusBadge, formatCount, formatDuration, formatINR } from "@/components/ui";
import type { CampaignResults as Results, ContactOutcome } from "@/lib/api/campaigns";
import { outcomeLabel } from "@/lib/callReview";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/** The outcome of one person, in the owner's words. Shared with the people table. */
export const OUTCOME_WORDS: Record<ContactOutcome, string> = {
  connected: "Spoke to the agent",
  no_answer: "No answer",
  busy: "Busy",
  voicemail: "Voicemail",
  failed: "Call failed",
  do_not_call: "Do not call",
  calling: "Being called now",
  not_called: "Not called yet",
};

/** The order outcomes are listed in: reached first, then the ways a call can miss. */
export const OUTCOME_ORDER: ContactOutcome[] = [
  "connected",
  "no_answer",
  "busy",
  "voicemail",
  "failed",
  "do_not_call",
  "calling",
  "not_called",
];

const SENTIMENT_WORDS: Record<string, string> = {
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
};

function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

/**
 * WHAT THE CAMPAIGN ACHIEVED (FLOWS §5): reach, how the conversations went, leads, spend.
 *
 * Every figure is the server's (`GET /v1/campaigns/{id}/results`). The outcome list is a
 * labelled count with a hairline bar for its share of the list, the one encoding that
 * helps here (which way the misses went); there is no chart for a figure a number says.
 * Credit spent is the server's NUMERIC string, formatted, never parsed (hard rule 7), and
 * is absent for a role that may not see billing.
 */
export function CampaignResults({
  slug,
  campaignId,
  results,
}: {
  slug: string;
  campaignId: string;
  results: { data: Results | undefined; isLoading: boolean; error: unknown; refetch: () => void };
}) {
  const { href } = useClientRealm();
  if (results.isLoading) return <Skeleton rows={3} />;
  if (!results.data) {
    return (
      <ProblemNotice
        error={results.error ?? new Error("This campaign's results did not load.")}
        onRetry={() => results.refetch()}
      />
    );
  }
  const r = results.data;
  const tags = Object.entries(r.outcome_tags).sort((a, b) => b[1] - a[1]);
  const sentiment = Object.entries(r.sentiment).filter(([, n]) => n > 0);
  return (
    <div className="space-y-8">
      <MetricRow label="Campaign results">
        <Metric
          label="Picked up"
          value={r.pickup_rate === null ? "—" : percent(r.pickup_rate)}
          hint={
            r.tried
              ? `${formatCount(r.outcomes.connected ?? 0)} of ${formatCount(r.tried)} people called`
              : "Nobody has been called yet"
          }
        />
        <Metric
          label="Average call"
          value={formatDuration(r.average_call_s)}
          hint={`${formatCount(Math.round(r.talk_seconds / 60))} minutes talked in all`}
        />
        <Metric
          label="Leads"
          value={formatCount(r.leads)}
          hint={r.hot_leads ? `${formatCount(r.hot_leads)} hot` : "None marked hot yet"}
        />
        <Metric
          label="Credit spent"
          value={r.credits_spent_inr === null ? "—" : formatINR(r.credits_spent_inr)}
          hint={r.credits_spent_inr === null ? "Your role doesn't show billing" : "On this campaign's calls"}
        />
      </MetricRow>

      <div className="grid grid-cols-1 gap-10 md:grid-cols-2">
        <Section title="How the calls went" headingLevel={3}>
          <OutcomeBreakdown outcomes={r.outcomes} />
          {r.opt_outs > 0 && (
            <p className="mt-3 text-meta text-ink-muted">
              {formatCount(r.opt_outs)} {r.opt_outs === 1 ? "person" : "people"} asked not to be called again and
              {r.opt_outs === 1 ? " is" : " are"} on your do-not-call list.
            </p>
          )}
        </Section>

        <Section title="What the conversations came to" headingLevel={3}>
          {tags.length === 0 && sentiment.length === 0 ? (
            <p className="text-body text-ink-muted">Nothing yet. This fills in as calls are answered.</p>
          ) : (
            <div className="space-y-4">
              {tags.length > 0 && (
                <dl className="divide-y divide-line border-y border-line">
                  {tags.map(([tag, count]) => (
                    <div key={tag} className="flex items-baseline justify-between gap-3 py-2 text-body">
                      <dt className="text-ink">{outcomeLabel(tag) ?? tag}</dt>
                      <dd className="tabular-nums text-ink-muted">{formatCount(count)}</dd>
                    </div>
                  ))}
                </dl>
              )}
              {sentiment.length > 0 && (
                <p className="text-meta text-ink-muted">
                  Mood:{" "}
                  {sentiment.map(([s, n]) => `${lookup(SENTIMENT_WORDS, s) ?? s} ${formatCount(n)}`).join(" · ")}
                </p>
              )}
            </div>
          )}
        </Section>
      </div>

      <Answers results={r} />

      {r.recent_leads.length > 0 && (
        <Section
          title="Leads from this campaign"
          headingLevel={3}
          action={
            <span className="flex flex-wrap gap-x-4 gap-y-1">
              <Link href={href(`/c/${slug}/leads?campaign_id=${campaignId}`)} className={TEXT_ACTION}>
                All its leads
              </Link>
              <Link href={href(`/c/${slug}/calls?campaign_id=${campaignId}`)} className={TEXT_ACTION}>
                All its calls
              </Link>
            </span>
          }
        >
          <ul className="max-w-xl divide-y divide-line border-y border-line">
            {r.recent_leads.map((lead) => (
              <li key={lead.id} className="relative flex items-center justify-between gap-3 py-2.5 touch:py-3">
                <Link
                  href={href(`/c/${slug}/leads/${lead.id}`)}
                  className="min-w-0 truncate text-body font-medium text-ink after:absolute after:inset-0 hover:underline focus-visible:outline-none focus-visible:after:rounded-md focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-brand"
                >
                  {lead.name?.trim() || "Unnamed lead"}
                </Link>
                <StatusBadge value={lead.status} />
              </li>
            ))}
          </ul>
          {r.leads > r.recent_leads.length && (
            <p className="mt-2 text-meta text-ink-muted">
              Showing {formatCount(r.recent_leads.length)} of {formatCount(r.leads)}, hot leads first.
            </p>
          )}
        </Section>
      )}
    </div>
  );
}

/**
 * WHAT PEOPLE SAID (D-905): the agent's own outcomes over the answered calls, and each
 * choice the agent asks about, counted over the people it spoke to. "Not given" is shown
 * beside the choices so a short list of answers is not read as everyone's answer.
 */
function Answers({ results }: { results: Results }) {
  const outcomes = results.business_outcomes;
  const fields = results.fields.filter((field) => field.values.some((v) => v.count > 0) || field.not_captured > 0);
  if (outcomes.length === 0 && fields.length === 0) return null;
  return (
    <Section title="What people said" headingLevel={3}>
      <div className="grid grid-cols-1 gap-x-10 gap-y-6 md:grid-cols-2">
        {outcomes.length > 0 && (
          <CountList
            title="How the calls ended for you"
            rows={outcomes.map((o) => ({ key: o.key, label: o.label, count: o.count }))}
            rest={{ label: "None of these", count: results.business_outcomes_unset }}
          />
        )}
        {fields.map((field) => (
          <CountList
            key={field.key}
            title={field.label}
            rows={field.values.map((v) => ({ key: v.value, label: v.value, count: v.count }))}
            rest={{ label: "Not given", count: field.not_captured }}
          />
        ))}
      </div>
    </Section>
  );
}

function CountList({
  title,
  rows,
  rest,
}: {
  title: string;
  rows: { key: string; label: string; count: number }[];
  rest: { label: string; count: number };
}) {
  return (
    <div className="min-w-0 space-y-2">
      <h4 className="text-body font-semibold text-ink">{title}</h4>
      <dl className="divide-y divide-line border-y border-line">
        {rows.map((row) => (
          <div key={row.key} className="flex items-baseline justify-between gap-3 py-2 text-body">
            <dt className="min-w-0 break-words text-ink">{row.label}</dt>
            <dd className="shrink-0 tabular-nums text-ink-muted">{formatCount(row.count)}</dd>
          </div>
        ))}
        {rest.count > 0 && (
          <div className="flex items-baseline justify-between gap-3 py-2 text-body">
            <dt className="min-w-0 text-ink-muted">{rest.label}</dt>
            <dd className="shrink-0 tabular-nums text-ink-muted">{formatCount(rest.count)}</dd>
          </div>
        )}
      </dl>
    </div>
  );
}

/** The outcomes a call to a person can END in; "calling" and "not called" are progress. */
const ENDED: ContactOutcome[] = ["connected", "no_answer", "busy", "voicemail", "failed", "do_not_call"];

/** Each ended outcome's mark. Colour is never alone: every mark has its row and count. */
const OUTCOME_FILL: Record<ContactOutcome, string> = {
  connected: "bg-brand",
  no_answer: "bg-chart-neutral",
  busy: "bg-chart-neutral/70",
  voicemail: "bg-chart-neutral/45",
  failed: "bg-chart-warn",
  do_not_call: "bg-chart-danger",
  calling: "bg-ink/10",
  not_called: "bg-ink/10",
};

/**
 * WHERE THE CALLS ENDED, as one bar of the people reached so far split by outcome, with
 * the labelled counts under it (data-visualization: part of a whole is one stacked bar,
 * not eight bars that each start at zero). People not yet called are not in it: they are
 * the progress panel's subject, and mixed in here they made "Not called yet" the longest
 * bar on a running campaign's results.
 */
function OutcomeBreakdown({ outcomes }: { outcomes: Record<string, number> }) {
  const rows = ENDED.map((outcome) => ({ outcome, count: outcomes[outcome] ?? 0 })).filter((row) => row.count > 0);
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  if (total === 0) return <p className="text-body text-ink-muted">Nobody has been called yet.</p>;
  return (
    <div className="space-y-3">
      <div aria-hidden className="flex h-2.5 gap-px overflow-hidden rounded-full bg-ink/[0.06]">
        {rows.map((row) => (
          <span key={row.outcome} className={`h-full ${OUTCOME_FILL[row.outcome]}`} style={{ flexGrow: row.count, flexBasis: 0 }} />
        ))}
      </div>
      <dl className="divide-y divide-line border-y border-line">
        {rows.map((row) => (
          <div key={row.outcome} className="flex items-center justify-between gap-3 py-2 text-body">
            <dt className="flex items-center gap-2 text-ink">
              <span aria-hidden className={`size-2.5 shrink-0 rounded-[3px] ${OUTCOME_FILL[row.outcome]}`} />
              {OUTCOME_WORDS[row.outcome]}
            </dt>
            <dd className="tabular-nums text-ink-muted">
              {formatCount(row.count)}
              <span className="ml-2 inline-block w-10 text-right text-meta">{Math.round((row.count / total) * 100)}%</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
