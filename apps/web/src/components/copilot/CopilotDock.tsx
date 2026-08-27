"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Sparkles } from "lucide-react";

import { adminSession } from "@/lib/api/admin";
import type { Session } from "@/lib/api/client";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurfaceHolder } from "@/lib/copilot/registry";

import { CopilotPanel } from "./CopilotPanel";

/**
 * The floating launcher, and the panel it anchors — mounted once per realm shell.
 *
 * ## It renders NOTHING on a screen that has not declared itself
 *
 * A screen becomes assistable by calling `useCopilotSurface` (`lib/copilot/registry.ts`)
 * and in no other way. A launcher on a screen with no declaration would open onto an
 * assistant that can see nothing and fill nothing, which is worse than no launcher: it
 * teaches a person the feature is broken on the screen where they first tried it. So the
 * button is absent until a surface is registered, and the list of screens that register
 * one is the honest list of where this works.
 *
 * ## Position, and the one collision it accepts
 *
 * Bottom-right, the conventional corner, at `z-[70]`. `components/interior/toaster.tsx`
 * puts the toast lane in the same corner at `z-[60]` and 360px wide, so a toast fires
 * BEHIND the 44px launcher and its bottom-right corner is covered. That is the accepted
 * trade rather than an oversight: moving the launcher left would put it over the
 * sidebar's account block above `lg`, and lowering it under the toasts would make the
 * control unclickable exactly while a toast is showing — a dead button is a worse defect
 * than a clipped corner of a notification that also says its text on the left.
 *
 * ## Realm
 *
 * Two exported wrappers rather than one component taking a session, because the two
 * realms obtain a session in ways that cannot be selected at runtime: the client realm
 * READS A HOOK that must run inside `ClientRealmProvider`, and the admin realm calls a
 * plain builder. A single component branching on a prop would be a conditional hook.
 */
function CopilotDock({ session, realm }: { session: Session; realm: "client" | "admin" }) {
  const holder = useCopilotSurfaceHolder();
  const [isOpen, setIsOpen] = useState(false);
  const launcher = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  // Set while the panel is closing, so focus is returned to the launcher — the modal
  // contract's last step, kept even though the panel deliberately does not trap focus.
  const shouldRestoreFocus = useRef(false);

  // A navigation swaps the surface underneath an open panel. The conversation is about
  // the OLD screen's fields, so it must not survive: closing is the honest response, and
  // it is what keeps `CopilotPanel`'s conversation state from being reused across two
  // different forms (it is unmounted, so there is nothing to reset).
  useEffect(() => {
    setIsOpen(false);
  }, [holder]);

  useEffect(() => {
    if (isOpen || !shouldRestoreFocus.current) return;
    shouldRestoreFocus.current = false;
    launcher.current?.focus();
  }, [isOpen]);

  if (holder === null) return null;

  return (
    <>
      <button
        ref={launcher}
        type="button"
        aria-expanded={isOpen}
        aria-label={isOpen ? "Close the screen assistant" : "Ask about this screen"}
        onClick={() => {
          shouldRestoreFocus.current = isOpen;
          setIsOpen((open) => !open);
        }}
        className="fixed bottom-4 right-4 z-[70] flex h-11 w-11 items-center justify-center rounded-full border border-line bg-brand-strong text-white shadow-lg transition-colors hover:bg-brand-deep focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
      >
        <Sparkles aria-hidden className="h-5 w-5" />
      </button>
      {isOpen && (
        <CopilotPanel
          session={session}
          holder={holder}
          realm={realm}
          labelledBy={titleId}
          onClose={() => {
            shouldRestoreFocus.current = true;
            setIsOpen(false);
          }}
        />
      )}
    </>
  );
}

/** Mounted by `app/c/[slug]/layout.tsx`, INSIDE `ClientRealmProvider`. */
export function ClientCopilotDock() {
  return <CopilotDock session={useClientSession()} realm="client" />;
}

/** Mounted by `app/admin/layout.tsx`. `adminSession()` takes no org — an operator's
 *  session is not scoped to one tenant, and the screens that are name it in the path. */
export function AdminCopilotDock() {
  return <CopilotDock session={adminSession()} realm="admin" />;
}
