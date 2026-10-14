import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VoiceNow } from "@/app/c/[slug]/agents/panels/publishing";
import type { PendingState } from "@/lib/api/publishing";

import { settledPending } from "./fixtures/sharedReads";

/** A voice the calling platform supplies: no provider of ours and no catalogue entry. */
const anika = { voice_id: "engine:anika", provider: null, voice_tier: "clear", catalog: null };

function engineVoiceState(published: boolean): PendingState {
  return settledPending({
    published,
    voice: {
      configured: anika,
      live: published ? anika : null,
      republish_required: false,
      unnamed_note: null,
      headline: published
        ? "Callers hear Anika."
        : "This agent is not on the voice platform yet; publishing it will use Anika.",
    },
  });
}

describe("VoiceNow with a voice the calling platform supplies", () => {
  it("says the voice is chosen, names it through the server's headline, and prices its rung", () => {
    render(<VoiceNow state={engineVoiceState(true)} published />);

    expect(screen.getByText("Chosen")).toBeTruthy();
    expect(screen.getByText("Callers hear Anika.")).toBeTruthy();
    expect(screen.getByText("Voice quality and rate")).toBeTruthy();
    expect(screen.getByText(/Clear — ₹2\.50 \/ min/)).toBeTruthy();
  });

  it("says it is used once switched on before the agent is published, with no rate yet", () => {
    render(<VoiceNow state={engineVoiceState(false)} published={false} />);

    expect(screen.getByText("Chosen, used once switched on")).toBeTruthy();
    expect(
      screen.getByText("This agent is not on the voice platform yet; publishing it will use Anika."),
    ).toBeTruthy();
    // The rate priced is the LIVE voice's, and nothing is live yet.
    expect(screen.queryByText("Voice quality and rate")).toBeNull();
  });
});
