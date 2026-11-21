import type { AgentLanguage } from "@/lib/api/agents";
import { founderLine } from "@/lib/founderLines";
import { lookup } from "@/lib/lookup";

/**
 * THE ONE TABLE OF LANGUAGE NAMES IN THE WEB APP. Every screen that names a language, an
 * agent's, a call's, a WhatsApp template's or a test line's, reads it from here, so a new
 * language is one row rather than five.
 *
 * Which languages an account may CHOOSE is never this table's to say: that is the server's
 * list (`lib/api/agentLanguages`), which also carries its own `name`. This table names what
 * the screen already holds, including call and transcript languages no agent speaks.
 *
 * English names keyed by the base language code, matching the server's
 * (`calevate_shared.languages`, `english_name`, without the region).
 */
const BASE_NAMES: Readonly<Record<string, string>> = {
  te: "Telugu",
  hi: "Hindi",
  en: "English",
  ta: "Tamil",
  kn: "Kannada",
  ml: "Malayalam",
  mr: "Marathi",
  bn: "Bengali",
  gu: "Gujarati",
  pa: "Punjabi",
  ur: "Urdu",
  or: "Odia",
};

/** The tags whose region is part of what a person chooses: an agent's "English (India)" and
 *  the English variants a WhatsApp template can be registered in. */
const REGION_NAMES: Readonly<Record<string, string>> = {
  "en-IN": "English (India)",
  "en-US": "English (US)",
  "en-GB": "English (UK)",
};

/** "te-IN", "te_IN" or "te" → "te". */
export function baseOf(tag: string | null | undefined): string {
  return (tag ?? "").toLowerCase().split(/[-_]/)[0] ?? "";
}

/** The language without its region ("en-IN" → "English"), or null for a tag this table
 *  does not know: a caller chooses its own wording for the unknown case. */
export function languageName(tag: string | null | undefined): string | null {
  const base = baseOf(tag);
  return base ? (lookup(BASE_NAMES, base) ?? null) : null;
}

/** The language with its region where the region is part of the choice ("en-IN" →
 *  "English (India)", "en_GB" → "English (UK)"), else its name, else the tag itself, so an
 *  unknown language is shown as what it is and never as another one. Empty for no tag. */
export function languageLabel(tag: string | null | undefined): string {
  if (!tag) return "";
  const [base = "", region = ""] = tag.split(/[-_]/);
  const regional = region ? lookup(REGION_NAMES, `${base.toLowerCase()}-${region.toUpperCase()}`) : undefined;
  return regional ?? languageName(tag) ?? tag;
}

/**
 * Every language an agent can be stored in, named. `Record<AgentLanguage, string>` over the
 * GENERATED union: a language added on the server is a type error here until it is named,
 * rather than an unnamed option.
 */
export const LANGUAGE_NAMES: Record<AgentLanguage, string> = {
  "te-IN": languageLabel("te-IN"),
  "hi-IN": languageLabel("hi-IN"),
  "en-IN": languageLabel("en-IN"),
  "ta-IN": languageLabel("ta-IN"),
  "kn-IN": languageLabel("kn-IN"),
  "ml-IN": languageLabel("ml-IN"),
  "mr-IN": languageLabel("mr-IN"),
};

/** Every language an agent can be stored in, in the server's declaration order. */
export const AGENT_LANGUAGES = Object.keys(LANGUAGE_NAMES) as AgentLanguage[];

/**
 * The language's own name in its own script, from the founder's `founderLines.json`
 * (founder rule 2: never written in code), or null where there is none on file. English has
 * none: its name is the English one.
 */
export function endonym(tag: string | null | undefined): string | null {
  const base = baseOf(tag);
  if (!base || base === "en") return null;
  try {
    return founderLine(`language.endonym.${base}-IN`);
  } catch {
    return null;
  }
}

/**
 * Which language a line written in one Indian script is, given the languages the agent
 * speaks: Devanagari is Hindi or Marathi, whichever the agent speaks (Hindi when it speaks
 * neither or both, the script's most common language). Keyed by the Unicode script name.
 */
const SCRIPT_LANGUAGES: Readonly<Record<string, readonly string[]>> = {
  Telugu: ["te"],
  Devanagari: ["hi", "mr"],
  Tamil: ["ta"],
  Kannada: ["kn"],
  Malayalam: ["ml"],
  Bengali: ["bn"],
  Gujarati: ["gu"],
  Oriya: ["or"],
  Gurmukhi: ["pa"],
};

export const INDIAN_SCRIPTS: readonly string[] = Object.keys(SCRIPT_LANGUAGES);

/** The name of the language a line in `script` is written in, read against the agent's own
 *  languages (`spoken`, BCP-47 tags) where the script is shared. */
export function scriptLanguageName(script: string, spoken: readonly string[] = []): string | null {
  const bases = lookup(SCRIPT_LANGUAGES, script);
  if (!bases) return null;
  const own = spoken.map(baseOf);
  const theirs = bases.filter((base) => own.includes(base));
  return languageName(theirs.length === 1 ? theirs[0] : bases[0]);
}
