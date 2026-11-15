"use client";

/**
 * KEEP EVERY OPEN PAGE ON THE LATEST DEPLOY (global rule 8).
 *
 * - On load: ask `/version.json` which build the server runs. If it is newer than the one
 *   this page was built from (a cached page, a tab restored from yesterday), clear the
 *   browser's caches and reload ONCE. A session key per server build stops a loop when the
 *   reload still serves the old build (a CDN lagging behind).
 * - While open: ask again every 5 minutes and whenever the tab comes back into view. A newer
 *   build then shows a bar with "Update now". It never reloads on its own, so nothing
 *   typed is lost.
 * - A missing code chunk after a deploy (the old file is gone from the server) reloads the
 *   page once, under the same guard.
 */

import { useEffect, useState } from "react";

import { BUILD, buildDay, isNewerBuild, type BuildInfo } from "@/lib/buildInfo";

const POLL_MS = 5 * 60 * 1000;
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

function isMissingChunk(reason: unknown): boolean {
  const text = reason instanceof Error ? `${reason.name} ${reason.message}` : String(reason ?? "");
  return /ChunkLoadError|Loading chunk [\w-]+ failed|Failed to fetch dynamically imported module|Importing a module script failed/i.test(
    text,
  );
}

export function UpdateWatcher() {
  const [newer, setNewer] = useState<BuildInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    void serverBuild().then((server) => {
      if (!cancelled && server && isNewerBuild(server)) void reloadFresh(server.commit);
    });

    const check = () => {
      void serverBuild().then((server) => {
        if (!cancelled && server && isNewerBuild(server)) setNewer(server);
      });
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    const timer = window.setInterval(check, POLL_MS);
    document.addEventListener("visibilitychange", onVisible);

    const onError = (event: ErrorEvent) => {
      if (isMissingChunk(event.error ?? event.message)) void reloadFresh(`chunk:${BUILD.commit}`);
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      if (isMissingChunk(event.reason)) void reloadFresh(`chunk:${BUILD.commit}`);
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  if (!newer) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-0 bottom-0 z-50 flex flex-wrap items-center justify-center gap-3 border-t border-info-line bg-info-soft px-4 py-3 text-body text-ink shadow-card"
    >
      <span>A new version of Calevate is ready (v{newer.version}). Save what you are typing, then update.</span>
      <button
        type="button"
        className="rounded-md bg-brand-strong px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-deep"
        onClick={() => void reloadFresh(`manual:${newer.commit}`)}
      >
        Update now
      </button>
      <button type="button" className="text-xs text-ink-muted underline" onClick={() => setNewer(null)}>
        Later
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
