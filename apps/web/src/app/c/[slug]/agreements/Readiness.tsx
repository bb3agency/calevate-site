"use client";

import { useState } from "react";

import { ChecklistRows, type ChecklistRow } from "@/components/console/checklist";
import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { NoticeBox } from "@/components/ui";
import type { LegalReadiness, ReadinessBlocker } from "@/lib/api/agreements";
import { useClientRealm } from "@/lib/api/session";

import { AcceptPanel } from "./AcceptPanel";
import { AutodialerNoticePanel } from "./AutodialerNoticePanel";
import { DocumentRows, TonePill } from "./documents";

/** Whose move a blocker is, in the two words its status pill says. */
const ACTOR_LABEL = { client: "Your move", calevate: "Ours to do" } as const;

/** The server's rule names for the two blockers this screen can clear itself. */
const AGREEMENTS_RULE = "agreements_not_accepted";
const isAutodialerRule = (rule: string) => rule.startsWith("autodialer_notice_");

/** D-692's outbound conditions, each cleared on Verify your business. */
const VERIFY_BUSINESS_RULES = new Set([
  "kyc_missing",
  "kyc_not_verified",
  "kyc_digilocker_required",
  "outbound_pledge_missing",
  "outbound_pledge_outdated",
]);

/**
 * The whole screen, over an answer that has already arrived.
 *
 * What stands in the way is ONE list, a row per item: its title, whose move it is, and the
 * server's reason and next step behind the row's ⓘ, word for word. Two items are always
 * listed because this screen is where they are cleared: the agreements and the autodialler
 * notice. Their state is the ABSENCE of their blocker in the same response, so nothing here
 * re-derives a verdict the dial gate computes.
 *
 * Inbound is said once, as the list's summary. The verdict, the reasons and the section
 * descriptions used to say it too, and the screen printed it three times.
 */
export function Readiness({ readiness }: { readiness: LegalReadiness }) {
  const { href, session } = useClientRealm();
  // Each press of "Record it" asks the notice panel to open its form and move to it.
  const [noticeRequest, setNoticeRequest] = useState(0);
  const blocking = readiness.documents.filter((doc) => doc.blocking);
  const readable = readiness.documents.filter((doc) => !doc.blocking);
  const agreements = readiness.blockers.find((row) => row.rule === AGREEMENTS_RULE);
  const autodialer = readiness.blockers.find((row) => isAutodialerRule(row.rule));
  const others = readiness.blockers.filter((row) => row !== agreements && row !== autodialer);

  const rows: ChecklistRow[] = [
    agreements
      ? blockerRow(agreements, { action: <JumpLink to="#accept" label="Accept below" /> })
      : { id: AGREEMENTS_RULE, label: "Agreements accepted", status: "done" },
    autodialer
      ? blockerRow(autodialer, {
          action: (
            <button
              type="button"
              className={TEXT_ACTION}
              aria-controls="autodialer-notice-form"
              onClick={() => setNoticeRequest((n) => n + 1)}
            >
              Record it
            </button>
          ),
          extra: "Trial test calls come from Calevate's own number and do not need this notice.",
        })
      : { id: "autodialer_notice", label: "Autodialler notice on file", status: "done" },
    ...others.map((row) =>
      blockerRow(
        row,
        VERIFY_BUSINESS_RULES.has(row.rule)
          ? { link: { href: href(`/c/${session.orgSlug}/verify-business`), label: "Verify your business" } }
          : {},
      ),
    ),
  ];

  return (
    <div className="max-w-2xl space-y-10 pb-12">
      <PageHeader
        status={
          <TonePill
            tone={readiness.may_operate ? "ok" : "stop"}
            label={readiness.may_operate ? "This account is ready to make calls." : "Outgoing calls are blocked."}
          />
        }
        description={readiness.verdict}
      />

      {readiness.provisional_notice && (
        <NoticeBox tone="warn">
          <span className="font-semibold">These are drafts.</span> {readiness.provisional_notice}
        </NoticeBox>
      )}

      <ChecklistRows
        heading="Before outgoing calls can start"
        headingLevel={2}
        summary={
          readiness.may_operate
            ? undefined
            : "Calls coming in are unaffected. Your agent keeps answering."
        }
        rows={rows}
        footer={
          others.length === 0
            ? "Nothing else at the account level is holding up outgoing calls. A campaign can have conditions of its own, named on the campaign."
            : undefined
        }
      />

      {/* The jump target of the list's "Accept below". */}
      <div id="accept" className="scroll-mt-4">
        <Section
          title="The agreements that bind this business"
          description="Read each one, then confirm below."
        >
          <DocumentRows docs={blocking} />
          <AcceptPanel readiness={readiness} />
        </Section>
      </div>

      <AutodialerNoticePanel readiness={readiness} openRequest={noticeRequest} />

      {readable.length > 0 && (
        <Section
          title="Also published, with nothing to accept"
          description="Notices we owe you, not promises you make us."
        >
          <DocumentRows docs={readable} />
        </Section>
      )}
    </div>
  );
}

/**
 * One blocker as a row. The ⓘ holds the server's two sentences, the reason first; the
 * step is dropped when the server sent the same sentence twice, so the tip never repeats.
 */
function blockerRow(
  row: ReadinessBlocker,
  {
    link,
    action,
    extra,
  }: { link?: ChecklistRow["link"]; action?: ChecklistRow["action"]; extra?: string },
): ChecklistRow {
  const step = row.next_step.trim() === row.reason.trim() ? null : row.next_step;
  return {
    id: row.rule,
    label: row.title,
    status: row.actor === "client" ? "not_started" : "waiting",
    statusText: ACTOR_LABEL[row.actor],
    info: (
      <>
        <p>{row.reason}</p>
        {step && <p className="text-ink">{step}</p>}
        {extra && <p>{extra}</p>}
      </>
    ),
    link,
    action,
  };
}

function JumpLink({ to, label }: { to: string; label: string }) {
  return (
    <a href={to} className={TEXT_ACTION}>
      {label}
    </a>
  );
}
