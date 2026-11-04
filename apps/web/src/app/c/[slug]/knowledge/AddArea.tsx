"use client";

import { useState } from "react";

import { SegmentedControl } from "@/components/interior/segmented-control";
import { RestrictionNote } from "@/components/ui";
import { useBusinessProfile } from "@/lib/api/businessProfile";
import { useClientSession } from "@/lib/api/session";
import { isTeachingBusy, useOpenTeaching } from "@/lib/api/teach";

import { AddFile, AddLink } from "./AddDocument";
import { AddToProfile, offerChoiceLabel, useProfileWrite } from "./ProfileKnowledge";
import { TeachBox } from "./TeachBox";
import { SubmissionConsequence } from "./permissions";

type Mode = "write" | "file" | "link";
/** What is being written. The first two go into the business profile, their one home. */
type Kind = "offer" | "question" | "other";

const MODES: { value: Mode; label: string }[] = [
  { value: "write", label: "Write it" },
  { value: "file", label: "File" },
  { value: "link", label: "Link" },
];

/**
 * THE ONE ADD AREA (D-874): a fact or an answer, a file, or a link, in one card at the top
 * of the page, so "where do I add things" has one answer.
 *
 * A segmented switch rather than three stacked forms: each way has its own explanation
 * (what reaches the agents, what does not yet), and three at once is a wall of text on a
 * phone. Writing is first because it is the way that always works and the quickest way to
 * correct one fact.
 *
 * Writing asks what it is first (D-968). Something the business offers and a question with
 * its answer are saved straight into the business profile, the one place both screens read;
 * the owner says which rather than the words being guessed at. Anything else goes to the
 * teach box.
 */
export function AddArea({ allowed, reason }: { allowed: boolean; reason: string | null }) {
  const session = useClientSession();
  const profile = useBusinessProfile(session);
  const profileWrite = useProfileWrite();
  const [mode, setMode] = useState<Mode>("write");
  const teaching = useOpenTeaching(session);
  // A teaching waiting for its review (or still being sorted) opens on the teach box, so
  // it is never hidden behind a choice the owner did not make.
  const status = teaching.data?.status;
  const reviewing = status === "ready" || isTeachingBusy(status);
  const [chosen, setKind] = useState<Kind | null>(null);
  const kind: Kind = chosen ?? (reviewing ? "other" : "offer");

  const kinds: { value: Kind; label: string }[] = [
    { value: "offer", label: profile.data ? offerChoiceLabel(profile.data.wording) : "What you offer" },
    { value: "question", label: "Question and answer" },
    { value: "other", label: "Something else" },
  ];

  return (
    <section
      aria-labelledby="kb-add-heading"
      className="rounded-card border border-line bg-surface p-4 shadow-card sm:p-5"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 id="kb-add-heading" className="text-heading text-ink">
            Add something
          </h2>
        </div>
        <SegmentedControl
          label="What are you adding?"
          options={MODES}
          value={mode}
          onValueChange={(next) => setMode(next as Mode)}
          className="w-full sm:w-72 sm:shrink-0"
        />
      </div>

      {/* All three stay mounted and the others are hidden, so switching never throws away
          half-typed words or an upload that is still sending. */}
      <div className="mt-4">
        <div hidden={mode !== "write"} className="space-y-4">
          <SegmentedControl
            label="What is it?"
            options={kinds}
            value={kind}
            onValueChange={(next) => setKind(next as Kind)}
            className="w-full sm:w-auto"
          />
          {kind !== "other" ? <RestrictionNote reason={profileWrite.reason} /> : null}
          <div hidden={kind !== "offer"}>
            <AddToProfile kind="offer" allowed={profileWrite.allowed} />
          </div>
          <div hidden={kind !== "question"}>
            <AddToProfile kind="question" allowed={profileWrite.allowed} />
          </div>
          <div hidden={kind !== "other"}>
            <TeachBox allowed={allowed} reason={reason} framed={false} />
          </div>
        </div>
        <div hidden={mode !== "file"}>
          <AddFile allowed={allowed} />
        </div>
        <div hidden={mode !== "link"}>
          <AddLink allowed={allowed} reason={reason} />
        </div>
      </div>

      <div className="mt-4 border-t border-line pt-3">
        <SubmissionConsequence />
      </div>
    </section>
  );
}
