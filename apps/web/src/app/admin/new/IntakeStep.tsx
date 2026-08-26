"use client";

import type { ReactNode } from "react";
import {
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  FileWarning,
  Plus,
  Save,
  ShieldAlert,
  Trash2,
} from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { useAdminAccess } from "@/app/admin/access";
import { ApiProblem } from "@/lib/api/client";
import {
  DAY_LABELS,
  blankBranch,
  blankEscalation,
  blankFaq,
  blankService,
  blankStaff,
  blockerCopy,
  intakeBlockers,
  intakeFieldId,
  placeIntakeFields,
  prosePrefillGap,
  pruneDraft,
  toIntakeBody,
  useRecordIntake,
  useSaveIntakeDraft,
  type IntakeDraft,
  type IntakeState,
  type Weekday,
} from "@/lib/api/intake";

import { WIZARD_LANGUAGES } from "./languages";

import type { UseQueryResult } from "@tanstack/react-query";
import { examplesFor } from "@/lib/verticalExamples";

/**
 * The wizard's intake step — FLOWS §1 step 3, "the real work".
 *
 * The API for this shipped in BUILD-LOG §45 and nothing in either realm called it, so an
 * operator onboarding a client had a wizard that jumped from step 1 to step 8 and an
 * intake form that existed only as a curl command. This is the form, built to what
 * `POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake` accepts rather than to
 * what a designer would draw: EIGHT cards for FLOWS §1's eight fields, and no ninth.
 *
 * The two steps still missing from `/admin/new` after this — number provisioning (6) and
 * the test-call gate (7) — stay ABSENT rather than stubbed, for the reason the wizard's
 * own header gives: they depend on Bolna verification this deployment has not done, and a
 * greyed-out control implying the feature exists is worse than a documented gap.
 *
 * ## The render paths, and what each one refuses to claim (BUILD-LOG §52)
 *
 * The prefill GET is the whole reason this step can be reopened, and it is also the most
 * dangerous read on the screen: the POST **replaces** the stored answer sheet, so a read
 * that failed must not become an empty form. An operator who is shown blank fields over a
 * 503 types the answers again and submits them over a sheet that was already there.
 *
 *   loading  → a skeleton, never an empty form;
 *   failed   → a refusal that WITHHOLDS the form, with the server's own words and a retry;
 *   answered → the form, seeded from the answers, whether or not there are any.
 *
 * The same rule reaches one level further in. `prose_answers: null` on a client that
 * plainly has stored intake is not "no services" — it is an org whose last submit predates
 * the column that holds them (migration c1f3a7d92b46), where the compiled block is the
 * only surviving record. `prosePrefillGap` says so above the form and the compiled block
 * is printed beneath it, because the alternative is an operator submitting blanks over an
 * agent that has been answering callers for months.
 *
 * ## Saving a draft: an explicit control, not an autosave
 *
 * `POST …/intake/draft` stores the sheet with no compile, no prompt version and no KB
 * seed — FLOWS §1's "draft state saved at every step" — and the operator presses a
 * button for it.
 *
 * The rejected alternative was a debounced autosave, and it was rejected on this form
 * SPECIFICALLY rather than on principle. Half of these controls are pattern-constrained
 * on the wire: `phone_e164` is `^\+[1-9]\d{7,18}$`, `price_inr` is `^\d+(\.\d{1,2})?$`.
 * An autosave fires MID-VALUE by construction, so typing "+9198…" would post a body the
 * server must refuse — correctly, since a sheet stored unvalidated comes back
 * unparseable and the next resume shows a blank form (`_sheet_answers`). The indicator
 * would therefore sit on "failed" through most of the typing it was meant to reassure
 * about, and an indicator that cries wolf teaches the operator to ignore it — the same
 * defect as a silent failure, one step along. A press is a moment the operator has
 * finished a thought, and it is the only moment the body is meant to be whole.
 *
 * What the press MUST do, and does: report its state honestly. Saving, saved with the
 * server's own outcome, or a refusal rendered exactly like the submit's — including
 * field-level messages at their inputs, because a draft is refused for the same
 * structural reasons a submit is.
 */
export function IntakeStep({
  tenantId,
  agentId,
  vertical,
  state,
  draft,
  onDraftChange,
  onContinue,
}: {
  tenantId: string;
  agentId: string;
  /**
   * The trade, from the server on both the creation and the resume path.
   *
   * EVERY EXAMPLE ON THIS FORM USED TO DESCRIBE A DENTAL CLINIC — "Consultation", "₹500",
   * "Dr Lakshmi Prasad", "Dentist", "Do you take walk-ins?", "never promise a specific
   * doctor without checking" — while four of the five verticals we ship are not clinics.
   * Nothing was pre-filled (these are `placeholder`s, so nothing could be submitted
   * unchanged), but a placeholder is the fastest instruction on a form, and forty fields
   * of clinic vocabulary teach an operator to describe a property office as if it had
   * patients. `lib/verticalExamples.ts` holds one row per trade.
   */
  vertical: string;
  state: UseQueryResult<IntakeState>;
  /** `null` until the prefill lands — the form is never rendered from a guess. */
  draft: IntakeDraft | null;
  onDraftChange: (draft: IntakeDraft) => void;
  onContinue: () => void;
}) {
  // ONE lookup, read by every field below. Threading twenty strings through this
  // component would be the same table with more places to get it wrong.
  const eg = examplesFor(vertical);
  const record = useRecordIntake(tenantId, agentId);
  const saveDraft = useSaveIntakeDraft(tenantId, agentId);
  // `agents:write` — the permission the ROUTE declares (`admin/routes.py`), not a guess
  // about seniority. Both admin roles hold it today (`core/rbac.py`), so this gate is
  // rarely the answer; it is here because "rarely" is not "never" and a dead submit
  // button at the foot of a forty-control form is the worst place to discover a 403.
  const write = useAdminAccess("agents:write", "record this client's intake");

  // A refusal, FIRST — before the skeleton, because a failed read leaves `draft` null
  // forever and the loading branch below would otherwise spin on it. The form is withheld
  // rather than merely unpopulated: the submit replaces the stored sheet outright, so
  // writing from here while the current answers are unreadable is a blind overwrite.
  if (state.error) {
    return (
      <div className="space-y-4">
        <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />
        <NoticeBox
          tone="warn"
          icon={<FileWarning aria-hidden className="h-5 w-5" />}
          title="Cannot fill the intake while the stored answers are unreadable"
        >
          <p className="mt-1 text-xs opacity-90">
            We could not read what is already on file for this agent. Submitting replaces
            that sheet outright, so an empty form here would invite you to type the answers
            again and post them over answers that may already be there. Retry the read
            above; the form comes back with it.
          </p>
        </NoticeBox>
        <button type="button" onClick={onContinue} className={SECONDARY_BUTTON}>
          Skip to the owner invite
          <ArrowRight aria-hidden className="h-4 w-4" />
        </button>
      </div>
    );
  }

  if (draft === null) return <Skeleton rows={8} />;

  const stored = state.data;
  const body = toIntakeBody(draft);
  const blockers = intakeBlockers(body);
  /**
   * The refusal on screen, from whichever write produced it.
   *
   * At most one can exist at a time: an edit resets both (see `update`), and each
   * button resets the other before firing. That is what keeps `placed` below sound —
   * a field message is only ever placed against the draft that produced it.
   */
  const failure = record.error ?? saveDraft.error ?? null;
  const problem = failure instanceof ApiProblem ? failure : null;
  const placed = placeIntakeFields(problem?.fields ?? [], body);
  const gap = stored ? prosePrefillGap(stored) : null;
  /**
   * The agent's OWN primary language, from the server.
   *
   * `stored` is defined whenever `draft` is — the parent seeds the draft from this
   * query's data and from nothing else — so the fallback is unreachable; it is written
   * as `""` rather than as a language so that an impossible undefined marks NO option
   * primary instead of silently asserting Telugu about a clinic that answers in Hindi.
   */
  const primaryLanguage = stored?.language_primary ?? "";

  /**
   * Every edit goes through here, and it resets the mutation on the way.
   *
   * That reset is what makes `placed` above correct without carrying an index map beside
   * the error: a field message can only be on screen while the draft is exactly the one
   * that produced it, because touching any control clears the refusal. It also clears the
   * success notice, which is right — a notice describing a submission the form no longer
   * matches is the same defect one screen smaller.
   */
  const update = (next: IntakeDraft) => {
    onDraftChange(next);
    record.reset();
    // The draft save's outcome is cleared with it, and for the stronger reason: "Draft
    // saved" left standing over an edited form tells the operator their current answers
    // are on file. They are not — that is the sentence a draft feature exists to make
    // true, so it must never be shown when it is false.
    saveDraft.reset();
  };

  /**
   * Save what is typed, refused only for the reasons the SERVER would refuse it.
   *
   * No blocker preflight, deliberately, and this is the mirror image of the submit
   * button's: `intakeBlockers` withholds the submit because the route would answer 422,
   * and it must NOT withhold this one because the route answers 200 — refusing to save
   * a draft for incompleteness refuses the only thing a draft is for.
   */
  const onSaveDraft = () => {
    record.reset();
    const pruned = pruneDraft(draft);
    onDraftChange(pruned);
    saveDraft.mutate(toIntakeBody(pruned));
  };

  const setDay = (day: Weekday, change: Partial<{ opens: string; closes: string; closed: boolean }>) =>
    update({
      ...draft,
      business_hours: draft.business_hours.map((row) =>
        row.day === day ? { ...row, ...change } : row,
      ),
    });

  const toggleLanguage = (tag: string, on: boolean) =>
    update({
      ...draft,
      languages: on
        ? [...draft.languages, tag]
        : draft.languages.filter((current) => current !== tag),
    });

  return (
    <div className="space-y-4">
      {stored?.submitted_at && (
        <NoticeBox tone="neutral" icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}>
          <p className="text-xs">
            Last submitted <span className="font-medium">{formatIST(stored.submitted_at)}</span>.
            The answers below are what is stored; submitting again recompiles the agent&apos;s
            facts and re-seeds its knowledge base.
          </p>
        </NoticeBox>
      )}

      {gap && (
        <NoticeBox
          tone="warn"
          icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
          title="Only the summary we build for the agent is kept for this client"
        >
          <p className="mt-1 text-xs opacity-90">{gap}</p>
        </NoticeBox>
      )}

      {/* What the agent says TODAY, printed rather than parsed back into fields: the block
          is a compiled sentence, and turning it back into a price list would be this form
          asserting a number it read out of a string it wrote. It carries no escalation
          number by construction (`compile_t0_facts` leaves them out on purpose — a staff
          mobile in a system prompt is a number the agent can read out to whoever asks). */}
      {stored?.compiled_t0_context && (
        <Card title="What the agent says today">
          {/* No `overflow-x-auto`: `whitespace-pre-wrap break-words` means this can never
              overflow sideways, so the utility only ever declared a scroll container that
              does not scroll — and an unreachable one at that (see `ScrollRegion`). */}
          <pre className="whitespace-pre-wrap break-words font-mono text-xs text-ink-muted">
            {stored.compiled_t0_context}
          </pre>
        </Card>
      )}

      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          // Prune BEFORE sending and put the pruned draft on screen, so a field refusal
          // about `services.1.price_inr` lands on the row the operator can see is row 1.
          // `toIntakeBody` prunes internally too; doing it to the draft as well is what
          // keeps the two indexings identical. See `pruneDraft` for the alternative.
          // A draft save's outcome must not sit under a submit's: one write is on
          // screen at a time, which is also what keeps `placed` unambiguous.
          saveDraft.reset();
          const pruned = pruneDraft(draft);
          onDraftChange(pruned);
          record.mutate(toIntakeBody(pruned));
        }}
      >
        <RestrictionNote reason={write.reason} />

        <Card title="Business hours">
          <p className="-mt-2 text-xs text-ink-muted">
            The agent uses these on every after-hours call, and reads them out to callers
            who ask. A day left blank means “nobody has answered this yet”, which is a
            different fact from “closed” — tick the box for closed.
          </p>
          <div className="mt-4 space-y-2">
            {draft.business_hours.map((row) => (
              <div
                key={row.day}
                className="grid items-end gap-3 rounded-card border border-line bg-app p-3 sm:grid-cols-[8rem_1fr_1fr_6rem]"
              >
                <span className="text-sm font-medium text-ink">{DAY_LABELS[row.day]}</span>
                {/* The DOM id is path-SHAPED but keyed by the day rather than by the wire
                    index: the form always shows seven days and the body carries only the
                    answered ones, so an index here would name a different day tomorrow. */}
                <Field
                  id={intakeFieldId(`business_hours.${row.day}.opens`)}
                  label="Opens"
                  error={placed.messageForDay(row.day, "opens")}
                >
                  {(props) => (
                    <input
                      {...props}
                      type="time"
                      value={row.opens}
                      disabled={row.closed || !write.allowed}
                      onChange={(e) => setDay(row.day, { opens: e.target.value })}
                      className={FIELD}
                    />
                  )}
                </Field>
                <Field
                  id={intakeFieldId(`business_hours.${row.day}.closes`)}
                  label="Closes"
                  error={placed.messageForDay(row.day, "closes")}
                >
                  {(props) => (
                    <input
                      {...props}
                      type="time"
                      value={row.closes}
                      disabled={row.closed || !write.allowed}
                      onChange={(e) => setDay(row.day, { closes: e.target.value })}
                      className={FIELD}
                    />
                  )}
                </Field>
                <label className="flex items-center gap-2 pb-1.5 text-sm text-ink-muted">
                  <input
                    type="checkbox"
                    checked={row.closed}
                    disabled={!write.allowed}
                    onChange={(e) => setDay(row.day, { closed: e.target.checked })}
                  />
                  Closed
                </label>
              </div>
            ))}
          </div>
        </Card>

        <RowSection
          title="Addresses and branches"
          description="Where the business is. “Where are you?” is the second question every caller asks, so at least one is required."
          rows={draft.branches}
          blank={blankBranch}
          addLabel="Add a branch"
          disabled={!write.allowed}
          onChange={(branches) => update({ ...draft, branches })}
        >
          {(row, index, patch) => (
            <>
              <Field
                id={intakeFieldId(`branches.${index}.label`)}
                label="What it is called"
                error={placed.messageAt(`branches.${index}.label`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.label}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ label: e.target.value })}
                    placeholder={eg.branchLabel}
                    className={FIELD}
                  />
                )}
              </Field>
              <Field
                id={intakeFieldId(`branches.${index}.address`)}
                label="Address"
                error={placed.messageAt(`branches.${index}.address`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.address}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ address: e.target.value })}
                    placeholder="Road, area, city, PIN"
                    className={FIELD}
                  />
                )}
              </Field>
            </>
          )}
        </RowSection>

        <RowSection
          title="Services and prices"
          description={
            "The price list is both the knowledge-base seed and the most-asked question, " +
            "so at least one is required. Leave the price blank for “" +
            eg.askOnArrival +
            "” — that is a real answer."
          }
          rows={draft.services}
          blank={blankService}
          addLabel="Add a service"
          disabled={!write.allowed}
          onChange={(services) => update({ ...draft, services })}
        >
          {(row, index, patch) => (
            <>
              <Field
                id={intakeFieldId(`services.${index}.name`)}
                label="Service"
                error={placed.messageAt(`services.${index}.name`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.name}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ name: e.target.value })}
                    placeholder={eg.serviceName}
                    className={FIELD}
                  />
                )}
              </Field>
              <Field
                id={intakeFieldId(`services.${index}.price_inr`)}
                label="Price (₹)"
                hint="Digits only — the agent reads back the digits the client typed, so it is never turned into a number here (hard rule 7)."
                error={placed.messageAt(`services.${index}.price_inr`)}
              >
                {(props) => (
                  <input
                    {...props}
                    inputMode="decimal"
                    value={row.price_inr}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ price_inr: e.target.value })}
                    placeholder={eg.servicePrice}
                    className={`${FIELD} font-mono`}
                  />
                )}
              </Field>
              <Field
                id={intakeFieldId(`services.${index}.notes`)}
                label="Note"
                error={placed.messageAt(`services.${index}.notes`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.notes}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ notes: e.target.value })}
                    placeholder={eg.serviceNote}
                    className={FIELD}
                  />
                )}
              </Field>
            </>
          )}
        </RowSection>

        <RowSection
          title="Top FAQs"
          description="Optional. What callers ask that the price list does not answer."
          rows={draft.faqs}
          blank={blankFaq}
          addLabel="Add an FAQ"
          emptyHint="None yet. A shop with no FAQ list is a real client — the submit does not require one."
          disabled={!write.allowed}
          onChange={(faqs) => update({ ...draft, faqs })}
        >
          {(row, index, patch) => (
            <>
              <Field
                id={intakeFieldId(`faqs.${index}.question`)}
                label="Question"
                error={placed.messageAt(`faqs.${index}.question`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.question}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ question: e.target.value })}
                    placeholder={eg.faqQuestion}
                    className={FIELD}
                  />
                )}
              </Field>
              <Field
                id={intakeFieldId(`faqs.${index}.answer`)}
                label="Answer"
                error={placed.messageAt(`faqs.${index}.answer`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.answer}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ answer: e.target.value })}
                    className={FIELD}
                  />
                )}
              </Field>
            </>
          )}
        </RowSection>

        <RowSection
          title="Staff names and pronunciations"
          description={
            "Optional. Spell each name the way it should be SAID — proper nouns work " +
            "best spelled phonetically, because " +
            eg.staffWhyItMatters +
            "."
          }
          rows={draft.staff}
          blank={blankStaff}
          addLabel="Add a person"
          emptyHint="None yet. The submit does not require any."
          disabled={!write.allowed}
          onChange={(staff) => update({ ...draft, staff })}
        >
          {(row, index, patch) => (
            <>
              <Field
                id={intakeFieldId(`staff.${index}.name`)}
                label="Name"
                error={placed.messageAt(`staff.${index}.name`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.name}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ name: e.target.value })}
                    placeholder={eg.staffName}
                    className={FIELD}
                  />
                )}
              </Field>
              <Field
                id={intakeFieldId(`staff.${index}.pronunciation`)}
                label="Said as"
                error={placed.messageAt(`staff.${index}.pronunciation`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.pronunciation}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ pronunciation: e.target.value })}
                    placeholder={eg.staffSpoken}
                    className={FIELD}
                  />
                )}
              </Field>
              <Field
                id={intakeFieldId(`staff.${index}.role`)}
                label="Role"
                error={placed.messageAt(`staff.${index}.role`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.role}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ role: e.target.value })}
                    placeholder={eg.staffRole}
                    className={FIELD}
                  />
                )}
              </Field>
            </>
          )}
        </RowSection>

        <Card title="Booking rules">
          <p className="-mt-2 text-xs text-ink-muted">
            Optional, and free prose: how appointments are taken, how far ahead, what the
            agent may promise and what it must not.
          </p>
          <div className="mt-4">
            <Field
              id={intakeFieldId("booking_rules")}
              label="Rules"
              hint="The agent uses this word for word, so write it the way the agent should understand it."
              error={placed.messageAt("booking_rules")}
            >
              {(props) => (
                <textarea
                  {...props}
                  rows={4}
                  maxLength={2000}
                  value={draft.booking_rules}
                  disabled={!write.allowed}
                  onChange={(e) => update({ ...draft, booking_rules: e.target.value })}
                  placeholder={eg.bookingRules}
                  className={FIELD}
                />
              )}
            </Field>
          </div>
        </Card>

        <RowSection
          title="Escalation contacts"
          description="Who a call is transferred to when the agent cannot help. At least one is required — a transfer has nowhere to go without it. These numbers are stored on the agent and are deliberately never put into the agent's instructions."
          rows={draft.escalation_contacts}
          blank={blankEscalation}
          addLabel="Add a contact"
          disabled={!write.allowed}
          onChange={(escalation_contacts) => update({ ...draft, escalation_contacts })}
        >
          {(row, index, patch) => (
            <>
              <Field
                id={intakeFieldId(`escalation_contacts.${index}.name`)}
                label="Name"
                error={placed.messageAt(`escalation_contacts.${index}.name`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.name}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ name: e.target.value })}
                    placeholder={eg.contactName}
                    className={FIELD}
                  />
                )}
              </Field>
              {/* The one number on this screen, and it is an INPUT rather than a display:
                  the operator is typing or correcting it. Nothing echoes it back anywhere
                  — not in the compiled block, not in the audit summary, not in a
                  confirmation line (hard rule 6). */}
              <Field
                id={intakeFieldId(`escalation_contacts.${index}.phone_e164`)}
                label="Phone"
                hint="With the country code — for example +91…"
                error={placed.messageAt(`escalation_contacts.${index}.phone_e164`)}
              >
                {(props) => (
                  <input
                    {...props}
                    inputMode="tel"
                    autoComplete="off"
                    value={row.phone_e164}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ phone_e164: e.target.value })}
                    placeholder="+919876543210"
                    className={`${FIELD} font-mono`}
                  />
                )}
              </Field>
              <Field
                id={intakeFieldId(`escalation_contacts.${index}.hours`)}
                label="When they are reachable"
                error={placed.messageAt(`escalation_contacts.${index}.hours`)}
              >
                {(props) => (
                  <input
                    {...props}
                    value={row.hours}
                    disabled={!write.allowed}
                    onChange={(e) => patch({ hours: e.target.value })}
                    placeholder="Mon–Sat, 9–6"
                    className={FIELD}
                  />
                )}
              </Field>
            </>
          )}
        </RowSection>

        <Card title="Languages">
          <p className="-mt-2 text-xs text-ink-muted">
            Which languages this business works in. The primary was chosen in step 1 and is
            fixed here — the API stores the OTHERS (DATA-MODEL §3), so a second copy of the
            primary would be dropped on the way in and come back missing.
          </p>
          <fieldset className="mt-4">
            <legend className={FIELD_LABEL}>Also handled</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              {WIZARD_LANGUAGES.map((option) => {
                const isPrimary = option.value === primaryLanguage;
                return (
                  <label
                    key={option.value}
                    className="flex items-center gap-2 rounded-card border border-line bg-surface p-3 text-sm text-ink"
                  >
                    <input
                      type="checkbox"
                      checked={isPrimary || draft.languages.includes(option.value)}
                      disabled={isPrimary || !write.allowed}
                      onChange={(e) => toggleLanguage(option.value, e.target.checked)}
                    />
                    <span>
                      {option.label}
                      {isPrimary && (
                        <span className="block text-xs text-ink-faint">
                          Primary — the agent&apos;s own language
                        </span>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
            {placed.messageAt("languages") && (
              <p className="mt-2 text-xs font-medium text-rose-700 dark:text-rose-400">
                {placed.messageAt("languages")}
              </p>
            )}
          </fieldset>
        </Card>

        {/*
         * Two error surfaces, split by WHERE the answer is — the split `/signup` already
         * makes. A problem with no field list is about the request as a whole
         * (`intake_incomplete`, a 403, a dropped connection) and `ProblemNotice` is this
         * repo's one way to render that, carrying `remediation`, `retryable` and the trace
         * ref. A problem WITH a field list is about specific answers, and those are
         * announced at their inputs above (`aria-invalid` + `aria-describedby`), so the
         * summary here only points at them — and carries anything the form has no input
         * for, because a refusal shown nowhere is worse than one shown twice.
         */}
        {problem && problem.fields?.length ? (
          <NoticeBox
            tone="stop"
            icon={<CircleAlert aria-hidden className="h-5 w-5" />}
            title={problem.message}
          >
            <div role="alert" className="mt-1 space-y-1 text-xs">
              <p>Check the answers marked below.</p>
              {problem.remediation && <p>{problem.remediation}</p>}
              {placed.unplaced.length > 0 && (
                <ul className="list-inside list-disc">
                  {placed.unplaced.map((field) => (
                    <li key={field.field}>
                      <span className="font-medium">{field.field}</span>: {field.message}
                    </li>
                  ))}
                </ul>
              )}
              {problem.traceId && <p className="font-mono">ref {problem.traceId}</p>}
            </div>
          </NoticeBox>
        ) : (
          failure != null && <ProblemNotice error={failure} />
        )}

        {saveDraft.data && (
          <NoticeBox
            tone="neutral"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Draft saved"
          >
            {/* What a draft did and, just as importantly, what it did not: an operator
                who read "saved" and walked away must not believe the agent now knows
                any of this. The blockers come from the SERVER's response rather than
                from the local preview, because this notice is a report of the write. */}
            <p className="mt-1 text-xs">
              These answers are on file and this client is on the resume list. Nothing has
              been built into the agent yet — the button below does that.
              {saveDraft.data.blockers.length > 0 &&
                ` ${saveDraft.data.blockers.length} answer${
                  saveDraft.data.blockers.length === 1 ? "" : "s"
                } still needed before it can be submitted.`}
            </p>
          </NoticeBox>
        )}

        {record.data && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Intake recorded"
          >
            {/* `regenerated: false` is not a failure and must not read like one — it is
                the honest result of reopening the step and saving it unchanged, which
                FLOWS §1's "every step idempotent" asks for. */}
            <p className="mt-1 text-xs">
              {record.data.regenerated ? (
                <>
                  Compiled into the agent&apos;s facts as prompt version{" "}
                  <span className="font-semibold">{record.data.prompt_version}</span>
                  {record.data.kb_source_id
                    ? ", and the same facts are queued in the knowledge base awaiting approval."
                    : "."}
                </>
              ) : (
                <>
                  Nothing changed — these answers already match what the agent carries, so
                  no new prompt version was minted.
                </>
              )}
            </p>
          </NoticeBox>
        )}

        {/* The gate the SERVER applies, said before the click rather than as a 422 after a
            long form. `intakeBlockers` mirrors `submission_blockers` and runs on the exact
            body that would be sent; the route remains the enforcement. */}
        {blockers.length > 0 && (
          <div className="rounded-card border border-line bg-app p-3 text-xs text-ink-muted">
            <p className="font-medium text-ink">Still needed before this can be submitted:</p>
            <ul className="mt-1.5 list-inside list-disc">
              {blockers.map((code) => (
                <li key={code}>{blockerCopy(code)}</li>
              ))}
            </ul>
            <p className="mt-2">
              FAQs, staff and booking rules are deliberately not on this list — a
              single-practitioner shop with none of them is a real client.
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          {/* Shared primary CTA: the "Submit intake" label stays mounted so the button's
              accessible name never flickers to "Recording…" mid-request; the spinner rides
              `loading`, and the two non-pending disable reasons are unchanged. */}
          <ActionButton
            type="submit"
            title={write.reason ?? undefined}
            loading={record.isPending}
            disabled={blockers.length > 0 || !write.allowed}
          >
            <CheckCircle2 aria-hidden className="h-4 w-4" />
            Submit intake
          </ActionButton>
          {/* Never gated on `blockers` — see `onSaveDraft`. Gated on the SAME
              permission as the submit, because it writes the same client's answers to
              the same row. */}
          <button
            type="button"
            onClick={onSaveDraft}
            title={write.reason ?? undefined}
            disabled={saveDraft.isPending || !write.allowed}
            className={SECONDARY_BUTTON}
          >
            <Save aria-hidden className="h-4 w-4" />
            {saveDraft.isPending ? "Saving…" : "Save draft"}
          </button>
          <button type="button" onClick={onContinue} className={SECONDARY_BUTTON}>
            Continue to the owner invite
            <ArrowRight aria-hidden className="h-4 w-4" />
          </button>
        </div>
        {/* Said where the buttons are, because it is the answer to "why is that one
            dead". `RestrictionNote` at the top of the form covers the disabled inputs;
            this covers the control at the bottom of a long page. */}
        {write.reason && <p className="text-xs text-ink-muted">{write.reason}</p>}
        {/* What is on file, from the SERVER's stamps rather than from a mutation this
            visit happens to remember — the sentence has to be true for an operator who
            arrived by resuming, whose saves happened in another session entirely. */}
        {stored?.saved_at ? (
          <p className="text-xs text-ink-faint">
            Draft on file from {formatIST(stored.saved_at)}. Edits since then are only in
            this browser until you save again; leaving the wizard loses them.
          </p>
        ) : (
          <p className="text-xs text-ink-faint">
            Nothing here is stored until you save the draft or submit. A saved draft can be
            picked up from the unfinished list on this screen.
          </p>
        )}
      </form>
    </div>
  );
}

/**
 * A repeatable section: a card, its rows, a remove per row and one add.
 *
 * Five of the eight fields are lists of two or three boxes each, and writing them out
 * five times is how the add button on one of them ends up doing something slightly
 * different. The row CONTENT stays at the call site as a render function, because that is
 * the only part that differs.
 *
 * Rows are keyed by index, which is safe here in a way it usually is not: every value is
 * held in the draft and passed down, so a row carries no state of its own for React to
 * mis-associate after a removal.
 */
function RowSection<T>({
  title,
  description,
  rows,
  blank,
  addLabel,
  emptyHint,
  disabled,
  onChange,
  children,
}: {
  title: string;
  description: string;
  rows: T[];
  blank: () => T;
  addLabel: string;
  emptyHint?: string;
  disabled: boolean;
  onChange: (rows: T[]) => void;
  children: (row: T, index: number, patch: (change: Partial<T>) => void) => ReactNode;
}) {
  return (
    <Card title={title}>
      <p className="-mt-2 text-xs text-ink-muted">{description}</p>
      <div className="mt-4 space-y-3">
        {rows.length === 0 && emptyHint && <p className="text-xs text-ink-faint">{emptyHint}</p>}
        {rows.map((row, index) => (
          <div key={index} className="relative rounded-card border border-line bg-app p-3 pr-10">
            <button
              type="button"
              aria-label={`Remove ${title.toLowerCase()} ${index + 1}`}
              disabled={disabled}
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
              className="absolute right-2 top-2 rounded-md p-1.5 text-ink-faint enabled:hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:enabled:hover:bg-white/5"
            >
              <Trash2 aria-hidden className="h-4 w-4" />
            </button>
            <div className="grid gap-3 sm:grid-cols-2">
              {children(row, index, (change) =>
                onChange(rows.map((current, i) => (i === index ? { ...current, ...change } : current))),
              )}
            </div>
          </div>
        ))}
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange([...rows, blank()])}
          className={SECONDARY_BUTTON_SM}
        >
          <Plus aria-hidden className="h-3.5 w-3.5" />
          {addLabel}
        </button>
      </div>
    </Card>
  );
}

/**
 * One labelled control, with its hint and its refusal WIRED to it.
 *
 * Copied from `/signup`'s `Field`, deliberately identically — same render-prop shape,
 * same `aria-describedby`/`aria-invalid` wiring, same reason: the input needs the
 * generated ids, and passing them down is what makes the association real rather than
 * visual. A screen reader announces "Price, invalid, string should match pattern" while
 * tabbing, instead of leaving the operator to hunt for a red block at the top of a form
 * that is forty controls long.
 *
 * It is copied rather than imported because `/signup/page.tsx` is a route file and Next
 * rejects a non-convention export from one. THE FOLLOW-UP is the same one `ui.tsx`'s form
 * constants already carry: promote `Field` into `ui.tsx` and delete both copies.
 */
function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: (props: {
    id: string;
    "aria-describedby"?: string;
    "aria-invalid"?: true;
  }) => ReactNode;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      {children({
        id,
        "aria-describedby": describedBy,
        ...(error ? { "aria-invalid": true as const } : {}),
      })}
      {hint && (
        <span id={hintId} className={FIELD_HINT}>
          {hint}
        </span>
      )}
      {error && (
        <span
          id={errorId}
          className="mt-1 block text-xs font-medium text-rose-700 dark:text-rose-400"
        >
          {error}
        </span>
      )}
    </div>
  );
}
