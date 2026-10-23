"use client";

/**
 * The bell's one feed (D-869): needs-attention items and announcements, newest first, with
 * `unread` per item and in total, against this person's read mark. `href` on an attention
 * item is realm-relative; on an announcement it is an https address or a console path.
 * Opening the bell should call `useMarkNotificationsSeen` with the newest `occurred_at`
 * shown, so an item that arrives while it is open stays unread.
 */

import { livePoll } from "@/lib/live/liveStatus";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type NotificationFeed = Schemas["NotificationFeedOut"];
export type Notification = Schemas["NotificationOut"];
export type NotificationsSeen = Schemas["SeenOut"];

export const notificationKeys = {
  feed: (org: string) => ["notifications", org] as const,
};

export function useNotifications(session: Session, limit = 30): UseQueryResult<NotificationFeed> {
  return useQuery({
    queryKey: notificationKeys.feed(session.orgSlug),
    queryFn: () => apiRequest<NotificationFeed>(session, `/v1/notifications?limit=${limit}`),
    refetchInterval: livePoll(60_000),
  });
}

export function useMarkNotificationsSeen(session: Session) {
  const client = useQueryClient();
  return useMutation({
    /** `through`: an ISO instant; left out, now. */
    mutationFn: (through?: string) =>
      apiRequest<NotificationsSeen>(session, "/v1/notifications/seen", {
        method: "POST",
        body: through ? { through } : {},
      }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: notificationKeys.feed(session.orgSlug) });
    },
  });
}
