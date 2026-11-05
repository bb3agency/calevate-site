import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IN_USE_THROUGH_DEFAULT, ModelTierSetting } from "@/components/modelTierSetting";
import type { ClientLlmDefaults } from "@/lib/api/llmModels";

const CATALOGUE: ClientLlmDefaults = {
  available: [
    {
      tier: "standard",
      label: "Standard",
      description: "Quick, natural replies.",
      client_surcharge_inr_per_minute: "0",
      is_available: false,
      is_platform_default: true,
      unavailable_reason: "It isn't switched on for your account yet; ask your Calevate team to enable it.",
    },
  ],
  default_llm_tier: null,
  effective_is_available: true,
  effective_tier: "standard",
  effective_tier_label: "Standard",
  in_force_surcharge_inr_per_minute: "0",
  tier_choosable: true,
  upgrade_surcharge_inr_per_minute: "0",
};

describe("the model running now is shown in one true state (A-24)", () => {
  it("never says the tier the default runs is not switched on", () => {
    render(
      <ModelTierSetting
        mode="agent"
        name="m"
        catalogue={CATALOGUE}
        saved={null}
        inForceLabel="Standard"
        source={null}
        followLabel="Standard"
        followSurcharge="0"
        baselineSurcharge="0"
        write={{ allowed: true, reason: null }}
        status="idle"
        error={null}
        savedAt={0}
        onSave={() => undefined}
      />,
    );
    expect(screen.queryByText(/isn.t switched on/i)).toBeNull();
    expect(screen.getByText(IN_USE_THROUGH_DEFAULT)).toBeTruthy();
  });
});
