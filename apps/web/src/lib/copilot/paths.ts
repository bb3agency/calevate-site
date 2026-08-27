/**
 * Applying a batch of fills to a screen that holds ONE typed draft object.
 *
 * This is the good path and the one most registered screens use: the intake sheet, the
 * commercial terms, the KYC record, the credit top-up, the extraction field list and the
 * call script all keep their answers in a single `useState` object, so a fill is an
 * ordinary immutable update and React re-renders from it. Nothing here touches the DOM,
 * so nothing here can be defeated by a control that does not listen on `input` — which is
 * the whole class of bug `dom.ts` has to work around and this path simply does not have.
 *
 * ## The path grammar, and why it is `intakeFieldId`'s
 *
 * `services.1.price_inr` — dots for members, a bare integer for an array index. It is the
 * WIRE path `lib/api/intake.ts` already derives its DOM ids from
 * (`intakeFieldId("services.1.price_inr") === "intake-services-1-price_inr"`), so a screen
 * that already has one semantic addressing scheme does not acquire a second.
 *
 * ## What it refuses to do
 *
 * It never CREATES a missing member or grows an array. A fill naming `services.9.name` on
 * a draft with two services is a fill for a row that does not exist, and inventing the row
 * — with every sibling field blank — would put a half-empty service on a form somebody is
 * about to submit. It returns the draft unchanged instead, and the panel reports fewer
 * fields filled than were offered, which is the truthful outcome.
 */

import type { CopilotFillItem } from "./types";

import { hasKey, lookup } from "@/lib/lookup";

type Unknown = Record<string, unknown>;

function isIndex(segment: string): boolean {
  return /^\d+$/.test(segment);
}

/**
 * `draft` with ONE path set to `value`, structurally shared everywhere else.
 *
 * Returns the ORIGINAL object (identity included) when the path does not exist, so a
 * caller can tell "applied" from "not applied" by identity and a React state setter
 * handed an unchanged object does not re-render.
 */
export function setByPath<T>(draft: T, path: string, value: unknown): T {
  const segments = path.split(".");
  const walk = (node: unknown, at: number): { node: unknown; changed: boolean } => {
    const segment = segments[at];
    const last = at === segments.length - 1;

    if (Array.isArray(node)) {
      if (!isIndex(segment)) return { node, changed: false };
      const index = Number(segment);
      if (index < 0 || index >= node.length) return { node, changed: false };
      if (last) {
        const copy = node.slice();
        copy[index] = value;
        return { node: copy, changed: true };
      }
      const inner = walk(node[index], at + 1);
      if (!inner.changed) return { node, changed: false };
      const copy = node.slice();
      copy[index] = inner.node;
      return { node: copy, changed: true };
    }

    if (node === null || typeof node !== "object") return { node, changed: false };
    const record = node as Unknown;
    // `hasKey` (which is `Object.hasOwn`) rather than `!== undefined` OR `in`, and both
    // halves matter. Against `undefined`: a member that is present and holds `undefined`
    // is still a member of this draft, and an optional field that is currently unset is
    // exactly the field a fill is most likely to be for. Against `in`: it walks the
    // prototype chain, so a path segment of `constructor` — which arrives from the WIRE —
    // would report as present and the walk would descend into `Object`
    // (src/lib/lookup.ts; the repo's lint rule enforces this).
    if (!hasKey(record, segment)) return { node, changed: false };
    if (last) return { node: { ...record, [segment]: value }, changed: true };
    // `lookup` and not `record[segment]` for the same reason as the guard above — the
    // repo's one way of reading a table with a wire-supplied key (`tests/
    // wireLookupGuard.test.ts` enforces it AST-wide, not by regex).
    const inner = walk(lookup(record, segment), at + 1);
    if (!inner.changed) return { node, changed: false };
    return { node: { ...record, [segment]: inner.node }, changed: true };
  };

  const result = walk(draft, 0);
  return result.changed ? (result.node as T) : draft;
}

/**
 * A whole batch, in ONE pass — which is the reason this exists at all rather than callers
 * folding `setByPath` themselves. Six sequential `setState` calls against a captured
 * draft lose five of them, and that is not a theoretical race: `apply` is called once
 * with the whole batch precisely so the screen can do this.
 *
 * `coerce` is how a screen converts the wire's strings into its own draft's types — a
 * count that must be a number, a checkbox that must be a boolean. It is per-path because
 * a draft has both kinds; returning the string unchanged is the common case.
 */
export function applyByPaths<T>(
  draft: T,
  // THE WIRE ITEM, not a string-valued copy of it. The server types each filled value to
  // the field's own declared `type` and has already validated it against that type and,
  // for a select, against its option list. Re-parsing here would be a second
  // implementation of a decision already taken — and the string-typing it replaced
  // (`value === "true"`) reads `true` as `false` the moment a real boolean arrives.
  items: CopilotFillItem[],
  toPath: (fieldId: string) => string | null,
  coerce: (path: string, value: unknown) => unknown = (_path, value) => value,
): T {
  let next = draft;
  for (const item of items) {
    const path = toPath(item.field_id);
    if (path === null) continue;
    next = setByPath(next, path, coerce(path, item.value));
  }
  return next;
}
