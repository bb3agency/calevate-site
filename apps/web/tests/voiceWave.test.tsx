import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthPageFrame } from "@/components/authPage";
import { VoiceWave } from "@/components/illustration/voiceWave";
import {
  LANE_ROWS,
  STILL_TIME,
  VOICE_RAMP,
  inkLayers,
  voiceField,
  voiceWaveFrame,
} from "@/lib/voiceWave";

/**
 * The auth screens' voice field: the frame generator's contract, and the component's
 * promises to a reader who cannot or does not want to see it move.
 */

describe("voiceField", () => {
  it.each([
    [1, 1],
    [7, 3],
    [37, 81], // a phone at 10px type
    [150, 69], // a desktop at 13px type
  ])("is exactly %i columns by %i rows", (cols, rows) => {
    for (const t of [0, 1.25, STILL_TIME, 600]) {
      const { lines } = voiceField(cols, rows, t);
      expect(lines).toHaveLength(rows);
      for (const line of lines) expect(line).toHaveLength(cols);
    }
  });

  it("gives an empty frame for a grid with no room", () => {
    expect(voiceField(0, 7, 1).lines).toEqual([]);
    expect(voiceField(40, 0, 1).lines).toEqual([]);
    expect(voiceField(-3, 5, 1).lines).toEqual([]);
  });

  it("uses only characters from the ramp", () => {
    const allowed = new Set(VOICE_RAMP);
    for (let t = 0; t < 30; t += 0.37) {
      for (const line of voiceField(80, 40, t).lines) {
        for (const ch of line) expect(allowed.has(ch)).toBe(true);
      }
    }
  });

  it("stacks as many lanes as fit, each centre line inside the grid", () => {
    const { centres } = voiceField(100, 70, 2);
    expect(centres.length).toBe(5);
    for (const c of centres) {
      expect(c).toBeGreaterThanOrEqual(0);
      expect(c).toBeLessThan(70);
    }
    expect(voiceField(100, LANE_ROWS - 4, 2).centres).toHaveLength(1);
  });

  it("moves with time and is deterministic for a given time", () => {
    expect(voiceField(60, 30, 2).lines).not.toEqual(voiceField(60, 30, 2.5).lines);
    expect(voiceField(60, 30, 2)).toEqual(voiceField(60, 30, 2));
  });

  it("takes its still at a moment of speech, not a pause", () => {
    const { lines, centres } = voiceField(60, 40, STILL_TIME);
    const offCentre = lines.filter((_, i) => !centres.includes(i));
    expect(offCentre.join("").trim()).not.toBe("");
  });

  it("gives each lane its own voice", () => {
    const a = voiceWaveFrame(60, 11, 3, { origin: 0.3, voice: 1 });
    const b = voiceWaveFrame(60, 11, 3, { origin: 0.3, voice: 2 });
    expect(a).not.toEqual(b);
  });
});

describe("inkLayers", () => {
  const { lines, centres } = voiceField(60, 40, STILL_TIME);
  const layers = inkLayers(lines, centres);

  it("splits a frame into three layers of its own shape that overlay back into it", () => {
    for (const layer of layers) {
      expect(layer).toHaveLength(40);
      for (const line of layer) expect(line).toHaveLength(60);
    }
    lines.forEach((line, row) => {
      [...line].forEach((ch, col) => {
        const inked = layers.map((l) => l[row]![col]).filter((c) => c !== " ");
        expect(inked).toEqual(ch === " " ? [] : [ch]);
      });
    });
  });

  it("puts the loud peaks in full ink and the quiet texture in faint ink", () => {
    expect(layers[2].join("")).toMatch(/[#%@]/);
    expect(layers[2].join("")).not.toMatch(/[.:\-=+*]/);
    expect(layers[0].join("")).not.toMatch(/[=+*#%@]/);
  });

  it("draws a centre line at least in mid ink, so a pause is a crisp line", () => {
    const pause = inkLayers(["     ", ".:-.:", "     "], [1]);
    expect(pause[1][1]).toBe(".:-.:");
    expect(pause[0][1]!.trim()).toBe("");
  });
});

describe("the contained band", () => {
  const loudRows = (lines: string[]) => lines.filter((line) => /[#%@*+]/.test(line)).length;

  it("is one lane as tall as the band, centred, with its centre line a row", () => {
    const { lines, centres } = voiceField(90, 8, STILL_TIME, { band: true });
    expect(lines).toHaveLength(8);
    expect(centres).toEqual([3]);
    expect(lines.every((line) => line.length === 90)).toBe(true);
  });

  it("is mid-speech in its still frame, the peaks reaching the band's edges", () => {
    const { lines } = voiceField(90, 7, STILL_TIME, { band: true });
    expect(loudRows(lines)).toBeGreaterThanOrEqual(5);
    expect(/[^ ]/.test(lines[0]!) && /[^ ]/.test(lines[6]!)).toBe(true);
  });

  it("talks most of the time: most moments show a waveform, not a flat line", () => {
    const moments = Array.from({ length: 120 }, (_, i) => i * 0.5);
    const talking = moments.filter((t) => loudRows(voiceField(90, 7, t, { band: true }).lines) >= 3);
    expect(talking.length / moments.length).toBeGreaterThan(0.7);
  });

  it("leaves the full-screen field as it was", () => {
    expect(voiceField(62, 81, STILL_TIME, {}).lines).toEqual(voiceField(62, 81, STILL_TIME).lines);
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
    // jsdom applies no Tailwind, so the field's `text-[10px]` is stated here.
    vi.spyOn(window, "getComputedStyle").mockReturnValue({
      fontSize: "10px",
      fontFamily: "monospace",
      color: "rgb(15, 107, 61)",
    } as CSSStyleDeclaration);
    return drawn;
  }

  afterEach(() => vi.restoreAllMocks());

  it("is hidden from assistive technology, inert to the pointer and holds nothing focusable", () => {
    const { container } = render(<VoiceWave />);
    const canvas = container.querySelector("canvas");
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
    expect(canvas?.className).toContain("pointer-events-none");
    expect(canvas?.className).toContain("fixed");
    expect(container.querySelectorAll("[tabindex], a, button, input")).toHaveLength(0);
  });

  it("draws one still frame under reduced motion and schedules no animation", () => {
    // `tests/setup.ts` answers `prefers-reduced-motion: reduce`, as jsdom has no motion.
    const raf = vi.spyOn(window, "requestAnimationFrame");
    const drawn = stubCanvas(375, 812);
    render(<VoiceWave />);
    // 375px / 6px cells = 62 columns; 812px / 10px lines = 81 rows.
    const { lines, centres } = voiceField(62, 81, STILL_TIME);
    expect(drawn.at(-1)).toEqual(inkLayers(lines, centres).flat());
    expect(raf).not.toHaveBeenCalled();
  });

  it("contained, fills its parent instead of the viewport, and stops when it scrolls out of view", () => {
    const observed: Element[] = [];
    let report: (entries: { isIntersecting: boolean }[]) => void = () => {};
    class Observer {
      constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
        report = callback;
      }
      observe(element: Element) {
        observed.push(element);
      }
      disconnect() {}
    }
    vi.stubGlobal("IntersectionObserver", Observer);
    const drawn = stubCanvas(320, 96);
    const { container, unmount } = render(<VoiceWave contained />);
    const canvas = container.querySelector("canvas");
    expect(canvas?.className).toContain("absolute");
    expect(canvas?.className).not.toContain("fixed");
    expect(canvas?.className).not.toContain("voice-field");
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
    expect(observed).toEqual([canvas]);
    // Reduced motion (tests/setup.ts): the one still frame, sized to the parent.
    const { lines, centres } = voiceField(53, 9, STILL_TIME, { band: true });
    expect(drawn.at(-1)).toEqual(inkLayers(lines, centres).flat());
    report([{ isIntersecting: false }]);
    unmount();
    vi.unstubAllGlobals();
  });

  it("full-screen, watches nothing: the fixed field is always in view", () => {
    const observe = vi.fn();
    vi.stubGlobal("IntersectionObserver", class { observe = observe; disconnect() {} });
    stubCanvas(375, 812);
    render(<VoiceWave />);
    expect(observe).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("is behind the public doors and not behind a signed-in settings page", () => {
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
