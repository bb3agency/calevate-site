/**
 * "Same leads. Completely different workflow." — the before/after chain.
 *
 * ## Why this is a figure and not three paragraphs
 *
 * This argument was the strongest writing on the page and it was buried at band 05 as
 * prose. The claim is about a SEQUENCE — how many steps a lead passes through before
 * anybody sells anything — and a sequence rendered as a paragraph asks the reader to hold
 * six items in their head to feel the difference. Two chains side by side make it in a
 * glance, which is the whole point of moving it.
 *
 * ## Every step on the WITH side is a shipped behaviour
 *
 * In order down the right-hand chain:
 *
 *  - answered on the first ring — the agent takes the call; an agent runs 24/7 by default
 *    (`apps/api/agents/business_hours.py`, FLOWS §3);
 *  - every enquiry gets a first call — `apps/api/ingest/service.py` turns a web enquiry
 *    into a dial through the compliance gate, and `apps/api/campaigns/service.py` works a
 *    list; the form→dial gap is timed by
 *    `apps/api/core/alerting.py:632::record_speed_to_lead`;
 *  - it comes back sorted — the six lead statuses are a fixed enum
 *    (`apps/api/crm/schemas.py:29`) and the hot-lead alert fires off the extracted fields
 *    (`apps/workers/pipeline.py:179::HOT_LEAD_FIELD_TRIGGERS`);
 *  - a filled-in row — the per-agent extraction schema drives the CRM columns
 *    (`apps/api/crm/columns.py`);
 *  - your team opens a shortlist — `apps/api/crm/performance.py` reads it back as
 *    Calls → Connected → Qualified.
 *
 * No number appears on either side. The arithmetic belongs to the calculator, where the
 * buyer supplies the inputs; a figure here would be a claim about a business we have
 * never seen.
 */

import { ArrowDown } from "lucide-react";

const WITHOUT: readonly string[] = [
  "The phone rings while your staff is with another customer",
  "Some calls are missed. Nobody knows which ones",
  "A web enquiry sits until somebody notices it",
  "Your salespeople ring the whole list to find out who is serious",
  "Notes end up in a diary, a WhatsApp thread and somebody's memory",
];

const WITH: readonly string[] = [
  "Every call is answered, at every hour, in your customer's language",
  "Every enquiry gets a first call without waiting for somebody to notice it",
  "The caller is asked what you said you needed to know",
  "It comes back as a filled-in row, marked contacted, interested or hot",
  "Your team opens the day on a shortlist and starts closer to the sale",
];

/** One chain. `tone` decides the colour and nothing else — the words carry the argument. */
function Chain({
  title, caption, steps, closing, tone,
}: {
  title: string;
  caption: string;
  steps: readonly string[];
  closing: string;
  tone: "without" | "with";
}) {
  const good = tone === "with";
  return (
    <section
      className={
        "rounded-2xl border p-5 sm:p-7 " +
        (good ? "border-brand/40 bg-brand-soft/30 dark:bg-brand-strong/10" : "border-line bg-surface")
      }
    >
      <h3 className="text-lg font-semibold text-ink">{title}</h3>
      <p className="mt-1 text-sm text-ink-muted">{caption}</p>
      <ol className="mt-6 space-y-0">
        {steps.map((step, index) => (
          <li key={step}>
            <div
              className={
                "rounded-xl border px-4 py-3 text-sm text-pretty " +
                (good
                  ? "border-brand/30 bg-surface text-ink"
                  : "border-line bg-app/60 text-ink-muted")
              }
            >
              {step}
            </div>
            {index < steps.length - 1 && (
              // Decorative: the ordered list already carries the sequence for a screen
              // reader, so the arrow is one more way to say the same thing to the eye.
              <div aria-hidden className="flex justify-center py-1.5">
                <ArrowDown
                  className={
                    "h-4 w-4 " + (good ? "text-brand-strong dark:text-brand-bright" : "text-ink-faint")
                  }
                />
              </div>
            )}
          </li>
        ))}
      </ol>
      <p
        className={
          "mt-6 border-t pt-4 text-base font-semibold text-pretty " +
          (good ? "border-brand/30 text-brand-strong dark:text-brand-bright" : "border-line text-ink")
        }
      >
        {closing}
      </p>
    </section>
  );
}

export function BeforeAfter() {
  return (
    <div className="mt-10 grid gap-4 sm:mt-12 lg:grid-cols-2">
      <Chain
        tone="without"
        title="Without Calevate"
        caption="The same enquiries, worked by hand."
        steps={WITHOUT}
        closing="Hours spent before selling even begins."
      />
      <Chain
        tone="with"
        title="With Calevate"
        caption="The same enquiries, already sorted."
        steps={WITH}
        closing="Your people start closer to the buying conversation."
      />
    </div>
  );
}
