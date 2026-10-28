import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthPageFrame } from "@/components/authPage";
import { VoiceWave } from "@/components/illustration/voiceWave";
import { STILL_TIME, VOICE_RAMP, voiceWaveFrame } from "@/lib/voiceWave";

/**
 * The auth screens' voice band: the frame generator's contract, and the component's
 * promises to a reader who cannot or does not want to see it move.
 */

describe("voiceWaveFrame", () => {
  it.each([
    [1, 1],
    [7, 3],
    [62, 7],
    [120, 11],
  ])("is exactly %i columns by %i rows", (cols, rows) => {
    for (const t of [0, 1.25, STILL_TIME, 600]) {
      const frame = voiceWaveFrame(cols, rows, t);
      expect(frame).toHaveLength(rows);
      for (const line of frame) expect(line).toHaveLength(cols);
    }
  });

  it("gives an empty frame for a grid with no room", () => {
    expect(voiceWaveFrame(0, 7, 1)).toEqual([]);
    expect(voiceWaveFrame(40, 0, 1)).toEqual([]);
    expect(voiceWaveFrame(-3, 5, 1)).toEqual([]);
  });

  it("uses only characters from the ramp", () => {
    const allowed = new Set(VOICE_RAMP);
    for (let t = 0; t < 30; t += 0.37) {
      for (const line of voiceWaveFrame(80, 9, t)) {
        for (const ch of line) expect(allowed.has(ch)).toBe(true);
      }
    }
  });

  it("moves with time and is deterministic for a given time", () => {
    expect(voiceWaveFrame(60, 7, 2)).not.toEqual(voiceWaveFrame(60, 7, 2.5));
    expect(voiceWaveFrame(60, 7, 2)).toEqual(voiceWaveFrame(60, 7, 2));
  });

  it("takes its still at a moment of speech, not a pause", () => {
    const still = voiceWaveFrame(60, 7, STILL_TIME);
    // Off the centre line, something is drawn: the still shows a voice, not a flat line.
    expect(still.filter((_, i) => i !== 3).join("").trim()).not.toBe("");
  });
});

describe("<VoiceWave />", () => {
  /** A 2D context that records what was drawn, since jsdom has no canvas. */
  function stubCanvas(width: number, height: number) {
    const drawn: string[][] = [];
    let current: string[] = [];
    const ctx = {
      clearRect: () => {
        current = [];
        drawn.push(current);
      },
      fillText: (line: string) => current.push(line),
      measureText: (s: string) => ({ width: s.length * 6 }),
      setTransform: () => {},
      font: "",
      fillStyle: "",
      globalAlpha: 1,
      textBaseline: "alphabetic",
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      ctx as unknown as CanvasRenderingContext2D,
    );
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(width);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(height);
    // jsdom applies no Tailwind, so the band's `text-[10px]` is stated here.
    vi.spyOn(window, "getComputedStyle").mockReturnValue({
      fontSize: "10px",
      fontFamily: "monospace",
      color: "rgb(15, 107, 61)",
    } as CSSStyleDeclaration);
    return drawn;
  }

  afterEach(() => vi.restoreAllMocks());

  it("is hidden from assistive technology and holds nothing focusable", () => {
    const { container } = render(<VoiceWave />);
    const canvas = container.querySelector("canvas");
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
    expect(container.querySelectorAll("[tabindex], a, button, input")).toHaveLength(0);
  });

  it("draws one still frame under reduced motion and schedules no animation", () => {
    // `tests/setup.ts` answers `prefers-reduced-motion: reduce`, as jsdom has no motion.
    const raf = vi.spyOn(window, "requestAnimationFrame");
    const drawn = stubCanvas(360, 72);
    render(<VoiceWave />);
    // 360px / 6px cells = 60 columns; 72px / 10px lines = 7 rows (odd already).
    expect(drawn.at(-1)).toEqual(voiceWaveFrame(60, 7, STILL_TIME));
    expect(raf).not.toHaveBeenCalled();
  });

  it("is on the public doors and not on a signed-in settings page", () => {
    const door = render(
      <AuthPageFrame realmLabel="Client console">
        <p>form</p>
      </AuthPageFrame>,
    );
    expect(door.container.querySelectorAll("canvas[aria-hidden='true']")).toHaveLength(1);
    door.unmount();

    const settings = render(
      <AuthPageFrame realmLabel="Client console" ground="surface">
        <p>form</p>
      </AuthPageFrame>,
    );
    expect(settings.container.querySelectorAll("canvas")).toHaveLength(0);
  });
});
