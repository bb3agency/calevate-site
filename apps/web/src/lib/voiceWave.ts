/**
 * The frames of the auth screens' voice field (`components/illustration/voiceWave.tsx`):
 * speech waveforms drawn in ASCII, as a pure function of grid size and time.
 *
 * The figure echoes the logo, a waveform between brackets. The field is a stack of lanes,
 * each one a voice: sound starts at the lane's origin and travels outward, so the origin
 * is "now" and the ends show what was said a moment ago. Loudness comes in phrases with
 * pauses between them, and syllables inside a phrase, so each lane reads as someone talking
 * rather than as a looping sine; in a pause it settles to a flat line, the way a quiet call
 * looks on a meter. Lanes start at different points and speak independently, so the screen
 * reads as several calls in progress rather than one pattern repeated.
 *
 * Pure and deterministic (no `Math.random`, no clock), so a test can pin a frame and the
 * reduced-motion still is the same picture on every load.
 */

/** Characters from silent to loud. Every cell of every frame is one of these. */
export const VOICE_RAMP = " .:-=+*#%@";

/**
 * The instant the reduced-motion still is taken at: mid-phrase on most lanes, so a reader
 * who asked for no motion still sees voices rather than flat lines.
 */
export const STILL_TIME = 7.4;

/** Rows in one lane (odd, so a single row sits on its centre line) and blank rows between. */
export const LANE_ROWS = 11;
const LANE_GAP = 2;

/** Seconds sound takes to travel from a lane's origin to its far end. */
const TRAVEL_S = 1.8;

// ---------------------------------------------------------------------------
// 2D simplex noise, after Stefan Gustavson's public-domain reference ("Simplex noise
// demystified", 2005). Hand-written here so the field adds no dependency (hard rule 9).
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

/**
 * How loud a speaker is at time `tau`, 0..1: phrases with pauses, syllables inside. A
 * `talkative` speaker (the contained band, where one lane is the whole picture) is in a
 * phrase most of the time, with short pauses and a higher floor, so a glance finds speech.
 */
function loudness(tau: number, voice: number, talkative = false): number {
  const noise = simplex2(tau * 0.3, 11.7 + voice * 17.3);
  const phrase = talkative ? smoothstep(-0.85, -0.45, noise) : smoothstep(-0.4, 0.15, noise);
  const syllable = 0.5 + 0.5 * simplex2(tau * 2.2, 3.1 + voice * 29.1);
  return phrase * (talkative ? 0.55 + 0.45 * syllable : 0.4 + 0.6 * syllable);
}

/** One lane's voice: where along the row its sound starts (0..1), and which speaker. */
export interface Lane {
  origin: number;
  voice: number;
  /** Speech most of the time (`loudness`). */
  talkative?: boolean;
}

const CENTRE_LANE: Lane = { origin: 0.5, voice: 0 };

/**
 * One lane: `rows` strings of exactly `cols` characters, every one from `VOICE_RAMP`.
 * Non-integer sizes are floored and anything below 1 gives an empty frame.
 */
export function voiceWaveFrame(
  cols: number,
  rows: number,
  timeS: number,
  lane: Lane = CENTRE_LANE,
): string[] {
  const w = Math.max(0, Math.floor(cols));
  const h = Math.max(0, Math.floor(rows));
  if (w === 0 || h === 0) return [];

  const top = VOICE_RAMP.length - 1;
  const reach = Math.max(lane.origin, 1 - lane.origin);
  const amp = new Float64Array(w);
  for (let x = 0; x < w; x++) {
    const u = w === 1 ? 0.5 : x / (w - 1);
    const fromOrigin = Math.abs(u - lane.origin) / reach;
    // Sound fades as it travels, and thins right at the screen's edges.
    const decay = 1 - 0.45 * fromOrigin;
    const taper = Math.pow(Math.sin(Math.PI * u), 0.3);
    // A little grain per column keeps the two sides from being exact mirror images.
    const grain = 0.12 * simplex2(u * 9, timeS * 0.9 + lane.voice * 7.7);
    const level = clamp01(
      (loudness(timeS - fromOrigin * TRAVEL_S, lane.voice, lane.talkative) + grain) * decay * taper,
    );
    // A band is a few rows tall, so its swing is opened out: a syllable reaches near the
    // band's edges instead of staying a thin line through its middle.
    amp[x] = lane.talkative ? Math.pow(level, 0.55) : level;
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
        const texture = 0.8 + 0.2 * simplex2(x * 0.7, y * 1.3 + timeS * 2.5 + lane.voice * 5);
        level = clamp01(Math.pow(a, 0.5) * (0.45 + 0.6 * falloff) * texture);
      }
      // The centre row never goes fully blank: silence is a line, not nothing.
      if (v < baseline) level = Math.max(level, 0.3);
      line += VOICE_RAMP[Math.round(level * top)];
    }
    lines.push(line);
  }
  return lines;
}

/**
 * The whole field: as many lanes as fit `rows`, centred vertically, with their centre-line
 * row indices. `lines` is exactly `rows` strings of `cols` characters from `VOICE_RAMP`.
 */
export function voiceField(
  cols: number,
  rows: number,
  timeS: number,
  options: { band?: boolean } = {},
): { lines: string[]; centres: number[] } {
  const w = Math.max(0, Math.floor(cols));
  const h = Math.max(0, Math.floor(rows));
  if (w === 0 || h === 0) return { lines: [], centres: [] };
  if (options.band) return voiceBand(w, h, timeS);

  const pitch = LANE_ROWS + LANE_GAP;
  const lanes = Math.max(1, Math.floor((h + LANE_GAP) / pitch));
  const laneRows = h >= LANE_ROWS ? LANE_ROWS : h % 2 === 1 ? h : Math.max(1, h - 1);
  const used = lanes * laneRows + (lanes - 1) * LANE_GAP;
  const top = Math.floor((h - used) / 2);

  const blank = " ".repeat(w);
  const lines = Array.from({ length: h }, () => blank);
  const centres: number[] = [];
  for (let i = 0; i < lanes; i++) {
    // Origins swing across the width so no two neighbouring lanes start in the same place.
    const lane = { origin: 0.5 + 0.32 * Math.sin(i * 2.4 + 0.7), voice: i + 1 };
    const start = top + i * (laneRows + LANE_GAP);
    voiceWaveFrame(w, laneRows, timeS, lane).forEach((line, r) => {
      lines[start + r] = line;
    });
    centres.push(start + (laneRows - 1) / 2);
  }
  return { lines, centres };
}

/**
 * A short band (`VoiceWave contained`): ONE talkative lane as tall as the band (odd, so the
 * centre line is a row), centred, rather than the field's 11-row lanes that leave a short
 * band mostly empty.
 */
function voiceBand(w: number, h: number, timeS: number): { lines: string[]; centres: number[] } {
  const laneRows = h % 2 === 1 ? h : Math.max(1, h - 1);
  const top = Math.floor((h - laneRows) / 2);
  const lines = Array.from({ length: h }, () => " ".repeat(w));
  voiceWaveFrame(w, laneRows, timeS, { origin: 0.5, voice: 2, talkative: true }).forEach((line, r) => {
    lines[top + r] = line;
  });
  return { lines, centres: [top + (laneRows - 1) / 2] };
}

/** Where each ramp character is inked: 0 faint, 1 mid, 2 full. Index by ramp position. */
const INK_TIER = [0, 0, 0, 0, 1, 1, 1, 2, 2, 2] as const;

/**
 * Splits a frame into three same-shaped layers, faint, mid and full ink, each holding only
 * its own characters with the rest blanked. Drawn at rising opacity they give the figure
 * depth: quiet texture stays light and the loud peaks carry the colour. Faint characters on
 * a centre row are lifted to mid ink, so a pause still shows a crisp line.
 */
export function inkLayers(
  frame: readonly string[],
  centres: readonly number[] = [(frame.length - 1) / 2],
): [string[], string[], string[]] {
  const layers: [string[], string[], string[]] = [[], [], []];
  const centreRows = new Set(centres);
  frame.forEach((line, row) => {
    const parts = ["", "", ""];
    const onCentre = centreRows.has(row);
    for (const ch of line) {
      const rank = VOICE_RAMP.indexOf(ch);
      let tier = rank <= 0 ? -1 : INK_TIER[rank]!;
      if (tier === 0 && onCentre) tier = 1;
      for (let k = 0; k < 3; k++) parts[k] += k === tier ? ch : " ";
    }
    for (let k = 0; k < 3; k++) layers[k as 0 | 1 | 2].push(parts[k]!);
  });
  return layers;
}
