> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# CPS & Cost Calculator

> Estimate Calls Per Second, simultaneous concurrency, and capacity requirements for your voice campaigns. Live calculator built into the page.

export const inputCls = "w-full px-3 py-2 bg-transparent border border-gray-200 dark:border-white/10 rounded-lg text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary text-sm transition";

export const labelCls = "block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5";

export const Field = ({label, children}) => <div>
    <label className={labelCls}>{label}</label>
    {children}
  </div>;

export const Stat = ({label, value, sub}) => <div className="flex items-baseline justify-between py-3 border-b border-gray-100 dark:border-white/5 last:border-0">
    <div>
      <div className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</div>
      {sub && <div className="text-xs text-gray-500 dark:text-gray-500 mt-0.5">{sub}</div>}
    </div>
    <div className="text-2xl font-semibold text-gray-900 dark:text-gray-50 tabular-nums">{value}</div>
  </div>;

export const CpsCalculator = () => {
  const [dailyVolume, setDailyVolume] = React.useState("100000");
  const [pickupRate, setPickupRate] = React.useState("25");
  const [avgDuration, setAvgDuration] = React.useState("60");
  const [avgRingTime, setAvgRingTime] = React.useState("14");
  const [callingHours, setCallingHours] = React.useState("12");
  const dVol = Number(dailyVolume) || 0;
  const pRate = Number(pickupRate) || 0;
  const aDur = Number(avgDuration) || 0;
  const aRing = Number(avgRingTime) || 0;
  const cHours = Number(callingHours) || 0;
  const callingSeconds = cHours * 3600;
  const expectedConnected = dVol * (pRate / 100);
  const unansweredCalls = dVol - expectedConnected;
  const connectedCallTime = expectedConnected * aDur;
  const unansweredCallTime = unansweredCalls * aRing;
  const totalCallTime = connectedCallTime + unansweredCallTime;
  const cps = callingSeconds > 0 ? dVol / callingSeconds : 0;
  const concurrency = callingSeconds > 0 ? totalCallTime / callingSeconds : 0;
  const cpm = cps * 60;
  const fmtNum = n => new Intl.NumberFormat().format(Math.round(n));
  const fmtDec = n => n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
  return <div className="grid lg:grid-cols-2 gap-4 my-6 not-prose">
      <div className="rounded-2xl border border-gray-200 dark:border-white/10 bg-white dark:bg-zinc-900 p-6">
        <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-5">Inputs</div>
        <div className="space-y-4">
          <Field label="Total call volume per day">
            <input type="number" min="0" value={dailyVolume} onChange={e => setDailyVolume(e.target.value)} className={inputCls} />
          </Field>
          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="Pickup rate (%)">
              <input type="number" min="0" max="100" value={pickupRate} onChange={e => setPickupRate(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Calling hours / day">
              <input type="number" min="0" max="24" value={callingHours} onChange={e => setCallingHours(e.target.value)} className={inputCls} />
            </Field>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="Avg call duration (sec)">
              <input type="number" min="0" value={avgDuration} onChange={e => setAvgDuration(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Avg ring time if unanswered (sec)">
              <input type="number" min="0" value={avgRingTime} onChange={e => setAvgRingTime(e.target.value)} className={inputCls} />
            </Field>
          </div>
        </div>

        <div className="mt-6 pt-5 border-t border-gray-100 dark:border-white/5 grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
          <div className="flex justify-between"><span className="text-gray-500">Connected</span><span className="font-mono text-gray-700 dark:text-gray-300">{fmtNum(expectedConnected)}</span></div>
          <div className="flex justify-between"><span className="text-gray-500">Unanswered</span><span className="font-mono text-gray-700 dark:text-gray-300">{fmtNum(unansweredCalls)}</span></div>
          <div className="flex justify-between"><span className="text-gray-500">Calling sec</span><span className="font-mono text-gray-700 dark:text-gray-300">{fmtNum(callingSeconds)}</span></div>
          <div className="flex justify-between"><span className="text-gray-500">Total call time</span><span className="font-mono text-gray-700 dark:text-gray-300">{fmtNum(totalCallTime)} s</span></div>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 dark:border-white/10 bg-white dark:bg-zinc-900 p-6 lg:sticky lg:top-24 self-start">
        <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Capacity required</div>

        <div className="mt-3">
          <Stat label="Calls per second (CPS)" value={fmtDec(cps)} />
          <Stat label="Concurrency" value={fmtDec(concurrency)} sub="Simultaneous active channels" />
          <Stat label="Calls per minute" value={fmtDec(cpm)} />
        </div>

        <div className="mt-5 px-3 py-2.5 bg-primary/10 border border-primary/20 rounded-lg text-xs text-gray-600 dark:text-gray-400">
          Provision at least 20% overhead for peak-hour stabilization.
        </div>
      </div>
    </div>;
};

Estimate Calls Per Second (CPS) and simultaneous concurrency for your voice campaigns. Adjust the inputs below - results recalculate live.

<CpsCalculator />

## How the math works

The calculator uses two formulas:

* **CPS** = Total daily volume ÷ (Calling hours × 3600)
* **Concurrency** = \[(Connected calls × Avg duration) + (Unanswered calls × Avg ring time)] ÷ (Calling hours × 3600)

Concurrency accounts for the "hold time" of both connected and unanswered calls - a busy ringing line still occupies a channel.

## Understanding the metrics

* **Calls Per Second (CPS)** - The rate at which your system initiates new calls. If CPS exceeds your account limit, calls get throttled. See [CPS](/docs/faq/cps).
* **Concurrency** - Number of calls active at the same instant (ringing + connected). This is your channel requirement. See [Concurrency](/docs/faq/concurrency).
* **Pickup rate** - % of dialled numbers that connect to a person. India outbound dialers typically see 15–30%; a verified opt-in list can hit 40–60%.
* **Avg ring time if unanswered** - How long a call rings before timing out. Default 14s. Lower values free channels faster on busy campaigns.

## Best practices

<Tip>
  * Monitor peak-hour traffic - typically 1.5× daily average.
  * Use shorter ring times (10–12s) on outbound dialers to recycle channels faster.
  * Match your SIP trunk's `concurrent_calls_limit` to the calculator's concurrency value plus 20% overhead.
  * Predictive dialers should target CPS slightly below their licensed rate to leave headroom for retries.
</Tip>

## Related

<Columns cols={2}>
  <Card title="Concurrency" icon="layer-group" href="/docs/faq/concurrency">
    How concurrent calls are counted and rate-limited.
  </Card>

  <Card title="CPS" icon="bolt" href="/docs/faq/cps">
    What CPS is and why it matters at scale.
  </Card>

  <Card title="Purchase capacity" icon="cart-shopping" href="/docs/faq/purchase-concurrency-cps">
    How to upgrade your concurrency / CPS limits.
  </Card>

  <Card title="Number utilization" icon="phone" href="/docs/best-practices/number-utilization">
    Get the most out of your DID inventory.
  </Card>
</Columns>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.