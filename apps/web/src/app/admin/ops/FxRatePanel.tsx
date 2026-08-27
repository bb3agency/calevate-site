"use client";

import { ArrowRightLeft, CircleHelp, TriangleAlert } from "lucide-react";

import {
  WithheldPanel,
  forbiddenReason,
  isForbidden,
} from "@/app/admin/withheld";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import {
  Card,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useFxRate, type FxRate } from "@/lib/api/opsFxRate";

/**
 * The exchange rate every dollar of vendor cost is converted at — what it is, how old it
 * is, and where it came from.
 *
 * ## Why an operator needs this screen at all
 *
 * Bolna and Azure invoice this business in dollars; every figure the platform records is
 * rupees. One multiplier stands between the two, and until it was pulled automatically it
 * was a number somebody typed months ago that quietly drifted with the market. The pull
 * fixed the drift and introduced a new way to be wrong — a feed that stops — so this panel
 * exists to make the second one visible. The question it answers in one line is: **is the
 * platform billing off a published rate right now, or off the typed fallback?**
 *
 * ## This panel computes nothing
 *
 * No arithmetic, no age, no staleness verdict. `state`, `using_fallback`, `age_label` and
 * every rate are the server's, printed as they arrive (`lib/api/opsFxRate.ts` carries the
 * argument). The one thing decided here is which sentence to show, and it is decided from
 * the server's own `state` rather than by re-testing a threshold this bundle would then
 * own a stale copy of.
 */

type FxState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "forbidden"; said: string | null }
  | { status: "read"; rate: FxRate };

export function fxRateState(query: {
  data: FxRate | undefined;
  error: unknown;
  isLoading: boolean;
}): FxState {
  if (isForbidden(query.error)) {
    return { status: "forbidden", said: forbiddenReason(query.error) };
  }
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  return { status: "read", rate: query.data };
}

/** The headline sentence, chosen from the SERVER's state and never re-derived. */
export function fxHeadline(rate: FxRate): {
  title: string;
  body: string;
  tone: "ok" | "warn";
} {
  if (rate.state === "live") {
    // The age clause is DROPPED rather than filled in when the server did not send one.
    // "fetched recently" would be this browser inventing a freshness claim, which is the
    // one sentence on this panel an operator would act on — and a missing age must never
    // render as a number either (a `0` here reads as "just now" and means "unknown").
    const when = rate.age_label ? `, fetched ${rate.age_label}` : "";
    return {
      tone: "ok",
      title: "Vendor costs are converting at the published rate",
      body: `Published by ${rate.published_source ?? "the rate source"} for ${rate.published_as_of ?? "an unknown date"}${when}.`,
    };
  }
  if (rate.state === "stale") {
    return {
      tone: "warn",
      title: "The published rate is too old to use",
      body: `The last one is from ${rate.published_as_of ?? "an unknown date"}, older than the ${rate.max_age_days}-day limit, so costs are converting at the fallback you set instead. Check that the rate pull is still running.`,
    };
  }
  return {
    tone: "warn",
    title: "No rate has been pulled yet",
    body: "Costs are converting at the fallback you set. This is normal for the first few minutes after a deploy; if it persists, the rate pull is not running.",
  };
}

export function FxRatePanel() {
  const query = useFxRate();
  const state = fxRateState(query);

  if (state.status === "forbidden") {
    return (
      <WithheldPanel
        title="Exchange rate"
        reason={
          state.said ??
          "The API refused this read: your admin account may not manage platform configuration."
        }
        subject="This panel would show the US dollar to rupee rate vendor costs are converted at, and how fresh it is."
      />
    );
  }

  return (
    <Card title="Exchange rate">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Your voice and model vendors bill in US dollars; everything you charge
          and record is in rupees. This is the rate in between. It is pulled
          automatically every five minutes from a published reference rate — the
          underlying rate itself is set once each business day — and the value
          you set under <MonoValue>usd_inr_rate</MonoValue> is the fallback used
          whenever a fresh one is not available.
        </p>

        {query.error && (
          <ProblemNotice error={query.error} onRetry={() => query.refetch()} />
        )}
        {state.status === "loading" && <Skeleton rows={3} />}

        {state.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We could not read the exchange rate"
          >
            <p className="mt-1">
              This panel will not show a rate it could not read — a made-up
              figure here reads exactly like a real one. The error above says
              what stopped the read. Billing itself is unaffected by this
              screen: the server keeps converting at whatever rate it last had.
            </p>
          </NoticeBox>
        )}

        {state.status === "read" && <FxRateBody rate={state.rate} />}
      </div>
    </Card>
  );
}

function FxRateBody({ rate }: { rate: FxRate }) {
  const headline = fxHeadline(rate);
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-line p-3">
        <div className="flex items-baseline gap-2">
          <ArrowRightLeft aria-hidden className="h-4 w-4 text-ink-faint" />
          <span className="text-sm text-ink-muted">
            1 {rate.base_currency} =
          </span>
          <MonoValue>{rate.effective_rate}</MonoValue>
          <span className="text-sm text-ink-muted">{rate.quote_currency}</span>
        </div>
        <p className="mt-1 text-sm text-ink-faint">
          {rate.using_fallback
            ? "This is the fallback you set, not a published rate."
            : "This is the published rate, in force now."}
        </p>
      </div>

      <NoticeBox
        tone={headline.tone === "ok" ? "ok" : "warn"}
        icon={
          headline.tone === "ok" ? (
            <ArrowRightLeft aria-hidden className="h-5 w-5" />
          ) : (
            <TriangleAlert aria-hidden className="h-5 w-5" />
          )
        }
        title={headline.title}
      >
        <p className="mt-1">{headline.body}</p>
      </NoticeBox>

      <dl className="grid grid-cols-2 gap-2 text-sm">
        <dt className="text-ink-muted">Fallback you set</dt>
        <dd>
          <MonoValue>{rate.fallback_rate}</MonoValue>
        </dd>
        <dt className="text-ink-muted">Last published rate</dt>
        <dd>
          {rate.published_rate ? (
            <MonoValue>{rate.published_rate}</MonoValue>
          ) : (
            <span className="text-ink-faint">none yet</span>
          )}
        </dd>
        <dt className="text-ink-muted">Source</dt>
        <dd>
          {rate.published_source ? (
            <MonoValue>{rate.published_source}</MonoValue>
          ) : (
            <span className="text-ink-faint">none yet</span>
          )}
        </dd>
      </dl>

      {rate.history.length > 0 && (
        <div>
          <p className="text-sm font-medium text-ink">Recent pulls</p>
          <ul className="mt-2 space-y-1 text-sm">
            {rate.history.map((observation) => (
              <li
                key={`${observation.source}-${observation.as_of}-${observation.rate}`}
                className="flex items-baseline justify-between gap-2"
              >
                <span className="text-ink-muted">{observation.as_of}</span>
                <MonoValue>{observation.rate}</MonoValue>
                <span className="text-ink-faint">
                  {formatIST(observation.observed_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
