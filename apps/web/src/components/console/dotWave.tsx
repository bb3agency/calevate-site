"use client";

// The dot wave is adapted from interior.dev's typing-indicator (github.com/ddoemonn/interior
// @3148000, MIT License, Copyright (c) 2026 ozzy; notice in components/interior/LICENSE).
// Only the wave is taken.

import { useEffect } from "react";
import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type MotionValue,
} from "motion/react";

/** One full pass of the wave across three dots. */
const WAVE_S = 1.1;

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

/** The three-dot wave, still under reduced motion: the assistant's "thinking" mark. */
export function DotWave({ active }: { active: boolean }) {
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
    // Still dots under reduced motion: the surrounding text carries the state.
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
