"use client";

import { FieldMessage } from "@/components/formValidation";
import { FIELD } from "@/components/ui";
import {
  PROFILE_LANGUAGES,
  blankBranch,
  blankContact,
  blankFaq,
  blankService,
  blankStaff,
  profileFieldId,
  showsPrice,
  type ProfileDraft,
  type ProfileWording,
  type StepId,
} from "@/lib/api/businessProfile";

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
 *
 * Every business-specific word — what it offers, what its price is called, each example
 * inside an empty field — is the business's own (`wording`, written for it from its own
 * description). Until that is written the labels are generic and no field has an example:
 * an example from another kind of business reads as a mistake about this one.
 */
export function SectionEditor({
  step,
  draft,
  onChange,
  disabled,
  errorAt,
  wording,
}: {
  step: StepId;
  draft: ProfileDraft;
  onChange: (next: ProfileDraft) => void;
  disabled: boolean;
  errorAt: (path: string) => string | undefined;
  wording: ProfileWording;
}) {
  const eg = wording.examples;
  const example = (value: string | null | undefined) => value ?? undefined;
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
                placeholder: example(eg.branch_label),
              })}
              {input(`branches.${i}.address`, "Address", row.address, (address) => patch({ address }), {
                placeholder: "Road, area, city, PIN",
              })}
            </>
          )}
        </RowList>
      );
    case "services": {
      // A business that quotes no price gets no price column; a price already on file
      // keeps it, so nothing stored is hidden.
      const priced = showsPrice(wording, draft.services);
      return (
        <RowList
          noun={wording.offer_label}
          rows={draft.services}
          blank={blankService}
          addLabel={`Add ${inSentence(wording.offer_label)}`}
          empty="Nothing listed yet."
          columns={priced ? 3 : 2}
          disabled={disabled}
          onChange={(services) => onChange({ ...draft, services })}
        >
          {(row, i, patch) => (
            <>
              {input(`services.${i}.name`, wording.offer_label, row.name, (name) => patch({ name }), {
                placeholder: example(eg.offer_name),
              })}
              {priced &&
                input(
                  `services.${i}.price_inr`,
                  `${wording.price_label ?? "Price"} (₹)`,
                  row.price_inr,
                  (price_inr) => patch({ price_inr }),
                  {
                    placeholder: example(eg.offer_price),
                    hint: "Digits only. Leave blank if you do not say it on the phone.",
                    inputMode: "decimal",
                    mono: true,
                  },
                )}
              {input(`services.${i}.notes`, "Note", row.notes, (notes) => patch({ notes }), {
                placeholder: example(eg.offer_note),
              })}
            </>
          )}
        </RowList>
      );
    }
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
                placeholder: example(eg.faq_question),
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
                placeholder: example(eg.staff_name),
              })}
              {input(`staff.${i}.pronunciation`, "Said as", row.pronunciation, (pronunciation) => patch({ pronunciation }), {
                placeholder: example(eg.staff_spoken),
              })}
              {input(`staff.${i}.role`, "Role", row.role, (role) => patch({ role }), {
                placeholder: example(eg.staff_role),
              })}
            </>
          )}
        </RowList>
      );
    case "booking":
      return (
        <Field
          id={profileFieldId("booking_rules")}
          label="Your rules"
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
              placeholder={example(eg.booking_rules)}
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
                placeholder: example(eg.contact_name),
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
          {errorAt("languages") && <FieldMessage id="profile-languages-error">{errorAt("languages")}</FieldMessage>}
        </fieldset>
      );
  }
}

/** A label as it reads mid-sentence: "Plan" becomes "plan", an acronym ("SIM plan") stays. */
export function inSentence(label: string): string {
  const [first = "", second = ""] = label;
  return second === second.toUpperCase() && second !== second.toLowerCase()
    ? label
    : first.toLowerCase() + label.slice(1);
}

/** Whether the draft for one step can be sent, or the sentence that says why not. */
export function stepProblem(draft: ProfileDraft, step: StepId): string | null {
  if (step === "hours" && Object.keys(hoursProblems(draft)).length > 0) {
    return "Some days have only one time. Give both, or tick Closed.";
  }
  return null;
}
