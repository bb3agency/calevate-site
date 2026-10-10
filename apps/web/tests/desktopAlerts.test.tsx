import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AttentionQueue } from "@/lib/api/attention";
import { desktopAlertState, turnOnDesktopAlerts, useDesktopAlerts } from "@/lib/desktopAlerts";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

/**
 * DESKTOP ALERTS (REDESIGN-2): asked only from a click, never a flood of what was already
 * waiting, and quiet when the browser says no.
 */
const created: { title: string; options?: NotificationOptions }[] = [];
let permission: NotificationPermission = "default";
let answer: NotificationPermission = "granted";
const requestPermission = vi.fn(async () => {
  permission = answer;
  return answer;
});

class FakeNotification {
  static get permission() {
    return permission;
  }
  static requestPermission = requestPermission;
  onclick: (() => void) | null = null;
  constructor(title: string, options?: NotificationOptions) {
    created.push({ title, options });
  }
  close() {}
}

function queue(ids: string[]): AttentionQueue {
  return {
    total: ids.length,
    counts: {},
    items: ids.map((id) => ({
      id,
      kind: "delivery_failed",
      title: `Item ${id}`,
      detail: "Something needs you.",
      href: null,
      occurred_at: "2026-10-10T04:00:00Z",
      rule: null,
    })),
  };
}

beforeEach(() => {
  created.length = 0;
  permission = "default";
  requestPermission.mockClear();
  vi.stubGlobal("Notification", FakeNotification);
  window.localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe("desktop alerts", () => {
  it("never asks the browser on load, only from the owner's click", async () => {
    renderHook(() => useDesktopAlerts("acme", queue(["a"]), (p) => p));
    expect(requestPermission).not.toHaveBeenCalled();
    answer = "granted";
    await act(async () => {
      expect(await turnOnDesktopAlerts("acme")).toBe("on");
    });
    expect(requestPermission).toHaveBeenCalledTimes(1);
  });

  it("announces only items that arrive while the tab is open", async () => {
    permission = "granted";
    await turnOnDesktopAlerts("acme");
    const { rerender } = renderHook(({ q }) => useDesktopAlerts("acme", q, (p) => p), {
      initialProps: { q: queue(["a", "b"]) },
    });
    expect(created).toHaveLength(0);
    rerender({ q: queue(["c", "a", "b"]) });
    expect(created.map((n) => n.title)).toEqual(["Item c"]);
  });

  it("stays quiet when the browser has said no", async () => {
    permission = "denied";
    expect(await turnOnDesktopAlerts("acme")).toBe("denied");
    expect(desktopAlertState("acme")).toBe("denied");
    const { rerender } = renderHook(({ q }) => useDesktopAlerts("acme", q, (p) => p), {
      initialProps: { q: queue(["a"]) },
    });
    rerender({ q: queue(["b", "a"]) });
    expect(created).toHaveLength(0);
  });
});
