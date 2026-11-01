import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import VoiceComparisonPage from "@/app/admin/ops/voice-comparison/page";
import {
  COMPARISON_ROUNDS_PATH,
  COMPARISON_SENTENCES_PATH,
  COMPARISON_SETUP_PATH,
  COMPARISON_VOICES_PATH,
  SETUP_CONFIRMATION,
  roundPath,
  trialPath,
  type ComparisonSummary,
} from "@/lib/api/opsVoiceComparison";

import {
  COMPARISON_ROUND,
  COMPARISON_ROUNDS,
  COMPARISON_ROUND_ID as ROUND_ID,
  COMPARISON_SENTENCES,
  COMPARISON_SETUP,
  COMPARISON_TRIAL_ID as TRIAL_ID,
  COMPARISON_VOICES,
} from "./fixtures/voiceComparison";
import { problem, renderAdminPage, stubDownloads } from "./harness";

/**
 * Ops > Voice comparison (D-946). What the screen must get right, worst failure first:
 *
 * 1. Before a round is finished nothing on screen names a voice or a provider.
 * 2. A rating sends both scores and the preference for the pair named.
 * 3. The set-up sends the server's confirmation string.
 * 4. It fits a 375px phone and a session without ops:manage is told so.
 */

const SUPERADMIN: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000e1",
  realm: "admin",
  role: "superadmin",
  permissions: ["ops:manage"],
};

const OPERATOR: AdminMe = {
  ...SUPERADMIN,
  role: "operator",
  permissions: ["org:read"],
};

const SUMMARY: ComparisonSummary = {
  round_id: ROUND_ID,
  finished_at: "2026-11-01T07:00:00Z",
  pairs: 1,
  no_preference: 0,
  voices: [
    {
      provider: "cartesia",
      vendor_id: "car-1",
      label: "Priya Studio",
      heard: 1,
      mean_naturalness: 4,
      preferred: 1,
      not_preferred: 0,
      no_preference: 0,
    },
    {
      provider: "sarvam",
      vendor_id: "anushka",
      label: "Anushka",
      heard: 1,
      mean_naturalness: 3,
      preferred: 0,
      not_preferred: 1,
      no_preference: 0,
    },
  ],
  providers: [
    {
      provider: "cartesia",
      voices: 1,
      heard: 1,
      mean_naturalness: 4,
      preferred: 1,
      preferred_share: 1,
      characters: 17,
    },
    {
      provider: "sarvam",
      voices: 1,
      heard: 1,
      mean_naturalness: 3,
      preferred: 0,
      preferred_share: 0,
      characters: 17,
    },
  ],
  cost_note: "Each provider bills our own account per character spoken.",
};

function routes(extra: Record<string, unknown> = {}) {
  return {
    [ADMIN_ME_PATH]: SUPERADMIN,
    [COMPARISON_SETUP_PATH]: COMPARISON_SETUP,
    [`POST ${COMPARISON_SETUP_PATH}`]: COMPARISON_SETUP,
    [COMPARISON_VOICES_PATH]: COMPARISON_VOICES,
    [COMPARISON_SENTENCES_PATH]: COMPARISON_SENTENCES,
    [COMPARISON_ROUNDS_PATH]: COMPARISON_ROUNDS,
    [`POST ${COMPARISON_ROUNDS_PATH}`]: COMPARISON_ROUND,
    [roundPath(ROUND_ID)]: COMPARISON_ROUND,
    [`PUT ${trialPath(TRIAL_ID)}`]: {
      ...COMPARISON_ROUND.trials[0],
      rating_a: 4,
      rating_b: 2,
      preference: "a",
      rated: true,
    },
    ...extra,
  };
}

function header(headers: Record<string, string> | undefined, name: string) {
  return Object.entries(headers ?? {}).find(
    ([k]) => k.toLowerCase() === name,
  )?.[1];
}

let restore: (() => void) | null = null;
afterEach(() => {
  restore?.();
  restore = null;
});

describe("Ops > Voice comparison", () => {
  it("names no voice and no provider on a pair before the round is finished", async () => {
    renderAdminPage(<VoiceComparisonPage />, routes());
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    const pair = await screen.findByRole("region", { name: "Pair 1 of 1" });
    expect(
      within(pair).getByRole("button", { name: "Play Voice A" }),
    ).toBeTruthy();
    expect(
      within(pair).getByRole("button", { name: "Play Voice B" }),
    ).toBeTruthy();
    for (const hidden of [
      "Cartesia",
      "Sarvam",
      "Priya Studio",
      "Anushka",
      "car-1",
      "anushka",
    ]) {
      expect(pair.textContent).not.toContain(hidden);
    }
    expect(screen.queryByText("Priya Studio")).toBeNull();
  });

  it("rates a pair with both scores and the preference", async () => {
    const page = renderAdminPage(<VoiceComparisonPage />, routes());
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    const pair = await screen.findByRole("region", { name: "Pair 1 of 1" });
    fireEvent.click(
      within(
        within(pair).getByRole("group", { name: "Voice A: how natural?" }),
      ).getByLabelText("4"),
    );
    fireEvent.click(
      within(
        within(pair).getByRole("group", { name: "Voice B: how natural?" }),
      ).getByLabelText("2"),
    );
    fireEvent.click(within(pair).getByLabelText("Voice A"));
    fireEvent.click(
      within(pair).getByRole("button", { name: "Save and next" }),
    );
    await waitFor(() =>
      expect(page.calls.some((c) => c.method === "PUT")).toBe(true),
    );
    const put = page.calls.find((c) => c.method === "PUT");
    expect(put?.path).toBe(trialPath(TRIAL_ID));
    expect(JSON.parse(put?.body ?? "{}")).toEqual({
      rating_a: 4,
      rating_b: 2,
      preference: "a",
    });
  });

  it("loads a clip again when it is pressed after a failed load", async () => {
    // jsdom has no media playback; this file is isolated, so the stubs need no undoing.
    stubDownloads();
    HTMLMediaElement.prototype.play = () => Promise.resolve();
    let attempts = 0;
    const page = renderAdminPage(
      <VoiceComparisonPage />,
      routes({
        [`${trialPath(TRIAL_ID)}/audio?side=a`]: () => {
          attempts += 1;
          return attempts === 1
            ? problem(503, { title: "Unavailable", status: 503 })
            : new Response(new Blob(["RIFF"], { type: "audio/wav" }), {
                status: 200,
                headers: { "content-type": "audio/wav" },
              });
        },
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    const pair = await screen.findByRole("region", { name: "Pair 1 of 1" });
    const button = within(pair).getByRole("button", { name: "Play Voice A" });
    fireEvent.click(button);
    await within(pair).findByText(/Could not load Voice A/);
    await waitFor(() => expect(button.matches(":disabled")).toBe(false));
    fireEvent.click(button);
    await waitFor(() =>
      expect(
        page.calls.filter((c) => c.path.endsWith("/audio?side=a")),
      ).toHaveLength(2),
    );
    await waitFor(() =>
      expect(within(pair).queryByText(/Could not load Voice A/)).toBeNull(),
    );
  });

  it("starts a round with the picked voices and the default sentences", async () => {
    const page = renderAdminPage(<VoiceComparisonPage />, routes());
    fireEvent.click(await screen.findByLabelText(/Priya Studio/));
    fireEvent.click(screen.getByLabelText(/Anushka/));
    await screen.findByText("2 pairs to rate.");
    fireEvent.click(screen.getByRole("button", { name: "Start the round" }));
    await waitFor(() =>
      expect(
        page.calls.some(
          (c) => c.method === "POST" && c.path === COMPARISON_ROUNDS_PATH,
        ),
      ).toBe(true),
    );
    const post = page.calls.find(
      (c) => c.method === "POST" && c.path === COMPARISON_ROUNDS_PATH,
    );
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      title: "",
      language: "te-IN",
      cartesia_voice_ids: ["car-1"],
      sarvam_voice_ids: ["anushka"],
      sentences: ["నమస్కారం అండి", "వన్ ట్వంటీ రూపీస్"],
    });
  });

  it("sets up Sarvam voices with the server's confirmation string", async () => {
    const page = renderAdminPage(<VoiceComparisonPage />, routes());
    fireEvent.click(
      await screen.findByRole("button", { name: "Set up Sarvam voices" }),
    );
    await waitFor(() =>
      expect(
        page.calls.some(
          (c) => c.method === "POST" && c.path === COMPARISON_SETUP_PATH,
        ),
      ).toBe(true),
    );
    const post = page.calls.find(
      (c) => c.method === "POST" && c.path === COMPARISON_SETUP_PATH,
    );
    expect(header(post?.headers, "x-confirm-action")).toBe(SETUP_CONFIRMATION);
  });

  it("reveals the providers once the round is finished, with the CSV", async () => {
    const finished = {
      ...COMPARISON_ROUND,
      finished_at: "2026-11-01T07:00:00Z",
      rated: 1,
    };
    renderAdminPage(
      <VoiceComparisonPage />,
      routes({
        [roundPath(ROUND_ID)]: finished,
        [`${roundPath(ROUND_ID)}/summary`]: SUMMARY,
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    const table = await screen.findByRole("table", {
      name: "Each voice, revealed",
    });
    expect(within(table).getByText("Priya Studio")).toBeTruthy();
    expect(within(table).getByText("Sarvam")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeTruthy();
  });

  it("fits a 375px phone: the two voices stack and every choice row wraps", async () => {
    const width = window.innerWidth;
    window.innerWidth = 375;
    restore = () => {
      window.innerWidth = width;
    };
    renderAdminPage(<VoiceComparisonPage />, routes());
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    const pair = await screen.findByRole("region", { name: "Pair 1 of 1" });
    const sides = within(pair)
      .getByRole("button", { name: "Play Voice A" })
      .closest(".flex-col");
    expect(sides?.className).toContain("sm:flex-row");
    for (const group of within(pair).getAllByRole("group")) {
      const row = group.querySelector("div");
      expect(row?.className).toContain("flex-wrap");
    }
    // Nothing on the screen asks for a fixed width wider than the phone.
    expect(document.body.innerHTML).not.toMatch(
      /\b(min-)?w-\[(3[5-9]\d|[4-9]\d\d)px\]/,
    );
  });

  it("tells a session without ops:manage that it may not run the comparison", async () => {
    const page = renderAdminPage(
      <VoiceComparisonPage />,
      routes({ [ADMIN_ME_PATH]: OPERATOR }),
    );
    expect(
      await screen.findByText(/run the blind voice comparison/),
    ).toBeTruthy();
    expect(
      page.calls.some((c) => c.path.startsWith("/v1/ops/voice-comparison")),
    ).toBe(false);
  });
});
