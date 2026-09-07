"use client";

import { useEffect } from "react";

/**
 * ASK BEFORE THROWING SOMEBODY'S TYPING AWAY — the half of the question that belongs to
 * the BROWSER rather than to the assistant.
 *
 * `lib/copilot/unsaved.ts` already answers this for one mover: the screen assistant, which
 * knows it is about to navigate and asks in `ConfirmDialog` first. Every other way out of
 * a half-finished form went unasked — a reload, a closed tab, a back gesture off the
 * console — and on a mid-range Android a background tab being reloaded is routine rather
 * than exotic. The work at stake is a call script, an extraction schema, a handover list
 * or a campaign: twenty minutes of typing, and nothing of it is saved until a button is
 * pressed.
 *
 * ## Why `beforeunload`, and what it does NOT cover
 *
 * This is the only mechanism the platform offers for a page the browser is ABOUT to
 * discard, and it is not a choice between mechanisms:
 *
 *  - The dialog is asked for by calling `preventDefault()` on the event, with
 *    `returnValue = ""` alongside it for older engines that still read that property.
 *    Both are documented as the way to trigger it, and the wording of the prompt is the
 *    browser's — a page cannot supply it, which is why this hook takes no message.
 *    (MDN, `Window: beforeunload event`, read 7 Sep 2026 — via search summary; the MDN
 *    host is egress-blocked from this container, so the API shape is additionally pinned
 *    by the test beside it rather than by a page anyone here could open.)
 *  - Browsers only show it after a **sticky activation** — a real interaction with the
 *    page. That is not a limitation here: this hook is armed only once somebody has typed
 *    into the form, which is itself the interaction.
 *  - **It does not fire for an in-app route change.** Next's App Router navigates on the
 *    client and the document is never unloaded, so a sidebar click is invisible to it.
 *    That leg is NOT invented a second time here — the assistant's path already asks
 *    (`lib/copilot/unsaved.ts`), and Next 15.5 additionally offers `<Link onNavigate>`
 *    with a `preventDefault()` (verified in the installed package's own types,
 *    `node_modules/next/dist/client/link.d.ts:4,88`, 7 Sep 2026) for whenever the shells'
 *    nav is taught to ask. A screen wanting that today declares `CopilotSurface.unsaved`
 *    truthfully rather than growing a third blocker.
 *
 * ## Why a hook rather than a component
 *
 * Because the thing it needs is a boolean the form already computes. Every caller here
 * had a `dirty` — or a comparison one line from being one — before this existed; the hook
 * adds no state, no context and no provider, and unregisters the moment the form is clean
 * again so a saved form does not nag on the way out.
 */
export function useUnsavedGuard(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return;
    const ask = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Legacy engines read this instead of the canceled flag. The STRING is ignored by
      // every current browser — none of them shows page-supplied text — so it is empty
      // rather than a sentence somebody would later try to word.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [dirty]);
}
