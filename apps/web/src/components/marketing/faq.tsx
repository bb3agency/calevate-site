"use client";

/**
 * The questions an Indian SMB buyer asks before they will take a call, answered.
 *
 * ## Every answer names a behaviour that exists, and the hardest one is the price
 *
 * The page's doctrine (see `app/page.tsx`) is that a line here is a promise the product
 * already keeps. An FAQ is where that erodes fastest, because a question invites an
 * answer even when the product does not have one — so the two questions with no settled
 * answer are answered with the SHAPE of the arrangement and no figure:
 *
 * - **Cost.** D-11's managed pricing is negotiated per client and D-34's self-serve tier
 *   has no published number, so the answer describes the structure (a plan with talk
 *   time included, a rate beyond it) and says plainly that the figures are agreed with
 *   you. A number here would be a quote nobody can honour.
 * - **Getting started.** Written so it is true on both sides of
 *   `self_serve_signup_enabled` — the flag-dependent sentence belongs to the doors
 *   section, which reads the flag, and duplicating it here would be a second place to
 *   get it wrong.
 *
 * The rest map to enforced behaviour: KB approval before anything is answerable
 * (`kb_sources` review states), `text_redacted` plus a role check and an `audit_log`
 * write for a raw number (hard rule 5), the CSV export and the signed outbound webhook
 * (D-23), DNC scrubbed before every dispatch (hard rule 5), and the PE/TM registration
 * gate that blocks outbound while leaving inbound alone (`pe_registration_blocker`,
 * `apps/api/compliance/registration.py`, which is exactly what `/verification` tells a
 * client whose outbound stopped).
 *
 * ## Why `<details>` rather than a built accordion
 *
 * It is the platform's disclosure widget: keyboard-operable, announced as expandable and
 * open/closed by every screen reader, and correct with no JavaScript at all — which
 * matters here more than elsewhere, because the whole page's rule is that it is finished
 * without its bundle. An accordion built from buttons plus `aria-expanded` would be more
 * code, would need its own focus handling, and would render a page whose answers are
 * unreachable if the bundle fails. The one thing script adds is the ScrollTrigger
 * refresh below, and that is an enhancement on top of a working control rather than the
 * thing that makes it work.
 */

import { ChevronDown } from "lucide-react";
import { ScrollTrigger } from "gsap/ScrollTrigger";

import { useMotion } from "./motion";

/** One question and the answer the product can stand behind. */
const QUESTIONS: { q: string; a: string }[] = [
  {
    q: "How do we get started?",
    a:
      "You talk to us. We set the workspace up with you, build the agent from what you " +
      "tell us about the business, and load the material it answers from. Nothing dials " +
      "anybody until you launch it.",
  },
  {
    q: "What does it cost?",
    a:
      "We quote it for your business: a plan with a bundle of talk time included, and a " +
      "rate for anything past that bundle. What those figures are depends on how much " +
      "you call and get called, so we agree them with you rather than publishing one " +
      "number and then changing it for every client.",
  },
  {
    q: "Where does the agent get its answers from?",
    a:
      "From the material you upload — your price list, your timings, your FAQs — and " +
      "only after somebody has approved that version. It is not answering from the open " +
      "internet, and a change you have not approved does not reach a caller.",
  },
  {
    q: "Who can see our callers' phone numbers?",
    a:
      "Nobody, by default. Transcripts come back with numbers masked in every screen and " +
      "every response. Seeing the raw text or exporting full numbers takes the right " +
      "role, and it writes an audit entry naming who looked.",
  },
  {
    q: "Can we get our leads out again?",
    a:
      "Yes, three ways: download them as a spreadsheet, push each one to your own CRM " +
      "over a signed webhook, or send them into a Google Sheet. Every delivery is " +
      "logged and failures are retried.",
  },
  {
    q: "What happens when someone says stop calling me?",
    a:
      "They go on your do-not-call list during that call, and the list is checked before " +
      "every dispatch after it. You can add numbers to it yourself and take those ones " +
      "back off — but an entry that records a caller's own request is not removable by " +
      "anyone, because it was not our decision or yours to begin with.",
  },
  {
    q: "Do we need a DLT registration to make outbound calls?",
    a:
      "Yes — Indian rules register the business whose calls are being made, and Calevate " +
      "is registered as the telemarketer that makes them. We do that part with you, and " +
      "outbound stays blocked until it is in place. Inbound is not affected by any of it.",
  },
  {
    q: "Can we stop it once it is running?",
    a:
      "Pause a campaign from your dashboard and it stops starting calls at the next " +
      "tick. A repeat you scheduled can be stopped the same way, before its next run.",
  },
];

export function Faq() {
  const { reduced } = useMotion();

  /**
   * Opening an answer changes the page's height, and every ScrollTrigger below this
   * section is holding start/end values measured against the OLD height. Nothing fires a
   * resize event for a `<details>` toggle, so without this the reveals under the FAQ
   * either fire early or not at all — the same stale-position bug `SmoothScroll` refreshes
   * for when Lenis is destroyed. Skipped under reduced motion because no ScrollTrigger
   * was ever created there.
   */
  const handleToggle = () => {
    if (reduced) return;
    ScrollTrigger.refresh();
  };

  return (
    <div className="mt-8 divide-y divide-line border-y border-line">
      {QUESTIONS.map(({ q, a }) => (
        <details key={q} className="group" onToggle={handleToggle}>
          <summary
            className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 py-4 [&::-webkit-details-marker]:hidden"
          >
            <h3 className="text-[17px] font-medium text-ink">{q}</h3>
            <ChevronDown
              aria-hidden
              className="h-4 w-4 shrink-0 text-ink-faint transition-transform duration-200 group-open:rotate-180 motion-reduce:transition-none"
            />
          </summary>
          <p className="max-w-2xl pb-5 text-sm text-ink-muted">{a}</p>
        </details>
      ))}
    </div>
  );
}
