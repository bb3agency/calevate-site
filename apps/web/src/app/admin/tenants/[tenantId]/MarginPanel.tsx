"use client";

import {
  Card,
  ProblemNotice,
  Skeleton,
  StatTile,
  formatCount,
  formatINR,
} from "@/components/ui";
import { useMargin, type Margin } from "@/lib/api/admin";

/**
 * Per-client margin (D-12), the number gate G2 turns on.
 *
 * It lives in the ADMIN console and nowhere else: `unit_cost_paid` is our supplier
 * pricing, and a client who can see it is a client negotiating against it. Their own
 * usage panel shows what they used and what it costs them, which is the half that is
 * theirs.
 *
 * MONEY: `revenue_inr` / `cost_inr` / `margin_inr` are exact decimal STRINGS and go
 * through `formatINR`, which formats the digits and never parses them. They used to be
 * interpolated raw as `₹{string}`, which printed `₹1015900.00` — ungrouped, and a
 * server-sent `1015900.0` would have printed a single paise digit. These are TOTALS, so
 * two decimals is what they mean; the rate on the invoice is the one figure that must
 * NOT be rounded like a rupee, and it is not shown here.
 */
export function MarginPanel({ tenantId }: { tenantId: string }) {
  const margin = useMargin(tenantId);
  if (margin.error) return <ProblemNotice error={margin.error} onRetry={() => margin.refetch()} />;
  if (!margin.data)
    return (
      <Card title="Margin">
        <Skeleton rows={2} />
      </Card>
    );
  const data = margin.data;
  const negative = data.margin_inr.trim().startsWith("-");

  return (
    <Card title={`Margin · ${data.month}`}>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Revenue" value={formatINR(data.revenue_inr)} />
        <StatTile label="Our cost" value={formatINR(data.cost_inr)} />
        <div className="rounded-card border border-line bg-surface p-5">
          <p className="text-[13px] font-medium text-ink-muted">Margin</p>
          <p
            className={
              negative
                ? "mt-1 text-2xl font-bold tracking-tight tabular-nums text-rose-600 dark:text-rose-400"
                : "mt-1 text-2xl font-bold tracking-tight tabular-nums text-brand-strong dark:text-brand-bright"
            }
          >
            {formatINR(data.margin_inr)}
          </p>
        </div>
        {/* null, not 0%: "nothing billed yet" and "we made nothing" are different
            facts, and an operator acts differently on each. */}
        <StatTile
          label="Margin %"
          value={data.margin_pct === null ? "not billed yet" : `${data.margin_pct}%`}
        />
      </div>
      <p className="mt-3 text-xs text-ink-muted">
        {data.minutes_used} minutes across {formatCount(data.calls)} calls. Cost is what we
        actually paid, stamped per usage row at capture time with the fx rate used.
      </p>
      <TierSplit tiers={data.tiers} />
    </Card>
  );
}

/**
 * What the margin's cost side is MADE of, by the OVERAGE RUNG each call was metered on.
 *
 * ## WHAT THIS CARD ACTUALLY SPLITS, because it used to say something else
 *
 * It was headed "Cost by TTS rung" and labelled its two buckets "Premium (v3)" and
 * "Value (v2)", which claimed a split by Bulbul model version. It is not that split. The
 * server reads `usage_events.meta.tts_tier` (`billing/service.py::_ROW_TIER_SQL`), and
 * that key is stamped by `apps/workers/pipeline.py` with `BASE_OVERAGE_RUNG` — the PLAN'S
 * OVERAGE-RATE SLOT, `plans.overage_rate` against `plans.overage_rate_second`. The code
 * says so in three places and one of them in capitals: `billing/service.py:1825-1832`
 * ("overage-rate slots ... NOT voice-quality tiers"), `pipeline.py` beside the stamp
 * ("THIS IS THE PLAN'S OVERAGE-RATE SLOT AND NOT A VOICE"), and `agents/voices.py:205-209`
 * ("`usage_events.meta.tts_tier` is the PLAN'S OVERAGE RUNG"). Which VOICE spoke is a
 * different fact stamped on a different key (`meta.voice_tier`), and this card does not
 * report it.
 *
 * So the old labels were wrong twice: they used rung vocabulary this product does not use,
 * and they named an axis the numbers do not come from. `overage_rate_second` is NULL on
 * every plan today, so in practice every minute lands in the base bucket — which is
 * exactly the reading an operator needs, and exactly what "Premium (v3)" hid.
 *
 * A thin margin is not actionable on its own — the operator's next move differs depending
 * on whether the minutes are all on the base rate (the plan is underpriced, or the rate
 * needs to move) or split across a second rate this client was quoted. The server nests
 * these under `tiers` on the same read, so this costs no round trip.
 *
 * The three costs are a PARTITION of `cost_inr` above and add up to it exactly — both
 * come from `_tier_totals`. Nothing is recomputed here: adding the strings client-side
 * would be float arithmetic on money (hard rule 7), and the total is already on the card.
 *
 * `unattributed` is shown even at zero. It is the count of minutes we could not prove a
 * rung for, and hiding it when empty would make its later appearance look like a new
 * feature rather than a metering gap — an operator who has never seen the row will not
 * know to ask what it means.
 */
function TierSplit({ tiers }: { tiers: Margin["tiers"] }) {
  // THE NEW WIRE NAME FIRST, THE DEPRECATED ONE AS THE FALLBACK — step 1 of a two-step
  // deprecation (hard rule 8, D-558). `minutes_premium` / `cost_value_inr` and friends
  // named a voice quality that never chose the rung; `minutes_base_rung` /
  // `cost_second_rung_inr` name the agreed rate, which is what the card is about.
  //
  // THE FALLBACK IS NOT DEAD CODE. This bundle and the API are deployed separately, so a
  // console that has shipped can be talking to an API that has not (and the reverse), and
  // the only version of this card that renders in BOTH worlds is one that accepts either
  // name. `??` and not `||`: the figures are strings and `"0.00"` is truthy, but an
  // empty-string rung would be a real reading and must not be replaced by the other name.
  //
  // STEP 2 deletes every `??` on this line and the server fields behind them, together.
  const rungs = [
    // NAMED FOR THE PLAN COLUMN EACH ONE IS, which is the thing an operator can act on:
    // `plans.overage_rate` and `plans.overage_rate_second`. Not a voice, not a model
    // version, and not the excluded rung vocabulary.
    {
      label: "Base overage rate",
      minutes: tiers.minutes_base_rung ?? tiers.minutes_premium,
      cost: tiers.cost_base_rung_inr ?? tiers.cost_premium_inr,
    },
    {
      label: "Second overage rate",
      minutes: tiers.minutes_second_rung ?? tiers.minutes_value,
      cost: tiers.cost_second_rung_inr ?? tiers.cost_value_inr,
    },
    {
      label: "Unattributed",
      minutes: tiers.minutes_unattributed,
      cost: tiers.cost_unattributed_inr,
    },
  ];
  return (
    <div className="mt-4 border-t border-line pt-3">
      {/* h3, not h4: this panel sits inside a `Card`, whose title is an <h2>, so an h4
          skips a level. Pre-existing and previously invisible to the axe sweep — jsdom
          implements no `matchMedia`, and without it axe cannot resolve media-query
          visibility, so it was not evaluating this heading at all. The stub added in
          tests/setup.ts for the marketing page's reduced-motion check made the sweep
          able to see it. Size is carried by the class, so nothing moves on screen. */}
      <h3 className="text-[13px] font-medium text-ink-muted">Cost by overage rung</h3>
      <dl className="mt-2 grid gap-3 sm:grid-cols-3">
        {rungs.map((rung) => (
          <div key={rung.label} className="rounded-card border border-line bg-surface px-4 py-3">
            <dt className="text-xs text-ink-muted">{rung.label}</dt>
            <dd className="mt-0.5 text-sm font-semibold tabular-nums">{formatINR(rung.cost)}</dd>
            <dd className="text-xs tabular-nums text-ink-muted">{rung.minutes} min</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
