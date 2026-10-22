"use client";

import { useId, useState } from "react";
import { Plus, X } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { FIELD, FIELD_LABEL, ProblemNotice, QUIET_ICON_BUTTON, Skeleton } from "@/components/ui";
import {
  useBuildAgent,
  useSaveAnswers,
  type FirstRun,
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

interface Draft {
  trade: string[];
  location: string;
  offer: { name: string; price: string }[];
  hours: { opens: string; closes: string; closed: Day[] };
  booking: string;
}

const EMPTY: Draft = {
  trade: [],
  location: "",
  offer: [{ name: "", price: "" }],
  hours: { opens: "09:00", closes: "18:00", closed: ["sun"] },
  booking: "",
};

/** The answers to send: only the questions answered, each in the profile's shape. */
export function answersOf(draft: Draft, answered: ReadonlySet<string>): FirstRunAnswers {
  const out: FirstRunAnswers = {};
  if (answered.has("trade") && draft.trade.length > 0) out.trade = draft.trade;
  if (answered.has("location") && draft.location.trim()) out.location = draft.location.trim();
  if (answered.has("offer")) {
    const rows = draft.offer
      .map((row) => ({ name: row.name.trim(), price: row.price.replace(/[^\d.]/g, "") }))
      .filter((row) => row.name !== "");
    if (rows.length > 0) out.offer = rows.map((row) => ({ name: row.name, price_inr: row.price || null }));
  }
  if (answered.has("hours")) out.hours = draft.hours;
  if (answered.has("booking") && draft.booking.trim()) out.booking = draft.booking.trim();
  return out;
}

/**
 * THE FOLLOW-UP QUESTIONS (D-855): at most three, one at a time, each one skippable.
 *
 * A worker chose them from a fixed set the brief had not answered (where you are, what you
 * offer and for how much, when you are open, how bookings work, and one multiple choice for
 * the trade); their answers go into the business profile, which every agent reads. While the
 * worker reads the brief the owner can already skip ahead and build.
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
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [answered, setAnswered] = useState<Set<string>>(() => new Set());
  const items = run.questions.items;
  const writing = run.questions.status === "writing";
  const question = items[at] ?? null;
  const pending = answer.isPending || build.isPending;

  const finish = async (keep: ReadonlySet<string>) => {
    const answers = answersOf(draft, keep);
    if (Object.keys(answers).length > 0) await answer.mutateAsync(answers);
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
    if (keep) nextAnswered.add(question.key);
    else nextAnswered.delete(question.key);
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
      <Answer question={question} draft={draft} onChange={setDraft} />
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
  draft,
  onChange,
}: {
  question: FirstRunQuestion;
  draft: Draft;
  onChange: (draft: Draft) => void;
}) {
  const id = useId();
  switch (question.kind) {
    case "choices":
      return (
        <fieldset>
          <legend className="sr-only">{question.prompt}</legend>
          <div className="flex flex-wrap gap-2">
            {question.options.map((option) => (
              <ChipChoice
                key={option}
                type="checkbox"
                name="trade"
                value={option}
                checked={draft.trade.includes(option)}
                onChange={(on) =>
                  onChange({
                    ...draft,
                    trade: on ? [...draft.trade, option] : draft.trade.filter((chosen) => chosen !== option),
                  })
                }
              >
                {option}
              </ChipChoice>
            ))}
          </div>
        </fieldset>
      );
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
            value={draft.location}
            onChange={(event) => onChange({ ...draft, location: event.target.value })}
            className={`${FIELD} mt-1 w-full text-[16px]`}
          />
        </div>
      );
    case "services":
      return <Services draft={draft} onChange={onChange} />;
    case "hours":
      return <Hours draft={draft} onChange={onChange} />;
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
            value={draft.booking}
            onChange={(event) => onChange({ ...draft, booking: event.target.value })}
            className={`${FIELD} w-full text-[16px]`}
          />
        </div>
      );
  }
}

/** The server's cap per answer (`first_run/schemas.AnswersIn.offer`). */
const MAX_OFFER_ROWS = 20;

function Services({ draft, onChange }: { draft: Draft; onChange: (draft: Draft) => void }) {
  const base = useId();
  const set = (index: number, row: { name: string; price: string }) =>
    onChange({ ...draft, offer: draft.offer.map((existing, i) => (i === index ? row : existing)) });
  return (
    <div className="space-y-3">
      {draft.offer.map((row, index) => (
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
          {draft.offer.length > 1 ? (
            <button
              type="button"
              aria-label={`Remove ${row.name || "this row"}`}
              className={QUIET_ICON_BUTTON}
              onClick={() => onChange({ ...draft, offer: draft.offer.filter((_, i) => i !== index) })}
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      ))}
      {draft.offer.length < MAX_OFFER_ROWS ? (
        <button
          type="button"
          className={TEXT_ACTION}
          onClick={() => onChange({ ...draft, offer: [...draft.offer, { name: "", price: "" }] })}
        >
          <Plus aria-hidden className="h-4 w-4" />
          Add another
        </button>
      ) : null}
    </div>
  );
}

function Hours({ draft, onChange }: { draft: Draft; onChange: (draft: Draft) => void }) {
  const opens = useId();
  const closes = useId();
  const hours = draft.hours;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <label htmlFor={opens} className="block">
          <span className={FIELD_LABEL}>Opens</span>
          <input
            id={opens}
            type="time"
            value={hours.opens}
            onChange={(event) => onChange({ ...draft, hours: { ...hours, opens: event.target.value } })}
            className={`${FIELD} mt-1 text-[16px]`}
          />
        </label>
        <label htmlFor={closes} className="block">
          <span className={FIELD_LABEL}>Closes</span>
          <input
            id={closes}
            type="time"
            value={hours.closes}
            onChange={(event) => onChange({ ...draft, hours: { ...hours, closes: event.target.value } })}
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
                  ...draft,
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
