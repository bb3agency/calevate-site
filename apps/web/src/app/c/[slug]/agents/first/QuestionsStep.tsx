"use client";

import { useId, useState } from "react";
import { Plus, X } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { FIELD, FIELD_LABEL, ProblemNotice, QUIET_ICON_BUTTON, Skeleton } from "@/components/ui";
import {
  useBuildAgent,
  useSaveAnswers,
  type FirstRun,
  type FirstRunAnswer,
  type FirstRunAnswers,
  type FirstRunQuestion,
} from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";

import { ChipChoice, StepScreen } from "./shell";

const DAYS = [
  { id: "mon", label: "Mon" },
  { id: "tue", label: "Tue" },
  { id: "wed", label: "Wed" },
  { id: "thu", label: "Thu" },
  { id: "fri", label: "Fri" },
  { id: "sat", label: "Sat" },
  { id: "sun", label: "Sun" },
] as const;
type Day = (typeof DAYS)[number]["id"];

/** One question's answer as it is being typed. */
interface Entry {
  choices: string[];
  text: string;
  offer: { name: string; price: string }[];
  hours: { opens: string; closes: string; closed: Day[] };
}

/** Every question's entry, by question id. */
type Draft = Record<string, Entry>;

const EMPTY_ENTRY: Entry = {
  choices: [],
  text: "",
  offer: [{ name: "", price: "" }],
  hours: { opens: "09:00", closes: "18:00", closed: ["sun"] },
};

function entryOf(draft: Draft, id: string): Entry {
  return draft[id] ?? EMPTY_ENTRY;
}

/** One answer in the field its question's kind uses, or null when nothing was given. */
function answerOf(question: FirstRunQuestion, entry: Entry): FirstRunAnswer | null {
  switch (question.kind) {
    case "choices":
    case "single_choice":
      return entry.choices.length > 0 ? { id: question.id, choices: entry.choices } : null;
    case "services": {
      const rows = entry.offer
        .map((row) => ({ name: row.name.trim(), price: row.price.replace(/[^\d.]/g, "") }))
        .filter((row) => row.name !== "");
      return rows.length > 0
        ? { id: question.id, services: rows.map((row) => ({ name: row.name, price_inr: row.price || null })) }
        : null;
    }
    case "hours":
      return { id: question.id, hours: entry.hours };
    default:
      return entry.text.trim() ? { id: question.id, text: entry.text.trim() } : null;
  }
}

/** The answers to send: only the questions answered, each in its kind's field. */
export function answersOf(
  questions: readonly FirstRunQuestion[],
  draft: Draft,
  answered: ReadonlySet<string>,
): FirstRunAnswers {
  const answers = questions
    .filter((question) => answered.has(question.id))
    .map((question) => answerOf(question, entryOf(draft, question.id)))
    .filter((answer): answer is FirstRunAnswer => answer !== null);
  return { answers };
}

/**
 * THE FOLLOW-UP QUESTIONS (D-855, D-863): at most four, one at a time, each one skippable.
 *
 * Our AI wrote them for this business from the brief, each with its kind of answer; the ones
 * that name a business-profile section are saved there, which every agent reads, and every
 * answer goes to the script writer. While the worker reads the brief the owner can already
 * skip ahead and build.
 */
export function QuestionsStep({
  run,
  onBack,
  onBuilding,
}: {
  run: FirstRun;
  onBack: () => void;
  onBuilding: () => void;
}) {
  const session = useClientSession();
  const answer = useSaveAnswers(session);
  const build = useBuildAgent(session);
  const [at, setAt] = useState(0);
  const [draft, setDraft] = useState<Draft>({});
  const [answered, setAnswered] = useState<Set<string>>(() => new Set());
  const items = run.questions.items;
  const writing = run.questions.status === "writing";
  const question = items[at] ?? null;
  const pending = answer.isPending || build.isPending;

  const finish = async (keep: ReadonlySet<string>) => {
    const answers = answersOf(items, draft, keep);
    if ((answers.answers ?? []).length > 0) await answer.mutateAsync(answers);
    await build.mutateAsync(null);
    onBuilding();
  };

  const skipAll = (
    <button type="button" className={TEXT_ACTION} disabled={pending} onClick={() => void finish(answered).catch(() => undefined)}>
      Skip {question && at < items.length - 1 ? "the rest" : "all"} and build
    </button>
  );

  if (writing || question === null) {
    return (
      <StepScreen
        title={writing ? "Reading what you wrote" : "Your description covers it"}
        hint={
          writing
            ? "A few seconds. It is checking what your agent still needs to know."
            : "Nothing else is needed before your agent is built."
        }
        onBack={onBack}
        primary={pending ? "Starting…" : "Build my agent"}
        pending={pending}
        disabled={writing}
        onSubmit={() => void finish(answered).catch(() => undefined)}
        aside={writing ? skipAll : null}
      >
        {writing ? <Skeleton rows={3} label="Reading your description" /> : null}
        <Errors errors={[answer.error, build.error]} />
      </StepScreen>
    );
  }

  const last = at === items.length - 1;
  const next = (keep: boolean) => {
    const nextAnswered = new Set(answered);
    if (keep) nextAnswered.add(question.id);
    else nextAnswered.delete(question.id);
    setAnswered(nextAnswered);
    if (last) void finish(nextAnswered).catch(() => undefined);
    else setAt(at + 1);
  };

  return (
    <StepScreen
      title={question.prompt}
      hint={
        <span className="flex flex-col gap-1">
          <span className="text-meta tabular-nums text-ink-faint">
            Question {at + 1} of {items.length}
          </span>
          <span>{question.hint}</span>
        </span>
      }
      onBack={at === 0 ? onBack : () => setAt(at - 1)}
      primary={pending ? "Building…" : last ? "Build my agent" : "Next"}
      pending={pending}
      onSubmit={() => next(true)}
      aside={
        <span className="flex flex-wrap items-center justify-center gap-x-5">
          <button type="button" className={TEXT_ACTION} disabled={pending} onClick={() => next(false)}>
            Skip this question
          </button>
          {last ? null : skipAll}
        </span>
      }
    >
      <Answer
        key={question.id}
        question={question}
        entry={entryOf(draft, question.id)}
        onChange={(entry) => setDraft({ ...draft, [question.id]: entry })}
      />
      {run.questions.disclosure ? <p className="text-meta text-ink-faint">{run.questions.disclosure}</p> : null}
      <Errors errors={[answer.error, build.error]} />
    </StepScreen>
  );
}

function Errors({ errors }: { errors: readonly (Error | null)[] }) {
  const first = errors.find((error) => error !== null) ?? null;
  return first ? <ProblemNotice error={first} /> : null;
}

function Answer({
  question,
  entry,
  onChange,
}: {
  question: FirstRunQuestion;
  entry: Entry;
  onChange: (entry: Entry) => void;
}) {
  const id = useId();
  switch (question.kind) {
    case "choices":
    case "single_choice": {
      const one = question.kind === "single_choice";
      return (
        <fieldset>
          <legend className="sr-only">{question.prompt}</legend>
          <div className="flex flex-wrap gap-2">
            {question.options.map((option) => (
              <ChipChoice
                key={option}
                type={one ? "radio" : "checkbox"}
                name={question.id}
                value={option}
                checked={entry.choices.includes(option)}
                onChange={(on) =>
                  onChange({
                    ...entry,
                    choices: one
                      ? on
                        ? [option]
                        : []
                      : on
                        ? [...entry.choices, option]
                        : entry.choices.filter((chosen) => chosen !== option),
                  })
                }
              >
                {option}
              </ChipChoice>
            ))}
          </div>
        </fieldset>
      );
    }
    case "address":
      return (
        <div>
          <label htmlFor={id} className={FIELD_LABEL}>
            Address
          </label>
          <textarea
            id={id}
            rows={3}
            autoComplete="street-address"
            maxLength={400}
            value={entry.text}
            onChange={(event) => onChange({ ...entry, text: event.target.value })}
            className={`${FIELD} mt-1 w-full text-[16px]`}
          />
        </div>
      );
    case "services":
      return <Services entry={entry} onChange={onChange} />;
    case "hours":
      return <Hours entry={entry} onChange={onChange} />;
    default:
      return (
        <div>
          <label htmlFor={id} className="sr-only">
            {question.prompt}
          </label>
          <textarea
            id={id}
            rows={4}
            maxLength={2000}
            value={entry.text}
            onChange={(event) => onChange({ ...entry, text: event.target.value })}
            className={`${FIELD} w-full text-[16px]`}
          />
        </div>
      );
  }
}

/** The server's cap per answer (`first_run/schemas.AnswerIn.services`). */
const MAX_OFFER_ROWS = 20;

function Services({ entry, onChange }: { entry: Entry; onChange: (entry: Entry) => void }) {
  const base = useId();
  const set = (index: number, row: { name: string; price: string }) =>
    onChange({ ...entry, offer: entry.offer.map((existing, i) => (i === index ? row : existing)) });
  return (
    <div className="space-y-3">
      {entry.offer.map((row, index) => (
        <div key={index} className="flex items-end gap-2">
          <label className="min-w-0 flex-1">
            <span className={FIELD_LABEL}>What you offer</span>
            <input
              id={`${base}-name-${index}`}
              value={row.name}
              maxLength={120}
              onChange={(event) => set(index, { ...row, name: event.target.value })}
              className={`${FIELD} mt-1 w-full text-[16px]`}
            />
          </label>
          <label className="w-28 shrink-0">
            <span className={FIELD_LABEL}>Price (₹)</span>
            <input
              value={row.price}
              inputMode="decimal"
              maxLength={12}
              onChange={(event) => set(index, { ...row, price: event.target.value })}
              className={`${FIELD} mt-1 w-full text-[16px] tabular-nums`}
            />
          </label>
          {entry.offer.length > 1 ? (
            <button
              type="button"
              aria-label={`Remove ${row.name || "this row"}`}
              className={QUIET_ICON_BUTTON}
              onClick={() => onChange({ ...entry, offer: entry.offer.filter((_, i) => i !== index) })}
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      ))}
      {entry.offer.length < MAX_OFFER_ROWS ? (
        <button
          type="button"
          className={TEXT_ACTION}
          onClick={() => onChange({ ...entry, offer: [...entry.offer, { name: "", price: "" }] })}
        >
          <Plus aria-hidden className="h-4 w-4" />
          Add another
        </button>
      ) : null}
    </div>
  );
}

function Hours({ entry, onChange }: { entry: Entry; onChange: (entry: Entry) => void }) {
  const opens = useId();
  const closes = useId();
  const hours = entry.hours;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <label htmlFor={opens} className="block">
          <span className={FIELD_LABEL}>Opens</span>
          <input
            id={opens}
            type="time"
            value={hours.opens}
            onChange={(event) => onChange({ ...entry, hours: { ...hours, opens: event.target.value } })}
            className={`${FIELD} mt-1 text-[16px]`}
          />
        </label>
        <label htmlFor={closes} className="block">
          <span className={FIELD_LABEL}>Closes</span>
          <input
            id={closes}
            type="time"
            value={hours.closes}
            onChange={(event) => onChange({ ...entry, hours: { ...hours, closes: event.target.value } })}
            className={`${FIELD} mt-1 text-[16px]`}
          />
        </label>
      </div>
      <fieldset>
        <legend className={FIELD_LABEL}>Closed on</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {DAYS.map((day) => (
            <ChipChoice
              key={day.id}
              type="checkbox"
              name="closed"
              value={day.id}
              checked={hours.closed.includes(day.id)}
              onChange={(on) =>
                onChange({
                  ...entry,
                  hours: {
                    ...hours,
                    closed: on ? [...hours.closed, day.id] : hours.closed.filter((closed) => closed !== day.id),
                  },
                })
              }
            >
              {day.label}
            </ChipChoice>
          ))}
        </div>
      </fieldset>
      <p className="text-meta text-ink-faint">
        Different hours on some days? Change them later in Business setup.
      </p>
    </div>
  );
}
