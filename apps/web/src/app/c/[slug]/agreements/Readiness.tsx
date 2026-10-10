"use client";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { NoticeBox } from "@/components/ui";
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
        <NoticeBox tone="warn">
          <span className="font-semibold">These are drafts.</span> {readiness.provisional_notice}
        </NoticeBox>
      )}

      <div className="space-y-3">
        <Checklist label="Before outgoing calls can start" headingLevel={2} items={items} />
        {others.length === 0 && (
          <p className="text-meta text-ink-muted">
            Nothing else at the account level is blocking outgoing calls. A campaign can still
            have conditions of its own — those are named on the campaign.
          </p>
        )}
      </div>

      {/* The jump target of the checklist's "Accept below". */}
      <div id="accept" className="scroll-mt-4">
        <Section
          title="The agreements that bind this business"
          description="Read each one, then confirm below. Calls coming IN are unaffected by anything on this page."
        >
          <DocumentRows docs={blocking} />
          <AcceptPanel readiness={readiness} />
        </Section>
      </div>

      <AutodialerNoticePanel readiness={readiness} />

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
      className={TEXT_ACTION}
    >
      {label}
    </a>
  );
}
