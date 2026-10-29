import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import type { Session } from "@/lib/api/client";
import {
  feedSeenThrough,
  notificationKeys,
  useMarkNotificationsSeen,
  type Notification,
  type NotificationFeed,
} from "@/lib/api/notifications";

import { problem, stubApi, stillLoading } from "./harness";

const SESSION: Session = { orgSlug: "acme" };

function item(id: string, at: string, unread: boolean): Notification {
  return {
    id,
    kind: "lead_hot",
    source: "attention",
    tone: "info",
    title: `Item ${id}`,
    detail: null,
    href: null,
    link_label: null,
    occurred_at: at,
    unread,
  };
}

const FEED: NotificationFeed = {
  items: [
    item("c", "2026-10-29T10:05:00Z", true),
    item("b", "2026-10-29T10:00:00Z", true),
    item("a", "2026-10-29T09:00:00Z", false),
  ],
  unread: 2,
  attention_total: 3,
  seen_through: "2026-10-29T09:30:00Z",
};

function harness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(notificationKeys.feed(SESSION.orgSlug), FEED);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const feed = () => client.getQueryData<NotificationFeed>(notificationKeys.feed(SESSION.orgSlug));
  return { wrapper, feed };
}

describe("the bell's read mark", () => {
  it("marks seen everything up to the mark and keeps what came after unread", () => {
    const next = feedSeenThrough(FEED, "2026-10-29T10:00:00Z");
    expect(next.items.map((i) => [i.id, i.unread])).toEqual([
      ["c", true],
      ["b", false],
      ["a", false],
    ]);
    expect(next.unread).toBe(1);
    expect(next.seen_through).toBe("2026-10-29T10:00:00Z");
    // Forward-only, like the server's GREATEST.
    expect(feedSeenThrough(FEED, "2026-10-29T08:00:00Z").seen_through).toBe(FEED.seen_through);
  });

  it("drops the badge while the write is still on its way", async () => {
    stubApi({ "GET /v1/notifications?limit=30": stillLoading(), "POST /v1/notifications/seen": stillLoading() });
    const { wrapper, feed } = harness();
    const { result } = renderHook(() => useMarkNotificationsSeen(SESSION), { wrapper });

    act(() => result.current.mutate("2026-10-29T10:05:00Z"));

    await waitFor(() => expect(feed()?.unread).toBe(0));
    expect(result.current.isPending).toBe(true);
  });

  it("puts the badge back when the write is refused", async () => {
    stubApi({
      "GET /v1/notifications?limit=30": stillLoading(),
      "POST /v1/notifications/seen": problem(503, { title: "Try again shortly." }),
    });
    const { wrapper, feed } = harness();
    const { result } = renderHook(() => useMarkNotificationsSeen(SESSION), { wrapper });

    act(() => result.current.mutate("2026-10-29T10:05:00Z"));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(feed()?.unread).toBe(2);
    expect(feed()?.items.filter((i) => i.unread).map((i) => i.id)).toEqual(["c", "b"]);
  });
});
