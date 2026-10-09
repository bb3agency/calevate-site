"use client";

import { useEffect, useRef } from "react";

/**
 * "OPEN THE ASSISTANT WITH THIS REQUEST" — how a button on a screen reaches the panel.
 *
 * The panel is mounted once by the realm shell and the buttons that prefill it live twenty
 * components away inside a screen, so this is a tiny event channel rather than a context: a
 * provider in the layout would be the same wiring plus a re-render of every screen on every
 * open. `registry.ts` is a store for the same reason.
 *
 * The request PREFILLS the ask box and never sends it. A person reads what is about to be
 * asked, edits it, and presses Ask themselves — so a button can never spend the account's
 * allowance, or start an action, on a single click.
 */

export interface AssistantRequest {
  /** What to put in the ask box. Absent opens the panel as it was. */
  prompt?: string;
}

type Listener = (request: AssistantRequest) => void;

const listeners = new Set<Listener>();

/** Open the side panel, optionally with a prefilled request. A no-op when no panel is
 *  mounted (a screen rendered outside a realm shell, as in a unit test). */
export function openAssistant(request: AssistantRequest = {}): void {
  for (const listener of listeners) listener(request);
}

/** The dock's half: be told when a screen asks for the panel. */
export function useAssistantRequests(onRequest: Listener): void {
  const latest = useRef(onRequest);
  useEffect(() => {
    latest.current = onRequest;
  });
  useEffect(() => {
    const listener: Listener = (request) => latest.current(request);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
}
