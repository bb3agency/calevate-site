"use client";

import { useId, useState } from "react";
import { ArrowRight, Clock, MapPin, Plus, RotateCw, SkipForward, Sparkles, X } from "lucide-react";

import { useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import {
  FIELD,
  FIELD_INLINE,
  FIELD_GROUP,
  FIELD_GROUP_AFFIX,
  FIELD_GROUP_INPUT,
  FIELD_LABEL,
  ProblemNotice,
  QUIET_ICON_BUTTON,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import {
  useBuildAgent,
  useSaveAnswers,
  useSaveBrief,
  type FirstRun,
  type FirstRunQuestion,
} from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import {
  DAYS,
  MAX_ADDRESS_CHARS,
  MAX_SERVICES,
  MAX_TEXT_CHARS,
  answersBody,
  emptyAnswer,
  type DraftAnswer,
  type Day,
  type HoursAnswer,
} from "@/lib/firstRunQuestions";

import { ReadingStage } from "./LiveStage";
import { ChipChoice, StepScreen } from "./shell";
import { FIRST } from "../../setup/_ui/copy";

/**
 * THE FOLLOW-UP QUESTIONS (D-855; founder, 23 Oct 2026): a few, one at a time, each one
 * skippable, each answered the way its kind wants to be answered: chips for a choice, a price
 * list for what is offered, open days and a time range for hours, a place for an address,
 * a box for anything else.
 *
 * While a worker reads the description, the stage shows the owner's own words being read;
 * the owner can skip ahead and build at any point. The answers go into the business profile,
 * which every agent reads, and into the script (D-863).
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
  // Saving the answers then starting the build is one press; its refusal is the notice under
  // the step (`Errors`), and the button carries the pair's state.
  const answerFeedback = useActionFeedback(answer, { errorDisplay: "inline" });
  const buildFeedback = useActionFeedback(build, { errorDisplay: "inline" });
  const questions = run.questions.items;
  const [at, setAt] = useState(0);
  const [answers, setAnswers] = useState<Record<string, DraftAnswer>>({});
  const [kept, setKept] = useState<Set<string>>(() => new Set());
  const retry = useSaveBrief(session);
  const writing = run.questions.status === "writing";
  const failed = run.questions.status === "failed";
  const question = questions[at] ?? null;
  const pending = answer.isPending || build.isPending || retry.isPending;
  const status: FeedbackStatus = pending
    ? "pending"
    : answerFeedback.status === "error" || buildFeedback.status === "error"
      ? "error"
      : "idle";

  const finish = async (keep: ReadonlySet<string>, drafts: Readonly<Record<string, DraftAnswer>> = answers) => {
    const sent = answersBody(
      questions.filter((entry) => keep.has(entry.id)),
      drafts,
    );
    if ((sent.answers ?? []).length > 0) await answer.mutateAsync(sent);
    await build.mutateAsync(null);
    onBuilding();
  };
  const go = (keep: ReadonlySet<string>, drafts?: Readonly<Record<string, DraftAnswer>>) =>
    void finish(keep, drafts).catch(() => undefined);

  if (failed && question === null) {
    // Saving the same brief again asks for the questions again (`save_brief` re-queues a
    // brief whose questions are not `writing` or `ready`).
    return (
      <StepScreen
        title={FIRST.questionsFailed}
        hint={FIRST.questionsFailedHint}
        onBack={onBack}
        primary="Build my agent"
        status={status}
        onSubmit={() => go(kept)}
        aside={
          <button
            type="button"
            className={TEXT_ACTION}
            disabled={pending}
            onClick={() => retry.mutate({ brief: run.brief ?? "" })}
          >
            <RotateCw aria-hidden className="h-4 w-4" />
            {retry.isPending ? "Trying…" : "Try again"}
          </button>
        }
      >
        <Errors errors={[retry.error, answer.error, build.error]} />
      </StepScreen>
    );
  }

  if (writing || question === null) {
    return (
      <StepScreen
        title={writing ? "A few details next" : "Your description covers it"}
        hint={
          writing
            ? FIRST.readingBrief
            : "Nothing else is needed before your agent is built."
        }
        onBack={onBack}
        primary={writing ? undefined : "Build my agent"}
        status={status}
        onSubmit={() => go(kept)}
        aside={
          writing ? (
            <button type="button" className={TEXT_ACTION} disabled={pending} onClick={() => go(kept)}>
              <SkipForward aria-hidden className="h-4 w-4" />
              {pending ? "Starting…" : "Skip the questions and build"}
            </button>
          ) : null
        }
      >
        {writing ? <ReadingStage brief={run.brief ?? ""} lang={run.language_primary ?? "en-IN"} /> : null}
        <Errors errors={[answer.error, build.error]} />
      </StepScreen>
    );
  }

  const last = at === questions.length - 1;
  const current = answers[question.id] ?? emptyAnswer(question.id);
  const next = (keep: boolean) => {
    const nextKept = new Set(kept);
    if (keep) nextKept.add(question.id);
    else nextKept.delete(question.id);
    setKept(nextKept);
    // What is on screen is the answer, including the defaults shown and never touched (the
    // usual open hours), so a kept question keeps its draft even if nothing was typed.
    const drafts = keep ? { ...answers, [question.id]: current } : answers;
    setAnswers(drafts);
    if (last) go(nextKept, drafts);
    else setAt(at + 1);
  };

  return (
    <StepScreen
      key={question.id}
      title={question.prompt}
      eyebrow={<QuestionProgress at={at} total={questions.length} />}
      hint={question.hint}
      onBack={at === 0 ? onBack : () => setAt(at - 1)}
      primary={
        <>
          {last ? "Build my agent" : "Next"}
          {last ? (
            <Sparkles aria-hidden className="h-4 w-4" />
          ) : (
            <ArrowRight aria-hidden className="h-4 w-4" />
          )}
        </>
      }
      status={status}
      onSubmit={() => next(true)}
      aside={
        <>
          <button type="button" className={TEXT_ACTION} disabled={pending} onClick={() => next(false)}>
            <SkipForward aria-hidden className="h-4 w-4" />
            Skip this question
          </button>
          {last ? null : (
            <button type="button" className={TEXT_ACTION} disabled={pending} onClick={() => go(kept)}>
              Skip the rest and build
            </button>
          )}
        </>
      }
    >
      <QuestionAnswer
        question={question}
        answer={current}
        onChange={(changed) => setAnswers((all) => ({ ...all, [question.id]: changed }))}
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

/** "Question 2 of 3" with a segment per question, filled up to this one. */
function QuestionProgress({ at, total }: { at: number; total: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-meta font-medium tabular-nums text-brand-strong">
        Question {at + 1} of {total}
      </span>
      <span aria-hidden className="flex gap-1">
        {Array.from({ length: total }, (_, index) => (
          <span
            key={index}
            className={`h-1 w-5 rounded-full transition-colors duration-(--duration-base) ${index <= at ? "bg-brand-strong" : "bg-line"}`}
          />
        ))}
      </span>
    </div>
  );
}

/** One question's answer, drawn for its kind. Props are the contract's question and answer,
 *  so the components serve the AI-written questions unchanged. */
export function QuestionAnswer({
  question,
  answer,
  onChange,
}: {
  question: FirstRunQuestion;
  answer: DraftAnswer;
  onChange: (answer: DraftAnswer) => void;
}) {
  switch (question.kind) {
    case "choices":
    case "single_choice":
      return <ChoicesAnswer question={question} answer={answer} onChange={onChange} />;
    case "address":
      return <AddressAnswer answer={answer} onChange={onChange} />;
    case "services":
      return <ServicesAnswer answer={answer} onChange={onChange} />;
    case "hours":
      return <HoursAnswerField answer={answer} onChange={onChange} />;
    default:
      return <TextAnswer question={question} answer={answer} onChange={onChange} />;
  }
}

function ChoicesAnswer({
  question,
  answer,
  onChange,
}: {
  question: FirstRunQuestion;
  answer: DraftAnswer;
  onChange: (answer: DraftAnswer) => void;
}) {
  const single = question.kind === "single_choice";
  return (
    <fieldset>
      <legend className="sr-only">{question.prompt}</legend>
      {question.hint.trim() === "" ? (
        <p className="mb-2.5 text-meta text-ink-muted">{single ? "Pick one." : "Pick all that fit."}</p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {question.options.map((option) => (
          <ChipChoice
            key={option}
            type={single ? "radio" : "checkbox"}
            name={question.id}
            value={option}
            checked={answer.choices.includes(option)}
            onChange={(on) =>
              onChange({
                ...answer,
                choices: single
                  ? [option]
                  : on
                    ? [...answer.choices, option]
                    : answer.choices.filter((chosen) => chosen !== option),
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

function TextAnswer({
  question,
  answer,
  onChange,
}: {
  question: FirstRunQuestion;
  answer: DraftAnswer;
  onChange: (answer: DraftAnswer) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="sr-only">
        {question.prompt}
      </label>
      <textarea
        id={id}
        rows={4}
        maxLength={MAX_TEXT_CHARS}
        value={answer.text}
        onChange={(event) => onChange({ ...answer, text: event.target.value })}
        className={`${FIELD} resize-y text-[16px] leading-relaxed`}
      />
      <p className="mt-1 text-right text-meta tabular-nums text-ink-faint">
        {Array.from(answer.text).length} of {MAX_TEXT_CHARS}
      </p>
    </div>
  );
}

function AddressAnswer({ answer, onChange }: { answer: DraftAnswer; onChange: (answer: DraftAnswer) => void }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className={FIELD_LABEL}>
        Address
      </label>
      <div className={`${FIELD_GROUP} mt-1`}>
        <span aria-hidden className={`${FIELD_GROUP_AFFIX} items-start pt-2.5`}>
          <MapPin className="h-4 w-4 text-brand-strong" />
        </span>
        <textarea
          id={id}
          rows={3}
          autoComplete="street-address"
          maxLength={MAX_ADDRESS_CHARS}
          placeholder="Shop number, street, area, city"
          aria-describedby={`${id}-hint`}
          value={answer.text}
          onChange={(event) => onChange({ ...answer, text: event.target.value })}
          className={`${FIELD_GROUP_INPUT} resize-y py-2 pl-14 text-[16px] leading-relaxed`}
        />
      </div>
      <p id={`${id}-hint`} className="mt-1 text-meta text-ink-faint">
        Your agent says this when a caller asks where you are.
      </p>
    </div>
  );
}

function ServicesAnswer({ answer, onChange }: { answer: DraftAnswer; onChange: (answer: DraftAnswer) => void }) {
  const base = useId();
  const rows = answer.services;
  const set = (index: number, row: { name: string; price: string }) =>
    onChange({
      ...answer,
      services: rows.map((existing, i) => (i === index ? row : existing)),
    });
  return (
    <div>
      <div className="overflow-hidden rounded-card border border-line bg-surface">
        <div
          aria-hidden
          className="grid grid-cols-[minmax(0,1fr)_8.5rem_2.75rem] gap-2 border-b border-line bg-surface-muted px-3 py-1.5 sm:grid-cols-[minmax(0,1fr)_9rem_2.75rem]"
        >
          <span className={FIELD_LABEL}>What you offer</span>
          <span className={FIELD_LABEL}>Price</span>
        </div>
        <ul className="divide-y divide-line">
          {rows.map((row, index) => (
            <li
              key={index}
              className="grid grid-cols-[minmax(0,1fr)_8.5rem_2.75rem] items-center gap-2 px-3 py-2 sm:grid-cols-[minmax(0,1fr)_9rem_2.75rem]"
            >
              <label htmlFor={`${base}-name-${index}`} className="sr-only">
                Service {index + 1}
              </label>
              <input
                id={`${base}-name-${index}`}
                value={row.name}
                maxLength={120}
                placeholder={index === 0 ? "e.g. Site visit" : "Another service"}
                onChange={(event) => set(index, { ...row, name: event.target.value })}
                className={`${FIELD_INLINE} w-full text-[16px]`}
              />
              <label htmlFor={`${base}-price-${index}`} className="sr-only">
                Price of service {index + 1}, in rupees
              </label>
              <span className={FIELD_GROUP}>
                <span aria-hidden className={`${FIELD_GROUP_AFFIX} px-2.5`}>
                  ₹
                </span>
                <input
                  id={`${base}-price-${index}`}
                  value={row.price}
                  inputMode="decimal"
                  maxLength={12}
                  placeholder="0"
                  onChange={(event) => set(index, { ...row, price: event.target.value })}
                  className={`${FIELD_GROUP_INPUT} pl-9 text-[16px] tabular-nums`}
                />
              </span>
              {rows.length > 1 ? (
                <button
                  type="button"
                  aria-label={`Remove ${row.name || `service ${index + 1}`}`}
                  className={QUIET_ICON_BUTTON}
                  onClick={() =>
                    onChange({
                      ...answer,
                      services: rows.filter((_, i) => i !== index),
                    })
                  }
                >
                  <X aria-hidden className="h-4 w-4" />
                </button>
              ) : (
                <span />
              )}
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
        {rows.length < MAX_SERVICES ? (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() =>
              onChange({
                ...answer,
                services: [...rows, { name: "", price: "" }],
              })
            }
          >
            <Plus aria-hidden className="h-3.5 w-3.5" />
            Add another
          </button>
        ) : null}
        <span className="text-meta text-ink-faint">Leave a price empty if it depends.</span>
      </div>
    </div>
  );
}

/** "Mon to Sat, 9:00 am to 6:00 pm", from the open days and the two times. */
export function hoursSummary(hours: HoursAnswer): string {
  const open = DAYS.filter((day) => !hours.closed.includes(day.id));
  if (open.length === 0) return "Closed every day";
  const runs: (typeof DAYS)[number][][] = [];
  for (const day of open) {
    const last = runs.at(-1);
    const previous = last?.at(-1);
    if (last && previous && DAYS.indexOf(previous) === DAYS.indexOf(day) - 1) last.push(day);
    else runs.push([day]);
  }
  const days =
    open.length === DAYS.length
      ? "Every day"
      : runs
          .map((run) =>
            run.length > 2 ? `${run[0]!.label} to ${run.at(-1)!.label}` : run.map((day) => day.label).join(", "),
          )
          .join(", ");
  return `${days}, ${clock(hours.opens)} to ${clock(hours.closes)}`;
}

function clock(value: string): string {
  const [h, m] = value.split(":").map(Number);
  if (h === undefined || Number.isNaN(h)) return value;
  const suffix = h >= 12 ? "pm" : "am";
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${hour}:${String(m ?? 0).padStart(2, "0")} ${suffix}`;
}

function HoursAnswerField({ answer, onChange }: { answer: DraftAnswer; onChange: (answer: DraftAnswer) => void }) {
  const opens = useId();
  const closes = useId();
  const hours = answer.hours;
  const setHours = (next: HoursAnswer) => onChange({ ...answer, hours: next });
  const toggleDay = (day: Day, open: boolean) =>
    setHours({
      ...hours,
      closed: open ? hours.closed.filter((closed) => closed !== day) : [...hours.closed, day],
    });
  return (
    <div className="space-y-4">
      <fieldset>
        <legend className={FIELD_LABEL}>Open on</legend>
        <div className="mt-1.5 grid grid-cols-7 gap-1.5">
          {DAYS.map((day) => {
            const open = !hours.closed.includes(day.id);
            return (
              <label
                key={day.id}
                className={`press grid min-h-11 cursor-pointer select-none place-items-center rounded-md border text-meta font-medium transition-colors duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand ${
                  open
                    ? "border-brand-strong bg-brand-soft text-brand-strong shadow-[inset_0_0_0_1px_var(--brand-strong)]"
                    : "border-line bg-surface text-ink-faint line-through decoration-ink-faint/60 hover:border-ink/30"
                }`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={open}
                  onChange={(event) => toggleDay(day.id, event.target.checked)}
                />
                <span aria-hidden>{day.label}</span>
                <span className="sr-only">{day.name}</span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
        <TimeField
          id={opens}
          label="Opens"
          value={hours.opens}
          onChange={(value) => setHours({ ...hours, opens: value })}
        />
        <TimeField
          id={closes}
          label="Closes"
          value={hours.closes}
          onChange={(value) => setHours({ ...hours, closes: value })}
        />
      </div>
      <p
        className="flex items-center gap-2 rounded-md bg-surface-muted px-3 py-2 text-meta text-ink"
        aria-live="polite"
      >
        <Clock aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
        {hoursSummary(hours)}
      </p>
      <p className="text-meta text-ink-faint">{FIRST.hoursLater}</p>
    </div>
  );
}

function TimeField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      <input
        id={id}
        type="time"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`${FIELD} text-[16px] tabular-nums`}
      />
    </div>
  );
}
