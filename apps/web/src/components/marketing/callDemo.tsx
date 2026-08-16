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
    <figure ref={scope} className="mt-14 grid gap-4 lg:grid-cols-[1.35fr_1fr]">
      {/* The call */}
      <div className="rounded-card border border-line bg-surface p-5">
        <div className="flex items-center gap-2 border-b border-line pb-3">
          <span
            aria-hidden
            className="h-2 w-2 rounded-full bg-emerald-500"
          />
          <span className="text-xs font-medium tracking-wide text-ink-muted uppercase">
            Inbound call
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
                    ? "bg-brand-soft text-brand-strong"
                    : "bg-black/5 text-ink dark:bg-white/10",
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

      {/* What the pipeline wrote down */}
      <div className="rounded-card border border-line bg-surface p-5">
        <div className="border-b border-line pb-3">
          <span className="text-xs font-medium tracking-wide text-ink-muted uppercase">
            Your columns
          </span>
        </div>
        <dl className="mt-4 space-y-3.5">
          {FIELDS.map((field) => (
            <div key={field.label} data-field>
              <dt className="text-xs text-ink-faint">{field.label}</dt>
              <dd className="mt-0.5 text-sm font-medium text-ink">{field.value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-5 border-t border-line pt-3 text-xs text-ink-faint">
          You choose these fields. They become the columns you sort and follow up from.
        </p>
      </div>

      <figcaption className="lg:col-span-2 text-xs text-ink-faint">
        An illustration of the shape of a call and the record it leaves. It is not a
        sample of measured performance.
      </figcaption>
    </figure>
  );
}
