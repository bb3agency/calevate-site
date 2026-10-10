"use client";

import { Section } from "@/components/console/section";
import { ArrowRightLeft, CircleHelp, TriangleAlert } from "lucide-react";

import {
  WithheldPanel,
  forbiddenReason,
  isForbidden,
} from "@/app/admin/withheld";
import { MonoValue, fxSourceCopy } from "@/app/admin/ops/opsLanguage";
import {
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useFxRate, type FxRate } from "@/lib/api/opsFxRate";

/**
 * The exchange rate every dollar of vendor cost is converted at — what is in force, why,
 * and how fresh it is.
 *
 * ## Why an operator needs this screen at all
 *
 * Cartesia and Azure invoice this business in dollars; every figure the platform records is
 * rupees. One multiplier stands between the two. It is pulled automatically, so the ways
 * to be wrong are a feed that stops publishing and a puller that stops running, and this
 * panel keeps them apart: "Published for" is the SOURCE's date and moves once a business
 * day; "Last checked" is the puller's own last completed tick and moves every five
 * minutes. A daily publication polled every five minutes is stored once, so the time a
 * publication was first stored is not evidence the puller is alive.
 *
 * ## This panel computes nothing
 *
 * No arithmetic, no age, no staleness verdict. `basis`, `state`, `last_checked_label` and
 * every rate are the server's, printed as they arrive (`lib/api/opsFxRate.ts` carries the
 * argument). The one thing decided here is which sentence to show, and it is decided from
 * the server's own `basis` rather than by re-testing a threshold this bundle would then
 * own a stale copy of.
 *
 * ## Which source is on each row, and why the raw string stays
 *
 * The pull walks a ladder of published sources (`apps/workers/fx_pull.LADDER`: FBIL
 * directly, then FBIL through Frankfurter, then Frankfurter's own rate). Every source it
 * fetched is stored, so "Recent publications" is a list of DIFFERENT SOURCES and not a
 * list of the same one over time. The source is printed verbatim AND glossed
 * (`fxSourceCopy`, opsLanguage §7): verbatim because it is the string stamped on every
 * `usage_events` row the rate converted (hard rule 4), glossed because the string alone
 * does not say whether the platform is billing off the Indian benchmark. A source this
 * bundle does not recognise prints raw with no gloss rather than being called something
 * wrong.
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

/** The one line under the rate: which rung it came from. From the SERVER's `basis`. */
export function fxReason(rate: FxRate): string {
  const date = rate.published_as_of ?? "an unknown date";
  switch (rate.basis) {
    case "published":
      return `Published rate for ${date}, in force now.`;
    case "stale_published":
      return `Last published rate, for ${date}. Stale: no source has published for more than ${rate.max_age_days} days.`;
    case "manual_override":
      return "Your manual rate. The override is on, so the published rate is not used.";
    case "manual_no_quote":
      return "Your manual rate. No rate has been published yet.";
  }
}

/** The headline notice, chosen from the SERVER's `basis` and never re-derived. */
export function fxHeadline(rate: FxRate): {
  title: string;
  body: string;
  tone: "ok" | "warn";
} {
  switch (rate.basis) {
    case "published":
      return {
        tone: "ok",
        title: "Vendor costs are converting at the published rate",
        body: `Published by ${rate.published_source ?? "the rate source"} for ${rate.published_as_of ?? "an unknown date"}.`,
      };
    case "stale_published":
      return {
        tone: "warn",
        title: "The published rate is out of date",
        body: `Costs keep converting at the last published rate, from ${rate.published_as_of ?? "an unknown date"}, until a source publishes again. Check the last-checked time below: if it is old, the rate pull is not running.`,
      };
    case "manual_override":
      return {
        tone: "warn",
        title: "Costs are converting at your manual rate",
        body: "The manual override is on in Platform configuration. Switch it off to return to the published rate.",
      };
    case "manual_no_quote":
      return {
        tone: "warn",
        title: "No rate has been published yet",
        body: "Costs are converting at your manual rate. This is normal for the first few minutes after a deploy; if it persists, the rate pull is not running.",
      };
  }
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
    <Section title="Exchange rate">
      <div className="space-y-4">
        <p className="text-body text-ink-muted">
          Your voice and model vendors bill in US dollars; everything you charge
          and record is in rupees. This is the rate in between. It is checked
          automatically every five minutes against a published reference rate,
          which itself changes once each business day. If no new rate has been
          published, the last published one stays in force. The manual rate
          under <MonoValue>usd_inr_rate</MonoValue> is used only before any rate
          has been published, or while you have the override switched on.
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
    </Section>
  );
}

/**
 * One source string, as the operator reads it and as the ledger holds it.
 *
 * Both, always: the gloss is what tells them whether this is the benchmark, and the raw
 * string is what they will be matching against a `usage_events` row six months from now.
 * An unrecognised source glosses to itself, so the pair collapses to the string alone
 * rather than to a label this bundle invented.
 */
function FxSource({ source }: { source: string }) {
  const copy = fxSourceCopy(source);
  return (
    <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="text-ink">{copy.label}</span>
      {copy.label !== source && <MonoValue>{source}</MonoValue>}
    </span>
  );
}

function FxRateBody({ rate }: { rate: FxRate }) {
  const headline = fxHeadline(rate);
  const manualInUse =
    rate.basis === "manual_override" || rate.basis === "manual_no_quote";
  return (
    <div className="space-y-4">
      <div className="border-y border-line py-3">
        <div className="flex items-baseline gap-2">
          <ArrowRightLeft aria-hidden className="h-4 w-4 text-ink-muted" />
          <span className="text-body text-ink-muted">
            1 {rate.base_currency} =
          </span>
          <MonoValue>{rate.effective_rate}</MonoValue>
          <span className="text-body text-ink-muted">{rate.quote_currency}</span>
        </div>
        <p className="mt-1 text-body text-ink-muted">{fxReason(rate)}</p>
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

      <dl className="grid grid-cols-2 gap-2 text-body">
        <dt className="text-ink-muted">Last checked</dt>
        <dd>
          {rate.last_checked_at ? (
            <span>
              {formatIST(rate.last_checked_at)}
              {rate.last_checked_label && (
                <span className="text-ink-muted">
                  {" "}
                  ({rate.last_checked_label})
                </span>
              )}
            </span>
          ) : (
            <span className="text-ink-muted">not recorded yet</span>
          )}
        </dd>
        <dt className="text-ink-muted">Published for</dt>
        <dd>
          {rate.published_as_of ?? (
            <span className="text-ink-muted">none yet</span>
          )}
        </dd>
        <dt className="text-ink-muted">Last published rate</dt>
        <dd>
          {rate.published_rate ? (
            <MonoValue>{rate.published_rate}</MonoValue>
          ) : (
            <span className="text-ink-muted">none yet</span>
          )}
        </dd>
        <dt className="text-ink-muted">Source</dt>
        <dd>
          {rate.published_source ? (
            <FxSource source={rate.published_source} />
          ) : (
            <span className="text-ink-muted">none yet</span>
          )}
        </dd>
        <dt className="text-ink-muted">Manual rate</dt>
        <dd>
          <MonoValue>{rate.manual_rate}</MonoValue>
          <span className="text-ink-muted">
            {manualInUse ? " (in use)" : " (not in use)"}
          </span>
        </dd>
      </dl>

      {rate.history.length > 0 && (
        <div>
          <p className="text-body font-medium text-ink">Recent publications</p>
          <p className="mt-1 text-body text-ink-muted">
            One row per publication stored, with the time it was first seen. A
            check that finds the same publication again adds no row, so these
            times do not show how recently the rate was checked.
          </p>
          <ul className="mt-2 space-y-2 text-body">
            {rate.history.map((observation) => (
              <li
                key={`${observation.source}-${observation.as_of}-${observation.rate}`}
                className="border-b border-line pb-2 last:border-0 last:pb-0"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
                  <span className="text-ink-muted">{observation.as_of}</span>
                  <MonoValue>{observation.rate}</MonoValue>
                  <span className="text-ink-muted">
                    {formatIST(observation.observed_at)}
                  </span>
                </div>
                <div className="mt-1">
                  <FxSource source={observation.source} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
