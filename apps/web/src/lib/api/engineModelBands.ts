/**
 * THE PER-MINUTE BAND OF EACH OF THE ENGINE'S OWN MODELS, as an operator recorded it.
 *
 *   GET  /v1/ops/engine-model-bands                        `ops:manage`
 *   POST /v1/ops/engine-model-bands/{engine}/{model_id}    step-up confirmed
 *
 * ThinnestAI's API does not say which models cost extra; its console does. An operator reads
 * the tag there and records it. Calevate offers only models included in the per-minute price
 * (D-750), so `none` makes a model offerable and `premium` records it as paid, which hides it
 * from every picker. A model with no record is "not checked yet" and is offered to nobody.
 *
 * `model_id` is the engine's raw id, which only the band routes take; `catalogue_id` is the
 * opaque id the agent's model list carries, so a row there can be matched to one here.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adminSession, confirmedAdminRequest } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

export type EngineModelBand = components["schemas"]["EngineModelBandOut"];
export type EngineModelBands = components["schemas"]["EngineModelBandsOut"];
export type ModelBand = NonNullable<EngineModelBand["band"]>;

export const ENGINE_MODEL_BANDS_PATH = "/v1/ops/engine-model-bands";
const QUERY_KEY = ["ops", "engine-model-bands"] as const;

/** The step-up string, copied verbatim from the route that checks it. */
export function recordEngineModelBandConfirmation(
  engine: string,
  modelId: string,
): string {
  return `record_engine_model_band:${engine}:${modelId}`;
}

export function useEngineModelBands(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: QUERY_KEY,
    enabled: options.enabled ?? true,
    queryFn: () =>
      apiRequest<EngineModelBands>(adminSession(), ENGINE_MODEL_BANDS_PATH),
  });
}

/** The band row behind one row of the agent's model list, by its opaque id. */
export function bandForCatalogueModel(
  bands: EngineModelBands | undefined,
  catalogueId: string,
): EngineModelBand | undefined {
  return bands?.models.find((row) => row.catalogue_id === catalogueId);
}

export interface RecordEngineModelBandInput {
  engine: string;
  /** The engine's raw model id (`EngineModelBand.model_id`), never the opaque one. */
  modelId: string;
  band: ModelBand;
  sourceNote: string;
}

export function useRecordEngineModelBand() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      engine,
      modelId,
      band,
      sourceNote,
    }: RecordEngineModelBandInput) =>
      confirmedAdminRequest<EngineModelBand>(
        `${ENGINE_MODEL_BANDS_PATH}/${encodeURIComponent(engine)}/${encodeURIComponent(modelId)}`,
        {
          method: "POST",
          body: { band, source_note: sourceNote },
          confirmAction: recordEngineModelBandConfirmation(engine, modelId),
        },
        "Recording this model's per-minute band.",
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: QUERY_KEY });
      // A recorded band decides which models the agent's list offers, or shows at all.
      void client.invalidateQueries({ queryKey: ["engine-catalogue"] });
    },
  });
}
