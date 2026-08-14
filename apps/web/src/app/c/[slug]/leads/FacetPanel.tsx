"use client";

import { Card, ProblemNotice, Skeleton, formatCount } from "@/components/ui";
import type { LeadFacets } from "@/lib/api/leads";

/**
 * The filter rail, built from the per-agent EXTRACTION SCHEMA (SURFACES §2).
 *
 * Never a hard-coded field list: a clinic's capture list and a builder's have nothing in
 * common, so the facets are whatever `GET /v1/leads/facets` says the enum fields are, and
 * a second vertical needs no code here.
 *
 * The researched shape, which this follows:
 *   - **A count on every value**, updated as other facets are applied, so "Over ₹50L (12)"
 *     tells a person what the click will give them before they make it.
 *   - **OR within a group, AND across groups.** Ticking two budgets widens; ticking a
 *     budget and a locality narrows. The server implements it; this only has to not lie
 *     about it, which is what the group's own hint sentence does.
 *   - **A zero is offered, not hidden.** A value with no rows renders greyed at 0 rather
 *     than disappearing, because a facet list that changes membership under you is a list
 *     you cannot learn.
 *
 * §52 discipline: loading is a skeleton, failure is the server's own refusal, and neither
 * is an empty panel — "you have no filters" and "we could not read your filters" are
 * different sentences and only one of them is ever true here.
 */
export function FacetPanel({
  facets,
  loading,
  error,
  selected,
  onChange,
  onRetry,
}: {
  facets: LeadFacets | undefined;
  loading: boolean;
  error: unknown;
  selected: Record<string, string[]>;
  onChange: (next: Record<string, string[]>) => void;
  onRetry: () => void;
}) {
  if (loading) {
    return (
      <Card bodyClassName="p-3">
        <Skeleton rows={2} />
      </Card>
    );
  }
  if (error) {
    return <ProblemNotice error={error} onRetry={onRetry} />;
  }
  // An agent whose capture list has no enum fields has no facets, and that is a fact
  // rather than a failure — the panel simply is not there, and the status chips above it
  // still are.
  if (!facets?.facets.length) return null;

  const toggle = (key: string, value: string) => {
    const current = selected[key] ?? [];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    const merged = { ...selected };
    // A key with no values is DELETED rather than left as an empty array: the API refuses
    // `f=key:` and an empty selection is not a filter, it is the absence of one.
    if (next.length) merged[key] = next;
    else delete merged[key];
    onChange(merged);
  };

  const anySelected = Object.values(selected).some((v) => v.length);

  return (
    <Card bodyClassName="space-y-3 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs font-semibold text-ink">Filter by what your agent captured</p>
        {anySelected && (
          <button
            type="button"
            onClick={() => onChange({})}
            className="text-xs font-medium text-brand-strong hover:underline dark:text-brand-bright"
          >
            Clear these filters
          </button>
        )}
      </div>

      {facets.facets.map((facet) => (
        <fieldset key={facet.key} className="space-y-1.5">
          {/* A PERSISTENT VISIBLE LABEL for the group. `<legend>` rather than an
              aria-label, so it is readable by everyone and not only by axe. */}
          <legend className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
            {facet.label}
          </legend>
          <div className="flex flex-wrap gap-1.5">
            {facet.values.map((value) => {
              const on = (selected[facet.key] ?? []).includes(value.value);
              return (
                <label
                  key={value.value}
                  className={
                    on
                      ? "flex cursor-pointer items-center gap-1.5 rounded-full bg-brand-strong px-3 py-1 text-xs font-semibold text-white"
                      : "flex cursor-pointer items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
                  }
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => toggle(facet.key, value.value)}
                    className="h-3 w-3"
                  />
                  <span>{value.value}</span>
                  {/* The count is the server's, over every OTHER filter — so it answers
                      "what would this give me", which is the only reading that lets a
                      person plan a click. */}
                  <span className="tabular-nums opacity-70">{formatCount(value.count)}</span>
                  {/* A value the data holds and the capture list no longer declares. Said
                      out loud rather than hidden: it is filterable, it is just no longer
                      something the agent is asked to capture. */}
                  {!value.declared && <span className="opacity-70">· retired</span>}
                </label>
              );
            })}
          </div>
        </fieldset>
      ))}

      {facets.omitted_field_count > 0 && (
        <p className="text-xs text-ink-faint">
          {formatCount(facets.omitted_field_count)} more capture{" "}
          {facets.omitted_field_count === 1 ? "field is" : "fields are"} filterable but not shown
          here — ask us to reorder your capture list if you need one of them.
        </p>
      )}
    </Card>
  );
}
