import { formatCountOf, formatINR } from "@/components/ui";
import type { CostBreakdown } from "@/lib/api/spend";

/**
 * WHAT A CLIENT COST US, SPLIT BY WHAT IT BOUGHT — one rendering for the three screens that
 * report it (Overview, Spend, the trial panel). The figures are the server's
 * `CostBreakdownOut`, read by one function (`billing/cost_breakdown.py`), so the screens
 * differ only in the window: the IST month, or the trial's own days.
 *
 * Admin realm only: every figure is our supplier cost. Nothing is added up here; the total
 * is the server's.
 */
export function CostBreakdownList({ breakdown }: { breakdown: CostBreakdown }) {
  const rows = [
    {
      label: "AI assistant and other AI help",
      value: breakdown.assistant_inr,
      detail: formatCountOf(breakdown.assistant_requests, "action"),
    },
    {
      label: "Preparing their knowledge",
      value: breakdown.knowledge_inr,
      detail: formatCountOf(breakdown.knowledge_requests, "job"),
    },
    {
      label: "Calls",
      value: breakdown.calls_inr,
      detail: formatCountOf(breakdown.calls, "call"),
    },
    { label: "Phone number rental", value: breakdown.other_inr, detail: null },
  ];
  return (
    <dl className="divide-y divide-line">
      {rows.map((row) => (
        <div key={row.label} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-1.5">
          <dt className="text-meta text-ink-muted">{row.label}</dt>
          <dd className="text-body tabular-nums text-ink">
            {formatINR(row.value)}
            {row.detail && <span className="ml-2 text-meta text-ink-muted">{row.detail}</span>}
          </dd>
        </div>
      ))}
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 py-1.5">
        <dt className="text-meta font-semibold text-ink">Total cost to us</dt>
        <dd className="text-body font-semibold tabular-nums text-ink">
          {formatINR(breakdown.total_inr)}
        </dd>
      </div>
    </dl>
  );
}

/** The same breakdown as copilot facts, so the assistant quotes the screen's own numbers. */
export function costBreakdownFacts(
  prefix: string,
  scope: string,
  breakdown: CostBreakdown,
): { key: string; label: string; value: string }[] {
  return [
    { key: `${prefix}_total_inr`, label: `Cost to us, all in, ${scope} (₹)`, value: breakdown.total_inr },
    {
      key: `${prefix}_assistant`,
      label: `AI assistant and other AI help, ${scope} (₹, actions)`,
      value: `${breakdown.assistant_inr} across ${formatCountOf(breakdown.assistant_requests, "action")}`,
    },
    {
      key: `${prefix}_knowledge`,
      label: `Preparing their knowledge, ${scope} (₹, jobs)`,
      value: `${breakdown.knowledge_inr} across ${formatCountOf(breakdown.knowledge_requests, "job")}`,
    },
    {
      key: `${prefix}_calls`,
      label: `Calls, ${scope} (₹, count)`,
      value: `${breakdown.calls_inr} across ${formatCountOf(breakdown.calls, "call")}`,
    },
    { key: `${prefix}_rental`, label: `Phone number rental, ${scope} (₹)`, value: breakdown.other_inr },
  ];
}
