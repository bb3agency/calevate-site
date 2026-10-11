import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceButton } from "@/app/c/[slug]/knowledge/TeachBox";

/**
 * "Say it" asks for the microphone in our own words before the browser does: allowed
 * records at once, not yet asked explains and then triggers the browser's prompt, blocked
 * says how to unblock it, and a device with no microphone is told so.
 */

class FakeRecorder {
  static isTypeSupported = () => true;
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start() {}
  stop() {
    this.onstop?.();
  }
}

const stream = { getTracks: () => [{ stop: vi.fn() }] };
let permission: PermissionState | "throws";
let getUserMedia: ReturnType<typeof vi.fn>;

beforeEach(() => {
  permission = "prompt";
  getUserMedia = vi.fn().mockResolvedValue(stream);
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: {
      query: vi.fn(async () => {
        if (permission === "throws") throw new TypeError("microphone is not a permission name");
        return { state: permission };
      }),
    },
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderButton(onTypeInstead = vi.fn()) {
  render(<VoiceButton disabled={false} onRecorded={vi.fn()} onTypeInstead={onTypeInstead} />);
  return onTypeInstead;
}

async function pressSayIt() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Say it" }));
  });
}

describe("asking for the microphone", () => {
  it("records straight away when the microphone is already allowed", async () => {
    permission = "granted";
    renderButton();
    await pressSayIt();
    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: /Stop/ })).toBeTruthy();
  });

  it("explains first when the browser has not asked yet, then lets the browser ask", async () => {
    renderButton();
    await pressSayIt();
    const dialog = screen.getByRole("dialog", { name: "Allow your microphone" });
    expect(dialog.textContent).toContain("Your browser will ask to use the microphone; choose Allow.");
    expect(getUserMedia).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Allow microphone" }));
    });
    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: /Stop/ })).toBeTruthy();
  });

  it("explains first when the browser cannot say whether it is allowed", async () => {
    permission = "throws";
    renderButton();
    await pressSayIt();
    expect(screen.getByRole("dialog", { name: "Allow your microphone" })).toBeTruthy();
  });

  it("says how to unblock a blocked microphone, and tries again", async () => {
    permission = "denied";
    renderButton();
    await pressSayIt();
    const dialog = screen.getByRole("dialog", { name: "Your microphone is blocked" });
    expect(dialog.textContent).toContain("set Microphone to Allow, then press Try again.");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    });
    expect(getUserMedia).toHaveBeenCalledOnce();
  });

  it("turns into the blocked state when the person refuses the browser's prompt", async () => {
    getUserMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    renderButton();
    await pressSayIt();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Allow microphone" }));
    });
    expect(screen.getByRole("dialog", { name: "Your microphone is blocked" })).toBeTruthy();
  });

  it("says so when the device has no microphone", async () => {
    permission = "granted";
    getUserMedia.mockRejectedValue(new DOMException("none", "NotFoundError"));
    renderButton();
    await pressSayIt();
    expect(screen.getByRole("alert").textContent).toBe("No microphone found on this device.");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes and hands over to the text box on Type it instead", async () => {
    const onTypeInstead = renderButton();
    await pressSayIt();
    fireEvent.click(screen.getByRole("button", { name: "Type it instead" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(onTypeInstead).toHaveBeenCalledOnce());
  });

  it("closes on Escape", async () => {
    renderButton();
    await pressSayIt();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
