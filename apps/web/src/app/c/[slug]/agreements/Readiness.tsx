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
import { AGREEMENTS_COPY as COPY } from "./copy";
import { DocumentRows } from "./documents";
import { WhyTip } from "./_ui/WhyTip";

/** Whose move a blocker is, in the two words its status says. */
const ACTOR_STATUS: Record<ReadinessBlocker["actor"], { label: string; tone: NoticeTone }> = {
  client: { label: COPY.yourMove, tone: "warn" },
  calevate: { label: COPY.oursToDo, tone: "neutral" },
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

/** D-941's calling-number rules, cleared in the Calling numbers card on Verify your business. */
const CALLING_NUMBER_RULES = new Set([
  "a2p_declaration_missing",
  "a2p_declaration_not_yet_effective",
  "a2p_number_undeclared",
]);

type NextAction = { href: string; label: string; internal: boolean };

/**
 * The whole screen, over an answer that has already arrived.
 *
 * Top: a status chip and the server's verdict, then a short "Before calls can start" list,
 * one row per blocker with whose move it is and the server's reason behind its ⓘ. Under
 * the list sits ONE primary button, the first thing the owner can do; a second, different
 * action is a quiet link beside it, so the rows carry no controls and stay one line on a
 * phone. The agreements row is always listed because this screen is where they are
 * cleared; its "done" is the ABSENCE of its blocker in the same response, so nothing here
 * re-derives the gate's verdict.
 *
 * Inbound is said once, under the list, in one line: it is the reassurance a blocked owner
 * needs, so it is not behind a tap.
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
        label: readiness.can_accept ? COPY.reviewAndAccept : COPY.seeAgreements,
        internal: true,
      };
    }
    if (VERIFY_BUSINESS_RULES.has(row.rule)) {
      return { href: href(`/c/${session.orgSlug}/verify-business`), label: COPY.verifyBusiness, internal: false };
    }
    if (CALLING_NUMBER_RULES.has(row.rule) && row.rule !== "a2p_declaration_not_yet_effective") {
      return {
        // The fragment after the realm query, so a view-as session keeps both.
        href: `${href(`/c/${session.orgSlug}/verify-business`)}#calling-numbers`,
        label: COPY.confirmNumbers,
        internal: false,
      };
    }
    return null;
  };
  // One action per destination: three verification rules are one trip to one page. An
  // upcoming item comes after every blocker: it does not stop calls yet.
  const actions = [...(agreements ? [agreements] : []), ...others, ...readiness.upcoming]
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
              {readiness.may_operate ? COPY.ready : COPY.blocked}
            </StatusPill>
          }
          description={readiness.verdict}
        />

        <div className="rounded-card border border-line bg-surface px-4 pb-4 pt-1 sm:px-5">
          <h2 className="pt-3 text-meta font-semibold text-ink-muted">{COPY.todoHeading}</h2>
          <ul className="divide-y divide-line">
            {agreements ? (
              <BlockerRow row={agreements} />
            ) : (
              <StatusRow label={COPY.agreementsDone} status={COPY.done} tone="ok" />
            )}
            {others.map((row) => (
              <BlockerRow key={row.rule} row={row} />
            ))}
            {readiness.upcoming.map((row) => (
              <BlockerRow key={`upcoming-${row.rule}`} row={row} upcoming />
            ))}
          </ul>

          {primary && (
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line pt-4">
              <ActionLink action={primary} className={`${PRIMARY_BUTTON} justify-center max-sm:w-full`} />
              {secondary && <ActionLink action={secondary} className={TEXT_ACTION} />}
            </div>
          )}

          <div className={`space-y-1 text-meta text-ink-muted ${primary ? "mt-3" : "mt-2 border-t border-line pt-3"}`}>
            {!readiness.may_operate && <p>{COPY.inboundFine}</p>}
            {others.length === 0 && (
              <p className="flex flex-wrap items-center gap-x-1">
                {COPY.nothingElse}
                <WhyTip about="campaign checks" label="More">
                  <p>{COPY.nothingElseWhy}</p>
                </WhyTip>
              </p>
            )}
          </div>
        </div>
      </div>

      {/* The jump target of "Review and accept". */}
      <div id="accept" className="scroll-mt-4">
        <Section
          title={COPY.sectionTitle}
          description={
            !outstanding
              ? COPY.sectionReadAgain
              : readiness.can_accept
                ? COPY.sectionAccept
                : COPY.sectionOwner
          }
        >
          {readiness.provisional_notice && (
            <NoticeBox tone="warn" title={COPY.drafts} className="mb-4">
              {readiness.provisional_notice}
            </NoticeBox>
          )}
          <DocumentRows docs={blocking} />
          <AcceptPanel readiness={readiness} />
        </Section>
      </div>

      {readable.length > 0 && (
        <Section title={COPY.alsoTitle} description={COPY.alsoNote}>
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
function BlockerRow({ row, upcoming = false }: { row: ReadinessBlocker; upcoming?: boolean }) {
  // An upcoming item does not stop calls yet, so its pill does not say "Your move" in the
  // blocking tone; its title carries the date.
  const status = upcoming ? { label: COPY.comingUp, tone: "neutral" as const } : ACTOR_STATUS[row.actor];
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
