"use client";

import { Lightbulb } from "lucide-react";

import { formatWorkTime, type ThoughtEntry } from "@/lib/copilot/liveEvents";

import { RowHead, TimelineRow } from "./TimelineRow";

/** How much of the end of a live thought is drawn fading, so the newest words read as arriving. */
const TAIL = 14;

/**
 * Pip's thinking for one model turn. While it is the turn in progress it reads "Thinking"
 * with the text arriving under it, newest words fading in at the end; once Pip moves on to
 * a lookup or the answer it folds to "Thought for 3s", which opens to the whole text.
 *
 * The text is not announced: a screen reader would hear every fragment. The answer is.
 */
export function ThoughtRow({
  thought,
  live,
  reduced,
  arrived,
}: {
  thought: ThoughtEntry;
  /** This is the open turn of a run that is still going. */
  live: boolean;
  /** The reader asked for less motion: no sweep across the label, no fading tail. */
  reduced: boolean;
  arrived: boolean;
}) {
  const icon = <Lightbulb aria-hidden className="h-3.5 w-3.5" />;
  if (live) {
    const head = thought.text.slice(0, Math.max(0, thought.text.length - TAIL));
    const tail = thought.text.slice(head.length);
    return (
      <TimelineRow icon={icon} arrived={arrived}>
        <p className="flex min-h-[1.625rem] items-center text-meta text-ink touch:min-h-11">
          <span className={reduced ? undefined : "text-shimmer"}>Thinking</span>
        </p>
        {/* The latest lines only, anchored to the bottom, older ones fading out at the top. */}
        <div
          data-testid="thought-live"
          className="flex max-h-[4.5rem] flex-col justify-end overflow-hidden text-meta whitespace-pre-wrap text-ink-muted [mask-image:linear-gradient(to_bottom,transparent,black_1.25rem)]"
        >
          <p className="break-words">
            {head}
            {reduced ? tail : <span className="opacity-50">{tail}</span>}
          </p>
        </div>
      </TimelineRow>
    );
  }
  const took = formatWorkTime(Math.max(1000, (thought.endedAt ?? thought.startedAt) - thought.startedAt));
  return (
    <TimelineRow icon={icon} arrived={arrived}>
      <RowHead
        label={`Thought for ${took}`}
        body={<p className="text-meta whitespace-pre-wrap break-words">{thought.text}</p>}
      />
    </TimelineRow>
  );
}
