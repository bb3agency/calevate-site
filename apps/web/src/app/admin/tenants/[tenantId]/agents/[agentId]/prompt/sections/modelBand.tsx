"use client";

import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice } from "@/components/ui";
import type { EngineCatalogueModel } from "@/lib/api/engineCatalogue";
import {
  bandForCatalogueModel,
  useEngineModelBands,
  useRecordEngineModelBand,
  type ModelBand,
} from "@/lib/api/engineModelBands";

/** Where the reading came from, recorded with the band. The route stamps who and when. */
const SOURCE_NOTE = "Checked in the voice platform's console model list";

/**
 * RECORD A MODEL'S PRICE from the agent's model list, for a model nobody has checked yet.
 *
 * Calevate offers only models included in the per-minute price (D-750). The platform's API
 * does not say which models cost extra, its console does, so an operator looks there and
 * records it. "No extra charge" makes the model offerable in one click. "Costs extra" records
 * it as paid, which hides it from every list, so it asks once more first. A model already
 * checked shows nothing here, and a paid one is not listed at all.
 */
export function ModelBandControl({ model }: { model: EngineCatalogueModel }) {
  const access = useAdminAccess(
    "ops:manage",
    "record whether a model costs extra",
  );
  const unchecked = model.price_band == null;
  const bands = useEngineModelBands({ enabled: unchecked && access.allowed });
  const record = useRecordEngineModelBand();
  const recordFeedback = useActionFeedback(record, { errorDisplay: "inline" });
  const statusFor = (band: ModelBand) =>
    record.variables?.band === band ? recordFeedback.status : "idle";
  const [confirmPaid, setConfirmPaid] = useState(false);
  if (!unchecked) return null;
  if (!access.allowed) {
    return access.reason ? (
      <p className="text-meta text-ink-muted">{access.reason}</p>
    ) : null;
  }
  if (bands.error != null) return <ProblemNotice error={bands.error} />;
  const row = bandForCatalogueModel(bands.data, model.model_id);
  const engine = bands.data?.engine;
  const ready = row !== undefined && engine != null;

  const save = (band: ModelBand) => {
    if (!row || engine == null) return;
    record.mutate({
      engine,
      modelId: row.model_id,
      band,
      sourceNote: SOURCE_NOTE,
    });
  };

  return (
    <div className="space-y-2">
      {confirmPaid ? (
        <div className="flex flex-wrap items-center gap-3 text-meta text-ink-muted">
          <span>Record it as paid? It will no longer be listed anywhere.</span>
          <ActionButton
            variant="secondary-sm"
            status={statusFor("premium")}
            successLabel="Recorded"
            disabled={!ready}
            onClick={() => save("premium")}
          >
            Record as paid
          </ActionButton>
          <button
            type="button"
            className={TEXT_ACTION}
            onClick={() => setConfirmPaid(false)}
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <ActionButton
            variant="secondary-sm"
            status={statusFor("none")}
            successLabel="Recorded"
            disabled={!ready}
            onClick={() => save("none")}
          >
            No extra charge (checked in the console)
          </ActionButton>
          <button
            type="button"
            className={TEXT_ACTION}
            disabled={!ready || record.isPending}
            onClick={() => setConfirmPaid(true)}
          >
            Costs extra
          </button>
        </div>
      )}
      {record.error != null && <ProblemNotice error={record.error} />}
    </div>
  );
}
