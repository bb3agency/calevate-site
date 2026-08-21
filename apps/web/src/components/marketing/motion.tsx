"use client";

/**
 * Smooth scrolling and scroll-triggered reveals for the marketing pages (D-161).
 *
 * ## Why this is one file and one provider
 *
 * Lenis and GSAP both want to own a `requestAnimationFrame` loop, and running two is the
 * documented way to get scroll animations that judder: two loops means two clocks, and
 * ScrollTrigger reads a scroll position Lenis has not finished interpolating. The
 * official integration is to give GSAP the only ticker and drive Lenis from it —
 * `lenis.on("scroll", ScrollTrigger.update)`, `gsap.ticker.add(t => lenis.raf(t * 1000))`
 * (seconds to milliseconds), and `gsap.ticker.lagSmoothing(0)` so GSAP does not silently
 * absorb a dropped frame and desynchronise the two.
 *
 * ## MOTION IS AN ENHANCEMENT, AND THE PAGE IS FINISHED WITHOUT IT
 *
 * Everything here degrades to a completely readable static page. That is a hard
 * requirement rather than a courtesy, and it is enforced in three places:
 *
 * 1. **Content is visible by default.** `Reveal` renders a plain element and GSAP
 *    animates FROM a displaced state. The common alternative — `opacity: 0` in CSS,
 *    animated to 1 — ships a page that is permanently blank if the bundle fails to load,
 *    is blocked, or is rendered by something that does not execute scripts.
 * 2. **`prefers-reduced-motion` is honoured and is not a lesser experience.** Lenis is
 *    never constructed and every reveal resolves instantly to its resting state. The
 *    reader gets the same page, immediately.
 * 3. **`useGSAP` owns cleanup.** It wraps everything in a `gsap.context()` and reverts on
 *    unmount, which is what stops a ScrollTrigger surviving a client-side route change
 *    and holding a scroll listener against a DOM node that no longer exists.
 *
 * ## Bundle cost is confined to this route
 *
 * `gsap` and `lenis` are imported only by client components under `components/marketing`,
 * which nothing under `/c` or `/admin` imports — so Next's route-level code splitting
 * keeps all three packages out of the dashboard bundles. Worth stating because the
 * dashboard is the surface a client uses every day and the marketing page is the one
 * they see once.
 */

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

gsap.registerPlugin(useGSAP, ScrollTrigger);

/**
 * Does this reader want motion at all?
 *
 * Read as STATE rather than at module scope, because the media query can change while
 * the page is open (a reader turning the OS setting on mid-visit is exactly the person
 * this must respond to) and because a module-scope read runs during SSR where
 * `matchMedia` does not exist.
 *
 * The initial value is `true` — "reduce" — on purpose. It flips to false only after the
 * effect has actually asked. Guessing the other way would start an animation on the
 * first frame for someone who asked for none.
 */
function usePrefersReducedMotion(): boolean {
  /**
   * READ SYNCHRONOUSLY ON THE FIRST CLIENT RENDER, and this is the whole entry-animation
   * glitch rather than a micro-optimisation.
   *
   * It used to initialise to `true` and correct itself in an effect. `true` is the right
   * DEFAULT — never animate until asked — but as an initial STATE it made the hero animate
   * one render too late: hydration ran `useGSAP` with motion off, the effect then flipped
   * `reduced` to false, and because `reduced` is a `useGSAP` dependency the hook re-ran and
   * only THEN called `gsap.from()`. So the browser painted the finished hero, and a tick
   * later GSAP pulled it back to opacity 0 and animated it in — the page appearing, then
   * appearing again. Exactly what it looked like.
   *
   * The lazy initialiser runs during the first client render, before any paint of the
   * hydrated tree, so `useGSAP` fires once with the real answer. `typeof window` guards the
   * server, where the answer is unknowable and `true` is the safe one; it cannot cause a
   * hydration mismatch because nothing here renders markup — `reduced` is read only by
   * effects.
   */
  const [reduced, setReduced] = useState(
    () => typeof window === "undefined" || window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduced(query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);

  return reduced;
}

const MotionContext = createContext<{ reduced: boolean }>({ reduced: true });

/** Whether this subtree should animate. Consumed by `Reveal` and the hero. */
export function useMotion(): { reduced: boolean } {
  return useContext(MotionContext);
}

/**
 * Installs Lenis and the shared ticker for its subtree.
 *
 * Rendered once, by the marketing layout. It renders nothing of its own beyond a
 * context — the scroller is the document, so there is no wrapper element to introduce
 * and no extra stacking context to reason about later.
 */
export function SmoothScroll({ children }: { children: ReactNode }) {
  const reduced = usePrefersReducedMotion();
  const value = useMemo(() => ({ reduced }), [reduced]);

  useEffect(() => {
    if (reduced) return;

    const lenis = new Lenis({
      // Slightly longer than the 1.0 default: the page is a reading surface rather than
      // a showcase, and a heavier glide makes the long compliance section feel slow to
      // get through. Measured by scrolling it, not chosen from a blog post.
      duration: 1.05,
      // Touch devices already have native inertia that feels correct and is tuned per
      // platform. Overriding it is the single most common way smooth-scroll libraries
      // make phones worse, so Lenis handles the wheel and leaves touch alone.
      smoothWheel: true,
      syncTouch: false,
    });

    lenis.on("scroll", ScrollTrigger.update);

    const raf = (time: number) => {
      // GSAP's ticker reports seconds; Lenis wants milliseconds.
      lenis.raf(time * 1000);
    };
    gsap.ticker.add(raf);
    // Without this, GSAP "catches up" after a stalled frame by fabricating time, which
    // pushes Lenis past where the reader actually is.
    gsap.ticker.lagSmoothing(0);

    return () => {
      gsap.ticker.remove(raf);
      gsap.ticker.lagSmoothing(500, 33); // GSAP's own defaults, restored.
      lenis.destroy();
      // A destroyed scroller leaves every ScrollTrigger holding stale start/end pixel
      // values. Refreshing is cheaper than the alternative bug: sections that never
      // reveal after a route change back.
      ScrollTrigger.refresh();
    };
  }, [reduced]);

  return <MotionContext.Provider value={value}>{children}</MotionContext.Provider>;
}

/**
 * One scroll-triggered reveal. Children are laid out normally and animated FROM below.
 *
 * `as` keeps the markup semantic: a reveal wrapping a section must not turn it into a
 * `div` and cost the page its landmark, which is also what the axe sweep would object to.
 */
export function Reveal({
  children,
  className,
  delay = 0,
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  as?: "div" | "section" | "li" | "header" | "footer";
}) {
  const { reduced } = useMotion();
  const scope = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      if (reduced) return;
      gsap.from(scope.current, {
        opacity: 0,
        y: 24,
        duration: 0.7,
        delay,
        ease: "power2.out",
        scrollTrigger: {
          trigger: scope.current,
          // Fires when the element's top passes 88% of the viewport height — early
          // enough that the motion is finished by the time it is comfortably read.
          start: "top 88%",
          // No `toggleActions` with a reverse: a section that fades out when scrolled
          // back up reads as a rendering fault rather than as an effect.
          once: true,
        },
      });
    },
    { scope, dependencies: [reduced, delay] },
  );

  return (
    <Tag ref={scope as never} className={className}>
      {children}
    </Tag>
  );
}

/**
 * The hero's entrance: a staggered rise, on load rather than on scroll.
 *
 * Separate from `Reveal` because the trigger is different in kind — the hero is already
 * in view, so a ScrollTrigger would either fire instantly (making the config a lie) or
 * never (leaving `gsap.from`'s starting state painted on screen).
 */
export function HeroStagger({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const { reduced } = useMotion();
  const scope = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      if (reduced) return;
      gsap.from(gsap.utils.toArray("[data-hero-item]", scope.current), {
        opacity: 0,
        y: 18,
        duration: 0.65,
        stagger: 0.08,
        ease: "power2.out",
      });
    },
    { scope, dependencies: [reduced] },
  );

  return (
    <div ref={scope} className={className}>
      {children}
    </div>
  );
}
