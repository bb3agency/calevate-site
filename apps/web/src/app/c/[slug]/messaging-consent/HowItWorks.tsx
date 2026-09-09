"use client";

import { type ReactNode } from "react";
import { CalendarClock, CircleHelp, FileSearch, PhoneOff, ShieldAlert } from "lucide-react";

import { Card } from "@/components/ui";
import { Term } from "@/lib/glossary";
import { CONSENT_VALIDITY_DAYS } from "@/lib/api/messagingConsent";

/**
 * The five rules that govern the record — including the two this screen exists to stop a
 * client getting wrong, and which it may never blur.
 *
 * SEC-COMP §4 is explicit: a campaign's `consent_source` provenance and a `callback`
 * ledger row "never satisfy it, and nothing backfills it". They are different purposes
 * under DPDP §6, they are refused by different gates, and a follow-up message still has to
 * pass `check_dispatch` — the do-not-call read — before this record is even consulted.
 */
export function HowItWorks() {
  return (
    <Card title="How this record works">
      <ul className="space-y-3 text-sm text-ink-muted">
        <Rule
          icon={<CalendarClock className="h-4 w-4" />}
          title={`An opt-in lasts ${CONSENT_VALIDITY_DAYS} days.`}
        >
          After that it stops authorising messages and someone has to ask again. A
          check above will say so rather than quietly failing on the day it lapses.
        </Rule>
        <Rule icon={<FileSearch className="h-4 w-4" />} title="Nothing is ever deleted.">
          Recording a refusal adds a new entry that supersedes the earlier one, so the
          history of what someone agreed to — and when — stays intact.
        </Rule>
        <Rule
          icon={<PhoneOff className="h-4 w-4" />}
          title="Agreeing to a call is not agreeing to a message."
        >
          Someone who asked to be called back has not opted in to WhatsApp, and
          nothing here fills that in for them. It is a separate purpose, and nothing
          backfills it from your campaign lists or your call records.
        </Rule>
        <Rule
          icon={<ShieldAlert className="h-4 w-4" />}
          title="This is in addition to do-not-call."
        >
          A follow-up still passes the same do-not-call and calling-hours checks a
          call does; consent never replaces them.
        </Rule>
        {/* SEC-COMP §4, TCCCPR 2018 as amended (Second Amendment, 12 Feb 2025): explicit
            consent under Reg. 2(y) is recorded by the Consent Registrar on DLT through
            Digital Consent Acquisition — a registrar function we cannot perform. What
            is captured here is OUR evidence. Saying so is not a disclaimer: a client
            who believes this screen produces registrar-grade consent will use it to
            answer a regulator, and that is the sentence they will be answering with. */}
        <Rule icon={<CircleHelp className="h-4 w-4" />} title="This is your evidence, not a DLT record.">
          It is what you would produce if a number is challenged — who agreed, when,
          and on what. It is not the consent recorded on{" "}
          <Term id="dlt" />, which
          Indian telecom rules define separately, and it does not stand in for one.
        </Rule>
      </ul>
    </Card>
  );
}

function Rule({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <li className="flex items-start gap-3">
      <span
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
        aria-hidden
      >
        {icon}
      </span>
      <span>
        <span className="font-medium text-ink">{title}</span> {children}
      </span>
    </li>
  );
}
