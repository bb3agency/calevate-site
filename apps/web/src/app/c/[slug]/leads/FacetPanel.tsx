"use client";

import { Disclosure, ProblemNotice, Skeleton, formatCount } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
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
  bare = false,
}: {
  /** Inside another disclosure ("More filters"): the groups alone, with no second fold. */
  bare?: boolean;
  facets: LeadFacets | undefined;
  loading: boolean;
  error: unknown;
  selected: Record<string, string[]>;
  onChange: (next: Record<string, string[]>) => void;
  onRetry: () => void;
}) {
  if (loading) {
    return <Skeleton rows={1} label="Loading the filters" />;
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
  const selectedCount = Object.values(selected).reduce((n, v) => n + v.length, 0);

  const body = (
      <div className="space-y-3">
      {anySelected && (
        <button
          type="button"
          onClick={() => onChange({})}
          className={TEXT_ACTION}
        >
          Clear these filters
        </button>
      )}

      {facets.facets.map((facet) => (
        <fieldset key={facet.key} className="space-y-1.5">
          {/* A PERSISTENT VISIBLE LABEL for the group. `<legend>` rather than an
              aria-label, so it is readable by everyone and not only by axe. */}
          <legend className="text-meta font-medium text-ink">
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
                      : "flex cursor-pointer items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-muted hover:bg-ink/[0.04]"
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
        <p className="text-meta text-ink-faint">
          {formatCount(facets.omitted_field_count)} more capture{" "}
          {facets.omitted_field_count === 1 ? "field is" : "fields are"} filterable but not shown
          here — ask us to reorder your capture list if you need one of them.
        </p>
      )}
      </div>
  );
  if (bare) return body;

  return (
    /* DISCLOSED (UX-DOCTRINE §3): a filter used now and then, low consequence. Open by
       itself whenever a value is chosen, so a filter in force is never out of sight, and
       the closed state says how many fields it offers and how many are in use. */
    <Disclosure
      variant="inline"
      title="Filter by what your agent captured"
      subtitle={`${facets.facets.map((facet) => facet.label).join(", ")}${
        anySelected ? ` · ${selectedCount} chosen` : ""
      }`}
      defaultOpen={anySelected}
    >
      {body}
    </Disclosure>
  );
}
