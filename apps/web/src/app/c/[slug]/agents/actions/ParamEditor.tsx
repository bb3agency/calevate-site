"use client";

/**
 * The values an action sends: one row per value, hairlines between them (REDESIGN-2).
 *
 * Each row is its name, where the value comes from, and the one second field that source
 * needs: what the agent should work out, which detail of the lead, or the fixed value.
 * Showing only the field that can apply is progressive disclosure at field scale; three
 * fields where one applies is three chances to fill in the wrong one. The wire values of
 * the source (`ai`, `lead_var`, `static`) are unchanged; only the words are ours.
 */

import { X } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { FIELD, FIELD_HINT, FIELD_LABEL, QUIET_ICON_BUTTON } from "@/components/ui";

import { leadVarOptions, newParam, type CapturedField, type DraftParam } from "./params";

const SOURCES: { value: DraftParam["source"]; label: string; hint: string }[] = [
  {
    value: "ai",
    label: "The agent works it out",
    hint: "Your agent asks the caller for it, or takes it from what they have said.",
  },
  {
    value: "lead_var",
    label: "From the lead",
    hint: "Filled in from this call, or from what your agent captured about this caller before.",
  },
  { value: "static", label: "A fixed value", hint: "The same value is sent every time." },
];

export function ParamEditor({
  params,
  onChange,
  fields = [],
}: {
  params: DraftParam[];
  onChange: (p: DraftParam[]) => void;
  /** The details this agent captures, offered by label under "From the lead". */
  fields?: readonly CapturedField[];
}) {
  const patch = (index: number, next: Partial<DraftParam>) =>
    onChange(params.map((q, j) => (j === index ? { ...q, ...next } : q)));

  return (
    <div>
      <p className="text-body font-medium text-ink">Values it sends</p>
      {params.length === 0 ? (
        <p className="mt-1 text-meta text-ink-muted">No values yet.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line border-y border-line">
          {params.map((p, i) => {
            const source = SOURCES.find((s) => s.value === p.source) ?? SOURCES[0]!;
            const name = p.name.trim() || `value ${i + 1}`;
            return (
              <li key={i} className="py-4">
                <div className="flex items-end gap-3">
                  <label className="min-w-0 flex-1">
                    <span className={FIELD_LABEL}>Name</span>
                    <input
                      className={FIELD}
                      value={p.name}
                      placeholder="order_id"
                      aria-label={`Parameter ${i + 1} name`}
                      onChange={(e) => patch(i, { name: e.target.value })}
                    />
                  </label>
                  <label className="min-w-0 flex-1">
                    <span className={FIELD_LABEL}>Where it comes from</span>
                    <select
                      className={FIELD}
                      value={p.source}
                      aria-label={`Parameter ${i + 1} value comes from`}
                      onChange={(e) => patch(i, { source: e.target.value as DraftParam["source"] })}
                    >
                      {SOURCES.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={() => onChange(params.filter((_, j) => j !== i))}
                    aria-label={`Remove ${name}`}
                    className={`${QUIET_ICON_BUTTON} mb-0.5`}
                  >
                    <X aria-hidden className="h-4 w-4" />
                  </button>
                </div>
                <p className={FIELD_HINT}>{source.hint}</p>

                <div className="mt-3">
                  {p.source === "static" ? (
                    <label className="block">
                      <span className={FIELD_LABEL}>Value</span>
                      <input
                        className={FIELD}
                        value={p.value}
                        aria-label={`Parameter ${i + 1} static value`}
                        onChange={(e) => patch(i, { value: e.target.value })}
                      />
                    </label>
                  ) : p.source === "lead_var" ? (
                    <label className="block">
                      <span className={FIELD_LABEL}>Which detail</span>
                      <select
                        className={FIELD}
                        value={p.lead_var}
                        aria-label={`Parameter ${i + 1} lead variable`}
                        onChange={(e) => patch(i, { lead_var: e.target.value })}
                      >
                        {leadVarOptions(fields, p.lead_var).map((v) => (
                          <option key={v.value} value={v.value}>
                            {v.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : (
                    <label className="block">
                      <span className={FIELD_LABEL}>What the agent should collect</span>
                      <input
                        className={FIELD}
                        value={p.description}
                        placeholder="The caller's order number"
                        aria-label={`Parameter ${i + 1} — what the AI should collect`}
                        onChange={(e) => patch(i, { description: e.target.value })}
                      />
                    </label>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <button type="button" className={`${TEXT_ACTION} mt-3`} onClick={() => onChange([...params, newParam()])}>
        + Add a parameter
      </button>
    </div>
  );
}
