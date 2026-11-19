"use client";

/**
 * Client-realm structured call-script builder hooks — `/v1/agents/{id}/script/...`.
 *
 * This is the exception's exception. `agents.ts` is read-only but for `useSetCallNotices`,
 * on D-21's ground that a script change routes through us. The founder's APPROVED DECISION
 * makes the STRUCTURED builder the primary client authoring surface, so these mutation
 * hooks exist — reconciled with D-21 rather than overriding it: every save STAGES (the
 * server's slow lane), and nothing reaches a live call until an explicit `useApplyScript`.
 * See `apps/api/agents/script_routes.py` for the flagged conflict and its resolution.
 *
 * TYPES ARE HAND-DECLARED rather than aliased from `./schema`. The generated `CallScript`
 * and its parts come from the REQUEST model, where every field with a server default is
 * optional; the builder reads the RESPONSE, where the server always fills them, and the
 * aliases would make every list and section "possibly undefined" throughout it. The shapes
 * mirror the Pydantic models in `script_routes.py`; a field added there must be added here.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { agentKeys } from "./agents";
import { apiRequest, type Session } from "./client";
import { untilRefused } from "./queryRetry";
import { publishingKeys } from "./publishing";
import { readinessKeys } from "./readiness";
import type { components } from "./schema";

/** One `{{ }}` merge field the author declared. Mirrors `ScriptVariable`. */
export interface ScriptVariable {
  key: string;
  label: string;
  example: string;
}

/** One ordered task-flow instruction. Mirrors `ScriptStep`. */
export interface ScriptStep {
  instruction: string;
}

/** One FAQ question/answer pair. Mirrors `FaqEntry`. */
export interface FaqEntry {
  question: string;
  answer: string;
}

/** How to say a word the voice might misread. Mirrors `Pronunciation`. */
export interface Pronunciation {
  word: string;
  say_as: string;
}

export type CodeMix = "light" | "natural" | "heavy";

/** How the agent sounds. Mirrors `SpeakingStyle`. */
export interface SpeakingStyle {
  tone: string;
  address_form: string;
  code_mix: CodeMix;
  sample_phrases: string[];
  pronunciations: Pronunciation[];
}

/** One section of the call graph. Mirrors `ConversationStage` (see the "Script API
 *  (lane 2)" contract in docs/evidence/first-call-review-2026-10-10.md). */
export interface ConversationStage {
  /** Stable id: branches and the canvas point at it. */
  id: string;
  name: string;
  /** "say": `instruction` is said as written (best effort). */
  mode?: "guide" | "say";
  instruction: string;
  /** One line in the call's language showing how the section sounds. */
  sounds_like?: string;
  /** `target` is a section id, or "end" | "hand_over" | "call_back". */
  branches?: { when: string; target: string; via?: { x: number; y: number } | null }[];
  /** Where to go when no branch holds; empty = the next section. */
  otherwise?: string;
  collect?: string[];
  /** Small steps the caller does one at a time (D-908), compiled into the instructions
   *  under the section's name. Mirrors `ProcedureStep`. */
  procedure?: { action: string; wait_for: string }[];
  /** Canvas layout only; never compiled. */
  position?: { x: number; y: number } | null;
  /** The bend of the arrow to `otherwise` (or the next section). Layout only. */
  otherwise_via?: { x: number; y: number } | null;
  /** The call flow step (column) this is a scenario of, 1-based; null: its own step. */
  step?: number | null;
  /** What to say in this scenario, by language tag. */
  scripts?: Record<string, string>;
  /** The caller's likely questions in this scenario, with the answers. */
  qa?: {
    question: string;
    answer: string;
    /** The same pair in another language, by tag. */
    translations?: Record<string, { question: string; answer: string }>;
  }[];
  /** How the owner wants the line said, heard and noted (language "" = every language). */
  coaching?: { language: string; note: string }[];
}

/** Mirrors `Objection`. */
export interface Objection {
  objection: string;
  response: string;
}

/** What the business allows the agent to do. Mirrors `ScriptPolicies`. */
export interface ScriptPolicies {
  offer_call_backs: boolean;
  share_prices: boolean;
  take_bookings: boolean;
}

/** One line of the example call. Mirrors `ExampleLine`. */
export interface ExampleLine {
  speaker: "caller" | "agent";
  text: string;
}

/**
 * A whole agent script, structured — or a raw escape hatch. Mirrors `CallScript`.
 *
 * `raw_override` null = structured mode (the fields below are used); a string = raw mode
 * (the fields are ignored and this text is the body verbatim). The server refuses both at
 * once, so the UI clears one side when switching modes.
 */
/**
 * What Pip did to one opening line to say the notices (D-971). Mirrors `OpeningNotices`.
 * Kept as the server sent it; the editor never writes it.
 */
export interface OpeningNotices {
  /** The line Pip wrote; the record counts only while the opening is still this line. */
  line?: string;
  ai?: string;
  recording?: string;
  /** The owner's line Pip replaced, shown with "Put mine back". */
  before?: string;
  kept_own?: string;
}

export interface CallScript {
  opening_line: string;
  /** A "both" agent's first words on a call it places (D-920); empty or absent: a composed line. */
  outbound_opening_line?: string;
  opening_notices?: OpeningNotices;
  outbound_opening_notices?: OpeningNotices;
  steps: ScriptStep[];
  faqs: FaqEntry[];
  faq_fallback: string;
  end_call_extra_rules: string[];
  variables: ScriptVariable[];
  raw_override: string | null;
  /** 1 for scripts saved before 10 Oct 2026; the builder always edits 2. */
  schema_version: 1 | 2;
  business_line: string;
  identity: string;
  goal: string;
  outbound_purpose: string;
  style: SpeakingStyle;
  stages: ConversationStage[];
  /** Where each end point sits on the canvas, by target. Layout only. */
  end_positions?: Record<string, { x: number; y: number }>;
  objections: Objection[];
  policies: ScriptPolicies;
  ending: string;
  example_exchange: ExampleLine[];
  /** The example was drafted by AI and no native speaker has read it yet. */
  example_needs_review: boolean;
  /** How closely the sections are followed. */
  adherence?: "flexible" | "strict";
}

/** The empty structured script a brand-new agent opens on. */
export const EMPTY_SCRIPT: CallScript = {
  opening_line: "",
  steps: [],
  faqs: [],
  faq_fallback: "",
  end_call_extra_rules: [],
  variables: [],
  raw_override: null,
  schema_version: 2,
  business_line: "",
  identity: "",
  goal: "",
  outbound_purpose: "",
  style: { tone: "", address_form: "", code_mix: "natural", sample_phrases: [], pronunciations: [] },
  stages: [],
  objections: [],
  policies: { offer_call_backs: true, share_prices: true, take_bookings: true },
  ending: "",
  example_exchange: [],
  example_needs_review: false,
};

/** What the builder shows beside the script and does not edit there. */
export interface ScriptContext {
  collect: { label: string; reason: string; required: boolean }[];
  call_backs_available: boolean;
  hand_over_enabled: boolean;
  direction: string;
  language: string;
  register_name: string | null;
  register_needs_review: boolean;
  business_type: string;
  /** The builder's limits on this deployment's engine (Script API, lane 2). */
  limits?: {
    max_sections: number;
    section_title_max: number;
    section_detail_max: number;
    sounds_like_max: number;
    max_branches: number;
    max_collect: number;
    /** A section's small steps (D-908). */
    max_procedure_steps: number;
    procedure_step_max: number;
    procedure_wait_max: number;
    instructions_limit: number | null;
    native_steps: boolean;
    special_targets: string[];
  };
}

export interface ScriptOut {
  script: CallScript;
  stored_schema_version: number | null;
  context: ScriptContext | null;
  /** The autosaved working copy, when one is unpublished. */
  draft?: { script: CallScript; saved_at: string } | null;
  version: number | null;
  is_freeform: boolean;
  has_pending: boolean;
  standard_variables: { key: string; label: string }[];
}

interface ApplyIn {
  expected_version?: number | null;
}

interface ApplyOut {
  applied: boolean;
  live_version: number;
  engine_synced: boolean;
}

interface UndoOut {
  undone: boolean;
  discarded_version: number | null;
  live_version: number | null;
}

export const scriptKeys = {
  one: (org: string, agentId: string) => ["script", org, agentId] as const,
};

const base = (agentId: string) => `/v1/agents/${agentId}/script`;

/** The agent's DRAFT script for the builder to edit. */
export function useScript(session: Session, agentId: string): UseQueryResult<ScriptOut, Error> {
  return useQuery({
    queryKey: scriptKeys.one(session.orgSlug, agentId),
    queryFn: () => apiRequest<ScriptOut>(session, base(agentId)),
  });
}

/** Apply the staged script to live calls (CAS on the version the author reviewed). */
export function useApplyScript(
  session: Session,
  agentId: string,
): UseMutationResult<ApplyOut, Error, ApplyIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: ApplyIn) =>
      apiRequest<ApplyOut>(session, `${base(agentId)}/apply`, { method: "POST", body: payload }),
    // Includes the history, which marks the version callers hear.
    onSuccess: () => invalidateScript(client, session, agentId),
  });
}

/** Discard the staged script; the draft returns to what callers hear. */
export function useUndoScript(
  session: Session,
  agentId: string,
): UseMutationResult<UndoOut, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<UndoOut>(session, `${base(agentId)}/undo`, { method: "POST" }),
    // Includes the history, which marks the version callers hear.
    onSuccess: () => invalidateScript(client, session, agentId),
  });
}

// --- what a new script version moves ---------------------------------------------------

/** Every read a new script version moves: the script, the agent, the tests, readiness. */
export function invalidateScript(client: ReturnType<typeof useQueryClient>, session: Session, agentId: string) {
  return Promise.all([
    client.invalidateQueries({ queryKey: scriptKeys.one(session.orgSlug, agentId) }),
    client.invalidateQueries({ queryKey: agentKeys.one(session.orgSlug, agentId) }),
    // The roster carries the applied script's opening line (`useReplaceOpeningLine` says
    // why), and the tests and readiness read whether the agent can be tried.
    client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
    client.invalidateQueries({ queryKey: agentKeys.tests(session.orgSlug, agentId) }),
    client.invalidateQueries({ queryKey: readinessKeys.all(session.orgSlug) }),
    client.invalidateQueries({ queryKey: publishingKeys.pending(session.orgSlug, agentId) }),
  ]);
}


export type OpeningLineOut = components["schemas"]["OpeningLineOut"];

/** Which opening line: the one callers who ring hear, or a "both" agent's for calls it places (D-920). */
export type OpeningWhen = components["schemas"]["OpeningLineIn"]["when"];

/**
 * Replace an opening line in the script callers hear and put it live, keeping the rest
 * (D-846). The way back from a notice switch refused for want of room, and with `when:
 * "calls"` the way to set a "both" agent's line for the calls it places (D-920). Awaits the
 * agent reads too, so a retried switch is measured against the new line.
 */
export function useReplaceOpeningLine(
  session: Session,
  agentId: string,
  when: OpeningWhen = "answers",
): UseMutationResult<OpeningLineOut, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (openingLine: string) =>
      apiRequest<OpeningLineOut>(session, `${base(agentId)}/opening-line`, {
        method: "PUT",
        body: { opening_line: openingLine, when },
      }),
    onSuccess: () =>
      Promise.all([
        invalidateScript(client, session, agentId),
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
      ]),
  });
}

/**
 * The Undo for Pip's notice rewrite (D-971, founder 5 Nov 2026): the owner's own opening line
 * goes live again and is not rewritten on the next publish.
 */
export function usePutBackOpeningLine(
  session: Session,
  agentId: string,
): UseMutationResult<OpeningLineOut, Error, OpeningWhen> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (when: OpeningWhen) =>
      apiRequest<OpeningLineOut>(session, `${base(agentId)}/opening-line/put-back`, {
        method: "POST",
        body: { when },
      }),
    onSuccess: () => invalidateScript(client, session, agentId),
  });
}

/** The opening Pip rewrote to say the notices, and the owner's line it replaced, or null. */
export function rewrittenOpening(
  script: CallScript,
  when: OpeningWhen,
): { before: string; after: string } | null {
  const line = (when === "calls" ? script.outbound_opening_line : script.opening_line) ?? "";
  const record = when === "calls" ? script.outbound_opening_notices : script.opening_notices;
  const before = (record?.before ?? "").trim();
  const flat = (s: string) => s.split(/\s+/).filter(Boolean).join(" ");
  if (!before || !line.trim() || flat(record?.line ?? "") !== flat(line)) return null;
  return { before, after: line.trim() };
}

// --- test conversations that improve the agent (D-724) ----------------------------------

export type TestVerdict = "passed" | "needs_fix" | "failed" | "unjudged";
export type FixKind = "script_step" | "knowledge" | "objection" | "style" | "settings" | "platform";

/** A step the agent took in a turn, in our words. */
export type TestAction = "knowledge" | "do_not_call" | "call_back" | "other";

export interface TestTurn {
  said: string;
  reply: string;
  actions?: TestAction[];
}

/** Who can fix a failure (D-823). */
export type TestOwner = "script" | "knowledge" | "setting" | "platform" | "test";

/** Why the last "Improve my agent" round stopped (D-823). */
export type ImproveStop = "completed" | "no_change" | "nothing_fixable_by_script" | "budget" | "failed";

export interface TestSetting {
  /** `handover` (the agent's call handling) or `agreements` (the account's agreements). */
  area: "handover" | "agreements";
  /** Why this setting decides the result. */
  reason: string;
}

export interface TestResult {
  key: string;
  /** The test's full name; "Why?" shows it when the card's is cut. */
  title: string;
  /** The card's name: `title` in six words or fewer (D-917). Optional so a reply cached
   * from the release before still renders, with `title`. */
  short_title?: string;
  category: string;
  /** `ai` · `recording` · `stop_calling` · `person` for a rule every agent must answer. */
  probe: string | null;
  /** `generated` · `standard` · `saved` · `retest` · `real`. */
  source: string;
  turns: TestTurn[];
  expect: string;
  verdict: TestVerdict;
  reason: string;
  fix: FixKind | string | null;
  step_id: string | null;
  formal_words: string[];
  /** What a test chat cannot show for this check, in the owner's words. */
  limit?: string | null;
  /** Who can fix it; null when it passed. */
  owner?: TestOwner | null;
  /** The setting that decides it, when `owner` is `setting`. */
  setting?: TestSetting | null;
  /** The owner marked this test wrong: out of the score and the fixes. */
  marked_wrong?: boolean;
  /** Tries that passed, of the tries judged (D-828). */
  passes?: number;
  judged_tries?: number;
  reliability?: TestReliability;
  /** Where it sits for the owner (`trial_results.standing`). */
  standing?: TestStanding;
  /** In the owner's score: their script or knowledge decides it. */
  counted?: boolean;
  /** Against the same test in the run this one repeated. */
  change?: TestChange | null;
  /** How its replies sounded, when wrong: ours to fix, never the verdict. */
  sounds?: TestSound[];
  /** Every try, in order. */
  tries?: TestTry[];
}

export type TestReliability = "passed" | "flaky" | "failed" | "unjudged";
export type TestStanding = "works" | "unreliable" | "broken" | "setting" | "check" | "ours" | "wrong";
export type TestChange = "fixed" | "broken" | "still" | "same" | "new";
export type SoundKind =
  | "brackets"
  | "symbols"
  | "time"
  | "money_digits"
  | "formal_words"
  | "spoken_number"
  | "repeated_question"
  | "several_questions"
  | "unmarked_question"
  | "too_long"
  | "wrong_language"
  | "third_person"
  | "foreign_script"
  | "repeated_turn"
  | "opened_again"
  | "memory_not_said";

export interface TestSound {
  kind: SoundKind;
  reason: string;
  tries: number;
}

export interface TestTry {
  verdict: TestVerdict;
  reason: string;
  turns: TestTurn[];
}

/** Before against after on the same tests (D-828). */
export interface TestComparison {
  with_run: string;
  /** The script version the earlier run talked to: restore it to undo. */
  with_version: number | null;
  fixed: number;
  broken: number;
  still: number;
  same: number;
  new: number;
  same_script: boolean;
}

/** One suggested edit, kept or left with its own tick box. */
export interface ScriptEdit {
  id: string;
  op: "set_step" | "add_step" | "set_objection" | "set_part";
  /** What it changes, in the owner's words. */
  label: string;
  before: string;
  after: string;
  because: string | null;
  why: string;
}

export interface ProposedFact {
  action: "add" | "fix";
  fact_id: string | null;
  question: string;
  /** Empty when only the owner knows the answer. */
  answer: string;
  because: string | null;
  why: string;
}

/** One of the agent's Inbound lines or open campaigns with a script (D-1017). */
export type FixHolder = components["schemas"]["TestFixHolderOut"];

/** How a round's script fixes ended up: a Pip draft on `holder`, or why not. */
export type ScriptFixes = "drafted" | "draft_open" | "no_holder" | "choose" | "none";

export interface Improvement {
  script_fixes?: ScriptFixes;
  /** Where the script fixes were drafted, reviewed and put live (D-1017). */
  holder?: FixHolder | null;
  draft_id?: string | null;
  /** What the draft changed, for reading here; it is kept or discarded on the holder's page. */
  edits: ScriptEdit[];
  facts: ProposedFact[];
  /** Suggested edits that did not fit the script and were left out. */
  dropped?: number;
  for_keys: string[];
  disclosure: string | null;
  created_at: string;
  /** False: no suggestion has been tried on the agent yet; "Test again" after putting kept ones live checks them. */
  tested?: boolean;
}

/** The owner's score: only tests their script or knowledge decides. */
export interface TestScore {
  /** Right on every try. */
  passed: number;
  /** Tests in the score. */
  judged: number;
  total: number;
  unreliable?: number;
  ours?: number;
  check?: number;
  setting?: number;
}

export interface TestRun {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  prompt_version: number | null;
  is_current: boolean;
  round: number;
  retest_of: string | null;
  auto_improve: boolean;
  score: TestScore;
  results: TestResult[];
  improvement: Improvement | null;
  note: string | null;
  /** "Improve my agent" is being worked out; the screen polls until it arrives. */
  improving?: boolean;
  /** Why the last "Improve my agent" could not be made. */
  improve_note?: string | null;
  /** Why the last improve round stopped. */
  improve_stop?: ImproveStop | null;
  created_at: string;
  completed_at: string | null;
  /** The version of the agent's test set this run asked. */
  set_version?: number | null;
  /** Tries per test, and tries finished. */
  trials?: number;
  trials_done?: number;
  /** Before against after, when this run repeated an earlier one. */
  comparison?: TestComparison | null;
  /** How replies sounded across the run: tests per kind, ours to fix. */
  sounds?: { kind: SoundKind; tests: number }[];
  error_code?: string | null;
}

export interface TestHistoryEntry {
  id: string;
  created_at: string;
  prompt_version: number | null;
  round: number;
  score: TestScore;
  set_version?: number | null;
}

export interface TestConversations {
  available: boolean;
  unavailable_reason: string | null;
  cost_note: string;
  /** Why the agent under test is behind the instructions every agent gets. */
  waiting_update?: string | null;
  latest: TestRun | null;
  history: TestHistoryEntry[];
  /** Saved tests and real-call questions the latest set does not have yet. */
  waiting_tests?: number;
  /** Practice callers may be asked for: the agent has few real calls. */
  practice_offered?: boolean;
  /** Facts callers ask for that the business has not given anywhere its agents read. */
  missing_facts?: "prices"[];
  /** Tries per test, and the most test-chat replies one run may use. */
  trials?: number;
  max_replies?: number;
  /** Where script fixes can be drafted: the owner picks one when there are several. */
  fix_holders?: FixHolder[];
}

/** What starts a run: "Test again" (`retest_of`), or a new set of tests. */
export interface RunTestsBody {
  retest_of?: string | null;
  auto_improve?: boolean;
  practice_callers?: boolean;
}

const testsKey = agentKeys.tests;

/** The agent's latest test run and score history. Polls while a run is queued or running. */
export function useTestConversations(
  session: Session,
  agentId: string,
): UseQueryResult<TestConversations, Error> {
  return useQuery({
    queryKey: testsKey(session.orgSlug, agentId),
    queryFn: () => apiRequest<TestConversations>(session, `${base(agentId)}/tests`),
    refetchInterval: untilRefused((query) => {
      const latest = query.state.data?.latest;
      const busy = latest?.status === "queued" || latest?.status === "running" || latest?.improving === true;
      return busy ? 3000 : false;
    }),
  });
}

/**
 * Start a run (or get the one already running). `retest_of` is "Test again": the same tests
 * as that run, for before against after. Without it the run makes a new set of tests.
 */
export function useRunTestConversations(
  session: Session,
  agentId: string,
): UseMutationResult<TestConversations, Error, RunTestsBody | void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<TestConversations>(session, `${base(agentId)}/tests`, { method: "POST", body: body ?? {} }),
    onSuccess: (data) => client.setQueryData(testsKey(session.orgSlug, agentId), data),
  });
}

/** "This test is wrong" (D-823): the test leaves the run's score and the fixes. */
export function useMarkTestWrong(
  session: Session,
  agentId: string,
): UseMutationResult<TestConversations, Error, { runId: string; key: string }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, key }) =>
      apiRequest<TestConversations>(
        session,
        `${base(agentId)}/tests/${runId}/results/${encodeURIComponent(key)}/wrong`,
        { method: "POST" },
      ),
    onSuccess: (data) => client.setQueryData(testsKey(session.orgSlug, agentId), data),
  });
}

/**
 * The kept fixes are saved: the server stops offering them, after a reload too. The tests
 * cache is left alone so the "Kept" notice stays until the owner closes it; closing refetches.
 */
export function useSettleImprovement(
  session: Session,
  agentId: string,
): UseMutationResult<TestConversations, Error, { runId: string }> {
  return useMutation({
    mutationFn: ({ runId }) =>
      apiRequest<TestConversations>(session, `${base(agentId)}/tests/${runId}/improvement/settle`, {
        method: "POST",
      }),
  });
}

