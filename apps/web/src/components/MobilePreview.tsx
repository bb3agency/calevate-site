"use client";

/**
 * WIDE OR MOBILE, on a desktop browser (global rule 13; founder, 16 Nov 2026: "give an option
 * at the top to see how it looks in a mobile, by default … wide screen mode. Do not give this
 * option when viewing on a mobile screen").
 *
 * The phone view is the same page in a 390×844 frame, not this page squeezed: the layout
 * switches on the WINDOW's width (Tailwind's media queries), so only a frame of phone width
 * shows what a phone shows. The frame is our own origin, which `frame-ancestors 'self'` and
 * the edge's `X-Frame-Options: SAMEORIGIN` allow and every other origin is still refused.
 *
 * The switch is shown only from 1024px up and never inside the frame itself. The choice is
 * remembered per browser; losing it only starts the next visit wide.
 */

import { Monitor, Smartphone, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { ScrollRegion } from "@/components/ui";

const KEY = "calevate:view";
const PHONE = { w: 390, h: 844 };

function remembered(): "wide" | "mobile" {
  try {
    return window.localStorage.getItem(KEY) === "mobile" ? "mobile" : "wide";
  } catch {
    return "wide";
  }
}

function remember(view: "wide" | "mobile"): void {
  try {
    window.localStorage.setItem(KEY, view);
  } catch {
    // No storage: the preview still opens, it is just not remembered.
  }
}

export function ViewSwitch() {
  const [ready, setReady] = useState(false);
  const [framed, setFramed] = useState(false);
  const [view, setView] = useState<"wide" | "mobile">("wide");
  useEffect(() => {
    setFramed(window.self !== window.top);
    setView(remembered());
    setReady(true);
  }, []);
  if (!ready || framed) return null;

  const choose = (next: "wide" | "mobile") => {
    setView(next);
    remember(next);
  };
  const option = (value: "wide" | "mobile", label: string, Icon: typeof Monitor) => (
    <button
      type="button"
      aria-pressed={view === value}
      onClick={() => choose(value)}
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-meta font-medium transition-colors ${
        view === value ? "bg-brand-strong text-white" : "text-ink-muted hover:text-ink"
      }`}
    >
      <Icon aria-hidden className="h-3.5 w-3.5" />
      {label}
    </button>
  );

  return (
    <>
      <div role="group" aria-label="How to view the app" className="hidden items-center rounded-full border border-line bg-surface p-0.5 lg:inline-flex">
        {option("wide", "Wide", Monitor)}
        {option("mobile", "Mobile", Smartphone)}
      </div>
      {view === "mobile" && <PhoneFrame onClose={() => choose("wide")} />}
    </>
  );
}

function PhoneFrame({ onClose }: { onClose: () => void }) {
  const [src] = useState(() => window.location.href);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Mobile preview"
      className="fixed inset-0 z-modal hidden flex-col bg-ink/60 lg:flex"
    >
      <ScrollRegion
        label="Mobile view"
        edgeCue={false}
        className="flex min-h-0 flex-1 flex-col items-center gap-3 overflow-y-auto p-4"
      >
        <div className="flex items-center gap-3 rounded-full bg-surface px-3 py-1.5 text-meta text-ink shadow-card">
          <Smartphone aria-hidden className="h-4 w-4 text-brand-strong" />
          <span>Mobile view ({PHONE.w}×{PHONE.h})</span>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 font-medium hover:bg-surface-muted"
          >
            <X aria-hidden className="h-3.5 w-3.5" />
            Back to wide
          </button>
        </div>
        <div
          className="shrink-0 overflow-hidden rounded-[2.5rem] border-[10px] border-ink bg-surface shadow-card"
          style={{ width: PHONE.w + 20, height: PHONE.h + 20 }}
        >
          <iframe title="This page on a phone" src={src} width={PHONE.w} height={PHONE.h} className="block border-0" />
        </div>
      </ScrollRegion>
    </div>,
    document.body,
  );
}
