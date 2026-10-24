import type { EngineCatalogue, EngineCatalogueModel } from "@/lib/api/engineCatalogue";

/**
 * The voice platform's model list as ThinnestAI production returned it (`GET /models`, read
 * by the founder 11 Oct 2026): id, the console name, and whether it may run beside our own
 * voice key. These names are the companies' and the platform's, so they may appear on the
 * admin console and must never appear on a client's screen (D-679).
 */
export const LIVE_ENGINE_MODELS: readonly { id: string; name: string; studio: boolean }[] = [
  { id: "prana", name: "Prana", studio: true },
  { id: "gpt-oss-120b", name: "GPT-OSS 120B", studio: true },
  { id: "prana-voice", name: "Prana [Voice]", studio: true },
  { id: "composer-v0.1", name: "Composer v0.1", studio: false },
  { id: "qwen3.6-27b", name: "Qwen3.6 27B", studio: false },
  { id: "gpt-5.6-luna", name: "GPT-5.6 Luna", studio: false },
  { id: "gpt-5-nano", name: "GPT-5 Nano", studio: true },
  { id: "gpt-5.4-nano", name: "GPT-5.4 Nano", studio: false },
  { id: "gpt-5-mini", name: "GPT-5 Mini", studio: false },
  { id: "gpt-4.1-nano", name: "GPT-4.1 Nano", studio: true },
];

/** The catalogue as an OPERATOR reads it: real names, bands and latencies. */
export function operatorEngineCatalogue(over: Partial<EngineCatalogue> = {}): EngineCatalogue {
  const models: EngineCatalogueModel[] = LIVE_ENGINE_MODELS.map((model) => ({
    model_id: `engine-model:${model.id}`,
    label: model.name,
    call_capable: true,
    plan_allows: true,
    usable_with_studio_voice: model.studio,
    band_disagrees: false,
    price_band: model.id === "gpt-5-mini" ? "premium" : model.id.startsWith("composer") || model.id.startsWith("qwen") ? null : "none",
    latency_ms: null,
    offerable: !(model.id.startsWith("composer") || model.id.startsWith("qwen")),
    reason:
      model.id.startsWith("composer") || model.id.startsWith("qwen")
        ? "Nobody has checked this model's charge in the platform console yet."
        : null,
  }));
  return {
    available: true,
    complete: true,
    choosable: true,
    studio_available: true,
    note: "2 of 2 voices can be chosen today.",
    default_model_label: "GPT-OSS 120B",
    voices: [
      {
        voice_id: "engine:anjali",
        label: "Anjali",
        rung: "clear",
        language_note: "Speaks Telugu, Hindi and English.",
        preview_available: false,
        is_custom: false,
        offerable: true,
        reason: null,
        standing: "offered",
      },
      {
        voice_id: "byok:meera",
        label: "Meera",
        rung: "studio",
        language_note: "Speaks English.",
        preview_available: false,
        is_custom: false,
        offerable: true,
        reason: null,
        standing: "offered",
      },
    ],
    models,
    ...over,
  };
}
