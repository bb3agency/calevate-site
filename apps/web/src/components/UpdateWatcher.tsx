"use client";

/**
 * KEEP EVERY OPEN PAGE ON THE LATEST DEPLOY (global rule 8).
 *
 * - On load: ask `/version.json` which build the server runs. If it is newer than the one
 *   this page was built from (a cached page, a tab restored from yesterday), clear the
 *   browser's caches and reload ONCE. A session key per server build stops a loop when the
 *   reload still serves the old build (a CDN lagging behind).
 * - Every page opened inside the app (a link, the sidebar) asks too, and a newer build turns
 *   that move into a full load of the same page on the new build: in-app navigation keeps the
 *   old code running otherwise, and nothing has been typed on a page just opened. A page the
 *   browser restores from its Back/Forward cache is checked the same way.
 * - While open: ask again every 5 minutes and whenever the tab comes back into view. A newer
 *   build then shows a bar with "Update now". It never reloads on its own, so nothing
 *   typed is lost.
 * - A page open for longer than a deploy keeps old files (`STALE_MS`, the `-mtime +2` prune
 *   in `scripts/vps-deploy.sh`) may already be missing pieces of itself, so there the bar says
 *   the new version is coming and updates after a short countdown — unless the person is
 *   typing in a field, when it stays as the ordinary "Update now" bar.
 * - A missing code chunk (`onMissingChunk`) reloads the page; it waits on an "Updating"
 *   screen only when a reload moments ago did not help. A route's RSC read that fails or
 *   names another build needs nothing here: Next turns that navigation into a full page
 *   load itself (`fetch-server-response.js`, `doMpaNavigation`).
 */

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { BUILD, buildDay, isNewerBuild, type BuildInfo } from "@/lib/buildInfo";

const POLL_MS = 5 * 60 * 1000;
/** Matches the deploy's prune of old web files (`find … -mtime +2 -delete`). */
const STALE_MS = 2 * 24 * 60 * 60 * 1000;
const COUNTDOWN_S = 5;
const RELOADED_KEY = "calevate:reloaded-for";

function readKey(): string | null {
  try {
    return window.sessionStorage.getItem(RELOADED_KEY);
  } catch {
    return null;
  }
}

function writeKey(value: string): void {
  try {
    window.sessionStorage.setItem(RELOADED_KEY, value);
  } catch {
    // A private window without storage: the reload still happens, the guard is the URL.
  }
}

async function serverBuild(): Promise<BuildInfo | null> {
  try {
    const res = await fetch(`/version.json?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as BuildInfo;
  } catch {
    return null;
  }
}

async function reloadFresh(forCommit: string): Promise<void> {
  if (readKey() === forCommit) return;
  writeKey(forCommit);
  await clearCachesAndReload();
}

async function clearCachesAndReload(): Promise<void> {
  try {
    if ("caches" in window) {
      const names = await window.caches.keys();
      await Promise.all(names.map((name) => window.caches.delete(name)));
    }
  } catch {
    // Clearing is best effort; the reload below still fetches the no-store HTML.
  }
  window.location.reload();
}

/** Someone is typing: a reload now would lose it. */
function isTyping(): boolean {
  const el = document.activeElement;
  if (!(el instanceof HTMLElement)) return false;
  return el.isContentEditable || el.tagName === "TEXTAREA" || (el instanceof HTMLInputElement && !["button", "submit", "checkbox", "radio", "reset"].includes(el.type));
}

function isMissingChunk(reason: unknown): boolean {
  if (typeof reason === "object" && reason !== null && (reason as { code?: unknown }).code === "CSS_CHUNK_LOAD_FAILED") {
    return true;
  }
  const text = reason instanceof Error ? `${reason.name} ${reason.message}` : String(reason ?? "");
  return /ChunkLoadError|Loading (?:CSS )?chunk [\w-]+ failed|Failed to fetch dynamically imported module|Importing a module script failed/i.test(
    text,
  );
}

/**
 * When this tab last reloaded for a missing chunk, as `<commit>@<epoch ms>`. A TIME rather
 * than a once-per-tab flag: the flag made every later chunk failure in the same tab (a
 * dropped phone signal hours afterwards) skip the reload and sit on the "Updating" screen
 * for `DEPLOY_WAIT_MS`, with no deploy happening.
 */
const CHUNK_RELOAD_KEY = "calevate:chunk-reload";
/** A chunk failing again this soon after its reload means the reload did not help. */
const CHUNK_RETRY_WINDOW_MS = 2 * 60_000;

function reloadedForChunkRecently(): boolean {
  let stored: string | null = null;
  try {
    stored = window.sessionStorage.getItem(CHUNK_RELOAD_KEY);
  } catch {
    return false;
  }
  const [commit, at] = (stored ?? "").split("@");
  return commit === BUILD.commit && Date.now() - Number(at) < CHUNK_RETRY_WINDOW_MS;
}

function markChunkReload(): void {
  try {
    window.sessionStorage.setItem(CHUNK_RELOAD_KEY, `${BUILD.commit}@${Date.now()}`);
  } catch {
    // No storage: the window check reads false and the next failure reloads again.
  }
}

/**
 * A code chunk could not be loaded: a deploy removed it, a deploy is mid-swap, or the
 * network dropped the request.
 *
 * - Offline: do nothing. A reload would replace the page with the browser's own offline
 *   screen; the error boundary's "Try again" and the offline banner are the way on.
 * - A newer build is live: reload onto it (once per build, `reloadFresh`'s guard).
 * - Otherwise reload, unless this tab already reloaded for a missing chunk moments ago —
 *   then the server is still serving files this build cannot find (a deploy mid-swap), so
 *   it says so and waits for `/version.json` to name a different commit.
 */
function onMissingChunk(): void {
  if (chunkHandled || waitingForDeploy) return;
  if (typeof navigator !== "undefined" && navigator.onLine === false) return;
  chunkHandled = true;
  void serverBuild().then((server) => {
    if (server && isNewerBuild(server) && readKey() !== `chunk:${server.commit}`) {
      void reloadFresh(`chunk:${server.commit}`);
      return;
    }
    if (!reloadedForChunkRecently()) {
      markChunkReload();
      void clearCachesAndReload();
      return;
    }
    waitForDeploy();
  });
}

function waitForDeploy(): void {
  waitingForDeploy = true;
  showUpdatingNotice();
  const started = Date.now();
  const poll = window.setInterval(() => {
    void serverBuild().then((server) => {
      if (server && server.commit !== BUILD.commit) {
        window.clearInterval(poll);
        void reloadFresh(server.commit);
      } else if (Date.now() - started > DEPLOY_WAIT_MS) {
        window.clearInterval(poll);
        window.location.reload();
      }
    });
  }, DEPLOY_POLL_MS);
}

/** One missing chunk is often reported twice (the boundary and the window); act once. */
let chunkHandled = false;
let waitingForDeploy = false;
/** How often a page caught mid-deploy asks whether the new version is live, and for how long. */
const DEPLOY_POLL_MS = 5_000;
const DEPLOY_WAIT_MS = 10 * 60_000;

/** Plain DOM, because the React tree may be the thing that failed to load. */
function showUpdatingNotice(): void {
  if (document.getElementById("calevate-updating")) return;
  const note = document.createElement("div");
  note.id = "calevate-updating";
  note.setAttribute("role", "status");
  Object.assign(note.style, {
    position: "fixed",
    inset: "0",
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px",
    textAlign: "center",
    background: "var(--app, #f9f3e4)",
    color: "var(--text, #1e2b3c)",
    font: "500 16px ui-sans-serif, system-ui, sans-serif",
    zIndex: "2147483647",
  });
  const text = document.createElement("p");
  text.textContent = "Updating Calevate… This page reloads by itself in a moment.";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Reload now";
  Object.assign(button.style, {
    minHeight: "44px",
    padding: "0 20px",
    borderRadius: "8px",
    border: "1px solid currentColor",
    background: "transparent",
    color: "inherit",
    font: "inherit",
    cursor: "pointer",
  });
  button.addEventListener("click", () => window.location.reload());
  note.append(text, button);
  document.body.appendChild(note);
}

/** For error boundaries: a missing code chunk after a deploy reloads onto the new build. */
export function recoverFromMissingChunk(error: unknown): boolean {
  if (!isMissingChunk(error)) return false;
  onMissingChunk();
  return true;
}

export function UpdateWatcher() {
  const [newer, setNewer] = useState<BuildInfo | null>(null);
  const [countdown, setCountdown] = useState<number | null>(null);
  const pathname = usePathname();
  const firstPath = useRef(true);

  useEffect(() => {
    if (firstPath.current) {
      firstPath.current = false;
      return;
    }
    let cancelled = false;
    void serverBuild().then((server) => {
      if (!cancelled && server && isNewerBuild(server)) void reloadFresh(`nav:${server.commit}`);
    });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  useEffect(() => {
    let cancelled = false;
    const loadedAt = Date.now();
    void serverBuild().then((server) => {
      if (!cancelled && server && isNewerBuild(server)) void reloadFresh(server.commit);
    });

    const check = () => {
      void serverBuild().then((server) => {
        if (cancelled || !server || !isNewerBuild(server)) return;
        setNewer(server);
        if (Date.now() - loadedAt > STALE_MS && !isTyping()) setCountdown((c) => c ?? COUNTDOWN_S);
      });
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    const onPageShow = (event: PageTransitionEvent) => {
      if (!event.persisted) return;
      void serverBuild().then((server) => {
        if (!cancelled && server && isNewerBuild(server)) void reloadFresh(`restore:${server.commit}`);
      });
    };
    window.addEventListener("pageshow", onPageShow);
    const timer = window.setInterval(check, POLL_MS);
    document.addEventListener("visibilitychange", onVisible);

    const onError = (event: ErrorEvent) => {
      if (isMissingChunk(event.error ?? event.message)) onMissingChunk();
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      if (isMissingChunk(event.reason)) onMissingChunk();
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("pageshow", onPageShow);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  useEffect(() => {
    if (countdown == null || !newer) return;
    if (countdown <= 0) {
      if (isTyping()) setCountdown(null);
      else void reloadFresh(`stale:${newer.commit}`);
      return;
    }
    const tick = window.setTimeout(() => setCountdown(countdown - 1), 1000);
    return () => window.clearTimeout(tick);
  }, [countdown, newer]);

  if (!newer) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-0 bottom-0 z-assistant flex flex-wrap items-center justify-center gap-3 border-t border-info-line bg-info-soft px-4 py-3 text-body text-ink shadow-card"
    >
      <span>
        {countdown != null
          ? `A new version of Calevate is ready (v${newer.version}). Updating in ${Math.max(countdown, 0)} s…`
          : `A new version of Calevate is ready (v${newer.version}). Save what you are typing, then update.`}
      </span>
      <button
        type="button"
        className="rounded-md bg-action px-3 py-1.5 text-xs font-semibold text-on-action hover:bg-action-hover"
        onClick={() => void reloadFresh(`manual:${newer.commit}`)}
      >
        Update now
      </button>
      <button
        type="button"
        className="text-xs text-ink-muted underline"
        onClick={() => {
          setCountdown(null);
          setNewer(null);
        }}
      >
        {countdown != null ? "Not now" : "Later"}
      </button>
    </div>
  );
}

/** The build this page runs, for the sidebar footer and the sign-in page. */
export function BuildStamp({ className = "" }: { className?: string }) {
  return (
    <p className={`text-[11px] text-ink-faint tabular-nums ${className}`} title={`Built ${BUILD.builtAt}`}>
      {`v${BUILD.version} · ${BUILD.commit}`}
      {BUILD.builtAt ? ` · ${buildDay(BUILD.builtAt)}` : ""}
    </p>
  );
}
