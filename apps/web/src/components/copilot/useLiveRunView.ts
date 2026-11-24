"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { draftWaiting } from "@/lib/copilot/liveEvents";
import { useNow } from "@/lib/copilot/useNow";
import type { CopilotConversation } from "@/lib/copilot/useCopilotConversation";

import type { RunHeaderState } from "./RunHeader";

/**
 * What the panel's live header shows, and where focus goes when it changes.
 *
 * - Working: the run said its id and is still answering; the header counts from its start.
 * - Waiting for you: the answer is in and a suggestion or a written script waits on a
 *   decision; the header counts from when the wait began.
 *
 * Focus moves only into a vacuum: when Stop (or the run's last control) has gone and focus
 * fell to the page, it goes back to the ask box; when a suggestion starts waiting and
 * nothing holds focus, it goes to the header so the next Tab reaches the choice. A person
 * typing keeps their caret.
 */
export function useLiveRunView(
  conversation: Pick<CopilotConversation, "live" | "asking" | "proposal">,
  panel: RefObject<HTMLElement | null>,
) {
  const { live, asking, proposal } = conversation;
  const running = asking && live.runId !== null;
  const [decided, setDecided] = useState<string | null>(null);
  const offerWaiting = !asking && proposal !== null && decided !== proposal.token;
  const waiting = !asking && (offerWaiting || draftWaiting(live.drafts));
  const [waitingSince, setWaitingSince] = useState<number | null>(null);
  useEffect(() => setWaitingSince(waiting ? Date.now() : null), [waiting]);
  const now = useNow(running || waiting);
  const header = useRef<HTMLHeadingElement>(null);

  const wasRunning = useRef(false);
  useEffect(() => {
    const ended = wasRunning.current && !running;
    wasRunning.current = running;
    if (!ended) return;
    const active = document.activeElement;
    if (active === null || active === document.body) {
      panel.current?.querySelector("textarea")?.focus({ preventScroll: true });
    }
  }, [running, panel]);

  useEffect(() => {
    if (!offerWaiting) return;
    const active = document.activeElement;
    if (active === null || active === document.body) header.current?.focus({ preventScroll: true });
  }, [offerWaiting]);

  const state: RunHeaderState | null = running
    ? live.phase === "stopping"
      ? "stopping"
      : "working"
    : waiting
      ? "waiting"
      : null;
  const since = running ? (live.startedAt ?? now) : (waitingSince ?? now);
  /** The suggestion was confirmed or refused: it no longer waits. */
  const decide = useCallback((token: string) => setDecided(token), []);
  return { running, state, since, now, header, decide };
}
