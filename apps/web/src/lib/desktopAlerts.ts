"use client";

/**
 * DESKTOP ALERTS (founder, REDESIGN-2): while the console is open in a tab, a new item on
 * the bell's own feed (`/v1/attention`) also appears as a browser notification, once the
 * owner has turned them on. Three rules make it polite:
 *
 * - The browser's permission is asked ONLY from the owner's click on "Turn on desktop
 *   alerts", never on page load (browsers penalise a prompt nobody asked for, and so do
 *   people).
 * - Items already on the feed when the tab opens are not announced; only ones that arrive
 *   while it is open are. Otherwise every reload would replay the queue.
 * - A denied or unsupported permission is respected quietly: the setting says so, and
 *   nothing retries.
 *
 * The opt-in is this browser's, per account (`localStorage`), because a notification is a
 * property of a device, not of the account. Every storage access is guarded: a private
 * window or blocked site data simply means "off".
 */

import { useEffect, useRef, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";

import type { AttentionQueue } from "@/lib/api/attention";

const KEY = (slug: string) => `calevate.desktopAlerts.${slug}`;
const EVENT = "calevate:desktop-alerts";

export type DesktopAlertState = "unsupported" | "denied" | "off" | "on";

function supported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

function readOptIn(slug: string): boolean {
  try {
    return window.localStorage.getItem(KEY(slug)) === "on";
  } catch {
    return false;
  }
}

function writeOptIn(slug: string, on: boolean): void {
  try {
    if (on) window.localStorage.setItem(KEY(slug), "on");
    else window.localStorage.removeItem(KEY(slug));
  } catch {
    // Storage blocked: the setting cannot be kept, so it stays off.
  }
  window.dispatchEvent(new Event(EVENT));
}

export function desktopAlertState(slug: string): DesktopAlertState {
  if (!supported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return Notification.permission === "granted" && readOptIn(slug) ? "on" : "off";
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** The setting's current state, live. */
export function useDesktopAlertState(slug: string): DesktopAlertState {
  return useSyncExternalStore(
    subscribe,
    () => desktopAlertState(slug),
    () => "off",
  );
}

/** From the owner's click: ask the browser (only now), and remember the answer. */
export async function turnOnDesktopAlerts(slug: string): Promise<DesktopAlertState> {
  if (!supported()) return "unsupported";
  const permission =
    Notification.permission === "default" ? await Notification.requestPermission() : Notification.permission;
  writeOptIn(slug, permission === "granted");
  return desktopAlertState(slug);
}

export function turnOffDesktopAlerts(slug: string): void {
  writeOptIn(slug, false);
}

/**
 * Mounted once in the console shell: watches the queue the bell already polls and raises
 * a notification for each item that arrives while the tab is open.
 */
export function useDesktopAlerts(slug: string, queue: AttentionQueue | undefined, href: (path: string) => string): void {
  const state = useDesktopAlertState(slug);
  const seen = useRef<Set<string> | null>(null);
  const router = useRouter();

  useEffect(() => {
    const items = queue?.items;
    if (!items) return;
    const ids = items.map((item) => item.id);
    // The first answer is what was already waiting: remember it, announce none of it.
    if (seen.current === null) {
      seen.current = new Set(ids);
      return;
    }
    const known = seen.current;
    const fresh = items.filter((item) => !known.has(item.id));
    for (const id of ids) known.add(id);
    if (state !== "on" || fresh.length === 0) return;
    for (const item of fresh) {
      const note = new Notification(item.title, { body: item.detail, tag: item.id });
      note.onclick = () => {
        window.focus();
        router.push(item.href ? href(item.href) : href(`/c/${slug}/attention`));
        note.close();
      };
    }
  }, [queue, state, slug, href, router]);
}
