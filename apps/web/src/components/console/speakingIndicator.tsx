"use client";

// The dot wave is adapted from interior.dev's typing-indicator (github.com/ddoemonn/interior
// @3148000, MIT License, Copyright (c) 2026 ozzy; notice in components/interior/LICENSE).
// Only the wave is taken: upstream draws one bubble for everyone, labels it "is typing" and
// announces every change, none of which fits two parties on a phone call.

import { useEffect, useRef, useState } from "react";
import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type MotionValue,
} from "motion/react";

export type Speaker = "caller" | "agent";

/** One full pass of the wave across three dots. */
const WAVE_S = 1.1;
/**
 * How long a side stays marked after its speech stops. Voice activity flickers between
 * words; without a short hold the mark would blink on every pause.
 */
export const SPEAKER_HOLD_MS = 400;

function Dot({ index, wave }: { index: number; wave: MotionValue<number> }) {
  const lift = useTransform(wave, (w) => {
    let distance = (w - index) % 3;
    if (distance < 0) distance += 3;
    if (distance > 1.5) distance -= 3;
    return Math.max(0, 1 - Math.abs(distance));
  });
  const scale = useTransform(lift, [0, 1], [0.7, 1]);
  const opacity = useTransform(lift, [0, 1], [0.35, 1]);
  return <motion.span className="block h-1.5 w-1.5 rounded-full bg-current" style={{ scale, opacity }} />;
}

function Wave({ active }: { active: boolean }) {
  const reduced = useReducedMotion();
  const wave = useMotionValue(0);
  useEffect(() => {
    if (!active || reduced) {
      wave.jump(0);
      return;
    }
    const controls = animate(wave, 3, {
      duration: WAVE_S,
      ease: "linear",
      repeat: Infinity,
      repeatType: "loop",
    });
    return () => controls.stop();
  }, [active, reduced, wave]);
  if (!active || reduced) {
    // Still dots: under reduced motion the "Speaking" word and the outline carry it.
    return (
      <span className={`flex items-center gap-1 ${active ? "" : "opacity-30"}`}>
        {[0, 1, 2].map((i) => (
          <span key={i} className="block h-1.5 w-1.5 rounded-full bg-current" />
        ))}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1">
      {[0, 1, 2].map((i) => (
        <Dot key={i} index={i} wave={wave} />
      ))}
    </span>
  );
}

/** The speaker on screen: follows `speaker`, but holds the last side for a moment. */
function useHeldSpeaker(speaker: Speaker | null): Speaker | null {
  const [shown, setShown] = useState<Speaker | null>(speaker);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (speaker !== null) {
      setShown(speaker);
      return;
    }
    timer.current = setTimeout(() => setShown(null), SPEAKER_HOLD_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [speaker]);
  return shown;
}

/**
 * WHO IS SPEAKING ON A LIVE CALL — caller on the left, agent on the right, the side that
 * is talking marked with a moving dot wave, an outline and the word "Speaking".
 *
 * HIDDEN FROM ASSISTIVE TECHNOLOGY ON PURPOSE. Turns change every few seconds; announcing
 * each one would talk over whatever the reader is doing. What a screen reader should hear
 * is what was SAID, which belongs in a `role="log"` transcript, not who holds the floor.
 *
 * `speaker` is the whole interface: `null` means nobody is speaking or the live signal is
 * not available, and both sides render at rest.
 */
export function SpeakingIndicator({
  speaker,
  labels = { caller: "Caller", agent: "Agent" },
  className = "",
}: {
  speaker: Speaker | null;
  labels?: { caller: string; agent: string };
  className?: string;
}) {
  const shown = useHeldSpeaker(speaker);
  const side = (who: Speaker) => {
    const active = shown === who;
    const tone =
      who === "agent"
        ? active
          ? "border-brand/50 bg-brand-soft text-brand-strong"
          : "border-line text-ink-faint"
        : active
          ? "border-ink/30 bg-ink/[0.04] text-ink"
          : "border-line text-ink-faint";
    return (
      <div
        className={`flex min-w-0 items-center gap-3 rounded-[10px] border px-3 py-2.5 transition-colors duration-(--duration-fast) ease-out ${tone} ${
          who === "agent" ? "flex-row-reverse text-right" : ""
        }`}
      >
        <Wave active={active} />
        <span className="min-w-0">
          <span className="block truncate text-[13px] font-medium text-ink">{labels[who]}</span>
          <span className="block text-[11px]">{active ? "Speaking" : " "}</span>
        </span>
      </div>
    );
  };
  return (
    <div aria-hidden className={`grid grid-cols-2 gap-2 ${className}`}>
      {side("caller")}
      {side("agent")}
    </div>
  );
}
