"use client";

import { FileText } from "lucide-react";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { PageHeader } from "@/components/console/pageHeader";
import { Disclosure } from "@/components/ui";
import type { LegalReadiness, ReadinessBlocker } from "@/lib/api/agreements";
import { useClientRealm } from "@/lib/api/session";

import { AcceptPanel } from "./AcceptPanel";
import { AutodialerNoticePanel } from "./AutodialerNoticePanel";
import { DocumentRows, TonePill } from "./documents";

/** Whose move a blocker is, in the two words the row is labelled with. */
const ACTOR_LABEL = { client: "Your move", calevate: "Ours to do" } as const;

/** The server's rule names for the two blockers this screen can clear itself. */
const AGREEMENTS_RULE = "agreements_not_accepted";
const isAutodialerRule = (rule: string) => rule.startsWith("autodialer_notice_");

/**
 * The whole screen, over an answer that has already arrived.
 *
 * What stands in the way is ONE checklist. Its open items are the server's blockers, word
 * for word (`title`, `reason`, `next_step`, `actor`). Two items are always listed because
 * this screen is where they are cleared: the agreements and the autodialler notice. Their
 * state is the ABSENCE of their blocker in the same response, so nothing here re-derives
 * a verdict the dial gate computes.
 */
export function Readiness({ readiness }: { readiness: LegalReadiness }) {
  const { href, session } = useClientRealm();
  const blocking = readiness.documents.filter((doc) => doc.blocking);
  const readable = readiness.documents.filter((doc) => !doc.blocking);
  const agreements = readiness.blockers.find((row) => row.rule === AGREEMENTS_RULE);
  const autodialer = readiness.blockers.find((row) => isAutodialerRule(row.rule));
  const others = readiness.blockers.filter((row) => row !== agreements && row !== autodialer);

  const items: ChecklistItem[] = [
    agreements
      ? blockerItem(agreements, { action: <JumpLink to="#accept" label="Accept below" /> })
      : { id: AGREEMENTS_RULE, label: "Agreements accepted", state: "done" },
    autodialer
      ? blockerItem(autodialer, { action: <JumpLink to="#autodialer-notice" label="Record it below" /> })
      : { id: "autodialer_notice", label: "Autodialler notice on file", state: "done" },
    ...others.map((row) =>
      blockerItem(
        row,
        row.rule === "pe_registration_missing" || row.rule === "kyc_missing"
          ? { link: { href: href(`/c/${session.orgSlug}/verification`), label: "Open Verification" } }
          : {},
      ),
    ),
  ];

  return (
    <div className="space-y-8 pb-12">
      <PageHeader
        status={
          <TonePill
            tone={readiness.may_operate ? "ok" : "stop"}
            label={readiness.may_operate ? "This account is ready to make calls." : "Outgoing calls are blocked."}
          />
        }
        description={
          <>
            {readiness.verdict}
            {!readiness.may_operate && (
              <span className="mt-1 block font-semibold text-ink">
                Calls coming IN are unaffected — your agent keeps answering the phone.
              </span>
            )}
          </>
        }
      />

      {readiness.provisional_notice && (
        <p className="flex items-start gap-2 rounded-md border border-warn-line bg-warn-soft px-3 py-2 text-[13px] text-warn">
          <FileText className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>
            <span className="font-semibold">These are drafts.</span> {readiness.provisional_notice}
          </span>
        </p>
      )}

      <Checklist label="Before outgoing calls can start" headingLevel={2} items={items} />
      {others.length === 0 && (
        <p className="-mt-5 text-[13px] text-ink-muted">
          Nothing else at the account level is blocking outgoing calls. A campaign can still
          have conditions of its own — those are named on the campaign.
        </p>
      )}

      <section id="accept" aria-labelledby="agreements-heading" className="scroll-mt-4">
        <h2 id="agreements-heading" className="text-[15px] font-semibold text-ink">
          The agreements that bind this business
        </h2>
        <p className="mt-1 text-[13px] text-ink-muted">
          Read each one, then confirm below. Calls coming IN are unaffected by anything on
          this page.
        </p>
        <div className="mt-3 rounded-card border border-line bg-surface">
          <DocumentRows docs={blocking} />
        </div>
        <AcceptPanel readiness={readiness} />
      </section>

      <AutodialerNoticePanel />

      {readable.length > 0 && (
        <Disclosure
          title="Also published, with nothing to accept"
          subtitle={`${readable.map((doc) => doc.title).join(", ")}. Notices we owe you, not promises you make us.`}
        >
          <DocumentRows docs={readable} />
        </Disclosure>
      )}
    </div>
  );
}

function blockerItem(
  row: ReadinessBlocker,
  extra: Pick<ChecklistItem, "link" | "action">,
): ChecklistItem {
  return {
    id: row.rule,
    label: row.title,
    state: row.actor === "client" ? "todo" : "waiting",
    detail: (
      <span className="block space-y-0.5">
        <span className="flex flex-wrap items-center gap-2">
          <TonePill tone={row.actor === "client" ? "warn" : "neutral"} label={ACTOR_LABEL[row.actor]} />
          <span>{row.reason}</span>
        </span>
        <span className="block text-ink">{row.next_step}</span>
      </span>
    ),
    ...extra,
  };
}

function JumpLink({ to, label }: { to: string; label: string }) {
  return (
    <a
      href={to}
      className="inline-flex items-center rounded-sm text-[13px] font-medium text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
    >
      {label}
    </a>
  );
}
