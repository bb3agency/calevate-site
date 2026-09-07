"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

/**
 * WHAT THE ASSISTANT SAYS INSIDE A D-22 VIEW-AS SESSION: that it cannot answer here, and
 * why — instead of a panel that issues a request guaranteed to be refused.
 *
 * ## The refusal is structural, not a bug to route around
 *
 * All four client copilot routes declare `copilot:use`
 * (`apps/api/copilot/routes.py:164,752,828,905`). `copilot:use` is in
 * `core/rbac.MUTATING_PERMISSIONS` — asking spends the ACCOUNT'S AI allowance, so it moves
 * a balance however read-only the answer looks — and it is NOT in
 * `rbac.IMPERSONATION_PERMITTED_MUTATIONS`, which holds `copilot:admin` alone because that
 * one can only ever spend the platform's own ledger. So `core/auth.requires` refuses an
 * impersonating principal with 403 "Impersonation is read-only" before any model is
 * called: the ask, the confirm, the stored conversation and the clear, all four.
 *
 * Without this panel an operator in view-as saw the ordinary assistant, typed a question,
 * and got a generic refusal — or, worse, read the silence as the feature being broken for
 * the CLIENT.
 *
 * ## Why not silently render the ADMIN assistant instead
 *
 * It is the reachable route (`copilot:admin` IS impersonation-permitted) and it was
 * considered and rejected. The admin assistant answers about PLATFORM state with the
 * platform's own credential and its own prompt; pointing it at a client screen would send
 * that client's field values into the platform's ledger and its context, under an
 * operator's identity, with no client-realm confirm route at the other end (see
 * `CopilotPanel`'s `confirmable`). That is a tenancy decision, not a fallback, and it is
 * not one this component may take on its own.
 *
 * ## Why not hide the launcher
 *
 * A control that vanishes explains nothing, and the operator's next move is to wonder
 * whether the client has the assistant at all. The answer they need is that the client
 * does, and that a read-only session is the reason they cannot use it from here.
 */
export function ViewAsPanel({
  labelledBy,
  onClose,
}: {
  labelledBy: string;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);

  // Escape closes, on `document` and for `CopilotPanel`'s reason — the person reaching for
  // it has very often just been reading the screen behind this, not standing inside it.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // The close button is the only control here, so it is what opening this focuses.
  useEffect(() => {
    panel.current?.querySelector("button")?.focus();
  }, []);

  return (
    <div
      ref={panel}
      role="dialog"
      aria-labelledby={labelledBy}
      data-testid="copilot-view-as-panel"
      className="fixed bottom-20 right-4 z-[70] flex max-h-[min(34rem,calc(100vh-7rem))] w-[min(24rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-card border border-line bg-surface shadow-lg"
    >
      <div className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <h2 id={labelledBy} className="text-sm font-semibold text-ink">
          Assistant unavailable in view-as
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the assistant"
          className="-mr-1 rounded-md p-1 text-ink-muted hover:bg-black/5 hover:text-ink dark:hover:bg-white/10"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      </div>
      <div className="space-y-2 px-4 py-3 text-sm">
        {/* NAMES THE MONEY, because that is the whole reason and an operator can act on
            it: the client's allowance is the client's, and a view-as session is read-only
            precisely so nothing an operator does inside one shows up on their bill. */}
        <p className="text-xs text-ink-muted">
          You are viewing this account as its owner, which is read-only. Asking the
          assistant would spend this client&apos;s own AI allowance, so it is refused
          inside a view-as session.
        </p>
        <p className="text-xs text-ink-muted">
          The client can use it normally on this screen. To ask about platform state, use
          the assistant in the admin console.
        </p>
      </div>
    </div>
  );
}
