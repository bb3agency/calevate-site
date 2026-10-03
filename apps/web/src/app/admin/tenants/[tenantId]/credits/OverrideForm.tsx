"use client";

import { useState } from "react";
import { CheckCircle2 } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  RestrictionNote,
  formatINR,
  formatIST,
  formatRupeeRate,
} from "@/components/ui";
import { TypedConfirmation } from "@/components/typedConfirmation";
import { WriteFailure } from "@/app/admin/writeFailure";
import {
  useApplyLotOverride,
  type CreditLot,
  type OverridePack,
} from "@/lib/api/creditLots";

/**
 * SELL THIS LOT AT ANOTHER PACK'S RATES — the founding-client promotion, and every
 * negotiated deal after it (plan §0 Q6).
 *
 * A control rather than a manual grant because a grant can only give more CREDIT, and what
 * is promised is a cheaper MINUTE: a bigger grant on the list rate still bills at the list
 * rate.
 *
 * - **The lot is chosen, never typed**, so the rates it carries are visible when choosing.
 * - **The pack is chosen from the SERVER's ladder**, with the rates it would freeze beside
 *   it. This console does no arithmetic and quotes no rate it was not sent.
 * - **The confirmation is the LOT's own id and goes on the wire**, bound to that lot, so a
 *   confirmation captured for one purchase cannot re-price another.
 * - **A reason is required**: this is the one act that makes the wallet disagree with the
 *   card the money was taken under, and the audit row is the only place that is explained.
 */

interface OverrideDraft {
  lotId: string;
  packId: string;
  confirm: string;
  reason: string;
}

const NO_OVERRIDE: OverrideDraft = { lotId: "", packId: "", confirm: "", reason: "" };

/** Said wherever the re-price control is withheld for want of a pack ladder. */
export function NoPackLadder() {
  return (
    <p className="text-xs text-ink-faint">
      Re-pricing a lot at another pack&apos;s rates is not offered here: this deployment
      sent no pack ladder, and a control that let you choose a pack whose rates it could
      not show you would be re-pricing a client&apos;s minutes blind.
    </p>
  );
}

export function OverrideForm({
  lots,
  packs,
  tenantId,
  write,
  clientName,
  initialLotId,
}: {
  lots: readonly CreditLot[];
  packs: readonly OverridePack[];
  tenantId: string;
  write: { allowed: boolean; reason: string | null };
  clientName: string;
  initialLotId?: string;
}) {
  const [draft, setDraft] = useState<OverrideDraft>(() => ({
    ...NO_OVERRIDE,
    lotId: initialLotId ?? "",
  }));
  const apply = useApplyLotOverride(tenantId);
  const chosen = lots.find((lot) => lot.lot_id === draft.lotId) ?? null;
  const pack = packs.find((row) => row.pack_id === draft.packId) ?? null;
  const ready =
    chosen !== null &&
    pack !== null &&
    draft.reason.trim().length >= 3 &&
    draft.confirm.trim() === chosen.lot_id;

  // An empty ladder offers NO CONTROL: a pack select with nothing in it would be
  // re-pricing a client's minutes blind.
  if (packs.length === 0) return <NoPackLadder />;

  return (
    <div className="space-y-4">
      <p className="text-xs text-ink-muted">
        For a promotion or a negotiated deal: {clientName}&apos;s credit stays exactly as
        it is, and the minutes it buys become cheaper. It changes a term this client was
        sold, so it is recorded in the audit log with your reason and cannot be undone —
        only re-priced again.
      </p>

      {apply.error && <WriteFailure error={apply.error} actionLabel="Re-price this lot" />}
      {apply.isSuccess && (
        <NoticeBox
          tone="ok"
          icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
          title="Re-priced — the lot now carries that pack's rates"
        >
          <p className="mt-1 text-xs">
            The lot list has been re-read. Credit did not move; only what a minute drawn
            from that lot costs.
          </p>
        </NoticeBox>
      )}

      <label className="block">
        <span className={FIELD_LABEL}>Which lot</span>
        <select
          value={draft.lotId}
          onChange={(e) =>
            // The confirmation is the LOT id, so changing the lot must clear it — otherwise
            // a confirmation typed for one purchase would arm the write against another.
            setDraft((was) => ({ ...was, lotId: e.target.value, confirm: "" }))
          }
          className={FIELD}
        >
          <option value="">Choose a lot…</option>
          {lots.map((lot) => (
            <option key={lot.lot_id} value={lot.lot_id}>
              {formatINR(lot.credits_remaining)} left · opened {formatIST(lot.opened_at)} ·{" "}
              {formatRupeeRate(lot.clear_inr_per_min)} /{" "}
              {formatRupeeRate(lot.studio_inr_per_min)} per min
            </option>
          ))}
        </select>
        <span className={FIELD_HINT}>
          Only this lot is re-priced. Credit already spent is not re-billed — a call is
          charged when it ends, at the rate the lot carried then.
        </span>
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>Sell it at</span>
        <select
          value={draft.packId}
          onChange={(e) => setDraft((was) => ({ ...was, packId: e.target.value }))}
          className={FIELD}
        >
          <option value="">Choose a pack…</option>
          {packs.map((row) => (
            <option key={row.pack_id} value={row.pack_id}>
              {row.pack_id} ({formatINR(row.amount_inr)}) · Gnani {formatRupeeRate(row.clear_inr_per_min)} ·
              Cartesia {formatRupeeRate(row.studio_inr_per_min)}
            </option>
          ))}
        </select>
        {pack && chosen && (
          <span className={FIELD_HINT}>
            This lot goes from Gnani {formatRupeeRate(chosen.clear_inr_per_min)} / Cartesia{" "}
            {formatRupeeRate(chosen.studio_inr_per_min)} to Gnani{" "}
            {formatRupeeRate(pack.clear_inr_per_min)} / Cartesia{" "}
            {formatRupeeRate(pack.studio_inr_per_min)} per minute.
          </span>
        )}
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>Reason</span>
        <input
          value={draft.reason}
          onChange={(e) => setDraft((was) => ({ ...was, reason: e.target.value }))}
          minLength={3}
          maxLength={500}
          placeholder="e.g. founding-client promotion, approved 7 Sep"
          className={FIELD}
        />
        <span className={FIELD_HINT}>
          Recorded in the audit log beside the pack this lot now borrows its rates from.
        </span>
      </label>

      <TypedConfirmation
        match="exact"
        label="Type the lot id to confirm"
        phrase={chosen?.lot_id ?? ""}
        value={draft.confirm}
        onChange={(next) => setDraft((was) => ({ ...was, confirm: next }))}
        placeholder={chosen ? chosen.lot_id : "choose a lot first"}
        disabled={chosen === null}
        hint="The id of the lot above, typed out. It is different every time, so it cannot become muscle memory the way a fixed word would."
      />

      {!write.allowed && <RestrictionNote reason={write.reason} />}

      <button
        type="button"
        disabled={!ready || !write.allowed || apply.isPending}
        onClick={() =>
          apply.mutate(
            { lotId: draft.lotId, packId: draft.packId, reason: draft.reason.trim() },
            { onSuccess: () => setDraft(NO_OVERRIDE) },
          )
        }
        className={PRIMARY_BUTTON}
      >
        {apply.isPending ? "Re-pricing…" : "Re-price this lot"}
      </button>
    </div>
  );
}
