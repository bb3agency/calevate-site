"use client";

/**
 * THE REST OF THE SCRIPT, AS A SUMMARY LIST — who the agent is, the goal, how it speaks,
 * push-backs, what it may do, how it ends and an example call.
 *
 * These are set once and changed rarely, while the opening line and the steps are what an
 * owner comes back to edit. So each part is one row saying what it holds now ("2 answers",
 * "Not written yet", "1 to finish") that opens its form in place: the GOV.UK summary-list
 * shape, with the change happening on the row rather than on another page, and NN/g's
 * progressive disclosure (frequent things up front, the rest one obvious click away, two
 * levels at most). A part with something to finish says so on its closed row, so nothing
 * that holds the autosave is hidden.
 *
 * The rows are native `<details>` (the kit's inline `Disclosure`): the forms stay in the
 * document while closed, so the screen assistant's fills, the page's find and a link to a
 * part's anchor (`#policies`, which opens its row) all keep working.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { Disclosure } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import type { CallScript, ScriptContext } from "@/lib/api/script";
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

const CODE_MIX_WORDS: Record<string, string> = {
  light: "mostly local words",
  natural: "an everyday mix of English",
  heavy: "lots of English",
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What one row says while it is closed. */
export function partSummaries(script: CallScript, context: ScriptContext | null): Record<string, string> {
  const none = "Not written yet";
  const style = script.style;
  const policies = script.policies;
  const trial = context !== null && !context.call_backs_available;
  const names = style.pronunciations.length;
  const lines = script.example_exchange.length;
  return {
    identity: script.business_line.trim() || script.identity.trim() || none,
    goal: script.goal.trim() || none,
    style:
      [
        style.tone.trim(),
        CODE_MIX_WORDS[style.code_mix] ?? "",
        names ? plural(names, "name", "names") : "",
      ]
        .filter(Boolean)
        .join(" · ") || none,
    objections: script.objections.length ? plural(script.objections.length, "answer", "answers") : "None yet",
    policies: [
      policies.offer_call_backs && !trial ? "Offers call backs" : "No call backs",
      policies.share_prices ? "tells prices" : "no prices",
      policies.take_bookings ? "takes bookings" : "no bookings",
    ].join(" · "),
    ending: script.ending.trim() || none,
    example: lines
      ? `${plural(lines, "line", "lines")}${script.example_needs_review ? " · waiting for a native speaker" : ""}`
      : "None yet",
  };
}

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
  const said = partSummaries(script, context);
  const eg = useVerticalExamples();
  const toFinish = (id: string) => {
    const owns = lookup(PART_ISSUES, id);
    return owns ? issues.filter((i) => i.section === null && owns(i.field)).length : 0;
  };

  const row = (id: string, title: string, body: ReactNode) => {
    const finish = toFinish(id);
    return (
      <Disclosure
        key={id}
        variant="inline"
        headingLevel={4}
        title={title}
        defaultOpen={openPart === id}
        subtitle={
          <span className="block truncate text-meta">
            {finish > 0 ? (
              <span className="font-medium text-danger">{plural(finish, "part", "parts")} to finish · </span>
            ) : null}
            {said[id]}
          </span>
        }
      >
        <div className="pt-1 text-ink">{body}</div>
      </Disclosure>
    );
  };

  return (
    <section aria-labelledby="parts-heading" className="space-y-2">
      <h3 id="parts-heading" className="text-heading text-ink">
        About the agent
      </h3>
      <div className="border-y border-line">
        {row("identity", "Who it is", <IdentitySection script={script} set={setField} eg={eg} />)}
        {row(
          "goal",
          "What a good call achieves",
          <GoalSection
            script={script}
            set={setField}
            eg={eg}
           
          />,
        )}
        {row(
          "style",
          "How it speaks",
          <StyleSection
            style={script.style}
            onChange={(v) => setField("style", v)}
            context={context}
            eg={eg}
           
          />,
        )}
        {row(
          "objections",
          "When callers push back",
          <ObjectionsSection objections={script.objections} onChange={(v) => setField("objections", v)} />,
        )}
        {row(
          "policies",
          "What it may do",
          <PoliciesSection policies={script.policies} onChange={(v) => setField("policies", v)} context={context} />,
        )}
        {row("ending", "How it ends the call", <EndingSection value={script.ending} onChange={(v) => setField("ending", v)} eg={eg} />)}
        {row(
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
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
          <div className="min-w-0">
            <h4 className="text-body font-medium text-ink">Quick facts</h4>
            <p className="text-meta text-ink-muted">Prices and timings, shared by all your agents.</p>
          </div>
          <Link href={knowledgeHref} className={TEXT_ACTION}>
            Open Knowledge
          </Link>
        </div>
      </div>
    </section>
  );
}
