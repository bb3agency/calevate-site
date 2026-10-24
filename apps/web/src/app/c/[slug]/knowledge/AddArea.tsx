"use client";

import { useEffect, useState } from "react";

import { SegmentedControl } from "@/components/interior/segmented-control";

import { AddFile, AddLink } from "./AddDocument";
import { TeachBox } from "./TeachBox";
import { SubmissionConsequence } from "./permissions";

type Mode = "write" | "file" | "link";

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
 */
export function AddArea({
  allowed,
  reason,
  answering,
}: {
  allowed: boolean;
  reason: string | null;
  /** Set by "Add the answer" on a question the agents could not answer. */
  answering: { gapId: string | null; question: string; key: number } | null;
}) {
  const [mode, setMode] = useState<Mode>("write");

  // Answering a caller's question is writing: bring the box back before it takes focus.
  useEffect(() => {
    if (answering) setMode("write");
  }, [answering]);

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
          <p className="mt-1 text-meta text-ink-muted">
            Every one of your agents shares what you add here.
          </p>
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
        <div hidden={mode !== "write"}>
          <TeachBox allowed={allowed} reason={reason} answering={answering} framed={false} />
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
