import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VoicePreviewButton } from "@/components/voicePreviewButton";
import type { Session } from "@/lib/api/client";

const clip = { data: undefined as Blob | undefined, isFetching: false, isError: false, error: null, refetch: vi.fn() };
vi.mock("@/lib/api/voicePreview", () => ({ useVoicePreview: () => clip }));

const session = { orgSlug: "acme" } as unknown as Session;

describe("a voice preview the browser will not start", () => {
  beforeEach(() => {
    clip.data = undefined;
    URL.createObjectURL = vi.fn(() => "blob:clip");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it("says the clip is ready and to tap again, rather than silently going back to Play", async () => {
    // The first press fetches the clip; play() then runs after the press, which a browser
    // that starts sound only from a tap refuses with NotAllowedError.
    vi.spyOn(HTMLMediaElement.prototype, "play").mockRejectedValue(
      new DOMException("play() needs a user gesture", "NotAllowedError"),
    );
    const { rerender } = render(
      <VoicePreviewButton session={session} path="/v1/voices/preview" voiceId="v1" label="Asha" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Play the preview of Asha" }));
    clip.data = new Blob(["x"], { type: "audio/mpeg" });
    await act(async () => {
      rerender(<VoicePreviewButton session={session} path="/v1/voices/preview" voiceId="v1" label="Asha" />);
    });

    expect(await screen.findByText("Ready. Tap again to listen.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Play the preview of Asha" })).toBeTruthy();

    // The next press starts it and the line goes.
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Play the preview of Asha" }));
    expect(screen.queryByText("Ready. Tap again to listen.")).toBeNull();
  });
});
