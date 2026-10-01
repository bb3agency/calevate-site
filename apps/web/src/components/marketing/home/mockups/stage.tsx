"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { useMotion } from "@/components/marketing/motion";

/**
 * The wrapper every below-the-fold mockup sits in. It owns the two attributes the
 * `.mk-rise` / `.mk-eq` rules in `globals.css` read, and renders nothing else.
 *
 * An IntersectionObserver rather than a GSAP ScrollTrigger: the entrance is a CSS
 * animation (off the main thread, finished without the bundle), so all this needs is a
 * yes/no on visibility. ScrollTrigger would add a scroll listener per mockup to answer it.
 *
 * Attributes are written to the DOM directly rather than through state: they change no
 * markup React renders, and a re-render per scroll crossing would be work for nothing.
 */
export function MockStage({
  children,
  className = "",
  label,
}: {
  children: ReactNode;
  className?: string;
  /**
   * A mockup that carries meaning gets a short name and is exposed as one image; one that
   * only decorates a sentence beside it is hidden from assistive technology entirely.
   */
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { reduced } = useMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;

    // Only a mockup the reader cannot see yet is hidden for its entrance. One already on
    // screen at hydration stays as painted: hiding it to replay it reads as a flicker.
    const box = el.getBoundingClientRect();
    const onScreen = box.top < window.innerHeight && box.bottom > 0;
    if (!reduced && !onScreen && el.dataset.stage === undefined) {
      el.dataset.stage = "pending";
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        if (entry.isIntersecting) delete el.dataset.offscreen;
        else el.dataset.offscreen = "";
        // A fifth of the figure in view: early enough that the stagger has finished by the
        // time the reader's eye arrives, late enough that it is not spent below the fold.
        if (entry.intersectionRatio >= 0.2 && el.dataset.stage === "pending") {
          el.dataset.stage = "in";
        }
      },
      { threshold: [0, 0.2] },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [reduced]);

  return (
    <div
      ref={ref}
      className={className}
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
    >
      {children}
    </div>
  );
}
