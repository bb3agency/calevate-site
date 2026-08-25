"use client";

/**
 * The parameter list on a new action — name, where the value comes from, and the value.
 *
 * Split out of `Actions.tsx` (UX-DOCTRINE §6). The three sources are the founder's spec's:
 * ✨ AI-decided, `</>` a lead/call variable, or a static value. Which second control
 * appears is a function of the source, which is progressive disclosure at field scale —
 * three fields where only one can ever apply is three chances to fill in the wrong one.
 */

import { Plus, Trash2 } from "lucide-react";

import { DANGER_BUTTON, FIELD, FIELD_HINT, SECONDARY_BUTTON_SM } from "@/components/ui";

import { LEAD_VARS, newParam, type DraftParam } from "./params";

export function ParamEditor({
  params,
  onChange,
}: {
  params: DraftParam[];
  onChange: (p: DraftParam[]) => void;
}) {
  const patch = (index: number, next: Partial<DraftParam>) =>
    onChange(params.map((q, j) => (j === index ? { ...q, ...next } : q)));

  return (
    <div className="space-y-2 rounded-card border border-line bg-surface p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-ink">Parameters</span>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          onClick={() => onChange([...params, newParam()])}
        >
          <Plus className="mr-1 inline h-3.5 w-3.5" /> Add parameter
        </button>
      </div>
      {params.length === 0 ? <p className={FIELD_HINT}>No parameters yet.</p> : null}
      {params.map((p, i) => (
        <div key={i} className="space-y-1 rounded border border-line p-2">
          <div className="flex gap-2">
            <input
              className={FIELD}
              value={p.name}
              placeholder="name"
              aria-label={`Parameter ${i + 1} name`}
              onChange={(e) => patch(i, { name: e.target.value })}
            />
            <select
              className={FIELD}
              value={p.source}
              aria-label={`Parameter ${i + 1} value comes from`}
              onChange={(e) => patch(i, { source: e.target.value as DraftParam["source"] })}
            >
              <option value="ai">✨ AI decides</option>
              <option value="lead_var">&lt;/&gt; Lead variable</option>
              <option value="static">Static value</option>
            </select>
            <button
              type="button"
              className={DANGER_BUTTON}
              onClick={() => onChange(params.filter((_, j) => j !== i))}
              aria-label="Remove parameter"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
          {p.source === "static" ? (
            <input
              className={FIELD}
              value={p.value}
              placeholder="value"
              aria-label={`Parameter ${i + 1} static value`}
              onChange={(e) => patch(i, { value: e.target.value })}
            />
          ) : null}
          {p.source === "lead_var" ? (
            <select
              className={FIELD}
              value={p.lead_var}
              aria-label={`Parameter ${i + 1} lead variable`}
              onChange={(e) => patch(i, { lead_var: e.target.value })}
            >
              {LEAD_VARS.map((v) => (
                <option key={v.value} value={v.value}>
                  {v.label}
                </option>
              ))}
            </select>
          ) : null}
          {p.source === "ai" ? (
            <input
              className={FIELD}
              value={p.description}
              placeholder="What should the AI collect? (e.g. the order id)"
              aria-label={`Parameter ${i + 1} — what the AI should collect`}
              onChange={(e) => patch(i, { description: e.target.value })}
            />
          ) : null}
        </div>
      ))}
    </div>
  );
}
