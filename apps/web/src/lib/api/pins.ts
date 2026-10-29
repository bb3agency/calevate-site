"use client";

/**
 * Pinned charts (D-934): the cards on the client home (`/v1/copilot/pins`) and on the admin
 * home (`/v1/admin/copilot/pins`). A pin is the chart's name and window; each card asks the
 * server to re-run it for whoever is looking (`.../card`), so a figure the viewer may not
 * see comes back as `refused`, never as somebody else's number.
 *
 * Live: the list moves with the `account` (client) or `platform` (admin) topic, and each
 * card with the topics whose data it draws (`lib/live/topics.ts`).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ChartRealm } from "@/lib/copilot/charts";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

export type Pin = components["schemas"]["PinOut"];
export type PinPage = components["schemas"]["PinPageOut"];
export type PinCard = components["schemas"]["PinCardOut"];
export type PinIn = components["schemas"]["PinIn"];

export function pinsPath(realm: ChartRealm): string {
  return realm === "admin" ? "/v1/admin/copilot/pins" : "/v1/copilot/pins";
}

/** The list's key: `pins` on the client realm, `admin/pins` on the admin one. */
export function pinsKey(session: Session, realm: ChartRealm): readonly string[] {
  return realm === "admin" ? ["admin", "pins"] : ["pins", session.orgSlug];
}

export function usePins(session: Session, realm: ChartRealm) {
  // One literal key per realm, so the live map (`lib/live/topics.ts`) can follow each.
  const list = () => apiRequest<PinPage>(session, pinsPath(realm));
  return useQuery(
    realm === "admin"
      ? { queryKey: ["admin", "pins"], queryFn: list }
      : { queryKey: ["pins", session.orgSlug], queryFn: list },
  );
}

export function usePinCard(session: Session, realm: ChartRealm, id: string) {
  const card = () =>
    apiRequest<PinCard>(session, `${pinsPath(realm)}/${encodeURIComponent(id)}/card`);
  return useQuery(
    realm === "admin"
      ? { queryKey: ["admin", "pin-card", id], queryFn: card }
      : { queryKey: ["pin-card", session.orgSlug, id], queryFn: card },
  );
}

function useRefreshPins(session: Session, realm: ChartRealm) {
  const client = useQueryClient();
  return () => void client.invalidateQueries({ queryKey: pinsKey(session, realm) });
}

export function useAddPin(session: Session, realm: ChartRealm) {
  const refresh = useRefreshPins(session, realm);
  return useMutation({
    mutationFn: (body: PinIn) => apiRequest<Pin>(session, pinsPath(realm), { method: "POST", body }),
    onSuccess: refresh,
  });
}

export function useRenamePin(session: Session, realm: ChartRealm) {
  const refresh = useRefreshPins(session, realm);
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiRequest<Pin>(session, `${pinsPath(realm)}/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: { title },
      }),
    onSuccess: refresh,
  });
}

export function useReorderPins(session: Session, realm: ChartRealm) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) =>
      apiRequest<PinPage>(session, `${pinsPath(realm)}/order`, { method: "PUT", body: { ids } }),
    onSuccess: (page) => client.setQueryData(pinsKey(session, realm), page),
    onError: () => void client.invalidateQueries({ queryKey: pinsKey(session, realm) }),
  });
}

export function useRemovePin(session: Session, realm: ChartRealm) {
  const refresh = useRefreshPins(session, realm);
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest<Pin>(session, `${pinsPath(realm)}/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
}

export function useRestorePin(session: Session, realm: ChartRealm) {
  const refresh = useRefreshPins(session, realm);
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest<Pin>(session, `${pinsPath(realm)}/${encodeURIComponent(id)}/restore`, {
        method: "POST",
      }),
    onSuccess: refresh,
  });
}
