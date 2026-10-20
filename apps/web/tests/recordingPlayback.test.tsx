import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CallDetailPage from "@/app/c/[slug]/calls/[callId]/page";
import { formatClock } from "@/components/callAudioPlayer";
import type { CallDetail, Me } from "@/lib/api/client";

import { renderClientPage } from "./harness";

/**
 * Listening to a call, and reading it at the same time.
 *
 * `tests/callDetail.test.tsx` owns the SAFETY claims about this screen — redaction by
 * default, no raw number in the DOM or an href, a refusal instead of an empty
 * transcript. This file owns the claims about the recording actually being usable,
 * which is a different question and was the one nobody had asked:
 *
 * 1. **The link outlives the audio.** A presigned URL that expires before the recording
 *    ends is not a link to that recording. The server derives the window from the call's
 *    duration; when it still expires, the player re-mints and RESTORES the position
 *    rather than dropping the listener back to zero.
 * 2. **One re-mint, then a refusal.** Re-signing in a loop against a bucket that is
 *    genuinely gone turns a broken recording into a request generator, and the person
 *    waiting is told nothing either way.
 * 3. **The transcript drives the audio.** Every turn carries `start_ms` and has since
 *    the pipeline was written; until now nothing read it. A turn is a seek target when —
 *    and only when — there is audio loaded AND that turn has a timestamp. Where either
 *    is missing it renders as text, never as a button that does nothing.
 * 4. **The turn being spoken is marked**, bounded by the NEXT turn's start rather than
 *    this turn's `end_ms`, which is nullable independently and would leave real gaps
 *    between adjacent turns unhighlighted.
 *
 * jsdom implements no media pipeline: `play()` is not a function on `HTMLMediaElement`
 * and `currentTime` never advances on its own. Both are stubbed BELOW rather than
 * mocked away, so what is under test is this component's logic against a real DOM
 * element, not a hand-written stand-in for one.
 */

// The route page reads its `params` as a promise (React 19 `use()`), so the harness
// takes a rendered ELEMENT rather than the component.
const page = (
  <CallDetailPage params={Promise.resolve({ slug: "acme", callId: "c1" })} />
);
const REC_PATH = "/v1/calls/c1/recording";

function me(over: Partial<Me> = {}): Me {
  return {
    user_id: "u1",
    realm: "client",
    role: "owner",
    permissions: ["calls:read", "leads:read"],
    impersonating: false,
    withheld_acts: [],
    organization: {
      id: "o1",
      name: "Sri Clinic",
      slug: "acme",
      status: "active",
    },
    ...over,
  };
}

function detail(over: Partial<CallDetail> = {}): CallDetail {
  return {
    id: "c1",
    agent_id: "a1",
    agent_name: "Reception",
    direction: "inbound",
    status: "completed",
    caller_e164: "+919876543210",
    sentiment: "positive",
    started_at: "2026-08-16T05:30:00Z",
    duration_s: 1200,
    outcome_tag: "call_back_booked",
    summary_state: "ready",
    test_call: false,
    caller_id_hidden: false,
    forwarding_test: false,
    forwarded_to_phone: false,
    translation_state: "not_needed",
    language: "te-IN",
    summary: "Caller asked for a Tuesday slot.",
    lead_id: "l1",
    extraction: {},
    extraction_valid: true,
    has_recording: true,
    disclosure_played: true,
    moments: [],
    quality: null,
    signals: [],
    captured: [],
    transcript: [
      {
        idx: 0,
        speaker: "agent",
        start_approximate: false, likely_cut_off: false,
        text: "Namaskaram.",
        redacted: true,
        start_ms: 0,
      },
      {
        idx: 1,
        speaker: "caller",
        start_approximate: false, likely_cut_off: false,
        text: "I need an appointment.",
        redacted: true,
        start_ms: 8000,
      },
      {
        idx: 2,
        speaker: "agent",
        start_approximate: false, likely_cut_off: false,
        text: "Tuesday at four?",
        redacted: true,
        start_ms: 21000,
      },
    ],
    ...over,
  };
}

function routes(d: CallDetail, extra: Record<string, unknown> = {}) {
  return {
    "/v1/me": me(),
    "/v1/calls/c1": d,
    "/v1/calls/c1/callback": {
      eligible: false,
      reason: "This call was answered.",
      rule: null,
    },
    ...extra,
  };
}

const LINK = {
  url: "https://cdn.example.test/rec.mp3?sig=one",
  expires_in_s: 2400,
  duration_s: 1200,
};

/**
 * jsdom has no media stack. Give `HTMLMediaElement` just enough to be driven: a `play`
 * that resolves, a settable `currentTime`, and a `duration` the component can read.
 * Everything else — events, attributes, the element itself — stays real.
 */
beforeEach(() => {
  Object.defineProperty(HTMLMediaElement.prototype, "play", {
    configurable: true,
    value: vi.fn().mockResolvedValue(undefined),
  });
  Object.defineProperty(HTMLMediaElement.prototype, "pause", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLMediaElement.prototype, "duration", {
    configurable: true,
    get: () => 1200,
  });
  let time = 0;
  Object.defineProperty(HTMLMediaElement.prototype, "currentTime", {
    configurable: true,
    get: () => time,
    set: (v: number) => {
      time = v;
    },
  });
});

async function openPlayer(
  extra: Record<string, unknown> = {},
  d: CallDetail = detail(),
) {
  const rendered = await renderClientPage(
    page,
    routes(d, { [REC_PATH]: LINK, ...extra }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /listen to this call/i }),
  );
  await screen.findByRole("button", { name: /play recording/i });
  return rendered;
}

describe("the recording player", () => {
  it("renders real controls rather than the browser's default element", async () => {
    const { container } = await openPlayer();

    // The three the native element cannot give a call reviewer: speed (the most-used
    // control when someone checks twenty calls), skip, and a seek bar its siblings can
    // drive. Asserted by accessible name so this fails if they become icon-only.
    expect(
      screen.getByRole("button", { name: /playback speed/i }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /back 10 seconds/i }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /forward 10 seconds/i }),
    ).toBeTruthy();
    expect(
      screen.getByRole("slider", { name: /seek within the recording/i }),
    ).toBeTruthy();
    // `controls` would give the user TWO transports for one element, and the native one
    // is the one without the speed control.
    expect(container.querySelector("audio")?.hasAttribute("controls")).toBe(
      false,
    );
  });

  it("draws the seek bar from the call's metered length before the audio reports one", async () => {
    await openPlayer();
    const slider = screen.getByRole("slider", {
      name: /seek within the recording/i,
    });
    // 1200 s. `<audio>.duration` is NaN until enough of the file has been fetched, and a
    // scrubber whose maximum arrives a second late is one people click through.
    expect(slider.getAttribute("max")).toBe("1200");
    // On the player itself — the call's header prints the same length.
    expect(slider.parentElement?.parentElement?.textContent).toContain("20:00");
  });

  it("cycles the playback speed rather than hiding it in a context menu", async () => {
    await openPlayer();
    const speed = screen.getByRole("button", { name: /playback speed/i });
    expect(speed.textContent).toContain("1×");
    fireEvent.click(speed);
    expect(
      screen.getByRole("button", { name: /playback speed/i }).textContent,
    ).toContain("1.25×");
  });

  it("seeks to a turn when the transcript is clicked", async () => {
    const { container } = await openPlayer();

    // 8000 ms in. The label carries the timestamp so a screen reader user knows where
    // the control goes before activating it.
    const turn = screen.getByRole("button", { name: /play from 0:08/i });
    fireEvent.click(turn);

    expect(container.querySelector("audio")?.currentTime).toBe(8);
  });

  it("shows a line's rough time once and names its control in words", async () => {
    // The bubble used to read "Play from ~0:09~0:09": a screen-reader span and the visible
    // time were both text in the button. Visible: "~0:09" once. Name: "Play from about 0:09".
    await openPlayer(
      {},
      detail({
        transcript: [
          {
            idx: 0,
            speaker: "agent",
            start_approximate: true, likely_cut_off: false,
            text: "Namaskaram.",
            redacted: true,
            start_ms: 9000,
          },
        ],
      }),
    );
    const turn = screen.getByRole("button", { name: "Play from about 0:09" });
    expect(turn.textContent).toBe("Namaskaram.~0:09");
    expect(turn.getAttribute("aria-describedby")).toBeTruthy();
    expect(document.getElementById(turn.getAttribute("aria-describedby")!)?.textContent).toBe(
      "Namaskaram.",
    );
  });

  it("leaves a turn as plain text when there is no audio loaded", async () => {
    // The link is never minted, so nothing can be sought. A clickable turn here would
    // be a control that silently does nothing — worse than no control.
    await renderClientPage(page, routes(detail(), { [REC_PATH]: LINK }));
    await screen.findByText("I need an appointment.");
    expect(
      screen.queryByRole("button", { name: /play from 0:08/i }),
    ).toBeNull();
  });

  it("leaves a turn as plain text when that turn carries no timestamp", async () => {
    // `start_ms` is nullable by design — an engine that gives us no per-turn offsets is
    // a supported engine — so the seek affordance is per TURN, not per screen.
    await openPlayer(
      {},
      detail({
        transcript: [
          {
            idx: 0,
            speaker: "agent",
            start_approximate: false, likely_cut_off: false,
            text: "Namaskaram.",
            redacted: true,
            start_ms: 0,
          },
          {
            idx: 1,
            speaker: "caller",
            start_approximate: false, likely_cut_off: false,
            text: "No offsets here.",
            redacted: true,
          },
        ],
      }),
    );
    expect(
      screen.getByRole("button", { name: /play from 0:00/i }),
    ).toBeTruthy();
    const untimed = screen.getByText("No offsets here.");
    expect(untimed.closest("button")).toBeNull();
  });

  it("re-mints an expired link and puts the listener back where they were", async () => {
    const { container, calls } = await openPlayer();
    const audio = container.querySelector("audio")!;
    const minted = () => calls.filter((c) => c.path === REC_PATH).length;
    expect(minted()).toBe(1);

    audio.currentTime = 640;
    fireEvent.error(audio);

    // A SECOND mint was asked for — the behaviour the bare <audio> did not have. S3
    // answers an expired signature with a 403, which the element surfaces as a generic
    // media error and nothing else; without this the listener simply lost the call.
    await vi.waitFor(() => expect(minted()).toBe(2));

    // A REAL <audio> rewinds to 0 when its `src` changes, and this stub must too — the
    // first version of this test kept the old value in a closure across the swap, so it
    // passed with the restore deleted. That is the whole assertion, so simulating the
    // rewind is not scaffolding; it is the precondition the restore has to survive.
    audio.currentTime = 0;
    fireEvent.loadedMetadata(audio);

    // Position survived. Dropping someone back to 0:00 eleven minutes into a
    // twenty-minute call is the same loss in a politer form.
    expect(audio.currentTime).toBe(640);
  });

  it("stops after one re-mint and says so, rather than looping on a dead object", async () => {
    const { container, calls } = await openPlayer();
    const audio = container.querySelector("audio")!;
    const minted = () => calls.filter((c) => c.path === REC_PATH).length;

    fireEvent.error(audio);
    await vi.waitFor(() => expect(minted()).toBe(2));
    fireEvent.error(audio);
    await screen.findByRole("alert");

    // Still two. An object that is genuinely gone must not turn this screen into a
    // signing-request generator against our own bucket, and the person waiting is told
    // in words instead of watching a control that never starts.
    expect(minted()).toBe(2);
    expect(screen.getByRole("alert").textContent).toMatch(
      /could not be reloaded/i,
    );
  });

  it("does not re-arm the guard when its own re-minted link comes back as a new src", async () => {
    // The parent stores the fresh link and hands it straight back down as `src`. When the
    // server signs a DIFFERENT url each time (it does), that used to reset the one-retry
    // guard, so a dead object re-minted forever, each mint an audited read.
    let n = 0;
    const { container, calls } = await openPlayer({
      [REC_PATH]: () => ({ ...LINK, url: `https://cdn.example.test/rec.mp3?sig=${++n}` }),
    });
    const minted = () => calls.filter((c) => c.path === REC_PATH).length;
    const audio = () => container.querySelector("audio")!;

    fireEvent.error(audio());
    await vi.waitFor(() => expect(minted()).toBe(2));
    fireEvent.error(audio());
    await screen.findByRole("alert");
    // A file that never plays errors on every src. However often, the card mints once more
    // and no further, even if the player were remounted (the guard lives on the card too).
    for (let i = 0; i < 4; i++) {
      fireEvent.error(audio());
      await new Promise((r) => setTimeout(r, 10));
    }

    expect(minted()).toBe(2);
    expect(screen.getByRole("alert").textContent).toMatch(/could not be reloaded/i);
  });
});

describe("key moments in the call", () => {
  const MOMENTS = [
    {
      at_ms: 8_000,
      turn_idx: 1,
      kind: "field_captured",
      category: "details",
      label: "Appointment slot captured",
      source: "derived",
      precision: "exact",
      importance: 2,
    },
    {
      at_ms: 21_000,
      turn_idx: 2,
      kind: "asked_delivery_or_payment",
      category: "buying",
      label: "Caller asked about payment",
      source: "model",
      precision: "approximate",
      importance: 2,
    },
    {
      at_ms: 34_000,
      turn_idx: null,
      kind: "opt_out",
      category: "attention",
      label: "Caller asked not to be called again",
      source: "derived",
      precision: "exact",
      importance: 3,
    },
  ] satisfies CallDetail["moments"];

  function momentRows() {
    return Array.from(
      screen.getByRole("heading", { name: /^key moments$/i }).closest("section")!.querySelectorAll("li"),
    );
  }

  it("is not rendered at all when the call has none", async () => {
    // An always-present "Key points" heading over an empty box on every short call is a
    // heading people learn to skip — and then miss on the call that has six.
    await renderClientPage(
      page,
      routes(detail({ moments: [] }), { [REC_PATH]: LINK }),
    );
    await screen.findByText("I need an appointment.");
    expect(screen.queryByText(/^key moments$/i)).toBeNull();
  });

  it("lists each moment with its time, its group and, when approximate, a ~", async () => {
    await renderClientPage(
      page,
      routes(detail({ moments: MOMENTS }), { [REC_PATH]: LINK }),
    );
    await screen.findByText(/^key moments$/i);
    expect(momentRows().map((li) => li.textContent)).toEqual([
      "0:08Appointment slot capturedDetails",
      "~0:21Caller asked about paymentBuying signal· Suggested",
      "0:34Caller asked not to be called againNeeds attention",
    ]);
    expect(screen.getByText(/times marked ~ are approximate/i)).toBeTruthy();
  });

  it("marks only the model's moment as suggested", async () => {
    // The provenance is the trust signal (D-36): a model moment is a suggestion.
    await renderClientPage(
      page,
      routes(detail({ moments: MOMENTS }), { [REC_PATH]: LINK }),
    );
    await screen.findByText(/^key moments$/i);
    const suggested = momentRows().filter((li) => li.textContent?.includes("Suggested"));
    expect(suggested.map((li) => li.textContent)).toEqual([
      "~0:21Caller asked about paymentBuying signal· Suggested",
    ]);
  });

  it("seeks to an exact moment, and a couple of seconds early to an approximate one", async () => {
    const { container } = await openPlayer({}, detail({ moments: MOMENTS }));
    fireEvent.click(screen.getByRole("button", { name: /play from 0:34/i }));
    expect(container.querySelector("audio")?.currentTime).toBe(34);
    fireEvent.click(screen.getByRole("button", { name: /play from about 0:21/i }));
    expect(container.querySelector("audio")?.currentTime).toBe(19);
  });

  it("opens the recording at the moment when it is pressed before the audio is loaded", async () => {
    const { container } = await renderClientPage(
      page,
      routes(detail({ moments: MOMENTS }), { [REC_PATH]: LINK }),
    );
    await screen.findByText(/^key moments$/i);
    expect(container.querySelector("audio")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /play from 0:34/i }));
    await screen.findByRole("button", { name: /pause recording|play recording/i });
    expect(container.querySelector("audio")?.currentTime).toBe(34);
  });

  it("draws a labelled marker for each moment on the recording's track", async () => {
    const { container } = await openPlayer({}, detail({ moments: MOMENTS }));
    const labels = Array.from(container.querySelectorAll("button[data-mark]")).map(
      (b) => b.textContent,
    );
    expect(labels).toEqual([
      "0:08 Appointment slot captured",
      "~0:21 Caller asked about payment",
      "0:34 Caller asked not to be called again",
    ]);
  });
});

describe("formatClock", () => {
  it("shows hours only when there are hours", () => {
    // A 2:17 call rendered as 0:02:17 is noise on every row; a 1:02:10 call rendered as
    // 62:10 is a number a person has to divide.
    expect(formatClock(137)).toBe("2:17");
    expect(formatClock(3730)).toBe("1:02:10");
  });

  it("answers 0:00 for the values a media element really produces", () => {
    // `<audio>.duration` is NaN before metadata and `currentTime` can be -0 after a
    // seek to the very start. Neither may render as "NaN:aN" on a client's screen.
    expect(formatClock(Number.NaN)).toBe("0:00");
    expect(formatClock(-1)).toBe("0:00");
  });
});
