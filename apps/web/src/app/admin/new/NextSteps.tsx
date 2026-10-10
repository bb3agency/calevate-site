"use client";

import Link from "next/link";
import { ArrowLeft, ListChecks, Plus } from "lucide-react";

import { HAIRLINE_LIST } from "@/components/admin/kit";
import { Section } from "@/components/console/section";
import { SECONDARY_BUTTON } from "@/components/ui";
import { viewAsHref } from "@/lib/api/session";
import { Term } from "@/lib/glossary";

/** What the operator does next for a client just created and invited. */
export function NextSteps({ created }: { created: { id: string; slug: string } }) {
  return (
    <div className="space-y-6">
      <Section title="What happens next">
        {/* The account this wizard just created is immediately HELD on three gates that
            each have a working screen — KYC, commercial terms, first-campaign release —
            and this card used to name neither, so the account dropped silently into
            /admin/holds to be discovered later from a queue instead of continued now
            from the flow that created it (ux-audit F-7). The three links, in the order
            the holds bite; then the two genuinely-manual items. */}
        <ol className={`${HAIRLINE_LIST} text-body text-ink-muted [&>li]:py-2.5`}>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              The owner fills in their business setup after they join. You can help from{" "}
              <a
                href={viewAsHref(created.slug, "/setup")}
                className="rounded-sm font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
              >
                view as client
              </a>
            </span>
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              <Link
                href={`/admin/tenants/${created.id}/kyc`}
                className="rounded-sm font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
              >
                Record their identity verification
              </Link>{" "}
              — number provisioning and outbound stay held until it is on file
            </span>
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              <Link
                href={`/admin/tenants/${created.id}/commercials`}
                className="rounded-sm font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
              >
                Set their commercial terms
              </Link>{" "}
              — nothing can be billed until the agreement is recorded
            </span>
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              <Link
                href={`/admin/tenants/${created.id}/first-campaign-review`}
                className="rounded-sm font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
              >
                Release their first campaign
              </Link>{" "}
              — every new account&apos;s first launch waits on this review
            </span>
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              Getting a phone number and registering with{" "}
              <Term id="dlt" />/
              <Term id="pe" term="PE" audience="operator" />{" "}
              — still done by hand
            </span>
          </li>
          <li className="flex gap-2">
            <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            A test call signed off before the agent goes live — still done by hand
          </li>
        </ol>
      </Section>
      <div className="flex flex-wrap gap-2">
        <Link href={`/admin/tenants/${created.id}`} className={SECONDARY_BUTTON}>
          <Plus aria-hidden className="h-3.5 w-3.5" />
          Open client
        </Link>
        <Link href="/admin" className={SECONDARY_BUTTON}>
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          Back to clients
        </Link>
      </div>
    </div>
  );
}
