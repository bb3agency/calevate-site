/**
 * WHO MADE A LANGUAGE MODEL, for the small logo tile beside its name on the ADMIN console.
 * The one place a model is mapped to a maker; nothing in JSX names a file.
 *
 * Never imported by a client-realm screen: a client sees tiers, never a model or the company
 * behind it (D-679, D-680). Files and their sources are in `public/brand/models/MANIFEST.md`.
 *
 * Matched on the model's id and its display name, because the voice platform's ids are opaque
 * for some models and its names are the only thing that says whose they are. A model no rule
 * matches has no maker here and is drawn as a monogram, never guessed.
 */

export interface ModelMaker {
  /** The maker's name, for the tile's accessible label. */
  name: string;
  /** The file under `public/`. */
  src: string;
}

const MAKERS: readonly { pattern: RegExp; maker: ModelMaker }[] = [
  { pattern: /\bprana\b/i, maker: { name: "ThinnestAI", src: "/brand/models/thinnestai.png" } },
  { pattern: /\bgpt|\bo[134]\b|\bopenai\b/i, maker: { name: "OpenAI", src: "/brand/models/openai.svg" } },
  { pattern: /\bgemini\b|\bgemma\b/i, maker: { name: "Google", src: "/brand/models/gemini-color.svg" } },
  { pattern: /\bqwen\b/i, maker: { name: "Qwen", src: "/brand/models/qwen-color.svg" } },
  { pattern: /\bllama\b|\bmeta\b/i, maker: { name: "Meta", src: "/brand/models/meta-color.svg" } },
  { pattern: /\bdeepseek\b/i, maker: { name: "DeepSeek", src: "/brand/models/deepseek-color.svg" } },
  { pattern: /\bmistral\b|\bmixtral\b|\bministral\b/i, maker: { name: "Mistral AI", src: "/brand/models/mistral-color.svg" } },
  { pattern: /\bclaude\b/i, maker: { name: "Anthropic", src: "/brand/models/claude-color.svg" } },
  { pattern: /\bgrok\b/i, maker: { name: "xAI", src: "/brand/models/xai.svg" } },
];

/** The maker of a model, or `null` when no rule names one (the tile is then a monogram). */
export function modelMaker(...names: (string | null | undefined)[]): ModelMaker | null {
  for (const name of names) {
    if (!name) continue;
    const hit = MAKERS.find((entry) => entry.pattern.test(name));
    if (hit) return hit.maker;
  }
  return null;
}

/** The monogram for a model with no known maker: its first letter or digit, upper-cased. */
export function modelMonogram(label: string): string {
  const first = label.trim().match(/[\p{L}\p{N}]/u);
  return first ? first[0].toUpperCase() : "?";
}
