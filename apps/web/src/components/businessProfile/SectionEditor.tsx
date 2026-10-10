"use client";

import { FIELD } from "@/components/ui";
import {
  PROFILE_LANGUAGES,
  blankBranch,
  blankContact,
  blankFaq,
  blankService,
  blankStaff,
  profileFieldId,
  type ProfileDraft,
  type StepId,
} from "@/lib/api/businessProfile";
import { examplesFor } from "@/lib/verticalExamples";

import { Field, RowList } from "./fields";
import { HoursEditor, hoursProblems } from "./HoursEditor";

/**
 * The editor for ONE topic of the business profile. The setup wizard shows one per step
 * and the Business profile screen shows each in its own section, so both screens edit the
 * same draft the same way.
 *
 * `errorAt(path)` is the server's message for a wire path of this section
 * (`services.1.price_inr`); rows are pruned before a save, so wire index and row index
 * are the same row.
 */
export function SectionEditor({
  step,
  draft,
  onChange,
  disabled,
  errorAt,
  vertical,
}: {
  step: StepId;
  draft: ProfileDraft;
  onChange: (next: ProfileDraft) => void;
  disabled: boolean;
  errorAt: (path: string) => string | undefined;
  vertical: string | null;
}) {
  const eg = examplesFor(vertical);
  const input = (path: string, label: string, value: string, set: (v: string) => void, extra?: {
    placeholder?: string;
    hint?: string;
    inputMode?: "decimal" | "tel";
    mono?: boolean;
  }) => (
    <Field id={profileFieldId(path)} label={label} hint={extra?.hint} error={errorAt(path)}>
      {(props) => (
        <input
          {...props}
          value={value}
          disabled={disabled}
          inputMode={extra?.inputMode}
          placeholder={extra?.placeholder}
          onChange={(e) => set(e.target.value)}
          className={`${FIELD}${extra?.mono ? " font-mono" : ""}`}
        />
      )}
    </Field>
  );

  switch (step) {
    case "hours": {
      const local = hoursProblems(draft);
      return (
        <HoursEditor
          draft={draft}
          onChange={onChange}
          disabled={disabled}
          errorAt={(day) => local[day as keyof typeof local] ?? errorAt("hours")}
        />
      );
    }
    case "branches":
      return (
        <RowList
          noun="branch"
          rows={draft.branches}
          blank={blankBranch}
          addLabel="Add a branch"
          empty="No address yet."
          disabled={disabled}
          onChange={(branches) => onChange({ ...draft, branches })}
        >
          {(row, i, patch) => (
            <>
              {input(`branches.${i}.label`, "Name", row.label, (label) => patch({ label }), {
                placeholder: eg.branchLabel,
              })}
              {input(`branches.${i}.address`, "Address", row.address, (address) => patch({ address }), {
                placeholder: "Road, area, city, PIN",
              })}
            </>
          )}
        </RowList>
      );
    case "services":
      return (
        <RowList
          noun="service"
          rows={draft.services}
          blank={blankService}
          addLabel="Add a service"
          empty="No services yet."
          columns={3}
          disabled={disabled}
          onChange={(services) => onChange({ ...draft, services })}
        >
          {(row, i, patch) => (
            <>
              {input(`services.${i}.name`, "Service", row.name, (name) => patch({ name }), {
                placeholder: eg.serviceName,
              })}
              {input(`services.${i}.price_inr`, "Price (₹)", row.price_inr, (price_inr) => patch({ price_inr }), {
                placeholder: eg.servicePrice,
                hint: `Digits only. Leave blank for “${eg.askOnArrival}”.`,
                inputMode: "decimal",
                mono: true,
              })}
              {input(`services.${i}.notes`, "Note", row.notes, (notes) => patch({ notes }), {
                placeholder: eg.serviceNote,
              })}
            </>
          )}
        </RowList>
      );
    case "faqs":
      return (
        <RowList
          noun="question"
          rows={draft.faqs}
          blank={blankFaq}
          addLabel="Add a question"
          empty="No questions yet. You can skip this."
          columns={1}
          disabled={disabled}
          onChange={(faqs) => onChange({ ...draft, faqs })}
        >
          {(row, i, patch) => (
            <>
              {input(`faqs.${i}.question`, "Question", row.question, (question) => patch({ question }), {
                placeholder: eg.faqQuestion,
              })}
              {input(`faqs.${i}.answer`, "Answer", row.answer, (answer) => patch({ answer }))}
            </>
          )}
        </RowList>
      );
    case "staff":
      return (
        <RowList
          noun="person"
          rows={draft.staff}
          blank={blankStaff}
          addLabel="Add a person"
          empty="Nobody yet. You can skip this."
          columns={3}
          disabled={disabled}
          onChange={(staff) => onChange({ ...draft, staff })}
        >
          {(row, i, patch) => (
            <>
              {input(`staff.${i}.name`, "Name", row.name, (name) => patch({ name }), {
                placeholder: eg.staffName,
              })}
              {input(`staff.${i}.pronunciation`, "Said as", row.pronunciation, (pronunciation) => patch({ pronunciation }), {
                placeholder: eg.staffSpoken,
              })}
              {input(`staff.${i}.role`, "Role", row.role, (role) => patch({ role }), {
                placeholder: eg.staffRole,
              })}
            </>
          )}
        </RowList>
      );
    case "booking":
      return (
        <Field
          id={profileFieldId("booking_rules")}
          label="Booking rules"
          hint="Your agents follow this as written."
          error={errorAt("booking_rules")}
        >
          {(props) => (
            <textarea
              {...props}
              rows={4}
              maxLength={2000}
              value={draft.booking_rules}
              disabled={disabled}
              placeholder={eg.bookingRules}
              onChange={(e) => onChange({ ...draft, booking_rules: e.target.value })}
              className={FIELD}
            />
          )}
        </Field>
      );
    case "contacts":
      return (
        <RowList
          noun="person"
          rows={draft.escalation_contacts}
          blank={blankContact}
          addLabel="Add a person"
          empty="Nobody yet."
          columns={3}
          disabled={disabled}
          onChange={(escalation_contacts) => onChange({ ...draft, escalation_contacts })}
        >
          {(row, i, patch) => (
            <>
              {input(`contacts.${i}.label`, "Name", row.name, (name) => patch({ name }), {
                placeholder: eg.contactName,
              })}
              {input(`contacts.${i}.phone_e164`, "Mobile", row.phone_e164, (phone_e164) => patch({ phone_e164 }), {
                placeholder: "+919876543210",
                inputMode: "tel",
                mono: true,
              })}
              {input(`contacts.${i}.note`, "When to call", row.hours, (hours) => patch({ hours }), {
                placeholder: "Weekdays, 9 to 6",
              })}
            </>
          )}
        </RowList>
      );
    case "languages":
      return (
        <fieldset className="space-y-2">
          <legend className="sr-only">Languages</legend>
          {PROFILE_LANGUAGES.map((option) => {
            const checked = draft.languages.includes(option.value);
            return (
              <label key={option.value} className="flex items-center gap-2 text-body text-ink touch:min-h-11">
                <input
                  id={profileFieldId(`languages.${option.value}`)}
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  onChange={(e) =>
                    onChange({
                      ...draft,
                      languages: e.target.checked
                        ? [...draft.languages, option.value]
                        : draft.languages.filter((tag) => tag !== option.value),
                    })
                  }
                />
                {option.label}
              </label>
            );
          })}
          {errorAt("languages") && <p className="text-meta font-medium text-danger">{errorAt("languages")}</p>}
        </fieldset>
      );
  }
}

/** Whether the draft for one step can be sent, or the sentence that says why not. */
export function stepProblem(draft: ProfileDraft, step: StepId): string | null {
  if (step === "hours" && Object.keys(hoursProblems(draft)).length > 0) {
    return "Some days have only one time. Give both, or tick Closed.";
  }
  return null;
}
