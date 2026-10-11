"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { TEXT_ACTION } from "@/components/console/section";
import { NoticeBox } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useForwarding } from "@/lib/api/forwarding";

const KEY = (slug: string) => `calevate:existing-number-prompt:${slug}`;

/** Remember on this device that the client chose "Not now". Storage may be unavailable. */
export function dismissExistingNumberPrompt(slug: string): void {
  try {
    window.localStorage.setItem(KEY(slug), "dismissed");
  } catch {
    // Private mode or blocked storage: the prompt simply shows again next time.
  }
}

function dismissed(slug: string): boolean {
  try {
    return window.localStorage.getItem(KEY(slug)) === "dismissed";
  } catch {
    return false;
  }
}

/**
 * THE ONBOARDING STEP'S DOOR (D-746): once the business has a Calevate number and no
 * existing number set up, one quiet line offers to keep the number callers already know.
 * "Not now" hides it on this device; the flow is always in Settings > Phone numbers.
 */
export function ExistingNumberPrompt({ session, href }: { session: Session; href: (path: string) => string }) {
  const forwarding = useForwarding(session);
  const slug = session.orgSlug;
  // Read after mount: storage does not exist during the server render.
  const [hidden, setHidden] = useState(true);
  useEffect(() => setHidden(dismissed(slug)), [slug]);

  const data = forwarding.data;
  if (hidden || !data || data.calevate_numbers.length === 0 || data.lines.length > 0) return null;
  return (
    <NoticeBox
      tone="neutral"
      title="Keep the number your callers already know"
      info="Your existing phone forwards calls to your Calevate number. You choose when: only calls you miss, or every call."
      action={
        <>
          <Link href={href(`/c/${slug}/setup/existing-number`)} className={TEXT_ACTION}>
            Set it up
          </Link>
          <button
            type="button"
            className={TEXT_ACTION}
            onClick={() => {
              dismissExistingNumberPrompt(slug);
              setHidden(true);
            }}
          >
            Not now
          </button>
        </>
      }
    />
  );
}
