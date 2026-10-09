"use client";

import type { ReactNode } from "react";
import { CircleHelp } from "lucide-react";

import { DashboardDataUsePanel } from "@/app/admin/ops/DashboardDataUsePanel";
import { EngineMinutePricePanel } from "@/app/admin/ops/EngineMinutePricePanel";
import { FxRatePanel } from "@/app/admin/ops/FxRatePanel";
import { ModelPricingPanel } from "@/app/admin/ops/ModelPricingPanel";
import { NumberPricePanel } from "@/app/admin/ops/NumberPricePanel";
import { RateCardPanel } from "@/app/admin/ops/RateCardPanel";
import { TtsPlanFeePanel } from "@/app/admin/ops/TtsPlanFeePanel";
import { WithheldPanel } from "@/app/admin/withheld";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import { NoticeBox } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import type { ConfigList } from "@/lib/api/opsConfig";

import { EnvOnlyKeys } from "./ConfigStatus";

type Access = { allowed: boolean; reason: string | null };

/**
 * The panels a section mounts beside its settings, keyed by the id the server serves in
 * `panels_before` / `panels_after` (`apps/api/ops/config_catalog.py`). The server decides
 * WHERE a panel sits; this table only knows how to draw each one. Each panel owns its read
 * and its refusal, so it renders whether or not the settings list did.
 */
const PANELS: Record<string, (access: Access, config: ConfigList) => ReactNode> = {
  // Above the self-serve price it dates (D-547): recording a card rewrites that price.
  rate_card: (access) => <RateCardPanel access={access} />,
  // A voice platform that reports no call cost is sold only at an attested rate.
  engine_minute_price: (access) => <EngineMinutePricePanel access={access} />,
  // Read-only: the operator's control over the live rate is its fallback setting.
  fx_rate: () => <FxRatePanel />,
  // Client number purchases are refused until this price is attested.
  number_price: () => <NumberPricePanel />,
  tts_plan_fee: (access) => <TtsPlanFeePanel access={access} />,
  // A model becomes available on a confirmed price, so prices sit with the models.
  model_pricing: (access) => <ModelPricingPanel access={access} />,
  dashboard_data_use: (access) => <DashboardDataUsePanel access={access} />,
  server_only_keys: (_access, config) => <EnvOnlyKeys keys={config.bootstrap} />,
};

/** One served panel, or a statement that this console build cannot draw it. */
export function ConfigPanel({ id, access, config }: { id: string; access: Access; config: ConfigList }) {
  const render = lookup(PANELS, id);
  if (render) return <>{render(access, config)}</>;
  return (
    <NoticeBox
      tone="warn"
      icon={<CircleHelp aria-hidden className="h-5 w-5" />}
      title="This console cannot show one of this section's panels"
    >
      <p className="mt-1">
        The platform placed a panel <MonoValue>{id}</MonoValue> here that this build of the
        console does not know. Nothing about it is shown rather than a guess; reload after the
        console is updated.
      </p>
    </NoticeBox>
  );
}

/**
 * What a session without `platform:config` is told the settings section would hold — its
 * subjects, never a value. One list, because without the read there is no section layout.
 */
export function WithheldSettings({ reason }: { reason: string | null }) {
  const why = reason ?? "Your admin account cannot change platform configuration.";
  return (
    <>
      <WithheldPanel
        title="Platform configuration"
        reason={why}
        subject="This panel would list every setting this deployment can change without logging into the server, and the value in force for each."
      />
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
      <WithheldPanel
        title="Exchange rate"
        reason={why}
        subject="This panel would show the US dollar to rupee rate vendor costs are converted at, and how fresh it is."
      />
    </>
  );
}
