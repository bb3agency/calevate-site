"use client";

import { useId, useState, type ComponentType } from "react";
import { FileUp, Link2, MessageCircleQuestion, MessageSquareText, Tag } from "lucide-react";

import { RestrictionNote } from "@/components/ui";
import { useBusinessProfile } from "@/lib/api/businessProfile";
import { useClientSession } from "@/lib/api/session";
import { isTeachingBusy, useOpenTeaching } from "@/lib/api/teach";

import { AddFile, AddLink } from "./AddDocument";
import { AddToProfile, offerChoiceLabel, useProfileWrite } from "./ProfileKnowledge";
import { TeachBox } from "./TeachBox";
import { SubmissionConsequence } from "./permissions";

/** The ways to teach. An offer and a question go into the business profile, their one home. */
type Way = "say" | "offer" | "question" | "file" | "link";

const ICONS: Record<Way, ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  say: MessageSquareText,
  offer: Tag,
  question: MessageCircleQuestion,
  file: FileUp,
  link: Link2,
};

/**
 * TEACH YOUR AGENTS: the one card for telling the agents something, on the knowledge page
 * and in an agent's Training tab alike, so an owner learns one way to teach (D-874).
 *
 * One row of five choices rather than the two stacked switches it replaced ("Write it /
 * File / Link", then "Service / Question / Something else" under the first): the nested pair
 * made the owner choose a channel before saying what they had, and hid two of the five ways
 * behind the first choice. The owner still says what it is (D-968): an offer or a question
 * is saved straight into the business profile rather than the words being guessed at.
 *
 * "Type or say it" comes first because it is the way that always works, takes a voice note,
 * and is where a teaching waiting for review is shown, so that review is never hidden
 * behind a choice the owner did not make. Every way stays mounted and the others are
 * hidden, so switching never throws away half-typed words or an upload still sending.
 */
export function AddArea({
  allowed,
  reason,
  headingLevel = 2,
}: {
  allowed: boolean;
  reason: string | null;
  /** 3 inside an agent's Training tab, whose tab label is the h2. */
  headingLevel?: 2 | 3;
}) {
  const session = useClientSession();
  const profile = useBusinessProfile(session);
  const profileWrite = useProfileWrite();
  const teaching = useOpenTeaching(session);
  const status = teaching.data?.status;
  const reviewing = status === "ready" || isTeachingBusy(status);
  const [chosen, setChosen] = useState<Way>("say");
  // A teaching Pip sorted (from typed words or a file it read) is reviewed in "Type or say
  // it", so its arrival brings that way forward once; the owner may still switch away.
  const arrived = reviewing ? teaching.data?.id : undefined;
  const [shownFor, setShownFor] = useState<string | undefined>(undefined);
  if (arrived && arrived !== shownFor) {
    setShownFor(arrived);
    setChosen("say");
  }
  const way = chosen;
  const headingId = useId();
  const Heading = headingLevel === 3 ? "h3" : "h2";

  const ways: { value: Way; label: string }[] = [
    { value: "say", label: "Type or say it" },
    { value: "offer", label: profile.data ? offerChoiceLabel(profile.data.wording) : "What you offer" },
    { value: "question", label: "Question and answer" },
    { value: "file", label: "Photo or file" },
    { value: "link", label: "Website link" },
  ];

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-card border border-line bg-surface p-4 shadow-card sm:p-6"
    >
      <Heading id={headingId} className="text-heading text-ink">
        Teach your agents
      </Heading>
      <p className="mt-1 text-body text-ink-muted">Anything you would tell a new member of staff.</p>

      <div
        role="radiogroup"
        aria-label="What do you want to add?"
        // Two columns on a phone with the always-works way across the top, so five choices
        // read as a tidy block rather than a ragged wrap; one row from `sm` up.
        className="mt-4 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap"
      >
        {ways.map(({ value, label }) => {
          const Icon = ICONS[value];
          const on = way === value;
          return (
            <label
              key={value}
              className={`press relative flex min-w-0 cursor-pointer items-center gap-2 rounded-xl border px-3 py-2.5 text-left text-sm font-medium leading-tight first:col-span-2 sm:rounded-full sm:px-3.5 sm:py-2 transition-colors duration-(--duration-fast) ease-out has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand has-[:focus-visible]:ring-offset-2 touch:min-h-11 ${
                on
                  ? "border-brand-strong bg-brand-soft text-brand-strong"
                  : "border-line bg-surface text-ink hover:bg-ink/[0.04]"
              }`}
            >
              <input
                type="radio"
                name={headingId}
                value={value}
                checked={on}
                onChange={() => setChosen(value)}
                className="sr-only"
              />
              <Icon aria-hidden className={`h-4 w-4 shrink-0 ${on ? "text-brand-strong" : "text-ink-muted"}`} />
              {label}
            </label>
          );
        })}
      </div>

      <div className="mt-5">
        <div hidden={way !== "say"}>
          <TeachBox allowed={allowed} reason={reason} />
        </div>
        <div hidden={way !== "offer"} className="space-y-3">
          <RestrictionNote reason={profileWrite.reason} />
          <AddToProfile kind="offer" allowed={profileWrite.allowed} />
        </div>
        <div hidden={way !== "question"} className="space-y-3">
          <RestrictionNote reason={profileWrite.reason} />
          <AddToProfile kind="question" allowed={profileWrite.allowed} />
        </div>
        <div hidden={way !== "file"}>
          <AddFile allowed={allowed} />
        </div>
        <div hidden={way !== "link"}>
          <AddLink allowed={allowed} reason={reason} />
        </div>
      </div>

      <div className="mt-5 border-t border-line pt-3">
        <SubmissionConsequence />
      </div>
    </section>
  );
}
