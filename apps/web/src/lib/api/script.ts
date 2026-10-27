"use client";

/**
 * Client-realm structured call-script builder hooks — `/v1/agents/{id}/script/...`.
 *
 * This is the exception's exception. `agents.ts` is read-only but for `useSetDisclosure`,
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
  branches?: { when: string; target: string }[];
  /** Where to go when no branch holds; empty = the next section. */
  otherwise?: string;
  collect?: string[];
  /** Small steps the caller does one at a time (D-908), compiled into the instructions
   *  under the section's name. Mirrors `ProcedureStep`. */
  procedure?: { action: string; wait_for: string }[];
  /** Canvas layout only; never compiled. */
  position?: { x: number; y: number } | null;
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
export interface CallScript {
  opening_line: string;
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
  faq_fallback: "నాకు ఆ వివరం ఖచ్చితంగా తెలియదు — మా టీమ్ మీకు తిరిగి కాల్ చేసి చెబుతుంది.",
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

interface SaveScriptIn {
  script: CallScript;
  notes?: string | null;
  /** The draft version the edit started from (null: no script yet). Sent, the server
   *  refuses the save with `script_changed_elsewhere` if the draft has moved since. */
  expected_version?: number | null;
}

interface SaveScriptOut {
  version: number;
  staged: boolean;
}

/** One part of what the calling system receives, and its length. Never its text. */
export interface SizePart {
  key: string;
  label: string;
  chars: number;
}

export interface PreviewOut {
  compiled: string;
  /** Characters of everything the calling system receives (Calevate's rules and the
   *  script) and its ceiling (null: none). */
  instructions_chars?: number;
  instructions_limit?: number | null;
  /** Stages sent as the engine's own step list. */
  native_steps?: number;
  /** How far over the ceiling, and the sentence to show then (null when it fits). */
  over_chars?: number;
  too_long?: string | null;
  layers?: SizePart[];
  /** The script's own sections, longest first. */
  script_parts?: SizePart[];
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

/** Save the structured script as a new version (staged on a live agent). */
export function useSaveScript(
  session: Session,
  agentId: string,
): UseMutationResult<SaveScriptOut, Error, SaveScriptIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: SaveScriptIn) =>
      apiRequest<SaveScriptOut>(session, base(agentId), { method: "PUT", body: payload }),
    // Includes the history, which marks the version callers hear.
    onSuccess: () => invalidateScript(client, session, agentId),
  });
}

/**
 * Compile a (possibly unsaved) script into the exact engine prompt. A mutation, not a
 * query: it takes the current editor state as input rather than reading the server's copy,
 * so "view compiled prompt" reflects unsaved edits.
 */
export function usePreviewScript(
  session: Session,
  agentId: string,
): UseMutationResult<PreviewOut, Error, CallScript> {
  return useMutation({
    mutationFn: (script: CallScript) =>
      apiRequest<PreviewOut>(session, `${base(agentId)}/preview`, {
        method: "POST",
        body: { script },
      }),
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

// --- the autosaved draft, "Put it live", history and the hand-written conversion ------

interface SaveDraftIn {
  script: CallScript;
  /** The draft's `saved_at` the editor loaded (null: there was none). Sent, the server
   *  refuses with `script_changed_elsewhere` (409) if the stored draft moved since. */
  base_saved_at?: string | null;
}

export interface DraftSavedOut {
  saved_at: string;
}

interface PublishIn {
  /** What changed, in the owner's words; becomes the history entry's note (1-200). */
  summary: string;
  /** The script to put live; left out, the autosaved draft is. */
  script?: CallScript;
  expected_version?: number | null;
}

export interface PublishOut {
  version: number;
  /** False while the agent is not switched on, or the push did not complete. */
  live: boolean;
}

/** One history entry. Mirrors `VersionOut`; `version` is an id, never shown. */
export interface ScriptVersion {
  version: number;
  summary: string | null;
  created_at: string;
  is_live: boolean;
}

const versionsKey = (org: string, agentId: string) => ["script-versions", org, agentId] as const;

function invalidateScript(client: ReturnType<typeof useQueryClient>, session: Session, agentId: string) {
  return Promise.all([
    client.invalidateQueries({ queryKey: scriptKeys.one(session.orgSlug, agentId) }),
    client.invalidateQueries({ queryKey: versionsKey(session.orgSlug, agentId) }),
    client.invalidateQueries({ queryKey: agentKeys.one(session.orgSlug, agentId) }),
    // The roster carries the applied script's opening line (`useReplaceOpeningLine` says
    // why), and the tests and readiness read whether the agent can be tried.
    client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
    client.invalidateQueries({ queryKey: agentKeys.tests(session.orgSlug, agentId) }),
    client.invalidateQueries({ queryKey: readinessKeys.all(session.orgSlug) }),
    client.invalidateQueries({ queryKey: publishingKeys.pending(session.orgSlug, agentId) }),
  ]);
}

/**
 * Autosave the working copy. Does NOT invalidate the script read: a save per pause in
 * typing would otherwise refetch per pause. The builder patches the cached read itself
 * (`withDraft`), so the read and the screen stay one copy.
 */
export function useSaveDraft(
  session: Session,
  agentId: string,
): UseMutationResult<DraftSavedOut, Error, SaveDraftIn> {
  return useMutation({
    mutationFn: (payload: SaveDraftIn) =>
      apiRequest<DraftSavedOut>(session, `${base(agentId)}/draft`, { method: "PUT", body: payload }),
  });
}

/** The cached script read with `draft` replaced, after an autosave or a restore. */
export function withDraft(out: ScriptOut, draft: { script: CallScript; saved_at: string }): ScriptOut {
  return { ...out, draft };
}

/** "Put it live": the draft becomes a history entry and is applied in one request. */
export function usePublishScript(
  session: Session,
  agentId: string,
): UseMutationResult<PublishOut, Error, PublishIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: PublishIn) =>
      apiRequest<PublishOut>(session, `${base(agentId)}/publish`, { method: "POST", body: payload }),
    // On a failure too: the version may be saved with only the apply refused, and the next
    // "Put it live" must see it waiting (`script_routes.publish_script`).
    onSettled: () => invalidateScript(client, session, agentId),
  });
}

/** The ready-made opening line in the agent's main language, put into the script draft. */
export function useRewriteOpeningInLanguage(
  session: Session,
  agentId: string,
): UseMutationResult<{ opening_line: string; saved_at: string }, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<{ opening_line: string; saved_at: string }>(
        session,
        `${base(agentId)}/opening-line/in-language`,
        { method: "POST" },
      ),
    onSuccess: () => invalidateScript(client, session, agentId),
  });
}

export type OpeningLineOut = components["schemas"]["OpeningLineOut"];

/**
 * Replace the opening line in the script callers hear and put it live, keeping the rest
 * (D-846). The way back from a notice switch refused for want of room. Awaits the agent
 * reads too, so a retried switch is measured against the new line.
 */
export function useReplaceOpeningLine(
  session: Session,
  agentId: string,
): UseMutationResult<OpeningLineOut, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (openingLine: string) =>
      apiRequest<OpeningLineOut>(session, `${base(agentId)}/opening-line`, {
        method: "PUT",
        body: { opening_line: openingLine },
      }),
    onSuccess: () =>
      Promise.all([
        invalidateScript(client, session, agentId),
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
      ]),
  });
}

/** The script's history, newest first. */
export function useScriptVersions(
  session: Session,
  agentId: string,
  enabled = true,
): UseQueryResult<ScriptVersion[], Error> {
  return useQuery({
    queryKey: versionsKey(session.orgSlug, agentId),
    queryFn: () => apiRequest<ScriptVersion[]>(session, `${base(agentId)}/versions`),
    enabled,
  });
}

/** Copy an earlier entry into the draft; callers keep the live one. */
export function useRestoreVersion(
  session: Session,
  agentId: string,
): UseMutationResult<{ script: CallScript; saved_at: string }, Error, number> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (version: number) =>
      apiRequest<{ script: CallScript; saved_at: string }>(
        session,
        `${base(agentId)}/versions/${version}/restore`,
        { method: "POST" },
      ),
    onSuccess: () => invalidateScript(client, session, agentId),
  });
}

// --- the suggestion Pip prepared (D-820) --------------------------------------------------

/** Mirrors `ScriptProposalOut`. */
export interface ScriptProposal {
  id: string;
  /** `change` (one change), `whole` (from the owner's answers), `steps` (from hand-writing). */
  mode: "change" | "whole" | "steps";
  status: "drafting" | "ready" | "failed";
  request: string | null;
  /** What it was made from: list the changes against this, apply them to the working copy. */
  base_script: CallScript;
  script: CallScript | null;
  unplaced: string[];
  disclosure: string | null;
  note: string | null;
  requested_at: string;
}

export const proposalKey = (org: string, agentId: string) => ["script-proposal", org, agentId] as const;

/** The suggestion waiting for review, or null. Polls while it is being written. */
export function useScriptProposal(
  session: Session,
  agentId: string,
): UseQueryResult<ScriptProposal | null, Error> {
  return useQuery({
    queryKey: proposalKey(session.orgSlug, agentId),
    queryFn: async () =>
      (await apiRequest<{ proposal: ScriptProposal | null }>(session, `${base(agentId)}/proposal`)).proposal,
    refetchInterval: (query) => (query.state.data?.status === "drafting" ? 3000 : false),
  });
}

/** Clear the suggestion: after its kept parts are in the draft, or to discard it. */
export function useClearProposal(
  session: Session,
  agentId: string,
): UseMutationResult<void, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (proposalId: string) =>
      apiRequest<void>(session, `${base(agentId)}/proposal/${proposalId}`, { method: "DELETE" }),
    onSuccess: () => client.setQueryData(proposalKey(session.orgSlug, agentId), null),
  });
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
  title: string;
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

export interface Improvement {
  base: "draft" | "live";
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
    refetchInterval: (query) => {
      const latest = query.state.data?.latest;
      const busy = latest?.status === "queued" || latest?.status === "running" || latest?.improving === true;
      return busy ? 3000 : false;
    },
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

export interface AppliedEdits {
  script: CallScript;
  /** Kept edits that no longer fit the working copy, left out. */
  skipped: string[];
}

/** The working copy with the kept suggested edits made. Nothing is saved. */
export function useApplySuggestedEdits(
  session: Session,
  agentId: string,
): UseMutationResult<AppliedEdits, Error, { runId: string; script: CallScript; edits: string[] }> {
  return useMutation({
    mutationFn: ({ runId, script, edits }) =>
      apiRequest<AppliedEdits>(session, `${base(agentId)}/tests/${runId}/improvement/apply`, {
        method: "POST",
        body: { script, edits },
      }),
  });
}
