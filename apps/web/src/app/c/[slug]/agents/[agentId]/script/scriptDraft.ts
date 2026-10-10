import type { CallScript } from "@/lib/api/script";

/**
 * How the builder's local draft follows the saved script underneath it.
 *
 * The builder edits a copy of what `GET /v1/agents/{id}/script` returned. That read is
 * refetched on focus, after every save and after anything else that invalidates it, and
 * the copy used to be taken ONCE, at mount (`useState(initial)`). So when the saved script
 * moved underneath an editor with no edits in it (a second tab, a knowledge recompile, a
 * rollback, a cached read replaced by a fresh one), the editor kept showing the old text,
 * and pressing Save wrote that old text over the newer version. The agent page then read
 * one opening line and the builder another, and the badge said "saved".
 *
 * The rule here: the server's copy wins whenever the author has nothing unsaved, and a save
 * adopts exactly what the server stored (it splits end-call rules, for one). When the author
 * HAS unsaved edits and the saved version moves, their edits are kept, the screen says so,
 * and the save carries the version they started from, which the server refuses if it moved.
 */

export interface SavedCopy {
  script: CallScript;
  version: number | null;
}

/** A fixed field order, so two scripts compare by content whatever order their keys arrived in. */
export function canonicalScript(script: CallScript): string {
  return JSON.stringify([
    script.opening_line,
    script.steps.map((step) => step.instruction),
    script.faqs.map((faq) => [faq.question, faq.answer]),
    script.faq_fallback,
    script.end_call_extra_rules,
    script.variables.map((v) => [v.key, v.label, v.example]),
    script.raw_override,
  ]);
}

export function sameScript(a: CallScript, b: CallScript): boolean {
  return canonicalScript(a) === canonicalScript(b);
}

export type Reconciled =
  /** Nothing new arrived. */
  | { kind: "unchanged" }
  /** Replace the editor with the server's copy. */
  | { kind: "adopt" }
  /** The author's own save came back while they kept typing: it becomes the new base. */
  | { kind: "rebase" }
  /** Keep the author's edits; the saved version is now `version`. */
  | { kind: "conflict"; version: number | null };

/**
 * What the editor does when a read arrives.
 *
 * `base` is the saved copy the local draft started from; `lastSave` is this editor's last
 * save (what it sent, and the version it became once the server answered), or null.
 */
export function reconcileDraft(
  local: CallScript,
  base: SavedCopy,
  incoming: SavedCopy,
  lastSave: SavedCopy | null,
): Reconciled {
  if (incoming.version === base.version && sameScript(incoming.script, base.script)) {
    return { kind: "unchanged" };
  }
  if (sameScript(local, base.script)) return { kind: "adopt" };
  // A null version is a save still in flight. The mutation refetches before it resolves,
  // so the read carrying this editor's own save arrives before its version number does;
  // the server's version check means no other writer's version can land in that window.
  if (lastSave !== null && (lastSave.version === null || incoming.version === lastSave.version)) {
    return sameScript(local, lastSave.script) ? { kind: "adopt" } : { kind: "rebase" };
  }
  return { kind: "conflict", version: incoming.version };
}
