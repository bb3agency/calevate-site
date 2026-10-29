"use client";

import Link from "next/link";

import { PageHeader } from "@/components/console/pageHeader";
import { CopyButton } from "@/components/interior/copy-button";
import { NOTICE_BAR, NOTICE_BASE, SECONDARY_BUTTON_SM } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { resolvePlaceholders } from "@/lib/legal/placeholders";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { WhyTip } from "../agreements/_ui/WhyTip";
import { BREACH_COPY as COPY, BREACH_STEPS, CUSTOMER_MESSAGE, RECORD_SHEET } from "./copy";

/**
 * What a business does if its customers' data leaks (D-943). Primary job: the next step,
 * in order, with the button for it. Static: nothing here is read from or written to us,
 * so it works when everything else is on fire.
 *
 * The timelines are the DPDP Rules 2025 as reported by secondary sources (the Rules' own
 * text was not read; `apps/api/compliance/breach.py` carries the same caveat), and the
 * duties commence about 13 May 2027 — earlier if a proposed shortening is notified, which
 * is UNKNOWN. The page says "about" and "reported" where the source is secondary.
 */
export default function BreachPlaybookPage() {
  const { href } = useClientRealm();

  useCopilotSurface({
    route: "/c/{slug}/breach-playbook",
    title: "If customer data leaks",
    realm: "client",
    fields: [],
    facts: [
      { key: "steps", label: "Steps on this page, in order", value: BREACH_STEPS.map((s) => s.title).join("; ") },
      { key: "advice", label: "Status of this page", value: "general steps, not legal advice" },
    ],
    apply: noFill,
  });

  return (
    <div className="max-w-3xl space-y-6 pb-12">
      <PageHeader description={COPY.description} />
      <p role="note" className={`${NOTICE_BASE} ${NOTICE_BAR.warn} text-meta leading-snug`}>
        {COPY.notAdvice}
      </p>

      <ol className="space-y-4">
        {BREACH_STEPS.map((step, index) => (
          <li key={step.title} className="rounded-card border border-line bg-surface px-4 py-3">
            <h2 className="text-section font-semibold text-ink">
              {index + 1}. {step.title}{" "}
              {step.why && (
                <WhyTip about={step.title} label="Why?">
                  <p>{step.why}</p>
                </WhyTip>
              )}
            </h2>
            <p className="mt-1 text-body text-ink-muted">{step.line}</p>
            {step.when && <p className="mt-1 text-meta font-medium text-ink">{step.when}</p>}
            <div className="mt-2 flex flex-wrap gap-2">
              {step.action === "record" && <CopyButton value={RECORD_SHEET} label={COPY.copyRecord} variant="text" />}
              {step.action === "message" && (
                <CopyButton value={CUSTOMER_MESSAGE} label={COPY.copyMessage} variant="text" />
              )}
              {step.action === "rights" && (
                <Link className={SECONDARY_BUTTON_SM} href={href("/data-rights")}>
                  {COPY.openRights}
                </Link>
              )}
              {step.action === "tell-us" && (
                <a className={SECONDARY_BUTTON_SM} href={`mailto:${resolvePlaceholders("{{SUPPORT_EMAIL}}")}?subject=Possible%20data%20breach`}>
                  {COPY.tellUs}
                </a>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
