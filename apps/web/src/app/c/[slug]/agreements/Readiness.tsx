"use client";

import { ChecklistRows, type ChecklistRow } from "@/components/console/checklist";
import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { NoticeBox } from "@/components/ui";
import type { LegalReadiness, ReadinessBlocker } from "@/lib/api/agreements";
import { useClientRealm } from "@/lib/api/session";

import { AcceptPanel } from "./AcceptPanel";
import { DocumentRows } from "./documents";
import { StatusPill } from "@/components/console/statusPill";

/** Whose move a blocker is, in the two words its status pill says. */
const ACTOR_LABEL = { client: "Your move", calevate: "Ours to do" } as const;

/** The server's rule name for the blocker this screen can clear itself. */
const AGREEMENTS_RULE = "agreements_not_accepted";

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
 * server's reason and next step behind the row's ⓘ, word for word. The agreements are
 * always listed because this screen is where they are cleared. Their state is the ABSENCE
 * of their blocker in the same response, so nothing here re-derives a verdict the dial gate
 * computes.
 *
 * Inbound is said once, as the list's summary. The verdict, the reasons and the section
 * descriptions used to say it too, and the screen printed it three times.
 */
export function Readiness({ readiness }: { readiness: LegalReadiness }) {
  const { href, session } = useClientRealm();
  const blocking = readiness.documents.filter((doc) => doc.blocking);
  const readable = readiness.documents.filter((doc) => !doc.blocking);
  const agreements = readiness.blockers.find((row) => row.rule === AGREEMENTS_RULE);
  const others = readiness.blockers.filter((row) => row !== agreements);

  const rows: ChecklistRow[] = [
    agreements
      ? blockerRow(agreements, { action: <JumpLink to="#accept" label="Accept below" /> })
      : { id: AGREEMENTS_RULE, label: "Agreements accepted", status: "done" },
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
          <StatusPill tone={readiness.may_operate ? "ok" : "stop"}>
            {readiness.may_operate ? "This account is ready to make calls." : "Outgoing calls are blocked."}
          </StatusPill>
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
  { link, action }: { link?: ChecklistRow["link"]; action?: ChecklistRow["action"] },
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
