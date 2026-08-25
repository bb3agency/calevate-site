"use client";

/**
 * THE SCRIPT — this screen's primary job, and the only hero on it.
 *
 * ## Why this component exists at all
 *
 * It replaces `ScriptNote`: a small text link headed "Its script", nested inside a card
 * called "What it says", which sat fifth in a flat stack of nine equally-weighted cards
 * between a lifecycle toggle and the extraction editor. What an agent SAYS is the product,
 * it is the most-edited thing an owner owns, and it was the hardest thing on the screen to
 * find. That is the defect UX-DOCTRINE §1 is written about, and this is the fix.
 *
 * ## How primacy is expressed here — the four channels, all four used
 *
 * POSITION: first block under the page header, above every other panel. SIZE: the only
 * `PRIMARY_BUTTON_LG` on the screen, and an `h2` at hero scale rather than card scale.
 * WEIGHT: a 2px brand border where every other panel has a 1px `--line` one. COLOUR: the
 * brand medallion, and the one brand-strong call to action. Nothing else on the screen is
 * allowed to use more than one of the four — see the doctrine.
 *
 * GOV.UK's Button guidance is the constraint this is held to: "Avoid using multiple
 * default buttons on a single page. Having more than one main call to action reduces their
 * impact, and makes it harder for users to know what to do next"
 * (github.com/alphagov/govuk-design-system `src/components/button/index.md`, read
 * 25 Aug 2026). This is that one button; every other primary on the workspace is bound to
 * a form it submits and sits inside it.
 *
 * ## Why it is a link to a route and not an editor inlined here
 *
 * The builder is a full authoring surface — steps, FAQ, merge fields, AI assist, compiled
 * -prompt preview — with its own unsaved state and its own two-speed Save/Apply ladder.
 * GOV.UK's own advice when a page has too much on it is to "split the content across
 * multiple pages" before reaching for a device that hides it
 * (`src/components/tabs/index.md`, same source and date). A destination is also what makes
 * the entry point cheap enough to make LARGE, which is the whole point.
 *
 * ## Why no request is made here
 *
 * The state sentence is derived from `agent.published`, which the screen already has. A
 * hero that had to wait for `GET /v1/agents/{id}/script` would either paint a skeleton in
 * the one slot that must never look broken, or invent a claim about a script it has not
 * read. What version is live and what is waiting is the publishing panel's subject, one
 * block down, where the two pointers are rendered as labelled data.
 */

import Link from "next/link";
import { ArrowRight, MessageSquareQuote } from "lucide-react";

import { PRIMARY_BUTTON_LG } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";

export function ScriptCallout({
  slug,
  agentId,
  published,
}: {
  slug: string;
  agentId: string;
  published: boolean;
}) {
  const { href } = useClientRealm();
  return (
    <section
      aria-labelledby="script-callout-heading"
      className="rounded-card border-2 border-brand bg-surface p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)] sm:p-6"
    >
      <div className="flex items-start gap-4">
        <span
          aria-hidden
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
        >
          <MessageSquareQuote className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="script-callout-heading" className="text-xl font-semibold text-ink">
            What it says on a call
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            The script is the agent. It decides what it says and how it handles a call —
            your prices, your staff, what to do when someone asks for something you do not
            offer. Build it as an opening line, steps and questions, or let AI draft it from
            a description of your business.
          </p>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            {published
              ? "Callers are hearing the applied version right now. A change never reaches a live call until you apply it, so nothing a caller hears moves by accident."
              : "This agent is not on the calling system yet, so no caller hears anything at all. Write the script first — an agent with none cannot be switched on."}
          </p>
          <Link
            href={href(`/c/${slug}/agents/${agentId}/script`)}
            className={`${PRIMARY_BUTTON_LG} mt-4`}
          >
            Open the script builder
            <ArrowRight aria-hidden className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}
