import type { CallScript } from "@/lib/api/script";

import { sectionsOf, type Section } from "./scriptModel";

/**
 * AN AI PROPOSAL AS A LIST OF CHANGES THE OWNER KEEPS OR DISCARDS ONE BY ONE.
 *
 * The helper and the hand-written conversion both return a whole script. Replacing the
 * owner's script with it would throw away every part they did not ask to change, so the
 * proposal is compared part by part and section by section, and only the changes they keep
 * are applied. Sections are matched by id first and then by name, because a model asked to
 * change one section often re-mints every id.
 *
 * The same comparison writes the one-line "what changed" note for "Put it live".
 */

type PartKey =
  | "business_line"
  | "identity"
  | "goal"
  | "outbound_purpose"
  | "opening_line"
  | "style"
  | "objections"
  | "ending"
  | "example_exchange"
  | "adherence";

const PARTS: { key: PartKey; label: string }[] = [
  { key: "business_line", label: "Your business in one line" },
  { key: "identity", label: "Its role" },
  { key: "goal", label: "The goal" },
  { key: "outbound_purpose", label: "Why you are calling" },
  { key: "opening_line", label: "Opening line" },
  { key: "style", label: "How it talks" },
  { key: "objections", label: "When callers push back" },
  { key: "ending", label: "How it ends the call" },
  { key: "example_exchange", label: "Example call" },
  { key: "adherence", label: "How closely it follows the sections" },
];

export type Change =
  | { id: string; kind: "part"; part: PartKey; label: string; before: string; after: string }
  | { id: string; kind: "section-added"; label: string; after: Section; index: number }
  | { id: string; kind: "section-removed"; label: string; before: Section }
  | { id: string; kind: "section-changed"; label: string; before: Section; after: Section };

function partText(script: CallScript, key: PartKey): string {
  switch (key) {
    case "style": {
      const s = script.style;
      if (!s) return "";
      return [
        s.tone && `Tone: ${s.tone}`,
        s.address_form && `Calls them: ${s.address_form}`,
        `English words: ${s.code_mix}`,
        ...s.sample_phrases.map((p) => `"${p}"`),
        ...s.pronunciations.map((p) => `${p.word} → ${p.say_as}`),
      ]
        .filter(Boolean)
        .join("\n");
    }
    case "objections":
      return (script.objections ?? []).map((o) => `${o.objection} → ${o.response}`).join("\n");
    case "example_exchange":
      return (script.example_exchange ?? [])
        .map((l) => `${l.speaker === "caller" ? "Caller" : "Agent"}: ${l.text}`)
        .join("\n");
    case "adherence":
      return script.adherence === "strict" ? "Follow closely" : "Use as a guide";
    default:
      return (script[key] ?? "").trim();
  }
}

/** The content of a section that matters to a caller (not its id or canvas position). */
function sectionText(section: Section, names: Map<string, string>): string {
  const target = (t: string) => names.get(t) ?? t;
  return JSON.stringify([
    section.name.trim(),
    section.mode,
    section.instruction.trim(),
    section.sounds_like.trim(),
    section.branches.map((b) => [b.when.trim(), target(b.target)]),
    section.otherwise ? target(section.otherwise) : "",
    section.collect,
  ]);
}

function matchSections(before: Section[], after: Section[]): Map<string, Section> {
  // after.id -> the section in `before` it replaces
  const out = new Map<string, Section>();
  const used = new Set<string>();
  for (const a of after) {
    const byId = before.find((b) => b.id === a.id && !used.has(b.id));
    const byName =
      byId ?? before.find((b) => !used.has(b.id) && b.name.trim().toLowerCase() === a.name.trim().toLowerCase());
    if (byName) {
      out.set(a.id, byName);
      used.add(byName.id);
    }
  }
  return out;
}

export function diffScripts(before: CallScript, after: CallScript): Change[] {
  const changes: Change[] = [];
  for (const { key, label } of PARTS) {
    const a = partText(before, key);
    const b = partText(after, key);
    if (a !== b) changes.push({ id: `part:${key}`, kind: "part", part: key, label, before: a, after: b });
  }
  const was = sectionsOf(before);
  const now = sectionsOf(after);
  const wasNames = new Map(was.map((s) => [s.id, s.name.trim()]));
  const nowNames = new Map(now.map((s) => [s.id, s.name.trim()]));
  const matched = matchSections(was, now);
  const matchedBefore = new Set([...matched.values()].map((s) => s.id));
  now.forEach((a, index) => {
    const b = matched.get(a.id);
    if (!b) {
      changes.push({ id: `add:${a.id}`, kind: "section-added", label: a.name.trim() || "New section", after: a, index });
    } else if (sectionText(b, wasNames) !== sectionText(a, nowNames)) {
      changes.push({ id: `change:${b.id}`, kind: "section-changed", label: b.name.trim() || "Section", before: b, after: a });
    }
  });
  for (const b of was) {
    if (!matchedBefore.has(b.id)) {
      changes.push({ id: `remove:${b.id}`, kind: "section-removed", label: b.name.trim() || "Section", before: b });
    }
  }
  return changes;
}

/**
 * The owner's script with only the kept changes applied. Ways out that point at a section
 * the result does not have are dropped (a discarded addition, a kept removal), so the
 * result is always a script the server accepts.
 */
export function applyChanges(current: CallScript, proposal: CallScript, kept: ReadonlySet<string>): CallScript {
  const changes = diffScripts(current, proposal).filter((c) => kept.has(c.id));
  let next: CallScript = { ...current };
  let sections = sectionsOf(current);
  // proposal id -> id in the result, so a kept branch between proposed sections lands right.
  const idMap = new Map<string, string>();
  const matched = matchSections(sectionsOf(current), sectionsOf(proposal));
  for (const [proposalId, existing] of matched) idMap.set(proposalId, existing.id);

  for (const change of changes) {
    if (change.kind === "part") {
      const part = change.part;
      next = { ...next, [part]: proposal[part] } as CallScript;
    } else if (change.kind === "section-removed") {
      sections = sections.filter((s) => s.id !== change.before.id);
    }
  }
  for (const change of changes) {
    if (change.kind === "section-changed") {
      sections = sections.map((s) =>
        s.id === change.before.id ? { ...change.after, id: s.id, position: s.position } : s,
      );
    } else if (change.kind === "section-added") {
      let id = change.after.id;
      const taken = new Set(sections.map((s) => s.id));
      for (let n = 2; taken.has(id); n += 1) id = `${change.after.id.slice(0, 36)}-${n}`;
      idMap.set(change.after.id, id);
      const at = Math.min(change.index, sections.length);
      sections = [...sections.slice(0, at), { ...change.after, id, position: null }, ...sections.slice(at)];
    }
  }
  const ids = new Set(sections.map((s) => s.id));
  const keep = (t: string) => {
    if (t === "end" || t === "hand_over" || t === "call_back") return t;
    const mapped = idMap.get(t) ?? t;
    return ids.has(mapped) ? mapped : null;
  };
  sections = sections.map((s) => ({
    ...s,
    otherwise: s.otherwise ? (keep(s.otherwise) ?? "") : "",
    branches: s.branches.flatMap((b) => {
      const target = keep(b.target);
      return target ? [{ ...b, target }] : [];
    }),
  }));
  const exampleKept = kept.has("part:example_exchange");
  return {
    ...next,
    stages: sections,
    schema_version: 2,
    raw_override: null,
    example_needs_review: exampleKept ? proposal.example_needs_review : current.example_needs_review,
  };
}

/** One line for the history, from what changed between the live script and the draft. */
export function changeSummary(live: CallScript, draft: CallScript): string {
  if (draft.raw_override !== null && live.raw_override === null) return "Switched to a hand-written script";
  if (draft.raw_override === null && live.raw_override !== null) return "Turned the hand-written script into sections";
  if (draft.raw_override !== null) return "Edited the hand-written script";
  const changes = diffScripts(live, draft);
  if (changes.length === 0) {
    const order = (x: CallScript) => sectionsOf(x).map((st) => st.id).join(" ");
    return order(live) === order(draft) ? "Tidied the flow picture" : "Changed the order of the sections";
  }
  const words = changes.map((c) =>
    c.kind === "section-added"
      ? `added "${c.label}"`
      : c.kind === "section-removed"
        ? `removed "${c.label}"`
        : c.kind === "section-changed"
          ? `changed "${c.label}"`
          : `changed ${c.label.toLowerCase()}`,
  );
  const line = words.slice(0, 3).join(", ") + (words.length > 3 ? ` and ${words.length - 3} more` : "");
  const sentence = line.charAt(0).toUpperCase() + line.slice(1);
  return sentence.length > 200 ? `${sentence.slice(0, 197)}...` : sentence;
}
