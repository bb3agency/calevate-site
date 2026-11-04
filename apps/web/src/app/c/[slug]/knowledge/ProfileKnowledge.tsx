"use client";

import Link from "next/link";
import { useId, useState, type FormEvent, type ReactNode } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { inSentence } from "@/components/businessProfile/SectionEditor";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import {
  showsPrice,
  stepCopy,
  useBusinessProfile,
  useChangeProfileList,
  type BusinessProfile,
  type FaqItem,
  type ProfileWording,
  type ServiceItem,
} from "@/lib/api/businessProfile";
import { useWriteAccess } from "@/lib/api/hooks";
import { formatPayableINR } from "@/lib/numberDisplay";
import { useClientRealm, useClientSession } from "@/lib/api/session";

import { Group } from "./KnowledgeGroup";

/**
 * WHAT THE BUSINESS OFFERS AND WHAT CALLERS OFTEN ASK, on the knowledge screen (D-968).
 *
 * Both have ONE home, the business profile, and this screen is a second view of it: every
 * row here is a row of Business details, and every change made here is a change to them,
 * through the same `PATCH /v1/business-profile`. Nothing is copied into facts, so the two
 * screens cannot disagree.
 *
 * The labels are the business's own (`wording`): a business that sells plans says "Plan",
 * and one that quotes no prices has no price field. Editing needs `org:manage`, the profile's
 * own gate; everyone who may read the page sees the rows.
 */

/** The access the profile's rows need, said in the words of this screen. */
export function useProfileWrite() {
  return useWriteAccess(useClientSession(), "org:manage", "change your business details");
}

/** What the offer choice is called: "Service and price", "Plan and monthly fee", "Course". */
export function offerChoiceLabel(wording: ProfileWording): string {
  return wording.price_label
    ? `${wording.offer_label} and ${inSentence(wording.price_label)}`
    : wording.offer_label;
}

const PRICE = /^\d+(\.\d{1,2})?$/;

const same = <T,>(a: T, b: T) => JSON.stringify(a) === JSON.stringify(b);

/** Thrown when the row being changed is no longer in the profile as it was shown. */
const MOVED_ON = "This changed elsewhere. Reload the page.";

function replaceOne<T>(list: T[], before: T, after: T | null): T[] {
  const index = list.findIndex((item) => same(item, before));
  if (index < 0) throw new Error(MOVED_ON);
  return after === null
    ? list.filter((_, i) => i !== index)
    : list.map((item, i) => (i === index ? after : item));
}

function clean(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

const matches = (query: string, ...values: (string | null | undefined)[]) => {
  const q = query.trim().toLocaleLowerCase();
  return !q || values.some((value) => value?.toLocaleLowerCase().includes(q));
};

export function profileMatchCount(profile: BusinessProfile | undefined, query: string): number {
  if (!profile) return 0;
  return (
    profile.services.filter((s) => matches(query, s.name, s.notes, s.price_inr)).length +
    profile.faqs.filter((f) => matches(query, f.question, f.answer)).length
  );
}

/** The two groups: what the business offers, and its common questions. */
export function ProfileKnowledge({ query }: { query: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const profile = useBusinessProfile(session);
  const write = useProfileWrite();
  const filtered = query.trim() !== "";

  if (profile.isLoading) return <Skeleton rows={3} label="Loading your business details" />;
  if (profile.error || !profile.data) {
    return (
      <ProblemNotice
        error={profile.error ?? new Error("We could not load your business details.")}
        onRetry={() => void profile.refetch()}
      />
    );
  }

  const { services, faqs, wording } = profile.data;
  const shownServices = services.filter((s) => matches(query, s.name, s.notes, s.price_inr));
  const shownFaqs = faqs.filter((f) => matches(query, f.question, f.answer));
  const detailsLink = (
    <Link
      href={href(`/c/${session.orgSlug}/settings/business`)}
      className="text-meta text-ink-muted underline underline-offset-2 touch:inline-flex touch:min-h-11 touch:items-center"
    >
      Business details
    </Link>
  );
  const info = <p>Saved in your business details. Change it here or there.</p>;

  return (
    <>
      <Group
        title={stepCopy("services").short}
        count={services.length}
        hidden={filtered && shownServices.length === 0}
        info={info}
        status={detailsLink}
      >
        {services.length === 0 ? (
          <p className="text-meta text-ink-muted">Nothing listed yet.</p>
        ) : (
          <ul className="divide-y divide-line border-y border-line" aria-label={stepCopy("services").short}>
            {shownServices.map((item) => (
              <ServiceRow
                key={JSON.stringify(item)}
                item={item}
                wording={wording}
                priced={showsPrice(wording, [{ price_inr: item.price_inr ?? "" }])}
                canWrite={write.allowed}
              />
            ))}
          </ul>
        )}
      </Group>
      <Group
        title={stepCopy("faqs").short}
        count={faqs.length}
        hidden={filtered && shownFaqs.length === 0}
        info={info}
        status={detailsLink}
      >
        {faqs.length === 0 ? (
          <p className="text-meta text-ink-muted">No questions yet.</p>
        ) : (
          <ul className="divide-y divide-line border-y border-line" aria-label={stepCopy("faqs").short}>
            {shownFaqs.map((item) => (
              <FaqRow key={JSON.stringify(item)} item={item} canWrite={write.allowed} />
            ))}
          </ul>
        )}
      </Group>
    </>
  );
}

/* ----------------------------------------------------------------------- the rows */

function RowShell({
  editing,
  form,
  view,
  canWrite,
  onEdit,
  onRemove,
  removeStatus,
  busy,
  error,
}: {
  editing: boolean;
  form: ReactNode;
  view: ReactNode;
  canWrite: boolean;
  onEdit: () => void;
  onRemove: () => void;
  removeStatus: ReturnType<typeof useActionFeedback>["status"];
  busy: boolean;
  error: Error | null;
}) {
  return (
    <li className="py-3">
      {editing ? (
        form
      ) : (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
          <div className="min-w-0 sm:flex-1">{view}</div>
          {canWrite ? (
            <div className="flex min-w-0 flex-wrap gap-1.5 sm:shrink-0">
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={onEdit} disabled={busy}>
                Edit
              </button>
              <ActionButton
                variant="secondary-sm"
                status={removeStatus}
                successLabel="Removed"
                disabled={busy && removeStatus !== "pending"}
                onClick={onRemove}
              >
                Remove
              </ActionButton>
            </div>
          ) : null}
        </div>
      )}
      {error && !editing ? (
        <div className="mt-2">
          <ProblemNotice error={error} />
        </div>
      ) : null}
    </li>
  );
}

function ServiceRow({
  item,
  wording,
  priced,
  canWrite,
}: {
  item: ServiceItem;
  wording: ProfileWording;
  priced: boolean;
  canWrite: boolean;
}) {
  const session = useClientSession();
  const change = useChangeProfileList(session);
  const changeFeedback = useActionFeedback(change, { errorDisplay: "inline" });
  const remove = useChangeProfileList(session);
  const removeFeedback = useActionFeedback(remove, { errorDisplay: "inline", successToast: "Removed" });
  const [editing, setEditing] = useState(false);
  return (
    <RowShell
      editing={editing}
      canWrite={canWrite}
      busy={change.isPending || remove.isPending}
      error={remove.error}
      removeStatus={removeFeedback.status}
      onEdit={() => setEditing(true)}
      onRemove={() =>
        removeFeedback.run({ section: "services", change: (list) => replaceOne(list, item, null) })
      }
      view={
        <>
          <p className="text-sm text-ink [overflow-wrap:anywhere]">
            {item.name}
            {item.price_inr ? (
              <span className="ml-2 tabular-nums text-ink-muted">{formatPayableINR(item.price_inr)}</span>
            ) : null}
          </p>
          {item.notes ? <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">{item.notes}</p> : null}
        </>
      }
      form={
        <OfferForm
          wording={wording}
          priced={priced}
          initial={item}
          mutation={change}
          feedback={changeFeedback}
          submitLabel="Save"
          onSubmit={(next) =>
            change.mutate(
              { section: "services", change: (list) => replaceOne(list, item, next) },
              { onSuccess: () => setEditing(false) },
            )
          }
          onCancel={() => setEditing(false)}
        />
      }
    />
  );
}

function FaqRow({ item, canWrite }: { item: FaqItem; canWrite: boolean }) {
  const session = useClientSession();
  const change = useChangeProfileList(session);
  const changeFeedback = useActionFeedback(change, { errorDisplay: "inline" });
  const remove = useChangeProfileList(session);
  const removeFeedback = useActionFeedback(remove, { errorDisplay: "inline", successToast: "Removed" });
  const [editing, setEditing] = useState(false);
  return (
    <RowShell
      editing={editing}
      canWrite={canWrite}
      busy={change.isPending || remove.isPending}
      error={remove.error}
      removeStatus={removeFeedback.status}
      onEdit={() => setEditing(true)}
      onRemove={() => removeFeedback.run({ section: "faqs", change: (list) => replaceOne(list, item, null) })}
      view={
        <>
          <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">{item.question}</p>
          <p className="text-sm text-ink [overflow-wrap:anywhere]">{item.answer}</p>
        </>
      }
      form={
        <QuestionForm
          initial={item}
          mutation={change}
          feedback={changeFeedback}
          submitLabel="Save"
          onSubmit={(next) =>
            change.mutate(
              { section: "faqs", change: (list) => replaceOne(list, item, next) },
              { onSuccess: () => setEditing(false) },
            )
          }
          onCancel={() => setEditing(false)}
        />
      }
    />
  );
}

/* ---------------------------------------------------------------------- the forms */

type ChangeMutation = ReturnType<typeof useChangeProfileList>;
type Feedback = Pick<ReturnType<typeof useActionFeedback>, "status">;

function TextField({
  label,
  value,
  onChange,
  hint,
  multiline,
  ...input
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  multiline?: boolean;
  maxLength: number;
  placeholder?: string;
  inputMode?: "decimal";
  className?: string;
  invalid?: boolean;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const { invalid, className, ...rest } = input;
  const props = {
    id,
    value,
    "aria-describedby": hintId,
    ...(invalid ? { "aria-invalid": true as const } : {}),
    className: `${FIELD} ${className ?? ""}`,
    ...rest,
  };
  return (
    <div className="min-w-0">
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      {multiline ? (
        <textarea {...props} rows={2} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input {...props} onChange={(e) => onChange(e.target.value)} />
      )}
      {hint ? (
        <span id={hintId} className={FIELD_HINT}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

function FormButtons({
  status,
  submitLabel,
  waitingFor,
  onCancel,
}: {
  status: ReturnType<typeof useActionFeedback>["status"];
  submitLabel: string;
  waitingFor: string | null;
  onCancel?: () => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <ActionButton
        type="submit"
        variant="primary-sm"
        status={status}
        pendingLabel="Saving…"
        successLabel={submitLabel === "Add" ? "Added" : "Saved"}
        waitingFor={waitingFor}
      >
        {submitLabel}
      </ActionButton>
      {onCancel ? (
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onCancel}>
          Cancel
        </button>
      ) : null}
    </div>
  );
}

/** One thing the business offers, in its own words; the price only where it gives one. */
export function OfferForm({
  wording,
  priced,
  initial,
  mutation,
  feedback,
  submitLabel,
  onSubmit,
  onCancel,
  disabled = false,
}: {
  wording: ProfileWording;
  priced: boolean;
  initial?: ServiceItem;
  mutation: ChangeMutation;
  feedback: Feedback;
  submitLabel: string;
  /** `clear` empties the form, for an Add form that stays open for the next one. */
  onSubmit: (item: ServiceItem, clear: () => void) => void;
  onCancel?: () => void;
  disabled?: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [price, setPrice] = useState(initial?.price_inr ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const badPrice = price.trim() !== "" && !PRICE.test(price.trim());
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (disabled || !name.trim() || badPrice || mutation.isPending) return;
    onSubmit(
      { name: name.trim(), price_inr: priced ? clean(price) : (initial?.price_inr ?? null), notes: clean(notes) },
      () => {
        setName("");
        setPrice("");
        setNotes("");
      },
    );
  };
  return (
    <form className="max-w-2xl space-y-3" noValidate onSubmit={submit}>
      <fieldset disabled={disabled} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <TextField
          label={wording.offer_label}
          value={name}
          onChange={setName}
          maxLength={120}
          placeholder={wording.examples.offer_name ?? undefined}
        />
        {priced ? (
          <TextField
            label={`${wording.price_label ?? "Price"} (₹)`}
            value={price}
            onChange={setPrice}
            maxLength={20}
            inputMode="decimal"
            className="font-mono"
            hint={badPrice ? "Digits only, like 1500 or 1500.50." : undefined}
            invalid={badPrice}
            placeholder={wording.examples.offer_price ?? undefined}
          />
        ) : null}
        <TextField
          label="Note"
          value={notes}
          onChange={setNotes}
          maxLength={200}
          placeholder={wording.examples.offer_note ?? undefined}
        />
      </fieldset>
      {mutation.error ? <ProblemNotice error={mutation.error} /> : null}
      <FormButtons
        status={feedback.status}
        submitLabel={submitLabel}
        waitingFor={!name.trim() ? `Write the ${inSentence(wording.offer_label)}.` : badPrice ? "Fix the price." : null}
        onCancel={onCancel}
      />
    </form>
  );
}

/** A question callers ask and the answer to give. */
export function QuestionForm({
  initial,
  mutation,
  feedback,
  submitLabel,
  onSubmit,
  onCancel,
  disabled = false,
  placeholder,
}: {
  initial?: FaqItem;
  mutation: ChangeMutation;
  feedback: Feedback;
  submitLabel: string;
  /** `clear` empties the form, for an Add form that stays open for the next one. */
  onSubmit: (item: FaqItem, clear: () => void) => void;
  onCancel?: () => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [question, setQuestion] = useState(initial?.question ?? "");
  const [answer, setAnswer] = useState(initial?.answer ?? "");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (disabled || !question.trim() || !answer.trim() || mutation.isPending) return;
    onSubmit({ question: question.trim(), answer: answer.trim() }, () => {
      setQuestion("");
      setAnswer("");
    });
  };
  return (
    <form className="max-w-2xl space-y-3" noValidate onSubmit={submit}>
      <fieldset disabled={disabled} className="space-y-3">
        <TextField
          label="What callers ask"
          value={question}
          onChange={setQuestion}
          maxLength={300}
          placeholder={placeholder}
        />
        <TextField label="The answer" value={answer} onChange={setAnswer} maxLength={1000} multiline />
      </fieldset>
      {mutation.error ? <ProblemNotice error={mutation.error} /> : null}
      <FormButtons
        status={feedback.status}
        submitLabel={submitLabel}
        waitingFor={!question.trim() ? "Write the question." : !answer.trim() ? "Write the answer." : null}
        onCancel={onCancel}
      />
    </form>
  );
}

/** The Add area's two profile forms: each adds one entry to the end of its list. */
export function AddToProfile({ kind, allowed }: { kind: "offer" | "question"; allowed: boolean }) {
  const session = useClientSession();
  const profile = useBusinessProfile(session);
  const add = useChangeProfileList(session);
  const addFeedback = useActionFeedback(add, { errorDisplay: "inline" });
  if (profile.isLoading) return <Skeleton rows={2} label="Loading your business details" />;
  if (profile.error || !profile.data) {
    return (
      <ProblemNotice
        error={profile.error ?? new Error("We could not load your business details.")}
        onRetry={() => void profile.refetch()}
      />
    );
  }
  const { wording, services } = profile.data;
  return kind === "offer" ? (
    <OfferForm
      wording={wording}
      priced={showsPrice(wording, services.map((s) => ({ price_inr: s.price_inr ?? "" })))}
      mutation={add}
      feedback={addFeedback}
      submitLabel="Add"
      disabled={!allowed}
      onSubmit={(item, clear) =>
        add.mutate({ section: "services", change: (list) => [...list, item] }, { onSuccess: clear })
      }
    />
  ) : (
    <QuestionForm
      mutation={add}
      feedback={addFeedback}
      submitLabel="Add"
      disabled={!allowed}
      placeholder={wording.examples.faq_question ?? undefined}
      onSubmit={(item, clear) =>
        add.mutate({ section: "faqs", change: (list) => [...list, item] }, { onSuccess: clear })
      }
    />
  );
}
