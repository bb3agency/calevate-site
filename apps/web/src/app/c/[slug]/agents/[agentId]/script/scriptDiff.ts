import type { CallScript } from "@/lib/api/script";

import { sectionsOf, type Section } from "./scriptModel";
import { exampleLanguages, examplesIn } from "./stepExamples";

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

export type PartKey =
  | "business_line"
  | "identity"
  | "goal"
  | "outbound_purpose"
  | "opening_line"
  | "outbound_opening_line"
  | "faqs"
  | "style"
  | "objections"
  | "ending"
  | "step_outcomes"
  | "example_exchange"
  | "adherence";

export const PARTS: { key: PartKey; label: string }[] = [
  { key: "business_line", label: "Your business in one line" },
  { key: "identity", label: "Its role" },
  { key: "goal", label: "The goal" },
  { key: "outbound_purpose", label: "Why you are calling" },
  { key: "opening_line", label: "Opening line" },
  { key: "outbound_opening_line", label: "Opening line when it calls" },
  { key: "faqs", label: "Quick facts" },
  { key: "style", label: "How it talks" },
  { key: "objections", label: "When callers push back" },
  { key: "ending", label: "How it ends the call" },
  { key: "step_outcomes", label: "What each step must reach" },
  { key: "example_exchange", label: "Example call" },
  { key: "adherence", label: "How closely it follows the steps" },
];

export type Change =
  | { id: string; kind: "part"; part: PartKey; label: string; before: string; after: string }
  | { id: string; kind: "section-added"; label: string; after: Section; index: number }
  | { id: string; kind: "section-removed"; label: string; before: Section }
  | {
      id: string;
      kind: "section-changed";
      label: string;
      before: Section;
      after: Section;
      /** Only its name changed (its ways out compared by the steps they lead to). */
      renamed?: boolean;
    }
  /** The steps both scripts have, put in another order: its own row, so a move Pip made is
   *  seen and kept or not like any other change, never a silent reshuffle. */
  | { id: typeof ORDER_CHANGE; kind: "order"; label: string; before: string[]; after: string[] };

export const ORDER_CHANGE = "order";

/** A changed step whose only change is its name. */
export function renamedOnly(change: Change): boolean {
  if (change.kind !== "section-changed") return false;
  if (change.renamed !== undefined) return change.renamed;
  const { before, after } = change;
  const same = (s: Section) => sectionText({ ...s, name: "" }, new Map());
  return before.name.trim() !== after.name.trim() && same(before) === same(after);
}

export function partText(script: CallScript, key: PartKey): string {
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
    case "faqs":
      return (script.faqs ?? []).map((f) => `${f.question} → ${f.answer}`).join("\n");
    case "example_exchange":
      return (script.example_exchange ?? [])
        .map((l) => `${l.speaker === "caller" ? "Caller" : "Agent"}: ${l.text}`)
        .join("\n");
    case "step_outcomes":
      return (script.step_outcomes ?? [])
        .slice()
        .sort((a, b) => a.step - b.step)
        .map((o) => `Step ${o.step}: ${o.outcome}`)
        .join("\n");
    case "adherence":
      return script.adherence === "strict" ? "Follow closely" : "Use as a guide";
    default:
      return (script[key] ?? "").trim();
  }
}

/**
 * Text as a caller would hear it: runs of spaces and line breaks are one space. A model that
 * re-wraps a line or adds a trailing space has changed nothing anybody hears, and listing it
 * would bury the changes that matter among ones that do not.
 */
export function spoken(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** One sentence or line of a quote, with whatever followed it, and whether it is new to the
 *  other side of the comparison. */
export interface Segment {
  text: string;
  /** The space or line break after it, kept so the quote reads as it was written. */
  gap: string;
  changed: boolean;
}

/** Sentence ends in the scripts' languages: `.`, `?`, `!` and the Devanagari danda. */
const SENTENCE_GAP = /(?<=[.!?।])[ \t]+|\n+/g;

function splitSentences(text: string): { text: string; gap: string }[] {
  const out: { text: string; gap: string }[] = [];
  let at = 0;
  for (const match of text.matchAll(SENTENCE_GAP)) {
    out.push({ text: text.slice(at, match.index), gap: match[0] });
    at = (match.index ?? 0) + match[0].length;
  }
  out.push({ text: text.slice(at), gap: "" });
  return out.filter((s) => s.text !== "" || s.gap !== "");
}

/**
 * `text` cut into sentences and lines, each marked `changed` when `other` has no sentence
 * that says the same. What the review highlights inside a changed row: the step, question,
 * answer or closing sentence that is new or gone, rather than the whole quote.
 */
export function changedSegments(text: string, other: string): Segment[] {
  const said = new Set(splitSentences(other).map((s) => spoken(s.text)).filter(Boolean));
  return splitSentences(text).map((s) => ({
    ...s,
    changed: spoken(s.text) !== "" && !said.has(spoken(s.text)),
  }));
}

/**
 * The content of a section that matters to a caller (not its id or canvas position). A way
 * out is compared by the step it leads to: `targets` maps a step id to that step's identity
 * on the other side, so renaming a step does not read as a change to every step leading to it.
 */
function sectionText(section: Section, targets: Map<string, string>): string {
  const target = (t: string) => targets.get(t) ?? t;
  return JSON.stringify([
    spoken(section.name),
    section.mode,
    spoken(section.instruction),
    spoken(section.sounds_like),
    section.branches.map((b) => [spoken(b.when), target(b.target)]),
    section.otherwise ? target(section.otherwise) : "",
    section.collect,
    section.procedure.map((p) => [spoken(p.action), spoken(p.wait_for)]),
    exampleText(section),
  ]);
}

/** A step's examples as a caller hears them: blank lines (which the server drops) and
 * spacing do not count, so only a changed way of saying it lists the step as changed. */
function exampleText(section: Section): string[][] {
  return exampleLanguages(section.examples)
    .sort()
    .map((tag) => {
      const ex = examplesIn(section.examples, tag);
      if (!ex) return [tag];
      return [tag, ...ex.turns.map(spoken).filter(Boolean), spoken(ex.confused), spoken(ex.stuck), spoken(ex.busy)];
    });
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
    if (spoken(a) !== spoken(b)) changes.push({ id: `part:${key}`, kind: "part", part: key, label, before: a, after: b });
  }
  const was = sectionsOf(before);
  const now = sectionsOf(after);
  const matched = matchSections(was, now);
  // A suggested step's ways out, read as the owner's steps they lead to.
  const asBefore = new Map([...matched].map(([nowId, b]) => [nowId, b.id]));
  const matchedBefore = new Set([...matched.values()].map((s) => s.id));
  const asIs = new Map<string, string>();
  now.forEach((a, index) => {
    const b = matched.get(a.id);
    if (!b) {
      changes.push({ id: `add:${a.id}`, kind: "section-added", label: a.name.trim() || "New step", after: a, index });
    } else if (sectionText(b, asIs) !== sectionText(a, asBefore)) {
      const unnamed = (s: Section, targets: Map<string, string>) => sectionText({ ...s, name: "" }, targets);
      changes.push({
        id: `change:${b.id}`,
        kind: "section-changed",
        label: b.name.trim() || "Step",
        before: b,
        after: a,
        renamed: unnamed(b, asIs) === unnamed(a, asBefore),
      });
    }
  });
  for (const b of was) {
    if (!matchedBefore.has(b.id)) {
      changes.push({ id: `remove:${b.id}`, kind: "section-removed", label: b.name.trim() || "Step", before: b });
    }
  }
  // The steps both have, in each script's order: a step added or removed moves the others'
  // numbers without moving them, so only the relative order of these counts as a move.
  const keptOrder = now.flatMap((a) => {
    const b = matched.get(a.id);
    return b ? [b.id] : [];
  });
  const wasOrder = was.filter((b) => matchedBefore.has(b.id)).map((b) => b.id);
  if (keptOrder.join("\n") !== wasOrder.join("\n")) {
    changes.push({
      id: ORDER_CHANGE,
      kind: "order",
      label: "Order of the steps",
      before: was.map((s) => s.name.trim() || "Step"),
      after: now.map((s) => s.name.trim() || "Step"),
    });
  }
  return changes;
}

/**
 * Does keeping `change` take away something the owner has: a removed step, or a part the
 * suggestion leaves empty? Such rows start unticked, so one "Keep" never deletes the
 * owner's work they did not look at (A-04).
 */
export function removesContent(change: Change): boolean {
  if (change.kind === "section-removed") return true;
  return change.kind === "part" && change.before.trim() !== "" && change.after.trim() === "";
}

/** The rows ticked when a suggestion opens: every change but the ones that remove content. */
export function keptAtFirst(changes: readonly Change[]): Set<string> {
  return new Set(changes.filter((c) => !removesContent(c)).map((c) => c.id));
}

/**
 * `keptAtFirst`, unless keeping Pip's new steps without its removed ones would go over
 * `maxSections`: a rewrite that replaces steps then starts with the removals ticked too, so
 * the first "Add" is the script Pip wrote rather than one the server refuses.
 */
export function keptAtFirstWithin(
  current: CallScript,
  proposal: CallScript,
  changes: readonly Change[],
  maxSections: number,
): Set<string> {
  const first = keptAtFirst(changes);
  if (sectionsOf(applyChanges(current, proposal, first)).length <= maxSections) return first;
  for (const change of changes) if (change.kind === "section-removed") first.add(change.id);
  return first;
}

/**
 * The owner's script with only the kept changes applied. Ways out that point at a section
 * the result does not have are dropped (a discarded addition, a kept removal), so the
 * result is always a script the server accepts.
 *
 * `edited` is the proposal as the owner changed it in the review: which changes exist and
 * how sections match is still read from `proposal`, so renaming a suggested step cannot
 * turn it into a different change; only the values come from `edited`.
 */
export function applyChanges(
  current: CallScript,
  proposal: CallScript,
  kept: ReadonlySet<string>,
  edited: CallScript = proposal,
): CallScript {
  return applyTraced(current, proposal, kept, edited).script;
}

/**
 * `applyChanges`, plus where each kept suggested section landed: result section id ->
 * the section's id in the proposal, so a problem the builder's validation finds in the
 * result can be shown on the row that suggested it.
 */
export function applyTraced(
  current: CallScript,
  proposal: CallScript,
  kept: ReadonlySet<string>,
  edited: CallScript = proposal,
): { script: CallScript; from: Map<string, string> } {
  const changes = diffScripts(current, proposal).filter((c) => kept.has(c.id));
  const editedSections = new Map(sectionsOf(edited).map((s) => [s.id, s]));
  const valueOf = (s: Section) => editedSections.get(s.id) ?? s;
  const from = new Map<string, string>();
  let next: CallScript = { ...current };
  let sections = sectionsOf(current);
  // proposal id -> id in the result, so a kept branch between proposed sections lands right.
  const idMap = new Map<string, string>();
  const matched = matchSections(sectionsOf(current), sectionsOf(proposal));
  for (const [proposalId, existing] of matched) idMap.set(proposalId, existing.id);

  for (const change of changes) {
    if (change.kind === "part") {
      const part = change.part;
      next = { ...next, [part]: edited[part] } as CallScript;
      // Pip's record of the notice words it wove into an opening travels with that line;
      // the server counts it only while the line is unchanged (D-971).
      if (part === "opening_line") next = { ...next, opening_notices: proposal.opening_notices };
      if (part === "outbound_opening_line") {
        next = { ...next, outbound_opening_notices: proposal.outbound_opening_notices };
      }
    } else if (change.kind === "section-removed") {
      sections = sections.filter((s) => s.id !== change.before.id);
    }
  }
  for (const change of changes) {
    if (change.kind === "section-changed") {
      from.set(change.before.id, change.after.id);
      sections = sections.map((s) =>
        s.id === change.before.id ? { ...valueOf(change.after), id: s.id, position: s.position } : s,
      );
    } else if (change.kind === "section-added") {
      let id = change.after.id;
      const taken = new Set(sections.map((s) => s.id));
      for (let n = 2; taken.has(id); n += 1) id = `${change.after.id.slice(0, 36)}-${n}`;
      idMap.set(change.after.id, id);
      from.set(id, change.after.id);
      const at = Math.min(change.index, sections.length);
      sections = [...sections.slice(0, at), { ...valueOf(change.after), id, position: null }, ...sections.slice(at)];
    }
  }
  if (kept.has(ORDER_CHANGE)) {
    // The proposal's order, for every step that has a place in it; a step it does not have
    // (a removal left unticked) stays right after the step it followed.
    const rank = new Map(sectionsOf(proposal).map((s, i) => [s.id, i]));
    const proposalIdOf = new Map<string, string>(from);
    for (const [proposalId, existing] of matched) proposalIdOf.set(existing.id, proposalId);
    let last = -1;
    const keyed = sections.map((s, i) => {
      const at = rank.get(proposalIdOf.get(s.id) ?? "");
      last = at ?? last + 1e-3;
      return { s, key: at ?? last, i };
    });
    sections = keyed.sort((a, b) => a.key - b.key || a.i - b.i).map((k) => k.s);
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
  // An example the owner rewrote is their own reading of it, as in the builder.
  const exampleTouched = JSON.stringify(edited.example_exchange) !== JSON.stringify(proposal.example_exchange);
  return {
    script: {
      ...next,
      stages: sections,
      schema_version: 2,
      raw_override: null,
      example_needs_review: exampleKept
        ? proposal.example_needs_review && edited.example_needs_review && !exampleTouched
        : current.example_needs_review,
    },
    from,
  };
}

/** One line for the history, from what changed between the live script and the draft. */
export function changeSummary(live: CallScript, draft: CallScript): string {
  if (draft.raw_override !== null && live.raw_override === null) return "Switched to a hand-written script";
  if (draft.raw_override === null && live.raw_override !== null) return "Turned the hand-written script into steps";
  if (draft.raw_override !== null) return "Edited the hand-written script";
  const changes = diffScripts(live, draft);
  if (changes.length === 0) {
    const order = (x: CallScript) => sectionsOf(x).map((st) => st.id).join(" ");
    return order(live) === order(draft) ? "Tidied the flow picture" : "Changed the order of the steps";
  }
  const words = changes.map((c) =>
    c.kind === "section-added"
      ? `added "${c.label}"`
      : c.kind === "section-removed"
        ? `removed "${c.label}"`
        : c.kind === "section-changed"
          ? renamedOnly(c)
            ? `renamed "${c.label}" to "${c.after.name.trim()}"`
            : `changed "${c.label}"`
          : c.kind === "order"
            ? "changed the order of the steps"
            : `changed ${c.label.toLowerCase()}`,
  );
  const line = words.slice(0, 3).join(", ") + (words.length > 3 ? ` and ${words.length - 3} more` : "");
  const sentence = line.charAt(0).toUpperCase() + line.slice(1);
  return sentence.length > 200 ? `${sentence.slice(0, 197)}...` : sentence;
}
