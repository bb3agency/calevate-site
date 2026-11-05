"use client";

import { ExternalLink, ShieldAlert } from "lucide-react";

import { Disclosure, SECONDARY_BUTTON_SM } from "@/components/ui";
import { Why } from "@/components/why";

/**
 * What a business can do when the people it calls see its number labelled "Suspected spam"
 * (e2e audit OB-24). Only the steps that are the business's own, from
 * `docs/evidence/caller-spam-labels-2026-11.md` §(b), read 4 Nov 2026: Samsung's caller ID is
 * Hiya's (samsung.com/in/apps/smart-call), Hiya registers a business's number free in its
 * own name, and every blocked call is another signal against the number. What that research
 * could not confirm is said as such: whether Hiya takes Indian numbers is unknown until its
 * form answers, and whether saving a contact lifts the block is not documented.
 *
 * Never advice to change numbers to shed a label: that is detection evasion, which TRAI's
 * 18 Sep 2026 amendment targets and which loses the account.
 */
export const SPAM_COPY = {
  title: "If callers see “Suspected spam”",
  closed: "Steps that help your number be known",
  save: "Ask them to save your number.",
  register: "Register your number with Hiya, free.",
  registerAction: "Register with Hiya",
  pause: "Pause calls from that number until the label goes.",
} as const;

/** The reasons, each shown only behind its "Why?" tap. */
export const SPAM_WHY = {
  save: "If they blocked it, ask them to take it off their blocked list too.",
  register:
    "Many Android phones label calls using Hiya. Register in your business's name. Hiya may not take Indian numbers yet; its form will tell you.",
  pause: "Each blocked call counts against the number.",
} as const;

/** Hiya's own number-registration form (linked from hiya.com/products/connect/number-registration). */
export const HIYA_REGISTRATION_URL =
  "https://business.hiya.com/registration/number-registration/account/details?preselected=true";

export function SpamLabels() {
  return (
    <Disclosure
      title={SPAM_COPY.title}
      subtitle={SPAM_COPY.closed}
      icon={<ShieldAlert className="h-4 w-4" />}
      headingLevel={2}
    >
      <ol className="list-decimal space-y-3 pl-5 text-body text-ink">
        <li>
          {SPAM_COPY.save}
          <Why>{SPAM_WHY.save}</Why>
        </li>
        <li className="space-y-2">
          <span>
            {SPAM_COPY.register}
            <Why>{SPAM_WHY.register}</Why>
          </span>
          <a
            href={HIYA_REGISTRATION_URL}
            target="_blank"
            rel="noopener noreferrer"
            className={`${SECONDARY_BUTTON_SM} w-full justify-center sm:w-auto`}
          >
            {SPAM_COPY.registerAction}
            <ExternalLink aria-hidden className="h-3.5 w-3.5" />
          </a>
        </li>
        <li>
          {SPAM_COPY.pause}
          <Why>{SPAM_WHY.pause}</Why>
        </li>
      </ol>
    </Disclosure>
  );
}
