/**
 * The hero figure: a call arriving in Telugu, and the filled-in lead it leaves behind.
 *
 * ## What it is, and the three things it deliberately is not
 *
 * It is an ILLUSTRATION of the shape of a call and the record the product writes from it.
 * It is not a recording, not a sample of a real customer's call, and not audio of any
 * kind — there is no call audio anywhere in this repository, so a "hear a sample call"
 * control would be a button with nothing behind it. The founder's decision (5 Sep 2026)
 * is this silent, staged text simulation instead, and the caption says in as many words
 * what the reader is looking at.
 *
 * It also carries NO claim about quality. D-36 records Telugu extraction quality as
 * UNMEASURED until task #87 scores it, so a figure like this may show a plausible
 * extraction and may never be labelled typical performance.
 *
 * ## Everything in it is a shape the product really produces
 *
 * - The opening line announces the AI. That is `agents.ai_disclosure_line` — NOT NULL and
 *   non-blank, and volunteered at the start by default (`ai_disclosure_enabled` DEFAULT
 *   true, D-163). The unswitchable half is the truthful ANSWER when a caller asks, which
 *   the trust section states rather than this figure.
 * - Telugu is where the call is held because Telugu is where an agent starts:
 *   `apps/api/agents/models.py:215` server-defaults `language_primary` to `te-IN`.
 * - The lower card is an EXTRACTION SCHEMA — the per-agent field list a client writes,
 *   which becomes their CRM columns (`apps/api/crm/columns.py`). "Interested" is one of
 *   the six real lead statuses (`apps/api/crm/schemas.py:29`), not a word invented for a
 *   mockup.
 * - The booked appointment is a `calendar` action (`apps/api/actions/models.py:53`,
 *   `apps/api/actions/calendar.py`), which the agent can call mid-call once the client's
 *   Google account is connected — the use-case card on the page states that condition,
 *   because `calendar_configured()` gates every route behind it.
 * - No phone number appears. The product's own screens redact by default (hard rule 6),
 *   and a marketing page has no business being looser with a caller's data than the
 *   dashboard is.
 *
 * ## Why the animation is CSS and why this file is a server component
 *
 * See the `.mk-sim-*` block in `globals.css`. In short: nothing here needs state, a client
 * island in the hero costs a visible delay on the low-end Android this page is written
 * for, every step's end frame IS its resting state (so the figure is complete if the
 * bundle never arrives), and the reduced-motion reader gets that end state painted on the
 * first frame with no code path of its own.
 */

import { CalendarCheck, Sparkles } from "lucide-react";

/**
 * One side of the conversation.
 *
 * `gloss` is the English underneath, and it is not decoration: the buyer reading this page
 * may be a Telugu speaker, a Hindi speaker or an English speaker, and a figure whose whole
 * point is "your customers speak the way they normally speak" is worth nothing to a reader
 * who cannot follow it. `lang="te"` is on the Telugu run only, so a screen reader switches
 * voice for it and reads the gloss in English.
 */
const TURNS: { who: "agent" | "caller"; te: string; gloss: string; delay: string }[] = [
  {
    who: "agent",
    te: "నమస్కారం, Sunrise Dental. నేను AI అసిస్టెంట్‌ని. మీకు ఎలా సహాయం చేయగలను?",
    gloss: "Namaskaram, Sunrise Dental. I am an AI assistant. How can I help?",
    delay: "mk-d1",
  },
  {
    who: "caller",
    te: "రూట్ కెనాల్ చేస్తారా? ఖర్చు ఎంత అవుతుంది?",
    gloss: "Do you do root canal? What does it cost?",
    delay: "mk-d2",
  },
  {
    who: "agent",
    te: "చేస్తాము. ఖర్చు పంటిని బట్టి ఉంటుంది — ముందుగా చెకప్ బుక్ చేయనా?",
    gloss: "We do. It depends on the tooth — shall I book a check-up first?",
    delay: "mk-d3",
  },
  {
    who: "caller",
    te: "అవును. మంగళవారం సాయంత్రం. నా పేరు ప్రియ.",
    gloss: "Yes. Tuesday evening. My name is Priya.",
    delay: "mk-d4",
  },
  {
    who: "agent",
    te: "మంగళవారం సాయంత్రం 6 గంటలకు బుక్ చేశాను.",
    gloss: "Booked for Tuesday at 6pm.",
    delay: "mk-d5",
  },
];

/** The client's own columns, in the order their schema defines them. */
const FIELDS: { label: string; value: string; delay: string }[] = [
  { label: "Name", value: "Priya", delay: "mk-d6" },
  { label: "Requirement", value: "Root canal", delay: "mk-d7" },
  { label: "Preferred time", value: "Tuesday, 6:00pm", delay: "mk-d8" },
];

export function HeroCallSim() {
  return (
    <figure className="relative">
      <div className="grid gap-3 sm:gap-4">
        {/* --- The call ------------------------------------------------------- */}
        <div className="rounded-2xl border border-line bg-surface p-4 shadow-sm sm:p-5">
          <div className="flex items-center justify-between gap-2 border-b border-line pb-3">
            <span className="flex items-center gap-2.5">
              <span aria-hidden className="relative flex h-2.5 w-2.5">
                <span className="mk-ping absolute inline-flex h-full w-full rounded-full bg-brand-bright" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-bright" />
              </span>
              <span className="text-xs font-semibold tracking-wide text-ink-muted uppercase">
                Incoming call
              </span>
            </span>
            <span className="flex items-center gap-2 text-brand-strong dark:text-brand-bright">
              <span aria-hidden className="mk-wave">
                <i />
                <i />
                <i />
                <i />
                <i />
              </span>
              <span className="text-[11px] font-medium text-ink-faint">Telugu</span>
            </span>
          </div>
          <ol className="mt-4 space-y-2.5">
            {TURNS.map((turn) => (
              <li
                key={turn.gloss}
                className={`mk-sim-step ${turn.delay} ${
                  turn.who === "caller" ? "flex justify-end" : "flex justify-start"
                }`}
              >
                <div
                  className={[
                    "max-w-[88%] rounded-2xl px-3.5 py-2",
                    turn.who === "agent"
                      ? "rounded-bl-sm bg-brand-soft text-brand-strong dark:text-ink"
                      : "rounded-br-sm bg-black/5 text-ink dark:bg-white/10",
                  ].join(" ")}
                >
                  <span className="sr-only">
                    {turn.who === "agent" ? "Agent said: " : "Caller said: "}
                  </span>
                  <p lang="te" className="text-sm leading-snug">
                    {turn.te}
                  </p>
                  <p
                    className={
                      "mt-1 text-xs leading-snug " +
                      (turn.who === "agent"
                        ? "text-brand-strong/80 dark:text-ink-muted"
                        : "text-ink-faint")
                    }
                  >
                    {turn.gloss}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        {/* The join. Decorative — the heading below carries the meaning in words. */}
        <div aria-hidden className="mk-sim-step mk-d6 flex justify-center">
          <span className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-[11px] font-semibold tracking-wide text-brand-strong uppercase shadow-sm dark:text-brand-bright">
            <Sparkles className="h-3.5 w-3.5" />
            Written down for you
          </span>
        </div>

        {/* --- What your team gets -------------------------------------------- */}
        <div className="rounded-2xl border border-line bg-surface p-4 shadow-sm sm:p-5">
          <div className="flex items-center justify-between gap-3 border-b border-line pb-3">
            {/* A PANEL LABEL, NOT A HEADING. It sat directly under the page's `<h1>` as an
                `<h3>`, which is a skipped level in the document outline (axe's
                `heading-order`) and, worse, puts a decorative figure's internal label into
                the heading list a screen-reader user navigates by. The `<figcaption>`
                below is what describes this figure. */}
            <p className="text-xs font-semibold tracking-wide text-ink-muted uppercase">
              New lead
            </p>
            <span className="mk-sim-field mk-d9 rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-strong">
              Interested
            </span>
          </div>
          <dl className="mt-3 grid gap-2 sm:grid-cols-3">
            {FIELDS.map((field) => (
              <div
                key={field.label}
                className={`mk-sim-field ${field.delay} rounded-lg border border-line/70 bg-app/60 px-3 py-2`}
              >
                <dt className="text-[11px] tracking-wide text-ink-faint uppercase">
                  {field.label}
                </dt>
                <dd className="mt-0.5 text-sm font-semibold text-ink">{field.value}</dd>
              </div>
            ))}
          </dl>
          <p className="mk-sim-field mk-d10 mt-3 flex items-center gap-2 border-t border-line pt-3 text-sm text-ink-muted">
            <CalendarCheck
              aria-hidden
              className="h-4 w-4 shrink-0 text-brand-strong dark:text-brand-bright"
            />
            Appointment booked — Tuesday, 6:00pm
          </p>
        </div>
      </div>

      <figcaption className="mt-3 text-xs text-ink-faint">
        An illustration of how a call becomes a lead. Not a recording, not a real customer,
        and not a measurement of how well it does it.
      </figcaption>
    </figure>
  );
}
