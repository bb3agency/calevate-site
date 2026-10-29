/**
 * Pip's charts (D-934): the `chart` stream frame and a pinned card's spec, as the browser
 * reads them. A spec is DATA — the console's own chart components draw it — and every value
 * is a decimal string, so money is shown exactly as the server computed it and parsed to a
 * number only to size a mark.
 */

import { formatDateShort } from "@/components/arc/ist-dates";
import { formatINR } from "@/lib/numberDisplay";

import type { components } from "@/lib/api/schema";

export type ChartSpec = components["schemas"]["ChartSpec"];
export type ChartRealm = "client" | "admin";

/** A value as a person reads it: rupees with the symbol, counts as they are. */
export function displayValue(spec: Pick<ChartSpec, "unit">, value: string): string {
  if (spec.unit === "inr") return formatINR(value);
  if (spec.unit === "percent") return `${value}%`;
  return value;
}

/** A number for sizing a bar or a slice; never shown. */
export function plotValue(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** An x label as a person reads it: IST dates short, names as they are. */
export function axisLabel(spec: Pick<ChartSpec, "x">, label: string): string {
  if (spec.x && spec.x.bucket !== "category") return formatDateShort(label).replace(/ \d{4}$/, "");
  return label;
}

/** The chart as rows and columns: the same table the chart's fallback shows. */
export function specTable(spec: ChartSpec): { columns: string[]; rows: string[][] } {
  if (spec.kind === "table") {
    return { columns: spec.columns.map((c) => c.label), rows: spec.rows };
  }
  if (!spec.x) {
    return {
      columns: spec.series.map((s) => s.label),
      rows: [spec.series.map((s) => displayValue(spec, s.values[0] ?? "0"))],
    };
  }
  const x = spec.x;
  return {
    columns: [x.label, ...spec.series.map((s) => s.label)],
    rows: x.labels.map((label, i) => [
      axisLabel(spec, label),
      ...spec.series.map((s) => displayValue(spec, s.values[i] ?? "0")),
    ]),
  };
}

function csvCell(value: string): string {
  // A cell a spreadsheet would run as a formula is prefixed, as the server's exports do.
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** The spec as CSV, with raw decimal values so a spreadsheet can sum them. */
export function specCsv(spec: ChartSpec): string {
  let columns: string[];
  let rows: string[][];
  if (spec.kind === "table") {
    columns = spec.columns.map((c) => c.label);
    rows = spec.rows;
  } else if (!spec.x) {
    columns = spec.series.map((s) => s.label);
    rows = [spec.series.map((s) => s.values[0] ?? "0")];
  } else {
    const x = spec.x;
    columns = [x.label, ...spec.series.map((s) => s.label)];
    rows = x.labels.map((label, i) => [label, ...spec.series.map((s) => s.values[i] ?? "0")]);
  }
  return [columns, ...rows].map((row) => row.map(csvCell).join(",")).join("\n");
}

/**
 * The console path that shows the same set, or null. `open.path` is a constant from the
 * server's own screen inventory, relative to the realm root; it is checked to be a plain
 * path before it is joined, so nothing in a frame can become an external address.
 */
export function openHref(spec: ChartSpec, realm: ChartRealm, slug: string): string | null {
  const open = spec.open;
  if (!open || !/^(\/[a-z0-9-]+)*$/.test(open.path)) return null;
  const root = realm === "admin" ? "/admin" : `/c/${encodeURIComponent(slug)}`;
  const query = new URLSearchParams(open.query ?? {}).toString();
  return `${root}${open.path}${query ? `?${query}` : ""}`;
}

/** "Top 10 of 34", or null when nothing was cut. */
export function cutNote(spec: Pick<ChartSpec, "shown" | "of">): string | null {
  return spec.shown != null && spec.of != null ? `Top ${spec.shown} of ${spec.of}` : null;
}
