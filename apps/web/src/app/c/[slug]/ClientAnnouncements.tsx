"use client";

import { AnnouncementBar, type AnnouncementTone } from "@/components/arc/announcement-bar";
import { useActionFeedback } from "@/components/arc/feedback";
import { useAnnouncements, useDismissAnnouncement, type Announcement } from "@/lib/api/announcements";
import { useClientRealm } from "@/lib/api/session";

const TONE: Record<Announcement["tone"], AnnouncementTone> = {
  info: "info",
  success: "info",
  warning: "warn",
  critical: "critical",
};

/**
 * A feed link: an https address as it is, or a console path ("/billing") inside
 * this account, through the realm's `href` so a view-as session keeps its account.
 */
export function consoleHref(
  link: string,
  slug: string,
  href: (path: string) => string,
): string {
  return link.startsWith("https://") ? link : href(`/c/${slug}${link}`);
}

/**
 * The announcement strip above the client top bar (D-869): the most urgent one this account
 * has not dismissed (the server sends critical first), one at a time. Dismissing puts it
 * away for the whole account and the next one, if any, takes its place.
 *
 * An operator viewing the account cannot dismiss for the client (the server refuses it), so
 * the strip offers no close button then. A failed read shows nothing: the strip is news,
 * and the bell carries the same items with its own failure state.
 */
export function ClientAnnouncements({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const announcements = useAnnouncements(session);
  const dismiss = useDismissAnnouncement(session);
  const feedback = useActionFeedback(dismiss, { errorTitle: "Could not dismiss the announcement" });
  const current = announcements.data?.items[0];
  if (!current) return null;
  const viewingAs = Boolean(session.impersonateOrg);
  return (
    <AnnouncementBar
      title={current.message}
      tone={TONE[current.tone]}
      role={current.tone === "critical" ? "alert" : "status"}
      action={
        current.link_url
          ? { href: consoleHref(current.link_url, slug, href), label: current.link_label ?? "See details" }
          : undefined
      }
      onDismiss={viewingAs ? undefined : () => feedback.run(current.id)}
      dismissLabel="Dismiss this announcement"
      dismissStatus={feedback.status}
    />
  );
}
