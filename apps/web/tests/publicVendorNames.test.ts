import { describe, expect, it } from "vitest";

import { copyUnder, type CopyString } from "./copyScan";

/**
 * A CLIENT NEVER READS THE NAME OF THE COMPANY THAT SPEAKS, AND NEVER READS ONE OF OUR
 * SETTINGS — over every surface a stranger or a client can reach, as a property of the
 * SOURCE rather than of one render.
 *
 * ## Why this exists as a sweep and not as another per-screen assertion
 *
 * The rule is the founder's, 7 September 2026, and it has a mechanism behind it: what a
 * client buys is a named voice QUALITY, defined once in `apps/api/billing/rates.py::
 * VOICE_TIER_LABELS` and carried to the browser on the rate card, the pack card, the voice
 * catalogue and the credit lots. Which company synthesises each quality is ours and must
 * be able to change without a client-visible rename — so `sarvam` and `cartesia` key the
 * money, the metering and the lot columns, and reach no screen.
 *
 * Four or five screens already assert this about their own render (`agents.test.tsx`,
 * `agentVoice.test.tsx`, `marketingPages.test.tsx`, `credits.test.tsx`). Each of those is
 * a claim about a component somebody remembered to write a test for, and the failure this
 * guard is built for is the opposite one: a sentence written on a screen NOBODY thought of
 * as a money screen — a glossary entry, an empty state, a tooltip, an `aria-label`, a FAQ
 * answer — where the field name was the handiest word to hand. That is precisely how
 * `studio_tier_label` becomes "the Cartesia voice" in copy, and no render test that does
 * not exist can catch it.
 *
 * ## The two rules, and why the second one is scoped away from the client realm
 *
 * 1. **No voice or telephony vendor, anywhere a client or a stranger reads.** The list is
 *    the speech and voice vendors, the models they are sold under (`Bulbul`, `Sonic`,
 *    `Timbre`) and, since D-679, the carriers and call platforms Calevate resells under a
 *    white label — a sentence naming the MODEL is the same disclosure as one naming the
 *    company. The legal documents are held to the same rule by `legalVendorNames.test.ts`.
 * 2. **No wire identifier on the marketing surfaces.** `plainLanguageGuard.test.ts` already
 *    holds that rule over `src/app/c`, and holding it twice would be two spellings of one
 *    thing — so this half runs over the pages the console guard never walked. The failure
 *    it exists for is a marketing page quoting a SETTING (`self_serve_inr_per_min` priced
 *    this card until D-547 and was named in copy on two surfaces) or a wire field
 *    (`bonus_pct`) as though it were a product word.
 *
 * ## What is deliberately NOT scanned
 *
 * - **`src/app/admin` and the ops console.** An operator reading "Cartesia" is the whole
 *   point: they install that key, they read that invoice, and `ModelPricingPanel.tsx` says
 *   so in its own header. The exception is deliberate and is the reason this guard names
 *   its roots rather than scanning `src/`.
 * - **`src/lib/legal`.** Not scanned here because `legalVendorNames.test.ts` reads the
 *   rendered documents against the internal register, which knows the full name list
 *   (D-679: the legal pages describe sub-processors by category and name a company only
 *   where the register marks it public).
 * - **Comments.** `copyScan` parses; a docstring is not a literal in a copy position, which
 *   is the whole reason this is an AST walk and not a grep (`tests/sourceScan.ts` records
 *   the three times that lesson was paid for).
 */

/**
 * The surfaces a person who is not an operator can reach: the client console, both realms'
 * account/sign-in screens, every marketing page and the components they are built from.
 *
 * `src/lib/marketing` is here because the residency paragraph and the four verticals live
 * there rather than in a page — a constant is exactly where a sentence hides from a guard
 * that only reads `src/app`.
 */
const PUBLIC_SURFACES = [
  "src/app/c",
  "src/app/(auth)",
  "src/app/page.tsx",
  "src/app/not-found.tsx",
  "src/app/error.tsx",
  "src/app/global-error.tsx",
  "src/app/pricing",
  "src/app/roi",
  "src/app/resources",
  "src/app/security",
  "src/app/solutions",
  "src/app/industries",
  "src/app/why-calevate",
  "src/app/signup",
  "src/app/invite",
  "src/app/legal",
  // EVERY shared component, not a hand-picked few. The admin console's own panels live
  // under `src/app/admin` and are not here; what is under `src/components` is either
  // client-facing or shared, and a shared component that names a vendor names it to a
  // client on one of its two mounts. `voicePicker.tsx` is the case in point: it is mounted
  // in the admin realm only today, and it still may not print `provider`.
  "src/components",
  "src/lib/marketing",
];

/** Everything above except the console, which `plainLanguageGuard.test.ts` already walks. */
const MARKETING_SURFACES = PUBLIC_SURFACES.filter((root) => root !== "src/app/c");

/**
 * The vendors, and the engines they are sold under. Word-bounded: "sonic" is a word, and a
 * ban that fired on "supersonic" is a ban somebody deletes.
 */
const VOICE_VENDOR =
  /\b(sarvam|cartesia|bulbul|saaras|sonic|gnani|timbre|vobiz|plivo|pipecat|thinnest(?:ai)?|bolna|exotel)\b/i;

/** A wire identifier: two or more lowercase words joined by underscores. */
const WIRE_NAME = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g;

function report(entry: CopyString, name: string): string {
  return `${entry.file}:${entry.line} — “${name}” in: ${entry.text.trim().slice(0, 120)}`;
}

describe("what a client reads names no vendor and no setting", () => {
  it("is reading the surfaces it claims to read", () => {
    // THE PREMISE, first and alone (`plainLanguageGuard`'s rule, for its reason): a walk
    // that has silently stopped matching finds nothing and passes for ever. Two sentences
    // from two roots that are NOT the client realm, so a marketing root dropping out of
    // the list is caught here rather than by a green suite.
    const seen = copyUnder(PUBLIC_SURFACES).map((entry) => entry.text);
    expect(seen.length, "the copy scan found almost nothing — have the roots moved?")
      .toBeGreaterThan(700);
    const all = seen.join("\n");
    expect(all).toContain("Evenings, Sundays and festival days");
    expect(all).toContain("Prepaid balance, if your account runs that way");
  });

  it("never names the company that speaks", () => {
    const found = copyUnder(PUBLIC_SURFACES)
      .filter((entry) => VOICE_VENDOR.test(entry.text))
      .map((entry) => report(entry, VOICE_VENDOR.exec(entry.text)?.[0] ?? ""));
    expect(
      found,
      "a client buys a named voice QUALITY, never a vendor. The two names are the " +
        "server's (`billing/rates.py::VOICE_TIER_LABELS`) and travel on the rate card, the " +
        "pack card, the voice catalogue and the lots — read the label the API sent, and " +
        "render nothing when it sent none. The admin console and the legal documents are " +
        "the two deliberate exceptions and are not scanned here.",
    ).toEqual([]);
  });

  it("never quotes one of our settings or wire fields on a marketing page", () => {
    const found: string[] = [];
    for (const entry of copyUnder(MARKETING_SURFACES)) {
      WIRE_NAME.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = WIRE_NAME.exec(entry.text)) !== null) found.push(report(entry, match[0]));
    }
    expect(
      found,
      "these are our own identifiers in copy a stranger reads. A setting name on a " +
        "marketing page is a promise about a control they cannot see and we may rename; " +
        "say the behaviour instead.",
    ).toEqual([]);
  });
});

/**
 * A CLIENT NEVER READS WHICH LANGUAGE MODEL ANSWERS, OR WHOSE IT IS (D-679, D-680).
 *
 * A client chooses a TIER — Standard, Plus, Pro — and the server resolves it to a model
 * (`apps/api/agents/llm_tiers.py`). Two halves, because the failure has two shapes:
 *
 * 1. **Copy.** A sentence on a client surface naming a model family or the company behind it
 *    ("runs on GPT", "powered by Gemini"). Swept over the same roots as the voice rule.
 * 2. **The wire.** A field on a client-realm response that carries a model id or a provider,
 *    which some screen will render the day somebody needs a label. Read off the OpenAPI
 *    snapshot the typed client is generated from, so a field added server-side fails here
 *    before any screen exists to leak it. The admin realm (`/v1/admin`, `/v1/ops`) keeps
 *    real models and is not read.
 */
const MODEL_VENDOR =
  /\b(gpt|gemini|openai|open ai|azure|claude|anthropic|prana|llama|mistral|deepseek|krutrim)\b|\bgpt-\d|\b4o-mini\b|\bflash-lite\b/i;

/** Every client-realm route whose response or body describes an agent's language model. */
const MODEL_ROUTES: readonly [string, string][] = [
  ["/v1/organization/llm-defaults", "get"],
  ["/v1/organization/llm-defaults", "put"],
  ["/v1/agents", "get"],
  ["/v1/agents/{agent_id}", "get"],
  ["/v1/agents/{agent_id}", "patch"],
  ["/v1/agents/engine-catalogue", "get"],
  ["/v1/usage", "get"],
];

/** A property that would carry a model id or a provider name onto a client's wire. */
const MODEL_FIELD = /^(model|provider|llm_model.*|default_llm_model|effective_default|llm_surcharge_models)$/;

type SchemaNode = Record<string, unknown>;

function schemaFields(spec: SchemaNode, root: unknown): string[] {
  const schemas = (spec.components as SchemaNode).schemas as Record<string, SchemaNode>;
  const seen = new Set<string>();
  const found: string[] = [];
  const walk = (node: unknown, owner: string): void => {
    if (!node || typeof node !== "object") return;
    const n = node as SchemaNode;
    if (typeof n.$ref === "string") {
      const name = n.$ref.split("/").pop() ?? "";
      if (seen.has(name)) return;
      seen.add(name);
      walk(schemas[name], name);
      return;
    }
    for (const [key, value] of Object.entries((n.properties as SchemaNode | undefined) ?? {})) {
      found.push(`${owner}.${key}`);
      walk(value, owner);
    }
    for (const key of ["items", "additionalProperties"]) walk(n[key], owner);
    for (const key of ["anyOf", "oneOf", "allOf"]) {
      for (const branch of (n[key] as unknown[] | undefined) ?? []) walk(branch, owner);
    }
  };
  walk(root, "");
  return found;
}

describe("what a client reads names no language model and no model vendor", () => {
  it("never names one in copy", () => {
    const found = copyUnder(PUBLIC_SURFACES)
      .filter((entry) => MODEL_VENDOR.test(entry.text))
      .map((entry) => report(entry, MODEL_VENDOR.exec(entry.text)?.[0] ?? ""));
    expect(
      found,
      "a client chooses an AI model TIER (Standard, Plus, Pro), never a model or its " +
        "maker. Render the tier label the API sent (`agents/llm_tiers.py`).",
    ).toEqual([]);
  });

  it("carries no model id or provider on any client-realm model route", async () => {
    const spec = (await import("@/lib/api/openapi.json")).default as unknown as SchemaNode;
    const paths = spec.paths as Record<string, Record<string, SchemaNode>>;
    const leaks: string[] = [];
    for (const [path, method] of MODEL_ROUTES) {
      const operation = paths[path]?.[method];
      expect(operation, `${method.toUpperCase()} ${path} is not in the snapshot`).toBeTruthy();
      const bodies = [
        (operation.requestBody as SchemaNode | undefined)?.content,
        ...Object.values((operation.responses as Record<string, SchemaNode>) ?? {}).map(
          (response) => response.content,
        ),
      ];
      for (const content of bodies) {
        const schema = ((content as SchemaNode | undefined)?.["application/json"] as
          | SchemaNode
          | undefined)?.schema;
        for (const field of schemaFields(spec, schema)) {
          if (MODEL_FIELD.test(field.split(".").pop() ?? "")) {
            leaks.push(`${method.toUpperCase()} ${path}: ${field}`);
          }
        }
      }
    }
    expect(
      leaks,
      "the client realm reads tiers; real models stay on `/v1/admin/organizations/{org_id}/" +
        "llm-defaults` (D-680)",
    ).toEqual([]);
  });

  it("is reading the routes it claims to read", async () => {
    // THE PREMISE: a walk that silently stopped resolving refs would find no fields and
    // pass. The tier fields must be visible to the same walk.
    const spec = (await import("@/lib/api/openapi.json")).default as unknown as SchemaNode;
    const paths = spec.paths as Record<string, Record<string, SchemaNode>>;
    const response = (paths["/v1/organization/llm-defaults"].get.responses as SchemaNode)[
      "200"
    ] as SchemaNode;
    const fields = schemaFields(
      spec,
      ((response.content as SchemaNode)["application/json"] as SchemaNode).schema,
    );
    expect(fields).toContain("ClientLlmDefaultsOut.effective_tier");
    expect(fields).toContain("LlmTierOptionOut.label");
  });
});
