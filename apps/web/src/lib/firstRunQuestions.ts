/**
 * THE FOLLOW-UP QUESTIONS SEAM (founder, 23 Oct 2026): our AI writes two to four questions
 * from the owner's description, each with its own answer type, and the answers feed the
 * script. The screens speak the contract the API is moving to:
 *
 *   question  {id, prompt, hint, kind, options, maps_to}
 *   answers   {answers: [{id, choices, text, services, hours}]}
 *
 * Until the server sends that shape, `askedOf` reads today's questions (a fixed key per
 * question) into it and `currentAnswers` writes the answers back into today's
 * profile-shaped body. Wiring the new API is these two adapters and `answersBody`; the
 * question components do not change.
 */

import type { FirstRunAnswers, FirstRunQuestion } from "@/lib/api/firstRun";

export type QuestionKind = "choices" | "single_choice" | "text" | "address" | "services" | "hours";

export interface AskedQuestion {
  id: string;
  prompt: string;
  hint: string;
  kind: QuestionKind;
  options: string[];
  /** The business-profile field the answer lands in, when it lands in one. */
  maps_to: string | null;
}

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

export interface AskedAnswer {
  id: string;
  choices: string[];
  text: string;
  services: ServiceRow[];
  hours: HoursAnswer;
}

/** The server's caps on one answer (`first_run/schemas.AnswersIn`). */
export const MAX_SERVICES = 20;
export const MAX_TEXT_CHARS = 2000;
export const MAX_ADDRESS_CHARS = 400;

/** Today's question, in the new contract's shape. */
export function askedOf(item: FirstRunQuestion | AskedQuestion): AskedQuestion {
  if ("id" in item) return item;
  return {
    id: item.key,
    prompt: item.prompt,
    hint: item.hint,
    kind: item.kind,
    options: item.options,
    maps_to: item.key,
  };
}

export function emptyAnswer(id: string): AskedAnswer {
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

function filledServices(answer: AskedAnswer) {
  return answer.services
    .map((row) => ({ name: row.name.trim(), price_inr: priceOf(row.price) }))
    .filter((row) => row.name !== "");
}

/** Whether an answer says anything: a skipped or empty answer is not sent. */
export function isAnswered(question: AskedQuestion, answer: AskedAnswer | undefined): boolean {
  if (!answer) return false;
  switch (question.kind) {
    case "choices":
    case "single_choice":
      return answer.choices.length > 0;
    case "services":
      return filledServices(answer).length > 0;
    case "hours":
      return answer.hours.closed.length < DAYS.length;
    default:
      return answer.text.trim() !== "";
  }
}

/** Today's body: each answered question written into the profile field its key names. */
export function currentAnswers(questions: readonly AskedQuestion[], answers: readonly AskedAnswer[]): FirstRunAnswers {
  const out: FirstRunAnswers = {};
  for (const question of questions) {
    const answer = answers.find((entry) => entry.id === question.id);
    if (!answer || !isAnswered(question, answer)) continue;
    switch (question.maps_to ?? question.id) {
      case "trade":
        out.trade = answer.choices;
        break;
      case "location":
        out.location = answer.text.trim();
        break;
      case "offer":
        out.offer = filledServices(answer);
        break;
      case "hours":
        out.hours = answer.hours;
        break;
      case "booking":
        out.booking = answer.text.trim();
        break;
    }
  }
  return out;
}

/** The new contract's body, for when the API takes it: only answered questions, each with
 *  only the part its kind uses. */
export function answersBody(questions: readonly AskedQuestion[], answers: readonly AskedAnswer[]) {
  return {
    answers: questions.flatMap((question) => {
      const answer = answers.find((entry) => entry.id === question.id);
      if (!answer || !isAnswered(question, answer)) return [];
      return [
        {
          id: question.id,
          choices: question.kind === "choices" || question.kind === "single_choice" ? answer.choices : [],
          text: question.kind === "text" || question.kind === "address" ? answer.text.trim() : "",
          services: question.kind === "services" ? filledServices(answer) : [],
          hours: question.kind === "hours" ? answer.hours : null,
        },
      ];
    }),
  };
}
