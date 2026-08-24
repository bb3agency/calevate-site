"use client";

/**
 * The one animated figure on the page: a call turning into a row.
 *
 * ## Why this exists, and why it is not a video or a screenshot
 *
 * The single hardest thing to explain about this product in a sentence is that the
 * agent does not merely *talk* — it fills in the columns the client chose. A screenshot
 * of the leads table shows the destination and not the mechanism; a screenshot of a
 * transcript shows the mechanism and not the point. The animation is the only form that
 * shows the join, which is the actual claim.
 *
 * ## Everything in it is a shape the product really produces
 *
 * The turns are an inbound receptionist call of the kind `apps/workers/pipeline.py`
 * processes, and the fields on the right are an EXTRACTION SCHEMA — the per-agent field
 * list a client defines, which becomes their CRM columns (`extraction_schemas.fields`).
 * The three chosen here are ordinary for a clinic, the vertical the seed templates
 * cover. Nothing here is a claim about accuracy: the figure is captioned as an
 * illustration, and D-36 records that Telugu extraction quality is UNMEASURED until
 * task #87 scores it. Showing a plausible extraction is honest; labelling it as typical
 * performance would not be.
 *
 * The phone number is deliberately absent. The product's own screens redact it by
 * default (hard rule 6, `text_redacted`), and a marketing page is a strange place to be
 * looser with a caller's data than the dashboard is.
 */

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Sparkles } from "lucide-react";
import { useRef } from "react";

import { useMotion } from "./motion";

gsap.registerPlugin(useGSAP, ScrollTrigger);

/** One side of the conversation. `caller` renders right-aligned, as in the transcript UI. */
const TURNS: { who: "agent" | "caller"; text: string }[] = [
  { who: "agent", text: "Namaskaram, Sunrise Dental. This call is handled by an AI assistant." },
  { who: "caller", text: "Hi — do you do root canal? What does it cost?" },
  { who: "agent", text: "We do. The cost depends on the tooth — shall I book a check-up first?" },
  { who: "caller", text: "Yes please. Tuesday evening if you have it. I'm Priya." },
  { who: "agent", text: "Tuesday 6pm is open. Booked — you'll get a message shortly." },
];

/** The client's own columns, in the order the schema defines them. */
const FIELDS: { label: string; value: string }[] = [
  { label: "Name", value: "Priya" },
  { label: "Treatment", value: "Root canal" },
  { label: "Appointment slot", value: "Tuesday, 6:00pm" },
];

export function CallDemo() {
  const { reduced } = useMotion();
  const scope = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      if (reduced) return;

      // ONE timeline, played once when the figure is comfortably in view. A loop was
      // rejected: this sits beside body copy, and a panel that restarts while someone
      // is reading the paragraph next to it is a distraction rather than an
      // illustration.
      const timeline = gsap.timeline({
        scrollTrigger: { trigger: scope.current, start: "top 75%", once: true },
      });

      timeline
        .from(gsap.utils.toArray("[data-turn]", scope.current), {
          opacity: 0,
          y: 10,
          duration: 0.4,
          stagger: 0.5,
          ease: "power2.out",
        })
        // The fields arrive AFTER the conversation, because that is the real order:
        // extraction runs post-call, on the transcript, in the worker.
        .from(
          gsap.utils.toArray("[data-field]", scope.current),
          { opacity: 0, x: 12, duration: 0.4, stagger: 0.12, ease: "power2.out" },
          "-=0.2",
        );
    },
    { scope, dependencies: [reduced] },
  );

  return (
    <figure
      ref={scope}
      className="relative grid gap-4 lg:grid-cols-[1.4fr_auto_1fr] lg:items-stretch lg:gap-0"
    >
      {/* The call */}
      <div className="relative z-10 rounded-2xl border border-line bg-surface p-5 shadow-sm sm:p-6 lg:rounded-r-none lg:border-r-0">
        <div className="flex items-center justify-between gap-2 border-b border-line pb-3">
          <span className="flex items-center gap-2.5">
            <span aria-hidden className="relative flex h-2.5 w-2.5">
              <span className="mk-ping absolute inline-flex h-full w-full rounded-full bg-brand-bright" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-bright" />
            </span>
            <span className="text-xs font-semibold tracking-wide text-ink-muted uppercase">
              Inbound call
            </span>
          </span>
          <span className="flex items-center gap-2 text-brand-strong dark:text-brand-bright">
            <span aria-hidden className="mk-wave">
              <i /><i /><i /><i /><i />
            </span>
            <span className="text-[11px] font-medium text-ink-faint">Telugu</span>
          </span>
        </div>
        <ol className="mt-4 space-y-3">
          {TURNS.map((turn, index) => (
            <li
              key={index}
              data-turn
              className={turn.who === "caller" ? "flex justify-end" : "flex justify-start"}
            >
              <p
                className={[
                  "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-snug",
                  turn.who === "agent"
                    ? "rounded-bl-sm bg-brand-soft text-brand-strong"
                    : "rounded-br-sm bg-black/5 text-ink dark:bg-white/10",
                ].join(" ")}
              >
                <span className="sr-only">
                  {turn.who === "agent" ? "Agent said: " : "Caller said: "}
                </span>
                {turn.text}
              </p>
            </li>
          ))}
        </ol>
      </div>

      {/* The join, drawn once between the two panels. Decorative: the figcaption and the
          two headings already carry the meaning, so the arrow is `aria-hidden`. It sits
          on the seam on large screens and turns into a centred downward chevron when the
          panels stack. */}
      <div
        aria-hidden
        className="relative z-20 -my-3 flex items-center justify-center lg:my-0 lg:-mx-4 lg:flex-col"
      >
        <span className="flex h-9 items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-[11px] font-semibold tracking-wide text-brand-strong uppercase shadow-sm dark:text-brand-bright">
          <Sparkles className="h-3.5 w-3.5" />
          Extracted
        </span>
      </div>

      {/* What the pipeline wrote down */}
      <div className="relative z-10 rounded-2xl border border-line bg-surface p-5 shadow-sm sm:p-6 lg:rounded-l-none lg:border-l-0">
        <div className="border-b border-line pb-3">
          <span className="text-xs font-semibold tracking-wide text-ink-muted uppercase">
            Your columns
          </span>
        </div>
        <dl className="mt-4 space-y-3">
          {FIELDS.map((field) => (
            <div
              key={field.label}
              data-field
              className="rounded-lg border border-line/70 bg-app/60 px-3 py-2"
            >
              <dt className="text-[11px] tracking-wide text-ink-faint uppercase">{field.label}</dt>
              <dd className="mt-0.5 text-sm font-semibold text-ink">{field.value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 border-t border-line pt-3 text-xs text-ink-faint">
          You choose these fields. They become the columns you sort and follow up from.
        </p>
      </div>

      <figcaption className="text-xs text-ink-faint lg:col-span-3 lg:mt-4">
        An illustration of the shape of a call and the record it leaves. It is not a
        sample of measured performance.
      </figcaption>
    </figure>
  );
}
