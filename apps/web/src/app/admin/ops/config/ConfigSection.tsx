"use client";

import { DashboardDataUsePanel } from "@/app/admin/ops/DashboardDataUsePanel";
import { EngineMinutePricePanel } from "@/app/admin/ops/EngineMinutePricePanel";
import { FxRatePanel } from "@/app/admin/ops/FxRatePanel";
import { ModelPricingPanel } from "@/app/admin/ops/ModelPricingPanel";
import { NumberPricePanel } from "@/app/admin/ops/NumberPricePanel";
import { RateCardPanel } from "@/app/admin/ops/RateCardPanel";
import { TtsPlanFeePanel } from "@/app/admin/ops/TtsPlanFeePanel";
import { WithheldPanel } from "@/app/admin/withheld";
import { SettingRows } from "@/components/console/settingRow";
import { Card, ProblemNotice, Skeleton } from "@/components/ui";
import { useOpsConfig } from "@/lib/api/opsConfig";

import { ConfigRow } from "./ConfigRow";
import { ConfigUnreadable, EnvOnlyKeys } from "./ConfigStatus";
import { configState } from "./configField";
import { fieldsIn, type ConfigSectionId } from "./configSections";

type Access = { allowed: boolean; reason: string | null };

const CONFIG_WITHHELD_SUBJECT =
  "This panel would list every setting this deployment can change without logging into the server, and the value in force for each.";

/**
 * One `platform:config` section: the panels that belong to its subject, and its settings.
 *
 * The panels each own their read and their refusal, so they render whether or not the
 * settings list arrived; the settings render exactly one of loading, unreadable, forbidden
 * or read (§52).
 */
export function ConfigSectionBody({ id, access }: { id: ConfigSectionId; access: Access }) {
  return (
    <>
      {/* The card is ABOVE the self-serve price it dates (D-547): the price write records
          the whole twelve-cell card under one `effective_from`, so the cells are read first. */}
      {id === "billing" && <RateCardPanel access={access} />}
      <SectionSettings id={id} access={access} />
      {/* A voice platform that reports no call cost is sold only at an attested rate. */}
      {id === "calling" && <EngineMinutePricePanel access={access} />}
      {/* The live exchange rate sits beside its fallback (`usd_inr_rate`, above). It is
          read-only: the operator's control over it is that fallback. */}
      {id === "billing" && <FxRatePanel />}
      {/* Client number purchases are refused until this price is attested. */}
      {id === "billing" && <NumberPricePanel />}
      {id === "billing" && <TtsPlanFeePanel access={access} />}
      {/* A model becomes available on a confirmed price, so the prices sit with the models
          they unlock rather than with the rate card clients pay. */}
      {id === "voices-models" && (
        <>
          <ModelPricingPanel access={access} />
          <DashboardDataUsePanel access={access} />
        </>
      )}
    </>
  );
}

function SectionSettings({ id, access }: { id: ConfigSectionId; access: Access }) {
  const query = useOpsConfig();
  const state = configState(query);

  if (state.status === "forbidden") {
    return (
      <WithheldPanel
        title="Platform configuration"
        reason={
          state.said ??
          "The API refused this read: your admin account may not see the platform configuration."
        }
        subject={CONFIG_WITHHELD_SUBJECT}
      />
    );
  }

  return (
    <div className="space-y-3">
      {query.error && <ProblemNotice error={query.error} onRetry={() => query.refetch()} />}
      {state.status === "loading" && (
        <Card>
          <Skeleton rows={4} />
        </Card>
      )}
      {state.status === "unreadable" && <ConfigUnreadable />}
      {state.status === "read" && (
        <>
          <SettingsList id={id} fields={fieldsIn(id, state.config.fields)} access={access} />
          {id === "platform" && <EnvOnlyKeys keys={state.config.bootstrap} />}
        </>
      )}
    </div>
  );
}

function SettingsList({
  id,
  fields,
  access,
}: {
  id: ConfigSectionId;
  fields: ReturnType<typeof fieldsIn>;
  access: Access;
}) {
  if (fields.length === 0) {
    // A statement from a read that ARRIVED. The billing and model sections still carry their
    // panels, so there the empty list says nothing at all.
    if (id === "billing" || id === "voices-models") return null;
    return (
      <p className="rounded-card border border-line px-4 py-6 text-center text-sm text-ink-muted">
        This deployment has no settings in this section.
      </p>
    );
  }
  return (
    <section aria-label="Settings" className="rounded-card border border-line bg-surface px-4 sm:px-5">
      <SettingRows>
        {fields.map((field) => (
          <ConfigRow key={field.key} field={field} access={access} />
        ))}
      </SettingRows>
    </section>
  );
}

/** A section shown to a session without `platform:config`: what it holds, not its values. */
export function WithheldSection({ id, reason }: { id: ConfigSectionId; reason: string | null }) {
  const why = reason ?? "Your admin account cannot change platform configuration.";
  return (
    <>
      <WithheldPanel title="Platform configuration" reason={why} subject={CONFIG_WITHHELD_SUBJECT} />
      {id === "voices-models" && (
        <>
          <WithheldPanel
            title="Model prices"
            reason={why}
            subject="This panel would list every model, who provides it, and the price per million tokens that billing uses."
          />
          <WithheldPanel
            title="Dashboard AI data-use"
            reason={why}
            subject="This panel would list every LLM provider the in-app AI assistant could run on, whether it may today, and the latest data-use attestation for each."
          />
        </>
      )}
      {id === "billing" && (
        <WithheldPanel
          title="Exchange rate"
          reason={why}
          subject="This panel would show the US dollar to rupee rate vendor costs are converted at, and how fresh it is."
        />
      )}
    </>
  );
}
