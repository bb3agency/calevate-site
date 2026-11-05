"use client";

import Link from "next/link";
import { PhoneOutgoing } from "lucide-react";

import { SECONDARY_BUTTON_SM } from "@/components/ui";

/**
 * CALL THIS LEAD — opens Make a call with the lead and this screen's agent filled in.
 *
 * It used to dial from the row and keep the gate's answer beside it. One form now places
 * every one-off call (founder, 5 Nov 2026), so the refusal, the next allowed time and the
 * live status are said there, once, in the same words for every door.
 */
export function CallControl({ href }: { href: string }) {
  return (
    <Link href={href} className={`${SECONDARY_BUTTON_SM} whitespace-nowrap`}>
      <PhoneOutgoing aria-hidden className="h-3.5 w-3.5 shrink-0" />
      Call with AI
    </Link>
  );
}
