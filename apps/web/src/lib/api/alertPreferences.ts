"use client";

/**
 * ALERTS YOU CAN SHAPE (D-1048): this person's alert table, quiet hours and daily email limit
 * (`/v1/notifications/preferences`), and "Send me a sample". The server owns which cells
 * exist (`none` where a kind never arrives), which are always on, and who may change the
 * account cells; this file only carries them.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { apiRequest, type Session } from "./client";
import { notificationKeys } from "./notifications";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AlertPreferences = Schemas["AlertPreferencesOut"];
export type AlertPreferencesIn = Schemas["AlertPreferencesIn"];
export type AlertKindRow = Schemas["AlertKindOut"];
export type AlertCellState = AlertKindRow["cells"][string];
export type SampleChannel = Schemas["SampleIn"]["channel"];

export const ALERT_PREFERENCES_PATH = "/v1/notifications/preferences";

export const alertPreferenceKeys = {
  mine: (org: string) => ["alert-preferences", org] as const,
};

export function useAlertPreferences(session: Session, enabled = true): UseQueryResult<AlertPreferences> {
  return useQuery({
    queryKey: alertPreferenceKeys.mine(session.orgSlug),
    queryFn: () => apiRequest<AlertPreferences>(session, ALERT_PREFERENCES_PATH),
    enabled,
    staleTime: 60_000,
  });
}

export function useSaveAlertPreferences(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AlertPreferencesIn) =>
      apiRequest<AlertPreferences>(session, ALERT_PREFERENCES_PATH, { method: "PUT", body }),
    onSuccess: (data) => {
      client.setQueryData(alertPreferenceKeys.mine(session.orgSlug), data);
      // The bell hides the rows this person switched off.
      void client.invalidateQueries({ queryKey: notificationKeys.feed(session.orgSlug) });
    },
  });
}

export function useSendAlertSample(session: Session) {
  return useMutation({
    mutationFn: (channel: SampleChannel) =>
      apiRequest<Schemas["SampleOut"]>(session, `${ALERT_PREFERENCES_PATH}/sample`, {
        method: "POST",
        body: { channel },
      }),
  });
}

/** The `kind:channel` cells this table has switched off. */
export function offCells(prefs: AlertPreferences): string[] {
  return prefs.kinds.flatMap((kind) =>
    Object.entries(kind.cells)
      .filter(([, state]) => state === "off")
      .map(([channel]) => `${kind.key}:${channel}`),
  );
}

/**
 * The attention kinds a desktop pop-up may show for this person: a kind whose `computer` cell
 * is off is left out. Kinds that are not rows of the table keep the default.
 */
const ATTENTION_ROW: Record<string, string> = {
  lead_hot: "hot_lead",
  credit_low: "credit_low",
  inbound_stopped: "inbound_stopped",
  call_failed: "call_failed",
};

export function computerAllows(prefs: AlertPreferences | undefined, attentionKind: string): boolean {
  const row = lookup(ATTENTION_ROW, attentionKind);
  if (!prefs || !row) return true;
  return prefs.kinds.find((kind) => kind.key === row)?.cells.computer !== "off";
}
