"use client";

import { AnnouncementBar, platformAnnouncementProps } from "@/components/arc/announcement-bar";
import { useActionFeedback } from "@/components/arc/feedback";
import { useToast } from "@/components/arc/toast";
import { useAnnouncements, useDismissAnnouncement } from "@/lib/api/announcements";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

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
 * The announcement strip above the client top bar (D-869), mapped by `platformAnnouncementProps`
 * so it reads exactly as the admin composer's preview: the most urgent one this account
 * has not dismissed (the server sends critical first), one at a time. Dismissing puts it
 * away for the whole account and the next one, if any, takes its place.
 *
 * Dismissing is an account setting (`org:manage`): someone without it sees no close button.
 * An operator viewing the account cannot dismiss for the client (the server refuses it), so
 * pressing close then says so in a note and sends nothing. A failed read shows nothing: the strip is news,
 * and the bell carries the same items with its own failure state.
 */
export function ClientAnnouncements({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const announcements = useAnnouncements(session);
  const dismiss = useDismissAnnouncement(session);
  const feedback = useActionFeedback(dismiss, { errorTitle: "Could not dismiss the announcement" });
  const toasts = useToast();
  const access = useWriteAccess(session, "org:manage", "put announcements away");
  const current = announcements.data?.items[0];
  if (!current) return null;
  const viewingAs = Boolean(session.impersonateOrg);
  const bar = platformAnnouncementProps(current);
  return (
    <AnnouncementBar
      {...bar}
      action={bar.action && { ...bar.action, href: consoleHref(bar.action.href, slug, href) }}
      onDismiss={
        !access.allowed && !viewingAs
          ? undefined
          : viewingAs
          ? () =>
              toasts.toast({
                kind: "info",
                title: "Only the account can dismiss this",
                description: "You are viewing as this account, so the announcement stays for its people to read.",
              })
          : () => feedback.run(current.id)
      }
      dismissLabel="Dismiss this announcement"
      dismissStatus={feedback.status}
    />
  );
}
