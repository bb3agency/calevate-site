/**
 * A missing code file reloads the page onto a working build; it never leaves a phone
 * looking at "Updating Calevate…" for a deploy that is not happening.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/buildInfo", async (original) => {
  const real = await original<typeof import("@/lib/buildInfo")>();
  const BUILD = { version: "1.0.0", commit: "aaaaaaa", builtAt: "" };
  return {
    ...real,
    BUILD,
    isNewerBuild: (server: Parameters<typeof real.isNewerBuild>[0], running = BUILD) => real.isNewerBuild(server, running),
  };
});

const CHUNK_ERROR = Object.assign(new Error("Loading chunk 812 failed.\n(error: https://app.example/_next/static/chunks/812.js)"), {
  name: "ChunkLoadError",
});

let reload: ReturnType<typeof vi.fn>;
let serverCommit: string;
let now: number;

async function freshModule() {
  vi.resetModules();
  return await import("@/components/UpdateWatcher");
}

/** Let the version read and the cache clearing settle. */
async function settle() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
  vi.useFakeTimers();
  now = Date.UTC(2026, 10, 17, 6, 0, 0);
  vi.setSystemTime(now);
  reload = vi.fn();
  serverCommit = "aaaaaaa";
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, reload },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ version: "1.0.0", commit: serverCommit, builtAt: "" }), { status: 200 })),
  );
  Object.defineProperty(navigator, "onLine", { configurable: true, get: () => true });
  window.sessionStorage.clear();
  document.getElementById("calevate-updating")?.remove();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("a missing code chunk", () => {
  it("reloads the page the first time", async () => {
    const { recoverFromMissingChunk } = await freshModule();
    expect(recoverFromMissingChunk(CHUNK_ERROR)).toBe(true);
    await settle();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(document.getElementById("calevate-updating")).toBeNull();
  });

  it("reloads again, with no 'Updating' screen, when it happens long after an earlier reload", async () => {
    let watcher = await freshModule();
    watcher.recoverFromMissingChunk(CHUNK_ERROR);
    await settle();
    expect(reload).toHaveBeenCalledTimes(1);

    // The reloaded page worked. An hour later, on the same tab, a bad signal drops a chunk.
    vi.setSystemTime(now + 60 * 60_000);
    watcher = await freshModule();
    watcher.recoverFromMissingChunk(CHUNK_ERROR);
    await settle();
    expect(reload).toHaveBeenCalledTimes(2);
    expect(document.getElementById("calevate-updating")).toBeNull();
  });

  it("waits for the new version when the page it just reloaded is still missing pieces", async () => {
    let watcher = await freshModule();
    watcher.recoverFromMissingChunk(CHUNK_ERROR);
    await settle();
    expect(reload).toHaveBeenCalledTimes(1);

    vi.setSystemTime(now + 10_000);
    watcher = await freshModule();
    watcher.recoverFromMissingChunk(CHUNK_ERROR);
    await settle();
    const notice = document.getElementById("calevate-updating");
    expect(notice?.textContent).toContain("Updating Calevate");
    expect(reload).toHaveBeenCalledTimes(1);

    // The notice is never a dead end: it offers its own reload.
    const button = notice?.querySelector("button");
    expect(button?.textContent).toBe("Reload now");

    serverCommit = "bbbbbbb";
    await vi.advanceTimersByTimeAsync(5_000);
    await settle();
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("reloads onto a newer build at once, even straight after a reload", async () => {
    let watcher = await freshModule();
    watcher.recoverFromMissingChunk(CHUNK_ERROR);
    await settle();
    serverCommit = "bbbbbbb";
    vi.setSystemTime(now + 10_000);
    watcher = await freshModule();
    watcher.recoverFromMissingChunk(CHUNK_ERROR);
    await settle();
    expect(reload).toHaveBeenCalledTimes(2);
    expect(document.getElementById("calevate-updating")).toBeNull();
  });

  it("does not reload while the phone is offline", async () => {
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });
    const { recoverFromMissingChunk } = await freshModule();
    expect(recoverFromMissingChunk(CHUNK_ERROR)).toBe(true);
    await settle();
    expect(reload).not.toHaveBeenCalled();
    expect(document.getElementById("calevate-updating")).toBeNull();
  });

  it("reloads once when the same failure is reported twice", async () => {
    const { recoverFromMissingChunk } = await freshModule();
    recoverFromMissingChunk(CHUNK_ERROR);
    recoverFromMissingChunk(CHUNK_ERROR);
    await settle();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(document.getElementById("calevate-updating")).toBeNull();
  });

  it("recognises a missing stylesheet chunk", async () => {
    const css = Object.assign(new Error("Loading CSS chunk 4410 failed.\n(/_next/static/css/4410.css)"), {
      code: "CSS_CHUNK_LOAD_FAILED",
    });
    const { recoverFromMissingChunk } = await freshModule();
    expect(recoverFromMissingChunk(css)).toBe(true);
    expect(recoverFromMissingChunk(new Error("undefined is not a function"))).toBe(false);
  });
});
