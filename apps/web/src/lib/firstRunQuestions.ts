/**
 * THE FOLLOW-UP QUESTIONS' ANSWERS (D-863): our AI writes a few questions from the owner's
 * description, each with its own answer kind, and `POST /v1/first-run/answers` takes
 * `{answers: [{id, choices, text, services, hours}]}` where each kind fills exactly one field
 * (a mismatch is refused as `first_run_answer_mismatch`).
 *
 * The screen keeps one draft per question with every field, so moving back and forth keeps
 * what was typed; `answersBody` sends only the answered questions, each with only its kind's
 * field.
 */

import type { FirstRunAnswer, FirstRunAnswers, FirstRunQuestion } from "@/lib/api/firstRun";

export type QuestionKind = FirstRunQuestion["kind"];

export const DAYS = [
  { id: "mon", label: "Mon", name: "Monday" },
  { id: "tue", label: "Tue", name: "Tuesday" },
  { id: "wed", label: "Wed", name: "Wednesday" },
  { id: "thu", label: "Thu", name: "Thursday" },
  { id: "fri", label: "Fri", name: "Friday" },
  { id: "sat", label: "Sat", name: "Saturday" },
  { id: "sun", label: "Sun", name: "Sunday" },
] as const;
export type Day = (typeof DAYS)[number]["id"];

export interface ServiceRow {
  name: string;
  /** As typed: "₹1,500" or "1500"; `priceOf` keeps the digits. */
  price: string;
}

export interface HoursAnswer {
  opens: string;
  closes: string;
  closed: Day[];
}

/** One question's draft on the screen. */
export interface DraftAnswer {
  id: string;
  choices: string[];
  text: string;
  services: ServiceRow[];
  hours: HoursAnswer;
}

/** The server's caps on one answer (`first_run/schemas.AnswerIn`). */
export const MAX_SERVICES = 20;
export const MAX_TEXT_CHARS = 2000;
export const MAX_ADDRESS_CHARS = 400;

export function emptyAnswer(id: string): DraftAnswer {
  return {
    id,
    choices: [],
    text: "",
    services: [{ name: "", price: "" }],
    hours: { opens: "09:00", closes: "18:00", closed: ["sun"] },
  };
}

/** Digits and one decimal point, so "₹1,500" is sent as "1500". */
export function priceOf(typed: string): string | null {
  const cleaned = typed.replace(/[^\d.]/g, "");
  return cleaned === "" ? null : cleaned;
}

function filledServices(answer: DraftAnswer) {
  return answer.services
    .map((row) => ({ name: row.name.trim(), price_inr: priceOf(row.price) }))
    .filter((row) => row.name !== "");
}

/** Whether a draft says anything: an empty answer is left out, like a skipped one. */
export function isAnswered(question: FirstRunQuestion, answer: DraftAnswer | undefined): boolean {
  if (!answer) return false;
  switch (question.kind) {
    case "choices":
      return answer.choices.length > 0;
    case "single_choice":
      return answer.choices.length === 1;
    case "services":
      return filledServices(answer).length > 0;
    case "hours":
      return answer.hours.closed.length < DAYS.length;
    default:
      return answer.text.trim() !== "";
  }
}

/** One answer on the wire: its id and the one field its kind uses. */
export function answerOf(question: FirstRunQuestion, answer: DraftAnswer): FirstRunAnswer {
  switch (question.kind) {
    case "choices":
    case "single_choice":
      return { id: question.id, choices: answer.choices };
    case "services":
      return { id: question.id, services: filledServices(answer) };
    case "hours":
      return { id: question.id, hours: answer.hours };
    default:
      return { id: question.id, text: answer.text.trim() };
  }
}

/** The body for `POST /v1/first-run/answers`: the kept questions that were answered. */
export function answersBody(
  questions: readonly FirstRunQuestion[],
  answers: Readonly<Record<string, DraftAnswer>>,
): FirstRunAnswers {
  return {
    answers: questions.flatMap((question) => {
      const answer = answers[question.id];
      return answer && isAnswered(question, answer) ? [answerOf(question, answer)] : [];
    }),
  };
}
