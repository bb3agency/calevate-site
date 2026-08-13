"use client";

/**
 * The wizard's intake step — FLOWS §1 step 3, as the API actually accepts it.
 *
 * `GET | POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake` (BUILD-LOG §45,
 * `apps/api/admin/intake.py`) shipped with no caller in either realm, so the step that
 * FLOWS §1 calls "the real work" existed only as a curl command and `/admin/new` jumped
 * from step 1 to step 8. This module is the console's half of it: the vocabulary, the
 * draft ⇄ wire conversion, the blocker preview and the two hooks.
 *
 * It follows `prompts.ts` rather than putting its hooks in `admin.ts`: both are
 * admin-realm sub-resources of ONE agent, both build their session with `adminSession()`
 * from that module, and keeping a slice's path, key and body-shaper in one file is what
 * stops a rename touching two.
 *
 * ## Eight fields, no invented ninth
 *
 * `IntakeFacts` is the API's own model and every draft type below is a mirror of it with
 * `""` where the wire has `null`, because a React controlled input cannot hold `null`.
 * Nothing here adds a field: `apps/api/admin/intake.py` argues at length that FLOWS §1
 * NAMES the list, so wanting a ninth is a conversation with the API, not a line here.
 *
 * ## Three properties of that API kept rather than smoothed over
 *
 * - **`languages` on the way out is not `languages` on the way in.** `record_intake`
 *   drops the agent's own `language_primary` before storing (`languages_extra` means the
 *   OTHERS, DATA-MODEL §3) and `read_intake` returns only the extras. So the draft holds
 *   every language including the primary — which is what an operator means by "which
 *   languages does this business work in" — and the round trip re-adds it from
 *   `language_primary`, which the SAME response now carries. It used to be re-added from
 *   a copy the wizard happened to hold because it had chosen it one step earlier; a
 *   resume has chosen nothing, so the response had to start answering it.
 * - **`prose_answers: null` is not "no answers".** It is "this org last submitted before
 *   migration c1f3a7d92b46, so the prose survives only as a compiled sentence". It is
 *   ALSO what a brand-new agent returns, and the two must not be rendered the same way —
 *   see `prosePrefillGap`.
 * - **A day that is absent and a day that is `null` are different answers.** `null` IS
 *   the closed day (`_hours_map`); absent means nobody filled it in. The prefill keeps
 *   both, because the agent says different things about them.
 *
 * ## The draft half, which used to be the gap
 *
 * `save_intake_draft` had no route in front of it, so the only write a browser could
 * reach was the submit — which runs `submission_blockers` first and refuses a half-filled
 * sheet. A partial intake could not be persisted at all, and because nothing partial
 * could be stored there was nothing to resume either. Both halves are now here:
 * `useSaveIntakeDraft` writes the sheet and nothing else, and `useUnfinishedOnboardings`
 * is how an operator finds the client they were half-way through.
 *
 * The DRAFT body is built by the same `toIntakeBody` as the submit, deliberately. The
 * server applies identical STRUCTURAL validation to both (the price pattern, E.164, the
 * length caps) and differs only in not running the completeness gate, so a second body
 * shaper "for drafts" would be a second set of rules for one endpoint pair to disagree
 * about. What differs is the PREFLIGHT: the submit is withheld while `intakeBlockers`
 * would refuse it, and the draft never is — refusing to save a draft for incompleteness
 * is refusing the only thing a draft is for.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { adminSession } from "./admin";
import { apiRequest, type ApiProblem } from "./client";
import { promptHistoryKey } from "./prompts";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The POST body — FLOWS §1's eight fields, every one optional (the step is resumable). */
export type IntakeFacts = Schemas["IntakeFacts"];
/** The GET body — what reopening the step prefills from. */
export type IntakeState = Schemas["IntakeStateOut"];
/** What the submit DID: which prompt version, and whether one was minted at all. */
export type IntakeResult = Schemas["IntakeOut"];
/** What a DRAFT save did: the sheet is stored, and here is what still blocks a submit.
 *  Carries no prompt version and no KB source because a draft mints neither. */
export type IntakeDraftResult = Schemas["IntakeDraftOut"];
/** One account whose wizard was started and never finished. */
export type UnfinishedOnboarding = Schemas["UnfinishedOnboardingOut"];

export type DayHours = Schemas["DayHours"];
export type Weekday = DayHours["day"];
export type Branch = Schemas["Branch"];
export type ServiceItem = Schemas["ServiceItem"];
export type Faq = Schemas["Faq"];
export type StaffMember = Schemas["StaffMember"];
export type EscalationContact = Schemas["EscalationContact"];

/** One `{field, rule, message}` triple off an RFC-9457 body (`core/errors.py`). */
export type ProblemField = NonNullable<ApiProblem["fields"]>[number];

/**
 * The week, in the order `apps/api/admin/intake.py::DAYS` compiles it.
 *
 * Same order, because `_hours_line` walks that tuple to build the sentence the agent
 * reads out — a form that collected Sunday first would still compile Monday first, and
 * an operator checking the compiled block against the form would be comparing two
 * orders. `Weekday` is the GENERATED union, so a day the API stops accepting fails this
 * build rather than the operator's first request.
 */
export const DAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export const DAY_LABELS: Record<Weekday, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

/* ------------------------------------------------------------------ the draft shapes */

/**
 * The form's own state: the wire model with `""` for every `null`.
 *
 * A separate type rather than `IntakeFacts` with looser fields, because the two differ in
 * a way that matters at exactly one moment. `IntakeFacts` is what the SERVER sees, and it
 * must not carry a row nobody filled in; the draft is what the OPERATOR sees, and it must
 * carry the row they just clicked "Add" on. `toIntakeBody` is the one place that
 * difference is resolved.
 */
export interface DayDraft {
  day: Weekday;
  /** `""` while unanswered. `<input type="time">` gives HH:MM or `""` and nothing else,
   *  which is exactly `DayHours`'s `^(?:[01]\d|2[0-3]):[0-5]\d$`. */
  opens: string;
  closes: string;
  closed: boolean;
}

export interface BranchDraft {
  label: string;
  address: string;
}

export interface ServiceDraft {
  name: string;
  /** A STRING all the way down (hard rule 7). The API's pattern is `\d+(\.\d{1,2})?`, so
   *  "₹500" is a field error rather than a number this form silently reinterprets. */
  price_inr: string;
  notes: string;
}

export interface FaqDraft {
  question: string;
  answer: string;
}

export interface StaffDraft {
  name: string;
  pronunciation: string;
  role: string;
}

export interface EscalationDraft {
  name: string;
  phone_e164: string;
  hours: string;
}

export interface IntakeDraft {
  /** Always all seven days, in `DAYS` order — the week is a fixed grid, not a list. */
  business_hours: DayDraft[];
  branches: BranchDraft[];
  services: ServiceDraft[];
  faqs: FaqDraft[];
  staff: StaffDraft[];
  booking_rules: string;
  escalation_contacts: EscalationDraft[];
  /** BCP-47 tags INCLUDING the agent's primary — see the module header. */
  languages: string[];
}

export const blankBranch = (): BranchDraft => ({ label: "", address: "" });
export const blankService = (): ServiceDraft => ({ name: "", price_inr: "", notes: "" });
export const blankFaq = (): FaqDraft => ({ question: "", answer: "" });
export const blankStaff = (): StaffDraft => ({ name: "", pronunciation: "", role: "" });
export const blankEscalation = (): EscalationDraft => ({ name: "", phone_e164: "", hours: "" });

/**
 * One blank row, so a REQUIRED section never opens with nothing to fill in.
 *
 * Applied to branches, services and escalation contacts and to nothing else, because
 * those are exactly the three lists `submission_blockers` refuses a submit without —
 * FAQs and staff are optional there on purpose ("a single-practitioner shop with no FAQ
 * list and no named staff is a real client"). So the form OPENS showing what must be
 * answered, and the optional sections are something you choose to add. A blank row in
 * every section would read as five obligations, two of which are not.
 *
 * It costs nothing on a resume where the operator has deleted every row: a blank row is
 * dropped again by `pruneDraft` before anything is sent.
 */
function atLeastOneRow<T>(rows: T[], blank: () => T): T[] {
  return rows.length > 0 ? rows : [blank()];
}

/* ------------------------------------------------------------------------ the prefill */

const text = (value: string | null | undefined): string => value ?? "";

/**
 * The stored answers as a form — `GET`'s whole reason for existing.
 *
 * Every branch here is about not inventing an answer. An org with `prose_answers: null`
 * gets EMPTY prose rows rather than rows guessed out of `compiled_t0_context`: the block
 * is a compiled sentence, and parsing it back into fields would be this form asserting a
 * price it read out of a string it wrote. `prosePrefillGap` is what tells the operator
 * that is what happened, so the emptiness is explained rather than silently trusted.
 *
 * The primary language comes from the RESPONSE (`state.language_primary`) rather than
 * from a caller-supplied copy. It used to be a parameter, which worked for exactly one
 * caller — the wizard, which had chosen the value one step earlier — and had no answer
 * for a resume that starts at a tenant id. One source, and it is the agent's own row.
 */
export function draftFromState(state: IntakeState): IntakeDraft {
  const prose = state.prose_answers;
  const primaryLanguage = state.language_primary;
  return {
    business_hours: DAYS.map((day) => {
      // `hasOwn` and not a truthiness test: `null` IS the closed day and `undefined` is
      // "nobody filled this in", and the agent says different things about them.
      if (!Object.hasOwn(state.business_hours, day)) {
        return { day, opens: "", closes: "", closed: false };
      }
      const hours = state.business_hours[day];
      if (hours === null) return { day, opens: "", closes: "", closed: true };
      return { day, opens: text(hours.opens), closes: text(hours.closes), closed: false };
    }),
    branches: atLeastOneRow(
      (prose?.branches ?? []).map((branch) => ({
        label: text(branch.label),
        address: text(branch.address),
      })),
      blankBranch,
    ),
    services: atLeastOneRow(
      (prose?.services ?? []).map((service) => ({
        name: text(service.name),
        price_inr: text(service.price_inr),
        notes: text(service.notes),
      })),
      blankService,
    ),
    faqs: (prose?.faqs ?? []).map((faq) => ({
      question: text(faq.question),
      answer: text(faq.answer),
    })),
    staff: (prose?.staff ?? []).map((person) => ({
      name: text(person.name),
      pronunciation: text(person.pronunciation),
      role: text(person.role),
    })),
    booking_rules: text(prose?.booking_rules),
    // Loosely typed on the wire (`list[dict[str, str | None]]`) because the API keeps
    // phone numbers out of `IntakeProse` and gives them their own key. Read defensively.
    escalation_contacts: atLeastOneRow(
      state.escalation_contacts.map((contact) => ({
        name: text(contact.name),
        phone_e164: text(contact.phone_e164),
        hours: text(contact.hours),
      })),
      blankEscalation,
    ),
    // The response carries the EXTRAS only; the primary is re-added here from the agent's
    // own language so the operator sees the full set they answered.
    languages: [primaryLanguage, ...state.languages.filter((tag) => tag !== primaryLanguage)],
  };
}

/**
 * Is there anything stored at all — i.e. is this a resume rather than a first visit?
 *
 * Used to tell the two `prose_answers: null` cases apart. A brand-new agent answers the
 * GET with every field empty; a pre-migration org answers it with hours, contacts,
 * languages or a compiled block and no prose.
 */
export function hasStoredIntake(state: IntakeState): boolean {
  return (
    state.prose_answers !== null ||
    state.compiled_t0_context !== null ||
    state.escalation_contacts.length > 0 ||
    state.languages.length > 0 ||
    Object.keys(state.business_hours).length > 0
  );
}

/**
 * Why the prose answers came back empty when something IS stored, or `null` when there
 * is nothing to explain.
 *
 * The §52 rule applied to a partial answer: an empty services list under an org that
 * plainly has an agent talking about services is not "no services", it is "we cannot show
 * you what they were". Saying so is what stops an operator submitting an empty prose set
 * over a compiled block that has been answering callers for months.
 */
export function prosePrefillGap(state: IntakeState): string | null {
  if (state.prose_answers !== null || !hasStoredIntake(state)) return null;
  return (
    "This client's answers were last submitted before they had a field-by-field home, so " +
    "only the compiled block below survives. Re-enter the addresses, services, FAQs, " +
    "staff and booking rules from it — submitting with them blank replaces the block."
  );
}

/* -------------------------------------------------------------------- the wire body */

const trimmed = (value: string): string | null => {
  const clean = value.trim();
  return clean === "" ? null : clean;
};

const dayAnswered = (day: DayDraft): boolean =>
  day.closed || day.opens !== "" || day.closes !== "";

const branchFilled = (row: BranchDraft): boolean => Boolean(row.label.trim() || row.address.trim());
const serviceFilled = (row: ServiceDraft): boolean =>
  Boolean(row.name.trim() || row.price_inr.trim() || row.notes.trim());
const faqFilled = (row: FaqDraft): boolean => Boolean(row.question.trim() || row.answer.trim());
const staffFilled = (row: StaffDraft): boolean =>
  Boolean(row.name.trim() || row.pronunciation.trim() || row.role.trim());
const escalationFilled = (row: EscalationDraft): boolean =>
  Boolean(row.name.trim() || row.phone_e164.trim() || row.hours.trim());

/**
 * Drop the rows nobody typed in.
 *
 * Called by the step BEFORE the submit and applied to the draft itself, so that what is
 * on screen and what went on the wire have the same indices. That matters because a
 * field error arrives as `branches.0.label`, and the only way to put that message next to
 * the right input is for wire index 0 and row 0 to be the same row.
 *
 * The rejected alternative was to send the pruned body and carry an index map beside the
 * error. It works, and it means the screen and the request disagree about what row 2 is
 * for as long as the error is displayed — one refactor away from a message landing on the
 * wrong address. Pruning what is submitted is the cheaper invariant: what you see is what
 * was sent.
 *
 * The seven day rows are NOT pruned: the week is a fixed grid on screen, and an
 * unanswered day is a blank in it rather than a missing row. `placeIntakeFields` resolves
 * a day-level message through the day NAME instead of through an index.
 */
export function pruneDraft(draft: IntakeDraft): IntakeDraft {
  return {
    ...draft,
    branches: draft.branches.filter(branchFilled),
    services: draft.services.filter(serviceFilled),
    faqs: draft.faqs.filter(faqFilled),
    staff: draft.staff.filter(staffFilled),
    escalation_contacts: draft.escalation_contacts.filter(escalationFilled),
  };
}

/**
 * The draft as `IntakeFacts`.
 *
 * Blank optional strings become `null` rather than `""` — `ServiceItem.price_inr` and
 * `EscalationContact.hours` are `str | None` with patterns and length caps, and `""`
 * fails the pattern where `null` means "not answered". A closed day sends no times at
 * all, because `_hours_map` reads `closed` first and a 09:00 left behind a ticked box
 * would be a time nothing reads and everyone sees.
 */
export function toIntakeBody(draft: IntakeDraft): IntakeFacts {
  const pruned = pruneDraft(draft);
  return {
    business_hours: pruned.business_hours.filter(dayAnswered).map((day) => ({
      day: day.day,
      closed: day.closed,
      opens: day.closed ? null : trimmed(day.opens),
      closes: day.closed ? null : trimmed(day.closes),
    })),
    branches: pruned.branches.map((row) => ({
      label: row.label.trim(),
      address: row.address.trim(),
    })),
    services: pruned.services.map((row) => ({
      name: row.name.trim(),
      price_inr: trimmed(row.price_inr),
      notes: trimmed(row.notes),
    })),
    faqs: pruned.faqs.map((row) => ({
      question: row.question.trim(),
      answer: row.answer.trim(),
    })),
    staff: pruned.staff.map((row) => ({
      name: row.name.trim(),
      pronunciation: trimmed(row.pronunciation),
      role: trimmed(row.role),
    })),
    booking_rules: trimmed(draft.booking_rules),
    escalation_contacts: pruned.escalation_contacts.map((row) => ({
      name: row.name.trim(),
      phone_e164: row.phone_e164.trim(),
      hours: trimmed(row.hours),
    })),
    languages: draft.languages,
  };
}

/* ---------------------------------------------------------------- the blocker preview */

/**
 * What still stands between this body and a submit — a MIRROR of
 * `apps/api/admin/intake.py::submission_blockers`, never a second definition of it.
 *
 * Same doctrine as `kyc.ts::recordBlockReason`: the route is the enforcement and stays
 * so, and this exists only to say the refusal before an operator has filled in a long
 * form and pressed a button that could only ever answer 422. Two things keep the mirror
 * honest: it runs on the BODY (`toIntakeBody`), which is the exact value the server
 * validates, and the codes it returns are the SERVER's codes, so the sentence beside the
 * button and the sentence in the server's `intake_incomplete` detail name one condition.
 *
 * If the two ever disagree the server wins, visibly: the submit is attempted and its
 * `ProblemNotice` renders the refusal.
 */
export function intakeBlockers(facts: IntakeFacts): string[] {
  const blockers: string[] = [];
  const hours = facts.business_hours ?? [];
  if (hours.length === 0) blockers.push("business_hours_missing");
  else if (hours.some((day) => !(day.closed || (day.opens && day.closes))))
    blockers.push("business_hours_incomplete");
  if ((facts.branches ?? []).length === 0) blockers.push("branch_missing");
  if ((facts.services ?? []).length === 0) blockers.push("service_missing");
  if ((facts.escalation_contacts ?? []).length === 0) blockers.push("escalation_contact_missing");
  return blockers;
}

/**
 * What each blocker code means, in the words of the docstring that defines it.
 *
 * Every entry names something DOWNSTREAM that cannot work without the answer, because
 * that is the argument `submission_blockers` makes for each one — this is not a
 * completeness score, and an operator told "4 of 8 sections done" would reasonably ask
 * why FAQs are not one of them.
 */
export const INTAKE_BLOCKER_COPY: Record<string, string> = {
  business_hours_missing:
    "No day has been answered. The after-hours branch (FLOWS §3) reads this, so an empty week is a branch that can never fire.",
  business_hours_incomplete:
    "A day has neither both times nor the closed box ticked. It compiles to nothing while looking answered.",
  branch_missing: "No address. “Where are you?” is the second question every caller asks.",
  service_missing:
    "No service. The price list is both the knowledge-base seed and the most-asked question.",
  escalation_contact_missing:
    "No escalation contact. A transfer during a call has nowhere to go without one.",
};

/** The sentence for a blocker code, falling back to the code itself — fail VISIBLE: a
 *  blocker this build cannot name is precisely the one worth reading. */
export function blockerCopy(code: string): string {
  return lookup(INTAKE_BLOCKER_COPY, code) ?? code;
}

/* ----------------------------------------------------------- placing a field refusal */

/** Every wire path this form renders an input for, given the body it sent. */
function renderedPaths(body: IntakeFacts): string[] {
  const paths = ["booking_rules", "languages"];
  const rows = (name: string, count: number, leaves: string[]) => {
    for (let i = 0; i < count; i += 1) for (const leaf of leaves) paths.push(`${name}.${i}.${leaf}`);
  };
  rows("business_hours", (body.business_hours ?? []).length, ["day", "opens", "closes", "closed"]);
  rows("branches", (body.branches ?? []).length, ["label", "address"]);
  rows("services", (body.services ?? []).length, ["name", "price_inr", "notes"]);
  rows("faqs", (body.faqs ?? []).length, ["question", "answer"]);
  rows("staff", (body.staff ?? []).length, ["name", "pronunciation", "role"]);
  rows("escalation_contacts", (body.escalation_contacts ?? []).length, [
    "name",
    "phone_e164",
    "hours",
  ]);
  return paths;
}

export interface PlacedFields {
  /** The server's message for one control, or nothing. */
  messageAt: (path: string) => string | undefined;
  /** The same, for a day of the week — resolved through the day NAME, because the body
   *  carries only the answered days and the form shows all seven. */
  messageForDay: (day: Weekday, part: "opens" | "closes" | "closed") => string | undefined;
  /** Messages this form has no input for. Rendered in the summary rather than dropped:
   *  a refusal shown twice is a nuisance, a refusal shown nowhere is a bug report. */
  unplaced: ProblemField[];
}

/**
 * Put every field-level refusal where its answer is.
 *
 * `field` is `.`-joined from Pydantic's `loc` minus the `body` prefix (`core/errors.py`),
 * so it arrives as `services.1.price_inr` — an index into what WAS SENT. The step prunes
 * the draft at submit, so that index is also the row on screen for the five lists; the
 * week is the one exception and is resolved by name.
 *
 * "Exact or a descendant" is the matching rule: a message about `languages.2` is shown at
 * the languages group, which is the only control there is for it.
 */
export function placeIntakeFields(fields: ProblemField[], body: IntakeFacts): PlacedFields {
  const messageAt = (path: string): string | undefined =>
    fields.find((f) => f.field === path || f.field.startsWith(`${path}.`))?.message;

  const dayIndex = new Map<Weekday, number>();
  (body.business_hours ?? []).forEach((day, i) => dayIndex.set(day.day, i));

  const rendered = renderedPaths(body);
  const unplaced = fields.filter(
    (f) => !rendered.some((path) => f.field === path || f.field.startsWith(`${path}.`)),
  );

  return {
    messageAt,
    messageForDay: (day, part) => {
      const index = dayIndex.get(day);
      return index === undefined ? undefined : messageAt(`business_hours.${index}.${part}`);
    },
    unplaced,
  };
}

/** The DOM id an input carries, derived from the WIRE path it sends — so a control and
 *  the refusal about it cannot be given two different names. */
export function intakeFieldId(path: string): string {
  return `intake-${path.replace(/\./g, "-")}`;
}

/* ------------------------------------------------------------------------- the hooks */

export function intakePath(tenantId: string, agentId: string): string {
  return `/v1/admin/tenants/${tenantId}/agents/${agentId}/intake`;
}

export function intakeDraftPath(tenantId: string, agentId: string): string {
  return `${intakePath(tenantId, agentId)}/draft`;
}

export function intakeQueryKey(tenantId: string, agentId: string) {
  return ["admin", "intake", tenantId, agentId] as const;
}

export const unfinishedOnboardingsKey = ["admin", "onboarding", "unfinished"] as const;
export const UNFINISHED_ONBOARDINGS_PATH = "/v1/admin/onboarding/unfinished";

/**
 * What is durably stored for this agent — `agents:read`, admin realm.
 *
 * `adminSession()` rather than `viewAsSession()`: this is an admin-realm route with the
 * tenant in the PATH (`requires("agents:read", realm="admin")`), so there is no
 * impersonation header to add and nothing a tenant session could answer.
 *
 * No `refetchInterval`. An intake sheet changes when a person fills a form in, and the
 * only person filling it in is the one looking at this screen.
 */
export function useIntake(tenantId: string, agentId: string): UseQueryResult<IntakeState> {
  return useQuery({
    queryKey: intakeQueryKey(tenantId, agentId),
    queryFn: () => apiRequest<IntakeState>(adminSession(), intakePath(tenantId, agentId)),
    enabled: Boolean(tenantId) && Boolean(agentId),
  });
}

/**
 * Submit the answers — `agents:write`, and everything downstream of it.
 *
 * The route's own note on why that permission and not `admin:tenants`: what this
 * ultimately changes is the agent's prompt and knowledge, which is the authority the
 * publish and KB-approval routes carry.
 *
 * Three caches can be stale the instant this succeeds, and each is invalidated for a
 * reason rather than by reflex:
 *
 * - the intake read, because the step must re-read what is now STORED rather than echo
 *   what it just sent — `record_intake` normalises (it drops the agent's primary language
 *   from the extras) so the response is not the resulting sheet;
 * - the prompt history, because a changed block mints a new `prompt_versions` row and
 *   moves the agent's pointer at it;
 * - the admin KB queue by PREFIX, because the same facts are seeded as a `text` source in
 *   `pending_approval` — an operator who submits an intake and walks to the knowledge
 *   queue must find it there.
 *
 * The publishing caches (`publishingKeys.pending`) are deliberately NOT invalidated even
 * though a LIVE agent is re-published in the same transaction: they are keyed by org SLUG
 * and this hook holds a tenant id, which is the same limit `prompts.ts` states for
 * itself. Threading a slug through for a caller that has no publishing panel on screen
 * would buy nothing.
 */
export function useRecordIntake(
  tenantId: string,
  agentId: string,
): UseMutationResult<IntakeResult, Error, IntakeFacts> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (facts: IntakeFacts) =>
      apiRequest<IntakeResult>(adminSession(), intakePath(tenantId, agentId), {
        method: "POST",
        body: facts,
      }),
    onSuccess: () =>
      void Promise.all([
        client.invalidateQueries({ queryKey: intakeQueryKey(tenantId, agentId) }),
        client.invalidateQueries({ queryKey: promptHistoryKey(tenantId, agentId) }),
        client.invalidateQueries({ queryKey: ["admin", "kb"] }),
        // The account leaves the resume list the moment its intake is submitted.
        client.invalidateQueries({ queryKey: unfinishedOnboardingsKey }),
      ]),
  });
}

/**
 * Save the answers as they stand — `agents:write`, the same authority as the submit.
 *
 * Two caches, and NEITHER of them is the prompt history or the KB queue: a draft mints
 * no prompt version and seeds no source, so invalidating those would be this module
 * claiming work the route explicitly does not do.
 *
 * - the intake read, because the sheet it returns is exactly what was just written;
 * - the resume list, because `blockers` and `draft_saved_at` on that account's row have
 *   both just changed, and a stale list is how an operator resumes into an answer they
 *   already gave.
 *
 * Refetching the intake read does NOT disturb the form: `/admin/new` seeds its draft
 * from the prefill ONCE, so a response arriving mid-edit updates `submitted_at` and the
 * compiled block without touching a control the operator is typing in.
 */
export function useSaveIntakeDraft(
  tenantId: string,
  agentId: string,
): UseMutationResult<IntakeDraftResult, Error, IntakeFacts> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (facts: IntakeFacts) =>
      apiRequest<IntakeDraftResult>(adminSession(), intakeDraftPath(tenantId, agentId), {
        method: "POST",
        body: facts,
      }),
    onSuccess: () =>
      void Promise.all([
        client.invalidateQueries({ queryKey: intakeQueryKey(tenantId, agentId) }),
        client.invalidateQueries({ queryKey: unfinishedOnboardingsKey }),
      ]),
  });
}

/**
 * Which onboardings are unfinished — `org:read`, admin realm.
 *
 * The list the wizard resumes from. It is a READ of accounts (no phone numbers, no
 * answers), which is why the route carries the read permission while every write it
 * leads to still carries `agents:write`.
 */
export function useUnfinishedOnboardings(): UseQueryResult<UnfinishedOnboarding[]> {
  return useQuery({
    queryKey: unfinishedOnboardingsKey,
    queryFn: () =>
      apiRequest<UnfinishedOnboarding[]>(adminSession(), UNFINISHED_ONBOARDINGS_PATH),
  });
}
