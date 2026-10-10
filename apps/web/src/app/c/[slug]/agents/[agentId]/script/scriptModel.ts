import type { CallScript, ConversationStage, ScriptContext } from "@/lib/api/script";
import { lookup } from "@/lib/lookup";

/**
 * THE ONE MODEL behind the flow canvas and the numbered list.
 *
 * Both views read and write `script.stages` and nothing else: the list's numbers are the
 * array order, the canvas's numbers are the same order, a branch is `{when, target}` on the
 * stage it leaves, and `otherwise` empty means "the next section in order". Canvas x/y is
 * `position`, which the server stores and never compiles. So there is no second structure
 * to keep in step, and an edit in either view is already an edit in the other.
 *
 * Every function here is pure: a script in, a script out. The limits mirror
 * `calevate_shared.call_script` (the server refuses a draft that breaks them, so the
 * builder holds the autosave and says why instead of sending a save that would bounce).
 */

export const END = "end";
export const HAND_OVER = "hand_over";
export const CALL_BACK = "call_back";
export const SPECIAL_TARGETS = [END, HAND_OVER, CALL_BACK] as const;

export interface Limits {
  maxSections: number;
  nameMax: number;
  detailMax: number;
  soundsLikeMax: number;
  maxBranches: number;
  maxCollect: number;
  instructionsLimit: number | null;
}

/** The server's numbers when the read carries none (`call_script.py`). */
export const DEFAULT_LIMITS: Limits = {
  maxSections: 12,
  nameMax: 80,
  detailMax: 600,
  soundsLikeMax: 200,
  maxBranches: 6,
  maxCollect: 10,
  instructionsLimit: null,
};

export function limitsFrom(context: ScriptContext | null): Limits {
  const l = context?.limits;
  if (!l) return DEFAULT_LIMITS;
  return {
    maxSections: l.max_sections,
    nameMax: l.section_title_max,
    detailMax: l.section_detail_max,
    soundsLikeMax: l.sounds_like_max,
    maxBranches: l.max_branches,
    maxCollect: l.max_collect,
    instructionsLimit: l.instructions_limit,
  };
}

/** A stage with every optional field filled, so views never branch on `undefined`. */
export type Section = Required<Omit<ConversationStage, "position">> & {
  position: { x: number; y: number } | null;
};

export function asSection(stage: ConversationStage): Section {
  return {
    id: stage.id,
    name: stage.name,
    mode: stage.mode ?? "guide",
    instruction: stage.instruction,
    sounds_like: stage.sounds_like ?? "",
    branches: stage.branches ?? [],
    otherwise: stage.otherwise ?? "",
    collect: stage.collect ?? [],
    position: stage.position ?? null,
  };
}

export function sectionsOf(script: CallScript): Section[] {
  return (script.stages ?? []).map(asSection);
}

function withSections(script: CallScript, sections: Section[]): CallScript {
  return { ...script, stages: sections };
}

// --- reading the graph ------------------------------------------------------------------

/** Python's `len`: code points, so a counter agrees with the server on any script. */
export function chars(text: string): number {
  return [...text].length;
}

const collapse = (text: string) => text.split(/\s+/).filter(Boolean).join(" ");
const quote = (text: string) => `"${collapse(text).replace(/"/g, "'")}"`;

/** The section's text exactly as the server builds it (`_stage_detail`), for the 600 count. */
export function sectionDetail(section: Pick<Section, "mode" | "instruction" | "sounds_like">): string {
  const text = collapse(section.instruction);
  let detail = section.mode === "say" ? `Say: ${quote(text)}` : text;
  if (section.sounds_like.trim()) detail += ` It sounds like: ${quote(section.sounds_like)}`;
  return detail;
}

/** Where a section goes when none of its branches holds. */
export function nextTarget(sections: Section[], index: number): string | null {
  const section = sections[index];
  if (!section) return null;
  if (section.otherwise) return section.otherwise;
  return sections[index + 1]?.id ?? null;
}

export interface Edge {
  from: string;
  to: string;
  /** "branch": a condition; "otherwise": chosen fallback; "next": the implied next in order. */
  kind: "branch" | "otherwise" | "next";
  label: string;
  /** Index of the branch on its section, for "branch" edges. */
  branch?: number;
}

/** Every way out of every section, the drawn arrows of the canvas. */
export function edgesOf(sections: Section[]): Edge[] {
  const edges: Edge[] = [];
  sections.forEach((section, i) => {
    section.branches.forEach((branch, b) => {
      edges.push({ from: section.id, to: branch.target, kind: "branch", label: branch.when, branch: b });
    });
    if (section.otherwise) {
      edges.push({ from: section.id, to: section.otherwise, kind: "otherwise", label: "Otherwise" });
    } else if (sections[i + 1]) {
      edges.push({ from: section.id, to: sections[i + 1].id, kind: "next", label: "Then" });
    }
  });
  return edges;
}

/** Sections that point at `id`, by name, for the delete confirmation. */
export function pointersTo(sections: Section[], id: string): string[] {
  return sections
    .filter((s) => s.id !== id && (s.otherwise === id || s.branches.some((b) => b.target === id)))
    .map((s) => s.name.trim() || "Untitled section");
}

// --- writing the graph ------------------------------------------------------------------

/** A short id the server accepts (`^[a-z0-9][a-z0-9_-]{0,39}$`), unique in the script. */
export function newSectionId(sections: Section[], name = ""): string {
  const slug =
    name
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 30) || "section";
  const taken = new Set(sections.map((s) => s.id));
  if (!taken.has(slug) && /^[a-z0-9]/.test(slug)) return slug;
  for (let n = 2; ; n += 1) {
    const id = `${/^[a-z0-9]/.test(slug) ? slug : "section"}-${n}`;
    if (!taken.has(id)) return id;
  }
}

export function addSection(
  script: CallScript,
  init: Partial<Section> = {},
  at?: number,
): { script: CallScript; id: string } {
  const sections = sectionsOf(script);
  const taken = new Set(sections.map((s) => s.name.trim().toLowerCase()));
  let n = sections.length + 1;
  while (taken.has(`section ${n}`)) n += 1;
  const name = init.name ?? `Section ${n}`;
  const id = newSectionId(sections, name);
  const section: Section = {
    id,
    name,
    mode: "guide",
    instruction: "",
    sounds_like: "",
    branches: [],
    otherwise: "",
    collect: [],
    position: null,
    ...init,
  };
  const next = [...sections];
  next.splice(at ?? next.length, 0, { ...section, id });
  return { script: withSections(script, next), id };
}

export function updateSection(script: CallScript, id: string, patch: Partial<Section>): CallScript {
  return withSections(
    script,
    sectionsOf(script).map((s) => (s.id === id ? { ...s, ...patch, id: s.id } : s)),
  );
}

/**
 * Remove a section, and every way out that pointed at it, so the script never names a
 * section that is not there (the server refuses that with a 422).
 */
export function removeSection(script: CallScript, id: string): CallScript {
  const kept = sectionsOf(script)
    .filter((s) => s.id !== id)
    .map((s) => ({
      ...s,
      otherwise: s.otherwise === id ? "" : s.otherwise,
      branches: s.branches.filter((b) => b.target !== id),
    }));
  return withSections(script, kept);
}

/** Reorder. The numbers on both views are the array order, so this IS the renumbering. */
export function moveSection(script: CallScript, from: number, to: number): CallScript {
  const sections = sectionsOf(script);
  if (from === to || from < 0 || to < 0 || from >= sections.length || to >= sections.length) {
    return script;
  }
  const next = [...sections];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return withSections(script, next);
}

export function setPosition(script: CallScript, id: string, position: { x: number; y: number }): CallScript {
  const rounded = { x: Math.round(position.x), y: Math.round(position.y) };
  return updateSection(script, id, { position: rounded });
}

/**
 * Join two sections from the canvas. The first link out of a section with no branches and
 * no chosen "otherwise" becomes its "otherwise"; any further link is a branch whose
 * condition the owner then writes. Returns the branch index when one was added.
 */
export function connect(
  script: CallScript,
  from: string,
  to: string,
  maxBranches = DEFAULT_LIMITS.maxBranches,
): { script: CallScript; branch: number | null } {
  if (from === to) return { script, branch: null };
  const sections = sectionsOf(script);
  const source = sections.find((s) => s.id === from);
  if (!source) return { script, branch: null };
  if (source.otherwise === to || source.branches.some((b) => b.target === to)) {
    return { script, branch: null };
  }
  if (!source.otherwise && source.branches.length === 0) {
    return { script: updateSection(script, from, { otherwise: to }), branch: null };
  }
  if (source.branches.length >= maxBranches) return { script, branch: null };
  const branches = [...source.branches, { when: "", target: to }];
  return { script: updateSection(script, from, { branches }), branch: branches.length - 1 };
}

// --- canvas layout ----------------------------------------------------------------------

export const NODE_W = 232;
export const NODE_H = 104;
const GAP_X = 64;
const GAP_Y = 56;
const MARGIN = 24;
const COLUMNS = 3;

/** Where a section with no saved position sits: reading order, three to a row. */
export function autoPosition(index: number): { x: number; y: number } {
  return {
    x: MARGIN + (index % COLUMNS) * (NODE_W + GAP_X),
    y: MARGIN + Math.floor(index / COLUMNS) * (NODE_H + GAP_Y),
  };
}

export function positionOf(section: Section, index: number): { x: number; y: number } {
  return section.position ?? autoPosition(index);
}

/** Clear every saved position, so the canvas lays the sections out in reading order. */
export function tidy(script: CallScript): CallScript {
  return withSections(
    script,
    sectionsOf(script).map((s) => ({ ...s, position: null })),
  );
}

// --- validation -------------------------------------------------------------------------

export interface Issue {
  /** The section it belongs to, or null for the whole script. */
  section: string | null;
  /** Which input it belongs to, for `aria-invalid` and the message under it. */
  field: string;
  message: string;
}

/**
 * Everything the server would refuse, in words an owner can act on. Any issue holds the
 * autosave, because a draft the server refuses is a draft that was not saved.
 */
export function validate(script: CallScript, limits: Limits = DEFAULT_LIMITS): Issue[] {
  const issues: Issue[] = [];
  if (script.raw_override !== null) return issues;
  const sections = sectionsOf(script);
  const ids = new Set(sections.map((s) => s.id));
  const add = (section: string | null, field: string, message: string) =>
    issues.push({ section, field, message });

  if (sections.length > limits.maxSections) {
    add(null, "sections", `At most ${limits.maxSections} sections. Join two to make room.`);
  }
  const names = new Map<string, number>();
  for (const s of sections) {
    const key = s.name.trim().toLowerCase();
    if (key) names.set(key, (names.get(key) ?? 0) + 1);
  }
  const label = (s: Section, i: number) => s.name.trim() || `Section ${i + 1}`;
  const targetOk = (t: string) => ids.has(t) || (SPECIAL_TARGETS as readonly string[]).includes(t);

  sections.forEach((s, i) => {
    if (!s.name.trim()) add(s.id, "name", "Give this section a name.");
    else if ((names.get(s.name.trim().toLowerCase()) ?? 0) > 1) {
      add(s.id, "name", "Another section has this name. Give each one its own.");
    }
    if (chars(s.name) > limits.nameMax) add(s.id, "name", `Keep the name under ${limits.nameMax} letters.`);
    if (!s.instruction.trim()) add(s.id, "instruction", `Say what ${label(s, i)} is for.`);
    const used = chars(sectionDetail(s));
    if (used > limits.detailMax) {
      add(s.id, "instruction", `${used - limits.detailMax} letters too long. Cut it to fit ${limits.detailMax}.`);
    }
    if (chars(s.sounds_like) > limits.soundsLikeMax) {
      add(s.id, "sounds_like", `Keep this line under ${limits.soundsLikeMax} letters.`);
    }
    if (s.branches.length > limits.maxBranches) {
      add(s.id, "branches", `At most ${limits.maxBranches} ways out of one section.`);
    }
    s.branches.forEach((b, j) => {
      if (!b.when.trim()) add(s.id, `branch-${j}`, "Say when the call goes this way.");
      if (!targetOk(b.target)) add(s.id, `branch-${j}`, "This goes to a section that is not there any more.");
    });
    if (s.otherwise && !targetOk(s.otherwise)) {
      add(s.id, "otherwise", "This goes to a section that is not there any more.");
    }
    if (s.collect.length > limits.maxCollect) {
      add(s.id, "collect", `At most ${limits.maxCollect} details in one section.`);
    }
  });

  const rows = <T,>(list: T[] | undefined, field: string, empty: (row: T) => boolean, message: string) =>
    (list ?? []).forEach((row, i) => {
      if (empty(row)) add(null, `${field}-${i}`, message);
    });
  rows(script.objections, "objection", (o) => !o.objection.trim() || !o.response.trim(), "Fill in both halves of this push-back, or remove it.");
  rows(script.example_exchange, "example", (l) => !l.text.trim(), "Write this line, or remove it.");
  rows(script.style?.pronunciations, "pronunciation", (p) => !p.word.trim() || !p.say_as.trim(), "Fill in the word and how to say it, or remove it.");
  rows(script.faqs, "fact", (f) => !f.question.trim() || !f.answer.trim(), "Fill in the question and the answer, or remove it.");
  if (chars(script.business_line ?? "") > 200) add(null, "business_line", "Keep this under 200 letters.");
  if (chars(script.outbound_purpose ?? "") > 300) add(null, "outbound_purpose", "Keep this under 300 letters.");
  return issues;
}

export function issuesFor(issues: Issue[], section: string | null, field?: string): Issue[] {
  return issues.filter((i) => i.section === section && (field === undefined || i.field === field));
}

// --- whole-script text, for the hand-written mode ----------------------------------------

const TARGET_WORDS: Record<string, string> = {
  [END]: "end the call",
  [HAND_OVER]: "hand the caller to a person",
  [CALL_BACK]: "offer a call back",
};

/**
 * The structured script as plain text an owner can keep editing by hand. Used when they
 * switch to writing it themselves, so nothing they built is lost in the switch.
 */
export function scriptAsText(script: CallScript): string {
  const sections = sectionsOf(script);
  const names = new Map(sections.map((s) => [s.id, s.name.trim()]));
  const target = (t: string) => lookup(TARGET_WORDS, t) ?? `go to "${names.get(t) ?? t}"`;
  const out: string[] = [];
  const para = (title: string, body: string | undefined) => {
    if (body?.trim()) out.push(`${title}\n${body.trim()}`);
  };
  if (script.opening_line.trim()) out.push(`[OPENING]\n${script.opening_line.trim()}`);
  para("About the business", script.business_line);
  para("Who you are", script.identity);
  para("The goal", script.goal);
  para("Why we are calling", script.outbound_purpose);
  if (sections.length) {
    const lines = sections.map((s, i) => {
      const parts = [`${i + 1}. ${s.name.trim()}: ${sectionDetail(s)}`];
      if (s.collect.length) parts.push(`   Find out: ${s.collect.join(", ")}.`);
      s.branches.forEach((b) => parts.push(`   When ${b.when.trim()}: ${target(b.target)}.`));
      if (s.otherwise) parts.push(`   Otherwise: ${target(s.otherwise)}.`);
      return parts.join("\n");
    });
    out.push(`The call\n${lines.join("\n")}`);
  }
  const style = script.style;
  if (style && (style.tone || style.address_form || style.sample_phrases.length)) {
    out.push(
      [
        "How you talk",
        style.tone && `Tone: ${style.tone}`,
        style.address_form && `Address callers as: ${style.address_form}`,
        ...style.sample_phrases.map((p) => `- ${p}`),
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
  if (script.objections?.length) {
    out.push(
      `When callers push back\n${script.objections.map((o) => `- "${o.objection}": ${o.response}`).join("\n")}`,
    );
  }
  para("Ending the call", script.ending);
  if (script.example_exchange?.length) {
    out.push(
      `Example call\n${script.example_exchange.map((l) => `${l.speaker === "caller" ? "Caller" : "Agent"}: ${l.text}`).join("\n")}`,
    );
  }
  return out.join("\n\n");
}
