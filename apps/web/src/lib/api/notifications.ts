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

/**
 * The feed as it reads once everything up to `through` is seen: those rows lose their
 * "new" look and the badge counts only what arrived after. Rows older than the oldest one
 * shown are all before `through`, so the rows on hand are the whole remaining count.
 */
export function feedSeenThrough(feed: NotificationFeed, through: string): NotificationFeed {
  const mark = Date.parse(through);
  if (Number.isNaN(mark)) return feed;
  const items = feed.items.map((item) =>
    item.unread && Date.parse(item.occurred_at) <= mark ? { ...item, unread: false } : item,
  );
  const previous = feed.seen_through ? Date.parse(feed.seen_through) : Number.NEGATIVE_INFINITY;
  return {
    ...feed,
    items,
    unread: items.filter((item) => item.unread).length,
    seen_through: mark > previous ? through : feed.seen_through,
  };
}

/**
 * Optimistic: the badge drops the moment the bell closes rather than after the write and
 * a re-read (TanStack Query v5, "Optimistic Updates" via the cache). The mark is forward-only
 * and harmless to repeat, so a failed write only restores the previous feed and the
 * re-read on settle makes the server's count the final word.
 */
export function useMarkNotificationsSeen(session: Session) {
  const client = useQueryClient();
  const key = notificationKeys.feed(session.orgSlug);
  return useMutation({
    /** `through`: an ISO instant; left out, now. */
    mutationFn: (through?: string) =>
      apiRequest<NotificationsSeen>(session, "/v1/notifications/seen", {
        method: "POST",
        body: through ? { through } : {},
      }),
    onMutate: async (through) => {
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<NotificationFeed>(key);
      if (before) client.setQueryData(key, feedSeenThrough(before, through ?? new Date().toISOString()));
      return { before };
    },
    onError: (_error, _through, context) => {
      if (context?.before) client.setQueryData(key, context.before);
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: key });
    },
  });
}
