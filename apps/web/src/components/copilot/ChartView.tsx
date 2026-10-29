"use client";

import { BarChart } from "@/components/arc/bar-chart";
import { DonutChart } from "@/components/arc/donut-chart";
import { LineChart } from "@/components/arc/line-chart";
import { ScrollRegion, StatTile } from "@/components/ui";
import { axisLabel, cutNote, displayValue, plotValue, type ChartSpec } from "@/lib/copilot/charts";

/**
 * One of Pip's charts (D-934), drawn with the console's own chart components. Every chart
 * kind keeps the components' "Show as table" fallback; a table spec is a real `<table>`.
 * Time buckets are columns, named categories are horizontal bars whose labels wrap (an
 * agent's or a campaign's name is never cut).
 */
export function ChartView({ spec, hideTitle = false }: { spec: ChartSpec; hideTitle?: boolean }) {
  const description = [spec.counted, cutNote(spec)].filter(Boolean).join(" ");
  const empty = "Nothing to show for this period yet.";
  const format = (value: number) => displayValue(spec, String(value));

  if (spec.kind === "number") {
    const value = spec.series[0]?.values[0] ?? spec.total ?? "0";
    return (
      <div className="space-y-2">
        <StatTile label={spec.title} value={displayValue(spec, value)} />
        <p className="text-meta text-ink-muted">{description}</p>
      </div>
    );
  }

  if (spec.kind === "table") {
    return (
      <figure className="min-w-0 space-y-2">
        <figcaption className={hideTitle ? "sr-only" : "text-body font-semibold text-ink"}>
          {spec.title}
        </figcaption>
        <p className="text-meta text-ink-muted">{description}</p>
        {spec.rows.length === 0 ? (
          <p className="text-body text-ink-muted">{empty}</p>
        ) : (
          <ScrollRegion label={spec.title}>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line">
                  {spec.columns.map((column) => (
                    <th
                      key={column.key}
                      scope="col"
                      className={`py-1.5 pr-3 font-medium text-ink-muted ${column.numeric ? "text-right" : ""}`}
                    >
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {spec.rows.map((row, r) => (
                  <tr key={r} className="border-b border-line last:border-0">
                    {row.map((cell, c) => (
                      <td
                        key={c}
                        className={`py-1.5 pr-3 text-ink [overflow-wrap:anywhere] ${spec.columns[c]?.numeric ? "text-right tabular-nums" : ""}`}
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </figure>
    );
  }

  const x = spec.x;
  const labels = x ? x.labels.map((label) => axisLabel(spec, label)) : [];

  if (spec.kind === "pie") {
    const series = spec.series[0];
    return (
      <DonutChart
        title={spec.title}
        hideTitle={hideTitle}
        description={description}
        labelColumn={x?.label ?? "Part"}
        segments={labels.map((label, i) => ({
          label,
          value: plotValue(series?.values[i] ?? "0"),
          display: displayValue(spec, series?.values[i] ?? "0"),
        }))}
        centerValue={spec.total ? displayValue(spec, spec.total) : undefined}
        centerLabel={spec.unit === "inr" ? "spent" : spec.unit}
        empty={empty}
      />
    );
  }

  if (spec.kind === "line") {
    return (
      <LineChart
        title={spec.title}
        hideTitle={hideTitle}
        description={description}
        labelColumn={x?.label ?? "Period"}
        labels={labels}
        series={spec.series.map((s) => ({
          label: s.label,
          values: s.values.map(plotValue),
          display: s.values.map((v) => displayValue(spec, v)),
        }))}
        formatTick={format}
        height={180}
        empty={empty}
      />
    );
  }

  return (
    <BarChart
      title={spec.title}
      hideTitle={hideTitle}
      description={description}
      labelColumn={x?.label ?? "Category"}
      categories={labels}
      series={spec.series.map((s) => ({
        label: s.label,
        values: s.values.map(plotValue),
        display: s.values.map((v) => displayValue(spec, v)),
      }))}
      stacked={spec.kind === "stacked_bar"}
      orientation={x?.bucket === "category" ? "horizontal" : "vertical"}
      showValues={x?.bucket === "category" && spec.series.length === 1}
      formatTick={format}
      height={180}
      empty={empty}
    />
  );
}
