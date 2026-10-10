import type { ScriptContext } from "@/lib/api/script";

import { CALL_BACK, END, HAND_OVER, type Section } from "./scriptModel";

/** Words shared by the canvas, the list and the editor, so one target reads one way. */

export function sectionLabel(sections: Section[], id: string): string {
  const i = sections.findIndex((s) => s.id === id);
  if (i < 0) return "a section that is not there";
  return `${i + 1}. ${sections[i].name.trim() || "Untitled section"}`;
}

export function targetLabel(sections: Section[], target: string, context: ScriptContext | null): string {
  if (target === END) return "End the call";
  if (target === HAND_OVER) {
    return context && !context.hand_over_enabled ? "Hand to a person (off: says nobody is free)" : "Hand to a person";
  }
  if (target === CALL_BACK) {
    return context && !context.call_backs_available
      ? "Offer a call back (not on your trial)"
      : "Offer a call back";
  }
  return sectionLabel(sections, target);
}

/** Where a section goes when no branch holds, in words. */
export function thenLabel(sections: Section[], index: number, context: ScriptContext | null): string {
  const s = sections[index];
  if (s.otherwise) return targetLabel(sections, s.otherwise, context);
  const next = sections[index + 1];
  return next ? sectionLabel(sections, next.id) : "Wraps up the call";
}

export function targetOptions(
  sections: Section[],
  selfId: string,
  context: ScriptContext | null,
): { value: string; label: string }[] {
  return [
    ...sections.filter((s) => s.id !== selfId).map((s) => ({ value: s.id, label: sectionLabel(sections, s.id) })),
    ...[END, HAND_OVER, CALL_BACK].map((t) => ({ value: t, label: targetLabel(sections, t, context) })),
  ];
}

/** The call's language in words, from the agent's language code. */
export function languageName(code: string | undefined): string {
  const base = (code ?? "").toLowerCase().split(/[-_]/)[0];
  const names: Record<string, string> = {
    te: "Telugu",
    hi: "Hindi",
    ta: "Tamil",
    kn: "Kannada",
    ml: "Malayalam",
    mr: "Marathi",
    bn: "Bengali",
    gu: "Gujarati",
    en: "English",
  };
  return names[base] ?? "your callers' language";
}
