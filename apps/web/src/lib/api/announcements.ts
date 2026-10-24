"use client";

/**
 * The announcement bar (D-869): the client's read and dismiss, and the admin composer.
 *
 * Client: `GET /v1/announcements` is what this account is shown now, most urgent first,
 * minus what it dismissed; `POST /v1/announcements/{id}/dismiss` puts one away for the
 * whole account (refused for an operator viewing the account). `link_url` is an https
 * address or a console path starting with "/".
 *
 * Admin: list, create, patch (only the fields sent change; send null to clear a link or an
 * end) and end, all audited. Times are sent with their offset (IST: +05:30).
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";
import { livePoll } from "@/lib/live/liveStatus";
import { notificationKeys } from "./notifications";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Announcement = Schemas["AnnouncementOut"];
export type AnnouncementList = Schemas["AnnouncementListOut"];
export type AdminAnnouncement = Schemas["AnnouncementAdminOut"];
export type AdminAnnouncementList = Schemas["AnnouncementAdminListOut"];
export type AnnouncementInput = Schemas["AnnouncementIn"];
export type AnnouncementUpdate = Schemas["AnnouncementUpdateIn"];

export const announcementKeys = {
  mine: (org: string) => ["announcements", org] as const,
  admin: (past: boolean) => ["admin", "announcements", past] as const,
  adminAll: () => ["admin", "announcements"] as const,
};

export function useAnnouncements(session: Session): UseQueryResult<AnnouncementList> {
  return useQuery({
    queryKey: announcementKeys.mine(session.orgSlug),
    queryFn: () => apiRequest<AnnouncementList>(session, "/v1/announcements"),
    staleTime: 60_000,
    // No live topic carries an operator's announcement to a client stream, so the bar polls.
    refetchInterval: livePoll(5 * 60_000),
  });
}

export function useDismissAnnouncement(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (announcementId: string) =>
      apiRequest<void>(session, `/v1/announcements/${announcementId}/dismiss`, {
        method: "POST",
      }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: announcementKeys.mine(session.orgSlug) });
      void client.invalidateQueries({ queryKey: notificationKeys.feed(session.orgSlug) });
    },
  });
}

export function useAdminAnnouncements(past = false): UseQueryResult<AdminAnnouncementList> {
  return useQuery({
    queryKey: announcementKeys.admin(past),
    queryFn: () =>
      apiRequest<AdminAnnouncementList>(
        adminSession(),
        `/v1/admin/announcements${past ? "?past=true" : ""}`,
      ),
  });
}

function useAdminWrite<TVars>(send: (vars: TVars) => Promise<AdminAnnouncement>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSettled: () => {
      void client.invalidateQueries({ queryKey: announcementKeys.adminAll() });
    },
  });
}

export function useCreateAnnouncement() {
  return useAdminWrite((input: AnnouncementInput) =>
    apiRequest<AdminAnnouncement>(adminSession(), "/v1/admin/announcements", {
      method: "POST",
      body: input,
    }),
  );
}

export function useUpdateAnnouncement() {
  return useAdminWrite(({ id, change }: { id: string; change: AnnouncementUpdate }) =>
    apiRequest<AdminAnnouncement>(adminSession(), `/v1/admin/announcements/${id}`, {
      method: "PATCH",
      body: change,
    }),
  );
}

export function useEndAnnouncement() {
  return useAdminWrite((id: string) =>
    apiRequest<AdminAnnouncement>(adminSession(), `/v1/admin/announcements/${id}/end`, {
      method: "POST",
    }),
  );
}
