import type { AlertPreferences } from "@/lib/api/alertPreferences";

/** The alert table as a fresh owner's account reads it (D-1048): every offered cell on. */
export function alertPreferencesFixture(over: Partial<AlertPreferences> = {}): AlertPreferences {
  const row = (
    key: string,
    label: string,
    cells: Record<string, "on" | "off" | "always" | "none">,
    why: string | null = null,
  ) => ({ key, label, always: why !== null, why, cells });
  return {
    kinds: [
      row("hot_lead", "A call flagged for you", { bell: "on", computer: "on", email: "on", whatsapp: "on" }),
      row("campaign_finished", "A campaign finished", { bell: "on", computer: "none", email: "on", whatsapp: "none" }),
      row(
        "credit_low",
        "Low credit",
        { bell: "always", computer: "always", email: "always", whatsapp: "none" },
        "When credit runs out your agents stop calling and answering.",
      ),
    ],
    quiet_enabled: false,
    quiet_start_hour: 21,
    quiet_end_hour: 8,
    daily_cap: 12,
    governs_account: true,
    account_editable: true,
    ...over,
  };
}

/** Every read the Alerts page makes beyond the opt-in, the team list and the daily summary. */
export const ALERTS_PAGE_READS = {
  "/v1/notifications/preferences": alertPreferencesFixture(),
  "/v1/campaigns": [],
  "/v1/inbound-lines": { lines: [] },
};
