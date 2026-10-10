import type { CallScript, ScriptOut } from "@/lib/api/script";

/**
 * How the builder's working copy follows the saved one underneath it, and what the save
 * line says.
 *
 * The builder edits a copy of the agent's DRAFT (`GET .../script` → `draft.script`, or the
 * saved script when there is no draft). That read is refetched on focus, after "Put it
 * live", after a restore, and whenever anything else invalidates it; a copy taken once at
 * mount would keep showing old text and autosave it over newer work. So:
 *
 * - with nothing unsaved, the server's copy wins;
 * - this editor's own save coming back is its own, even before the stamp is known;
 * - with unsaved edits and somebody else's newer copy, the edits are kept and the screen
 *   offers both ways out. The autosave carries the stamp it started from
 *   (`base_saved_at`), and the server refuses a stale one with `script_changed_elsewhere`.
 */

export interface SavedCopy {
  script: CallScript;
  /** Identifies one stored copy: the draft's `saved_at`, else the saved version. Null
   *  while this editor's own save is in flight. */
  stamp: string | null;
  /** The draft's `saved_at`, sent back as `base_saved_at`; null when there is no draft. */
  savedAt: string | null;
}

/** The copy the builder edits, from one read. */
export function workingCopy(out: ScriptOut): SavedCopy {
  if (out.draft) {
    return { script: out.draft.script, stamp: `d:${out.draft.saved_at}`, savedAt: out.draft.saved_at };
  }
  return { script: out.script, stamp: `v:${out.version ?? "none"}`, savedAt: null };
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
    script.schema_version ?? 1,
    script.business_line ?? "",
    script.identity ?? "",
    script.goal ?? "",
    script.outbound_purpose ?? "",
    script.style
      ? [
          script.style.tone,
          script.style.address_form,
          script.style.code_mix,
          script.style.sample_phrases,
          script.style.pronunciations.map((p) => [p.word, p.say_as]),
        ]
      : null,
    (script.stages ?? []).map((s) => [
      s.id,
      s.name,
      s.mode ?? "guide",
      s.instruction,
      s.sounds_like ?? "",
      (s.branches ?? []).map((b) => [b.when, b.target]),
      s.otherwise ?? "",
      s.collect ?? [],
      s.position ? [s.position.x, s.position.y] : null,
    ]),
    (script.objections ?? []).map((o) => [o.objection, o.response]),
    script.policies
      ? [script.policies.offer_call_backs, script.policies.share_prices, script.policies.take_bookings]
      : null,
    script.ending ?? "",
    (script.example_exchange ?? []).map((l) => [l.speaker, l.text]),
    script.example_needs_review ?? false,
    script.adherence ?? "flexible",
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
  /** The editor's own save came back while the owner kept typing: it becomes the new base. */
  | { kind: "rebase" }
  /** Keep the owner's edits; somebody else's copy is now the stored one. */
  | { kind: "conflict" };

/**
 * What the editor does when a read arrives. `base` is the stored copy the local edits
 * started from; `lastSave` is this editor's last save (what it sent, and the stamp it
 * became once the server answered), or null.
 */
export function reconcileDraft(
  local: CallScript,
  base: SavedCopy,
  incoming: SavedCopy,
  lastSave: SavedCopy | null,
): Reconciled {
  if (incoming.stamp === base.stamp && sameScript(incoming.script, base.script)) {
    return { kind: "unchanged" };
  }
  if (sameScript(local, base.script)) return { kind: "adopt" };
  if (lastSave !== null && (lastSave.stamp === null || incoming.stamp === lastSave.stamp)) {
    return sameScript(local, lastSave.script) ? { kind: "adopt" } : { kind: "rebase" };
  }
  if (sameScript(local, incoming.script)) return { kind: "adopt" };
  return { kind: "conflict" };
}

/** How long typing must pause before the draft is saved. */
export const AUTOSAVE_DELAY_MS = 1200;

export type SaveState =
  | { kind: "clean"; savedAt: string | null }
  | { kind: "waiting" }
  | { kind: "saving" }
  | { kind: "held"; reason: string }
  | { kind: "conflict" }
  | { kind: "failed" }
  | { kind: "read-only" };

/** The one save line under the builder's title, from what the editor knows. */
export function saveState(input: {
  dirty: boolean;
  saving: boolean;
  canWrite: boolean;
  conflict: boolean;
  failed: boolean;
  issueCount: number;
  savedAt: string | null;
}): SaveState {
  if (!input.canWrite) return { kind: "read-only" };
  if (input.conflict) return { kind: "conflict" };
  if (input.saving) return { kind: "saving" };
  if (!input.dirty) return { kind: "clean", savedAt: input.savedAt };
  if (input.issueCount > 0) {
    return {
      kind: "held",
      reason:
        input.issueCount === 1
          ? "Not saved yet: one part needs finishing."
          : `Not saved yet: ${input.issueCount} parts need finishing.`,
    };
  }
  if (input.failed) return { kind: "failed" };
  return { kind: "waiting" };
}

/** True when there is something to put live: the draft differs from what is saved, or a
 *  saved change is still waiting to be applied. */
export function hasUnpublished(out: ScriptOut, local: CallScript): boolean {
  if (out.version === null) return hasContent(local);
  return out.has_pending || !sameScript(local, out.script);
}

/** Anything an owner wrote, in either mode. */
export function hasContent(script: CallScript): boolean {
  if (script.raw_override !== null) return script.raw_override.trim() !== "";
  return Boolean(
    script.opening_line.trim() ||
      script.business_line?.trim() ||
      script.identity?.trim() ||
      script.goal?.trim() ||
      (script.stages ?? []).length ||
      script.steps.length,
  );
}
