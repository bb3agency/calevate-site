"use client";

/**
 * THE REST OF THE SCRIPT — who the agent is, the goal, what it may do, and the parts most
 * owners never open: how it speaks, push-backs, how it ends and an example call.
 *
 * Progressive disclosure split by what owners change (NN/g, "Progressive Disclosure": the
 * options most people need up front, the rest one clearly labelled step away, never more
 * than two levels). Who it is, the goal and what it may do are shown as their fields, in
 * full, because they decide every call and are short. The other four sit together behind
 * one "More settings" row naming what is inside, the way voice-agent builders keep speech
 * and pronunciation under one "More settings" area (Retell, configure-basic-settings).
 * One row rather than a row each: seven identical "Show" rows, each with its value cut off,
 * made every part look equally important and none readable.
 *
 * The folded parts are a native `<details>` (the kit's `Disclosure`): the forms stay in the
 * document while closed, so the screen assistant's fills, the page's find and a link to a
 * part's anchor (`#objections`, which opens the row) all keep working. A part with
 * something to finish says so on the closed row, so nothing that holds the autosave is
 * hidden.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { DISCLOSURE_LIST, Disclosure } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import { useBusinessProfile } from "@/lib/api/businessProfile";
import type { CallScript, ScriptContext } from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";
import { goAheadLabel, quotesPrices, useBusinessCapabilities } from "@/lib/businessCapabilities";
import { lookup } from "@/lib/lookup";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

import {
  EndingSection,
  ExampleSection,
  GoalSection,
  IdentitySection,
  ObjectionsSection,
  PoliciesSection,
  StyleSection,
} from "./ScriptSections";
import type { Issue } from "./scriptModel";

/** The anchors a part answers to, and the whole-script issue fields that belong to it. */
export const PART_ISSUES: Record<string, (field: string) => boolean> = {
  identity: (f) => f === "business_line",
  style: (f) => f.startsWith("pronunciation-"),
  objections: (f) => f.startsWith("objection-"),
  example: (f) => f.startsWith("example-"),
};

/** The parts behind "More settings", in the order they are shown. */
export const FOLDED_PARTS = ["style", "objections", "ending", "example"] as const;

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function ScriptParts({
  script,
  context,
  issues,
  openPart,
  knowledgeHref,
  setField,
  edit,
}: {
  script: CallScript;
  context: ScriptContext | null;
  issues: Issue[];
  /** The part to open on arrival, from the address's `#anchor`. */
  openPart: string | null;
  knowledgeHref: string;
  setField: <K extends keyof CallScript>(key: K, value: CallScript[K]) => void;
  edit: (next: (s: CallScript) => CallScript) => void;
}) {
  const eg = useVerticalExamples();
  const caps = useBusinessCapabilities();
  const profile = useBusinessProfile(useClientSession());
  const offers = {
    prices: quotesPrices(caps, profile.data?.wording.price_label),
    goAhead: goAheadLabel(caps),
  };
  const ownObjection = caps.objections[0];
  const objectionExample = ownObjection
    ? { says: ownObjection.caller_says, answer: ownObjection.how_to_answer }
    : undefined;
  const issuesOf = (id: string) => {
    const owns = lookup(PART_ISSUES, id);
    return owns ? issues.filter((i) => i.section === null && owns(i.field)) : [];
  };
  const foldedToFinish = FOLDED_PARTS.reduce((n, id) => n + issuesOf(id).length, 0);
  const exampleToCheck = script.example_needs_review && script.example_exchange.length > 0;

  const part = (id: string, title: string, body: ReactNode) => (
    <div key={id} className="space-y-2 border-t border-line pt-5 first:border-t-0 first:pt-0">
      <h5 className="text-body font-semibold text-ink">{title}</h5>
      {body}
    </div>
  );

  return (
    <section aria-labelledby="parts-heading" className="space-y-5">
      <h3 id="parts-heading" className="text-heading text-ink">
        About the agent
      </h3>

      <div className="space-y-4">
        <IdentitySection script={script} set={setField} eg={eg} />
        {issuesOf("identity").map((issue) => (
          <p key={issue.field} className="text-meta text-danger">
            {issue.message}
          </p>
        ))}
        <GoalSection script={script} set={setField} eg={eg} />
      </div>

      <div className="space-y-2">
        <h4 className="text-body font-semibold text-ink">What it may do</h4>
        <PoliciesSection
          policies={script.policies}
          onChange={(v) => setField("policies", v)}
          context={context}
          offers={offers}
        />
      </div>

      <div className={DISCLOSURE_LIST}>
        <Disclosure
          variant="row"
          headingLevel={4}
          title="More settings"
          defaultOpen={openPart !== null && (FOLDED_PARTS as readonly string[]).includes(openPart)}
          subtitle="How it speaks, push-backs, how it ends the call and an example call."
          status={
            foldedToFinish > 0 ? (
              <span className="font-medium text-danger">{plural(foldedToFinish, "part", "parts")} to finish</span>
            ) : exampleToCheck ? (
              "Example to check"
            ) : undefined
          }
        >
          <div className="space-y-6 text-ink">
            {part(
              "style",
              "How it speaks",
              <StyleSection style={script.style} onChange={(v) => setField("style", v)} context={context} eg={eg} />,
            )}
            {part(
              "objections",
              "When callers push back",
              <ObjectionsSection
                objections={script.objections}
                onChange={(v) => setField("objections", v)}
                example={objectionExample}
              />,
            )}
            {part(
              "ending",
              "How it ends the call",
              <EndingSection value={script.ending} onChange={(v) => setField("ending", v)} eg={eg} />,
            )}
            {part(
              "example",
              "An example call",
              <ExampleSection
                lines={script.example_exchange}
                needsReview={script.example_needs_review}
                onChange={(lines, stillNeedsReview) =>
                  edit((s) => ({ ...s, example_exchange: lines, example_needs_review: stillNeedsReview }))
                }
              />,
            )}
          </div>
        </Disclosure>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <h4 className="text-body font-semibold text-ink">Quick facts</h4>
          <p className="text-meta text-ink-muted">
            {offers.prices ? "Prices and timings" : "Timings and answers"}, shared by all your agents.
          </p>
        </div>
        <Link href={knowledgeHref} className={TEXT_ACTION}>
          Open What your agents know
        </Link>
      </div>
    </section>
  );
}
