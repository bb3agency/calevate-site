/**
 * The frames of the auth screens' voice band (`components/illustration/voiceWave.tsx`):
 * a speech waveform drawn in ASCII, as a pure function of grid size and time.
 *
 * The figure echoes the logo, a waveform between brackets: sound starts at the centre of
 * the band and travels outward, so the middle is "now" and each edge shows what was said a
 * moment ago. Loudness comes in phrases with pauses between them, and syllables inside a
 * phrase, so it reads as someone talking rather than as a looping sine. In a pause the band
 * settles to a flat line, the way a quiet call looks on a meter.
 *
 * Pure and deterministic (no `Math.random`, no clock), so a test can pin a frame and the
 * reduced-motion still is the same picture on every load.
 */

/** Characters from silent to loud. Every cell of every frame is one of these. */
export const VOICE_RAMP = " .:-=+*#%@";

/**
 * The instant the reduced-motion still is taken at: mid-phrase, so a reader who asked for
 * no motion still sees a voice rather than a flat line.
 */
export const STILL_TIME = 7.4;

/** Seconds sound takes to travel from the centre to either edge. */
const TRAVEL_S = 1.8;

// ---------------------------------------------------------------------------
// 2D simplex noise, after Stefan Gustavson's public-domain reference ("Simplex noise
// demystified", 2005). Hand-written here so the band adds no dependency (hard rule 9).
// ---------------------------------------------------------------------------

const GRAD: ReadonlyArray<readonly [number, number]> = [
  [1, 1], [-1, 1], [1, -1], [-1, -1],
  [1, 0], [-1, 0], [1, 0], [-1, 0],
  [0, 1], [0, -1], [0, 1], [0, -1],
];
const F2 = 0.5 * (Math.sqrt(3) - 1);
const G2 = (3 - Math.sqrt(3)) / 6;

/** A fixed shuffle of 0..255, doubled so `perm[i + perm[j]]` never needs a wrap. */
const PERM: Uint8Array = (() => {
  const p = Array.from({ length: 256 }, (_, i) => i);
  let seed = 0x2f6b3d; // any constant; fixed so every frame is reproducible
  for (let i = 255; i > 0; i--) {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const j = seed % (i + 1);
    [p[i], p[j]] = [p[j]!, p[i]!];
  }
  const out = new Uint8Array(512);
  for (let i = 0; i < 512; i++) out[i] = p[i & 255]!;
  return out;
})();

function corner(gi: number, x: number, y: number): number {
  const t = 0.5 - x * x - y * y;
  if (t < 0) return 0;
  const g = GRAD[gi % 12]!;
  const t2 = t * t;
  return t2 * t2 * (g[0] * x + g[1] * y);
}

/** Smooth noise in roughly [-1, 1]. */
export function simplex2(xin: number, yin: number): number {
  const s = (xin + yin) * F2;
  const i = Math.floor(xin + s);
  const j = Math.floor(yin + s);
  const t = (i + j) * G2;
  const x0 = xin - (i - t);
  const y0 = yin - (j - t);
  const i1 = x0 > y0 ? 1 : 0;
  const j1 = x0 > y0 ? 0 : 1;
  const x1 = x0 - i1 + G2;
  const y1 = y0 - j1 + G2;
  const x2 = x0 - 1 + 2 * G2;
  const y2 = y0 - 1 + 2 * G2;
  const ii = i & 255;
  const jj = j & 255;
  const n0 = corner(PERM[ii + PERM[jj]!]!, x0, y0);
  const n1 = corner(PERM[ii + i1 + PERM[jj + j1]!]!, x1, y1);
  const n2 = corner(PERM[ii + 1 + PERM[jj + 1]!]!, x2, y2);
  return 70 * (n0 + n1 + n2);
}

// ---------------------------------------------------------------------------

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function smoothstep(edge0: number, edge1: number, v: number): number {
  const x = clamp01((v - edge0) / (edge1 - edge0));
  return x * x * (3 - 2 * x);
}

/** How loud the speaker is at time `tau`, 0..1: phrases with pauses, syllables inside. */
function loudness(tau: number): number {
  const phrase = smoothstep(-0.25, 0.3, simplex2(tau * 0.3, 11.7));
  const syllable = 0.5 + 0.5 * simplex2(tau * 2.2, 3.1);
  return phrase * (0.3 + 0.7 * syllable);
}

/**
 * One frame: `rows` strings of exactly `cols` characters, every one from `VOICE_RAMP`.
 * Non-integer sizes are floored and anything below 1 gives an empty frame.
 */
export function voiceWaveFrame(cols: number, rows: number, timeS: number): string[] {
  const w = Math.max(0, Math.floor(cols));
  const h = Math.max(0, Math.floor(rows));
  if (w === 0 || h === 0) return [];

  const top = VOICE_RAMP.length - 1;
  const amp = new Float64Array(w);
  for (let x = 0; x < w; x++) {
    const u = w === 1 ? 0.5 : x / (w - 1);
    const fromCentre = Math.abs(u - 0.5) * 2;
    // Zero at both edges, so the band dissolves into the page instead of ending in a cut.
    const window = Math.pow(Math.sin(Math.PI * u), 0.7);
    // A little grain per column keeps the two halves from being exact mirror images.
    const grain = 0.12 * simplex2(u * 9, timeS * 0.9);
    amp[x] = clamp01((loudness(timeS - fromCentre * TRAVEL_S) + grain) * window);
  }

  const lines: string[] = [];
  const baseline = 1 / h + 1e-9;
  for (let y = 0; y < h; y++) {
    const v = Math.abs(h === 1 ? 0 : ((y + 0.5) / h) * 2 - 1);
    let line = "";
    for (let x = 0; x < w; x++) {
      const a = amp[x]!;
      let level = 0;
      if (v < a) {
        // Densest on the centre line and at the loudest columns, thinning toward the
        // envelope, so a loud syllable is a shape with an edge rather than a solid block.
        const falloff = 1 - v / a;
        const texture = 0.8 + 0.2 * simplex2(x * 0.7, y * 1.3 + timeS * 2.5);
        level = clamp01(Math.pow(a, 0.6) * (0.4 + 0.6 * falloff) * texture);
      }
      // The centre row never goes fully blank: silence is a line, not nothing.
      if (v < baseline) level = Math.max(level, 0.3);
      line += VOICE_RAMP[Math.round(level * top)];
    }
    lines.push(line);
  }
  return lines;
}
