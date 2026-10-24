"use client";

/**
 * A strip across the top of a shell that says one thing to everyone on it: a platform
 * announcement, a trial running out, planned maintenance.
 *
 * Adapted from uiarc's `announcement-bar` (MIT, see ./LICENSE) into the D-771 site strip:
 * white under a hairline, ink text, a tone dot, no tinted band and no marquee. It is
 * presentational — the caller owns where the message comes from and how a dismissal is
 * remembered (the trial strip keeps a per-day browser key; a platform announcement records
 * the dismissal on the server and passes its `useActionFeedback` status here).
 *
 * The headline always shows; `detail` joins it from `sm`, so a phone keeps it to two lines.
 */

import Link from "next/link";
import type { ReactNode } from "react";
import { X } from "lucide-react";
import clsx from "clsx";

import { TEXT_ACTION } from "@/components/console/section";
import { NOTICE_DOT } from "@/components/console/statusPill";
import { SHELL_RAIL_CLASS } from "@/components/ui";

import type { FeedbackStatus } from "./feedback";

export type AnnouncementTone = "info" | "success" | "warn" | "critical";

const TONE_DOT: Record<AnnouncementTone, string> = {
  info: NOTICE_DOT.neutral,
  success: NOTICE_DOT.ok,
  warn: NOTICE_DOT.warn,
  critical: NOTICE_DOT.stop,
};

export type AnnouncementBarProps = {
  /** The one line that must be read. */
  title: ReactNode;
  /** A second sentence, shown from `sm` up. */
  detail?: ReactNode;
  tone?: AnnouncementTone;
  /** The one thing to do about it. */
  action?: { href: string; label: string };
  /** Omit for a strip that cannot be closed (a critical outage notice). */
  onDismiss?: () => void;
  dismissLabel?: string;
  /** The dismissal's own state, when it is recorded on the server. */
  dismissStatus?: FeedbackStatus;
  /** `status` (polite) by default; a `critical` strip about live calls may take `alert`. */
  role?: "status" | "alert" | "region";
  /** The region's name when `role="region"`. */
  label?: string;
};

/** A platform announcement as the server sends it (`AnnouncementOut`, D-869). */
export type PlatformAnnouncement = {
  message: string;
  tone: "info" | "success" | "warning" | "critical";
  link_url: string | null;
  link_label: string | null;
};

/**
 * The one mapping from a platform announcement to this bar, shared by the client shell
 * that shows it and the admin composer that previews it, so the preview cannot drift from
 * what clients see. A link with no label reads "Learn more"; a critical one is an alert.
 */
export function platformAnnouncementProps(
  announcement: PlatformAnnouncement,
  linkFallbackLabel = "Learn more",
): Pick<AnnouncementBarProps, "title" | "tone" | "action" | "role"> {
  const tone: AnnouncementTone = announcement.tone === "warning" ? "warn" : announcement.tone;
  return {
    title: announcement.message,
    tone,
    action: announcement.link_url
      ? { href: announcement.link_url, label: announcement.link_label || linkFallbackLabel }
      : undefined,
    role: tone === "critical" ? "alert" : "status",
  };
}

export function AnnouncementBar({
  title,
  detail,
  tone = "info",
  action,
  onDismiss,
  dismissLabel = "Dismiss",
  dismissStatus = "idle",
  role = "status",
  label,
}: AnnouncementBarProps) {
  const busy = dismissStatus === "pending";
  return (
    <div
      role={role}
      aria-label={role === "region" ? label : undefined}
      data-tone={tone}
      className="border-b border-line bg-surface px-4 text-ink lg:px-8"
    >
      <div className={clsx(SHELL_RAIL_CLASS, "flex items-center gap-3 py-1 text-sm")}>
        <span aria-hidden className={clsx("h-2 w-2 shrink-0 rounded-full", TONE_DOT[tone])} />
        <p className="min-w-0 flex-1 break-words py-1">
          <span className="font-semibold">{title}</span>
          {detail ? <span className="hidden sm:inline"> {detail}</span> : null}
        </p>
        {action ? (
          <Link href={action.href} className={clsx(TEXT_ACTION, "max-w-[45%] shrink-0")}>
            {action.label}
          </Link>
        ) : null}
        {onDismiss ? (
          <button
            type="button"
            aria-label={dismissLabel}
            aria-busy={busy || undefined}
            onClick={() => {
              if (!busy) onDismiss();
            }}
            className="press -mr-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <X aria-hidden className={clsx("h-4 w-4", busy && "opacity-40")} />
          </button>
        ) : null}
      </div>
    </div>
  );
}
