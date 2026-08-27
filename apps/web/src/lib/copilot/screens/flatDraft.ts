"use client";

import type { CopilotField, CopilotFillItem, CopilotSurface } from "../types";

/**
 * The declaration for a screen whose form is ONE flat object of strings — which is what
 * the three admin record forms are: commercial terms, the KYC record, and a credit
 * top-up all keep every answer as a string in a single `useState` draft, because that is
 * what crosses the wire (hard rule 7: money is a decimal string, never a float).
 *
 * Three screens with one shape is exactly the case for one helper rather than three
 * hand-written surfaces: the alternative is three copies of the same `apply` loop, and
 * the second copy is where one of them starts silently ignoring a field somebody added
 * to its draft.
 *
 * ## What the spec buys over deriving the fields from the object's keys
 *
 * A label, a type, and — the one that matters — a decision about whether the value is
 * personal data. None of those is inferable from a key name, and guessing the last one is
 * the failure that sends a director's PAN to a model. So the screen writes the list out,
 * and the `key` is checked against the draft's own type by the compiler.
 */
/**
 * The members of a draft that hold a STRING, as a union of their names.
 *
 * The constraint used to be `T extends Record<string, string>`, which every one of these
 * drafts satisfies in spirit and none satisfies to the compiler — an `interface` has no
 * index signature, so a perfectly all-string `Draft` was rejected. This says the thing
 * actually required (each named member is a string) and, as a bonus, refuses a spec that
 * names a member the draft holds as something else.
 */
export type StringKeys<T> = Extract<
  { [K in keyof T]-?: T[K] extends string ? K : never }[keyof T],
  string
>;

export interface FlatFieldSpec<K extends string> {
  /** The control's DOM id, which is also the copilot field id. */
  id: string;
  /** The draft member this control edits — type-checked against the draft. */
  key: K;
  label: string;
  type: CopilotField["type"];
  options?: CopilotField["options"];
  help?: string;
  personal?: CopilotField["personal"];
  writable?: boolean;
}

export function flatDraftSurface<T>(
  meta: { route: string; title: string; realm: "client" | "admin" },
  draft: T,
  specs: readonly FlatFieldSpec<StringKeys<T>>[],
  onChange: (next: T) => void,
  facts: CopilotSurface["facts"] = [],
): CopilotSurface {
  const byId = new Map(specs.map((spec) => [spec.id, spec]));
  return {
    ...meta,
    fields: specs.map((spec) => ({
      id: spec.id,
      label: spec.label,
      type: spec.type,
      // `StringKeys` guarantees this member is a string; TypeScript cannot narrow the
      // indexed access through the mapped type, so the assertion states what the
      // constraint has already proved rather than papering over an unknown.
      value: draft[spec.key] as string,
      options: spec.options ?? null,
      help: spec.help ?? null,
      personal: spec.personal,
      writable: spec.writable ?? true,
    })),
    facts,
    apply: (items: CopilotFillItem[]) => {
      // ONE object, ONE call. Six `set(key, value)` calls against a captured draft would
      // keep the last and lose five — the reason `apply` takes the whole batch.
      const next = { ...draft };
      let changed = false;
      for (const item of items) {
        const spec = byId.get(item.field_id);
        if (spec === undefined) continue;
        // A `select` may only receive a value it offers. The model is sent the list, so
        // this is a guard against a wrong answer rather than a translation — and the
        // alternative is a control holding a value its own options do not contain, which
        // renders as blank and submits as garbage.
        if (spec.options && !spec.options.some((option) => option.value === item.value)) continue;
        next[spec.key] = item.value as T[StringKeys<T>];
        changed = true;
      }
      if (changed) onChange(next);
    },
  };
}
