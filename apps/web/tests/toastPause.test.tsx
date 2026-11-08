import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast, type ToastApi } from "@/components/arc/toast";

/**
 * The stack pauses while it is hovered or holds focus. Closing a toast removes the very
 * element the pointer or the focus was on, and a removed element sends no `pointerout` or
 * `focusout` in every browser (nor in jsdom), so the pause must not outlive the card that
 * caused it (audit 8 Nov W4-02).
 */

let api: ToastApi | null = null;

function Grab() {
  api = useToast();
  return null;
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: false });
});

afterEach(() => {
  vi.useRealTimers();
  api = null;
});

describe("the toast stack's pause", () => {
  it("ENDS WHEN THE TOAST THAT HELD FOCUS IS CLOSED, so the next one still leaves on its own", async () => {
    render(
      <ToastProvider>
        <Grab />
      </ToastProvider>,
    );
    await act(async () => {
      api?.toast({ kind: "error", title: "Could not save" });
    });
    const close = screen.getByRole("button", { name: "Dismiss" });
    await act(async () => {
      close.focus();
    });
    await act(async () => {
      close.click();
    });

    await act(async () => {
      api?.toast({ kind: "success", title: "Saved", duration: 1000 });
    });
    expect(screen.getByText("Saved")).toBeTruthy();
    // In steps, so the closed card's exit animation and the frame after it both run.
    for (let step = 0; step < 40; step += 1) {
      await act(async () => {
        vi.advanceTimersByTime(100);
      });
    }
    expect(screen.queryByRole("group", { name: "Done: Saved" })).toBeNull();
  });

  it("STILL PAUSES while a remaining toast is focused", async () => {
    render(
      <ToastProvider>
        <Grab />
      </ToastProvider>,
    );
    await act(async () => {
      api?.toast({ kind: "success", title: "Saved", duration: 1000 });
    });
    const close = screen.getByRole("button", { name: "Dismiss" });
    await act(async () => {
      close.focus();
    });
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("group", { name: "Done: Saved" })).toBeTruthy();
  });
});
