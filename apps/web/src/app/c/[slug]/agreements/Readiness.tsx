"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";

import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { NoticeBox, PRIMARY_BUTTON, type NoticeTone } from "@/components/ui";
import { needsAction, type LegalReadiness, type ReadinessBlocker } from "@/lib/api/agreements";
import { useClientRealm } from "@/lib/api/session";

import { AcceptPanel } from "./AcceptPanel";
import { DocumentRows } from "./documents";

/** Whose move a blocker is, in the two words its status says. */
const ACTOR_STATUS: Record<ReadinessBlocker["actor"], { label: string; tone: NoticeTone }> = {
  client: { label: "Your move", tone: "warn" },
  calevate: { label: "Ours to do", tone: "neutral" },
};

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

type NextAction = { href: string; label: string; internal: boolean };

/**
 * The whole screen, over an answer that has already arrived.
 *
 * Top: the server's verdict and what stands in the way, a row per blocker with whose move
 * it is and the server's reason behind its ⓘ. Under the list sits ONE primary action, the
 * first thing the owner can do; a second, different action is a quiet link beside it, so
 * the rows themselves carry no controls and stay one line on a phone. The agreements row
 * is always listed because this screen is where they are cleared; its "done" is the
 * ABSENCE of its blocker in the same response, so nothing here re-derives the gate's
 * verdict.
 *
 * Inbound is said once, under the list.
 */
export function Readiness({ readiness }: { readiness: LegalReadiness }) {
  const { href, session } = useClientRealm();
  const blocking = readiness.documents.filter((doc) => doc.blocking);
  const readable = readiness.documents.filter((doc) => !doc.blocking);
  const agreements = readiness.blockers.find((row) => row.rule === AGREEMENTS_RULE);
  const others = readiness.blockers.filter((row) => row !== agreements);
  const outstanding = blocking.some(needsAction);

  const actionFor = (row: ReadinessBlocker): NextAction | null => {
    if (row.actor !== "client") return null;
    if (row.rule === AGREEMENTS_RULE) {
      return {
        href: "#accept",
        label: readiness.can_accept ? "Review and accept" : "See the agreements",
        internal: true,
      };
    }
    if (VERIFY_BUSINESS_RULES.has(row.rule)) {
      return { href: href(`/c/${session.orgSlug}/verify-business`), label: "Verify your business", internal: false };
    }
    return null;
  };
  // One action per destination: three verification rules are one trip to one page.
  const actions = [...(agreements ? [agreements] : []), ...others]
    .map(actionFor)
    .filter((action): action is NextAction => action !== null)
    .filter((action, index, all) => all.findIndex((other) => other.href === action.href) === index);
  const [primary, secondary] = actions;

  return (
    <div className="max-w-2xl space-y-10 pb-12">
      <div className="space-y-4">
        <PageHeader
          status={
            <StatusPill tone={readiness.may_operate ? "ok" : "stop"}>
              {readiness.may_operate ? "This account is ready to make calls." : "Outgoing calls are blocked."}
            </StatusPill>
          }
          description={readiness.verdict}
        />

        <div className="rounded-card border border-line bg-surface px-4 pb-4 pt-1 sm:px-5">
          <h2 className="sr-only">Before outgoing calls can start</h2>
          <ul className="divide-y divide-line">
            {agreements ? (
              <BlockerRow row={agreements} />
            ) : (
              <StatusRow label="Agreements accepted" status="Done" tone="ok" />
            )}
            {others.map((row) => (
              <BlockerRow key={row.rule} row={row} />
            ))}
          </ul>

          {primary && (
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line pt-4">
              <ActionLink action={primary} className={`${PRIMARY_BUTTON} justify-center max-sm:w-full`} />
              {secondary && <ActionLink action={secondary} className={TEXT_ACTION} />}
            </div>
          )}

          <div className={`space-y-1 text-meta text-ink-muted ${primary ? "mt-3" : "mt-2 border-t border-line pt-3"}`}>
            {!readiness.may_operate && <p>Calls coming in are unaffected. Your agent keeps answering.</p>}
            {others.length === 0 && (
              <p>
                Nothing else at the account level is holding up outgoing calls. A campaign can have conditions of
                its own, named on the campaign.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* The jump target of "Review and accept". */}
      <div id="accept" className="scroll-mt-4">
        <Section
          title="Agreements that bind your business"
          description={
            !outstanding
              ? "Open any of them to read it again."
              : readiness.can_accept
                ? "Read each one, then accept them together below."
                : "Read each one. The account owner accepts them."
          }
        >
          {readiness.provisional_notice && (
            <NoticeBox tone="warn" title="These are drafts" className="mb-4">
              {readiness.provisional_notice}
            </NoticeBox>
          )}
          <DocumentRows docs={blocking} />
          <AcceptPanel readiness={readiness} />
        </Section>
      </div>

      {readable.length > 0 && (
        <Section
          title="Also published, nothing to accept"
          description="Notices we owe you, not promises you make us."
        >
          <DocumentRows docs={readable} />
        </Section>
      )}
    </div>
  );
}

/**
 * One line: what it is on the left, whose move on the right. The ⓘ holds the server's two
 * sentences, the reason first; the step is dropped when the server sent the same sentence
 * twice, so the tip never repeats itself.
 */
function BlockerRow({ row }: { row: ReadinessBlocker }) {
  const status = ACTOR_STATUS[row.actor];
  const step = row.next_step.trim() === row.reason.trim() ? null : row.next_step;
  return (
    <StatusRow
      label={row.title}
      status={status.label}
      tone={status.tone}
      info={
        <>
          <p>{row.reason}</p>
          {step && <p className="mt-1 text-ink">{step}</p>}
        </>
      }
    />
  );
}

function StatusRow({
  label,
  status,
  tone,
  info,
}: {
  label: string;
  status: string;
  tone: NoticeTone;
  info?: ReactNode;
}) {
  return (
    <li className="flex min-h-12 items-center justify-between gap-3 py-1">
      <span className="flex min-w-0 items-center gap-0.5">
        <span className="min-w-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{label}</span>
        {info && (
          <InfoTip label={label} className="shrink-0">
            {info}
          </InfoTip>
        )}
      </span>
      <StatusPill tone={tone}>{status}</StatusPill>
    </li>
  );
}

function ActionLink({ action, className }: { action: NextAction; className: string }) {
  const body = (
    <>
      {action.label}
      <ArrowRight aria-hidden className="h-4 w-4 shrink-0" />
    </>
  );
  return action.internal ? (
    <a href={action.href} className={className}>
      {body}
    </a>
  ) : (
    <Link href={action.href} className={className}>
      {body}
    </Link>
  );
}
