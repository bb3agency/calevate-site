"use client";

/**
 * "SHOW ME AROUND" — a five-step tour of the agent page that the owner starts (D-855).
 *
 * It never opens by itself. The trigger sits under the header line; once a person has
 * taken the tour on this browser it turns from the brand colour to muted ink and stays
 * where it was. `?tour=1` opens it once from a link the owner clicked (`TOUR_PARAM`).
 *
 * WHY A MANUAL POPOVER AND NOT `<dialog showModal>`. The step card sits beside the thing
 * it points at with the page readable around it, which is the non-modal tour pattern
 * (modern-web-guidance "persistent-app-tours"). `popover="manual"` puts the layer in the
 * top layer, above the sticky header and any page stacking context, without light-dismiss
 * (a click elsewhere must not end the tour). Focus is held by `useFocusTrap`, the one
 * modal focus contract in this app; Escape and the close button both end the tour and
 * focus goes back to the trigger. A browser without the Popover API shows the same
 * fixed-position layer at `z-modal`.
 *
 * WHY THE TOUR NEVER SWITCHES TABS. Every target is visible from any tab: three tab
 * buttons, the header's Try it, and Pip's launcher in the console header. Opening a tab for
 * the owner would go through the unsaved-edits guard, which can stop on a confirm dialog
 * halfway through a step.
 *
 * The layer is not portalled: it renders inside the page so the accessibility sweep
 * scans it with the page (`tests/a11y.test.tsx`).
 */

import { Compass, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import { PRIMARY_BUTTON_SM, QUIET_ICON_BUTTON, SECONDARY_BUTTON_SM } from "@/components/ui";
import { useFocusTrap } from "@/lib/focusTrap";
import { useMe } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

import { placeCard, readSeen, SHEET_BELOW_PX, TOUR_PARAM, TOUR_STEPS, writeSeen, type Box, type Placement } from "./tourModel";

const TRIGGER =
  "press inline-flex items-center gap-1.5 rounded-sm text-body font-medium underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11";

export function AgentTour() {
  const session = useClientSession();
  const me = useMe(session);
  const userId = me.data?.user_id ?? null;
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const [step, setStep] = useState<number | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  // Unknown until read after mount (storage does not exist on the server): drawn quiet,
  // so an owner who has seen it never sees the button flash to the brand colour.
  const [seen, setSeen] = useState<boolean | null>(null);

  useEffect(() => {
    if (userId) setSeen(readSeen(userId));
  }, [userId]);

  const asked = params.get(TOUR_PARAM) === "1";
  const handledAsk = useRef(false);
  useEffect(() => {
    if (!asked || handledAsk.current) return;
    handledAsk.current = true;
    setStep(0);
    const rest = new URLSearchParams(params.toString());
    rest.delete(TOUR_PARAM);
    const query = rest.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [asked, params, pathname, router]);

  const close = useCallback(() => {
    setStep(null);
    setSeen(true);
    if (userId) writeSeen(userId);
    // Opened from `?tour=1`, nothing had focus to give back to; the trigger is the place a
    // keyboard user can start it again from.
    requestAnimationFrame(() => {
      if (document.activeElement === document.body || document.activeElement === null) trigger.current?.focus();
    });
  }, [userId]);

  return (
    <div>
      <button
        ref={trigger}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={step !== null}
        onClick={() => setStep(0)}
        className={`${TRIGGER} ${seen === false ? "text-brand-strong" : "text-ink-muted hover:text-ink"}`}
      >
        <Compass aria-hidden className="h-4 w-4" />
        Show me around
      </button>
      {step !== null && <TourLayer step={step} onStep={setStep} onClose={close} />}
    </div>
  );
}

/** The highlight's distance outside the target, so the ring never covers its edge. */
const RING_PAD = 4;

type Geometry = { ring: Box | null; place: Placement };

function TourLayer({
  step,
  onStep,
  onClose,
}: {
  step: number;
  onStep: (step: number) => void;
  onClose: () => void;
}) {
  const layerRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();
  const current = TOUR_STEPS[step];
  const last = step === TOUR_STEPS.length - 1;
  // Starts in the shape the viewport calls for, so the first measurement is of that shape.
  const [geometry, setGeometry] = useState<Geometry>(() => ({
    ring: null,
    place:
      window.innerWidth < SHEET_BELOW_PX ? { mode: "sheet" } : { mode: "float", top: 0, left: 0, origin: "center" },
  }));
  const shape = useRef(geometry.place.mode);
  const [announcement, setAnnouncement] = useState("");
  const announced = useRef(step);

  useLayoutEffect(() => {
    const layer = layerRef.current;
    if (layer && supportsPopover()) {
      try {
        layer.showPopover();
      } catch {
        // Already shown, or the element left the document: nothing to promote.
      }
    }
  }, []);

  useFocusTrap(cardRef, true, onClose, "container");
  // After the trap has armed (it focuses the card): Next is where a keyboard user goes.
  useEffect(() => {
    nextRef.current?.focus();
  }, []);

  // Each later step is read out; the first is announced by focus entering the dialog.
  // Compared with the last step announced rather than counted, so Strict Mode's second
  // effect run on mount does not announce step 1.
  useEffect(() => {
    if (announced.current === step) return;
    announced.current = step;
    setAnnouncement(`Step ${step + 1} of ${TOUR_STEPS.length}. ${current.title}. ${current.body}`);
  }, [step, current]);

  useLayoutEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const target = current.target(document);
    if (target) bringIntoView(target, reduce);
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    function measure() {
      const card = cardRef.current?.getBoundingClientRect();
      const box = boxOf(current.target(document));
      const viewport = { width: window.innerWidth, height: window.innerHeight };
      const place = placeCard(box, { width: card?.width ?? 0, height: card?.height ?? 0 }, viewport);
      setGeometry({ ring: box, place });
      // The card was measured in the other shape (sheet and card differ in width), so
      // measure again once it has been drawn in this one.
      if (place.mode !== shape.current) {
        shape.current = place.mode;
        schedule();
      }
    }
    measure();
    window.addEventListener("resize", schedule);
    // Capture: the console scrolls its main region, not the window.
    window.addEventListener("scroll", schedule, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
    };
  }, [current]);

  const back = () => {
    onStep(step - 1);
    // Back disappears on the first step; focus must not go with it.
    if (step - 1 === 0) requestAnimationFrame(() => nextRef.current?.focus());
  };
  const next = () => (last ? onClose() : onStep(step + 1));

  const { place, ring } = geometry;
  const cardStyle: CSSProperties | undefined =
    place.mode === "float" ? { top: place.top, left: place.left, transformOrigin: place.origin } : undefined;

  return (
    <div
      ref={layerRef}
      // Only where the API exists: an engine that knows the attribute's hiding rule but not
      // `showPopover` (jsdom is one) would otherwise never show the layer.
      popover={supportsPopover() ? "manual" : undefined}
      className="pointer-events-none fixed inset-0 z-modal m-0 size-full max-h-none max-w-none overflow-visible border-0 bg-transparent p-0"
    >
      {ring && (
        <div
          aria-hidden
          className="fixed left-0 top-0 rounded-lg ring-2 ring-brand-strong transition-transform duration-(--duration-base) ease-(--ease-out-strong) motion-reduce:transition-none"
          style={{
            width: ring.width + RING_PAD * 2,
            height: ring.height + RING_PAD * 2,
            transform: `translate(${ring.left - RING_PAD}px, ${ring.top - RING_PAD}px)`,
          }}
        />
      )}
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        style={cardStyle}
        className={`modal-enter pointer-events-auto fixed border border-line bg-surface p-4 text-ink shadow-overlay outline-none ${
          place.mode === "sheet"
            ? "inset-x-0 bottom-0 rounded-t-2xl pb-[calc(1rem+env(safe-area-inset-bottom,0px))]"
            : "w-[22rem] max-w-[calc(100vw-2rem)] rounded-card"
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <p className="text-meta text-ink-muted">
            Step {step + 1} of {TOUR_STEPS.length}
          </p>
          <button type="button" onClick={onClose} aria-label="Close the tour" className={`${QUIET_ICON_BUTTON} -mr-2`}>
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>
        <div key={step} className="settings-enter">
          <h2 id={titleId} className="break-words text-heading text-ink">
            {current.title}
          </h2>
          <p id={bodyId} className="mt-1 break-words text-body text-ink-muted">
            {current.body}
          </p>
        </div>
        <div className="mt-4 flex justify-end gap-2 max-sm:*:flex-1 max-sm:*:justify-center">
          {step > 0 && (
            <button type="button" onClick={back} className={SECONDARY_BUTTON_SM}>
              Back
            </button>
          )}
          <button ref={nextRef} type="button" onClick={next} className={PRIMARY_BUTTON_SM}>
            {last ? "Done" : "Next"}
          </button>
        </div>
        <p aria-live="polite" className="sr-only">
          {announcement}
        </p>
      </div>
    </div>
  );
}

/** Rendered only after a click or an effect, so this never runs on the server. */
function supportsPopover(): boolean {
  return typeof HTMLElement !== "undefined" && typeof HTMLElement.prototype.showPopover === "function";
}

/** The target's box, or null when it is not laid out (hidden, or no layout engine). */
function boxOf(target: HTMLElement | null): Box | null {
  if (!target) return null;
  const rect = target.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return { top: rect.top, left: rect.left, width: rect.width, height: rect.height };
}

/**
 * Scrolls only when the target is out of view or would sit under the phone sheet. A tab
 * off the end of the scrolling tab row is brought in sideways by `inline: "nearest"`.
 */
function bringIntoView(target: HTMLElement, reduce: boolean): void {
  if (typeof target.scrollIntoView !== "function") return;
  const rect = target.getBoundingClientRect();
  const sheet = window.innerWidth < SHEET_BELOW_PX;
  const lowest = sheet ? window.innerHeight / 2 : window.innerHeight;
  const offRow = rect.left < 0 || rect.right > window.innerWidth;
  const offPage = rect.top < 0 || rect.bottom > lowest;
  if (!offRow && !offPage) return;
  // "start" only when it is under the sheet: a tab that is merely off the end of its row
  // must not move the page up or down as well.
  target.scrollIntoView({
    block: sheet && offPage ? "start" : "nearest",
    inline: "nearest",
    behavior: reduce ? "auto" : "smooth",
  });
}
