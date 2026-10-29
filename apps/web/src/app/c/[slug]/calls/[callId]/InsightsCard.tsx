"use client";

import { Section } from "@/components/console/section";
import { formatIST } from "@/components/ui";
import type { CallDetail } from "@/lib/api/client";

/**
 * "What it came to": how the call ended, why a no was a no, the objections and problems the
 * customer named in their own words, and the next step agreed (D-940). Short lines, one per
 * item; the screen hides the card when the call has no reading.
 */

type Insights = NonNullable<CallDetail["insights"]>;
type Note = Insights["objections"][number];
type NextStep = NonNullable<Insights["next_step"]>;

export const OUTCOME_WORDS: Record<Insights["outcome"], string> = {
  converted: "Said yes",
  interested: "Interested",
  callback: "Wants a call back",
  promise_to_pay: "Promised to pay",
  not_interested: "Not interested",
  no_decision: "No decision yet",
  wrong_person: "Wrong person",
  do_not_call: "Asked not to be called",
};

const NO_REASON_WORDS: Record<NonNullable<Insights["no_reason"]>, string> = {
  price: "price",
  timing: "timing",
  trust: "trust",
  fit: "not a fit",
  already_has: "already has one",
  other: "another reason",
};

const KIND_WORDS: Record<Note["kind"], string> = {
  price: "Price",
  timing: "Timing",
  trust: "Trust",
  fit: "Not a fit",
  need: "No need",
  authority: "Not their decision",
  competitor: "Uses someone else",
  payment: "Payment",
  billing: "Billing",
  login: "Login",
  delivery: "Delivery",
  product: "Product",
  other: "Other",
};

const STEP_WORDS: Record<NextStep["kind"], string> = {
  callback: "Call back",
  promise_to_pay: "Payment promised",
  send_info: "Send details",
  visit: "Visit",
  hand_to_sales: "Pass to sales",
};

function Notes({ heading, notes }: { heading: string; notes: Note[] }) {
  if (notes.length === 0) return null;
  return (
    <div>
      <h3 className="text-meta text-ink-muted">{heading}</h3>
      <ul className="mt-1 space-y-1">
        {notes.map((note, i) => (
          <li key={`${note.kind}-${i}`} className="text-body text-ink">
            <span className="text-ink-muted">{KIND_WORDS[note.kind]}: </span>
            {note.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function InsightsCard({ insights }: { insights: Insights }) {
  const step = insights.next_step;
  const reason =
    insights.outcome === "not_interested" && insights.no_reason
      ? ` (${NO_REASON_WORDS[insights.no_reason]})`
      : "";
  return (
    <Section title="What it came to">
      <div className="mt-1 space-y-4">
        <p className="text-body font-medium text-ink">
          {OUTCOME_WORDS[insights.outcome]}
          {reason}
        </p>
        <Notes heading="Objections" notes={insights.objections} />
        <Notes heading="Problems they raised" notes={insights.issues} />
        {step && (
          <div>
            <h3 className="text-meta text-ink-muted">Next step</h3>
            <p className="mt-1 text-body text-ink">
              {STEP_WORDS[step.kind]}
              {step.at ? `, ${formatIST(step.at)}` : ""}
              {step.status === "done" ? " · done" : ""}
            </p>
            {step.note && <p className="mt-0.5 text-meta text-ink-muted">{step.note}</p>}
          </div>
        )}
      </div>
    </Section>
  );
}
