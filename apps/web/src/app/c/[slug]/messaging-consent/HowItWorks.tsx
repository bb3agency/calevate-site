"use client";

import { type ReactNode } from "react";

import { Disclosure } from "@/components/ui";
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
 *
 * Folded, because it is read once and the lookup above is the job. The two facts a reader
 * most needs stay visible above it on every screen, a phone included (a closed panel's
 * subtitle is hidden there), because the DLT one is what a client would answer a regulator
 * with.
 */
export function HowItWorks() {
  return (
    <div className="border-t border-line">
    <p className="pt-3 text-meta text-ink-muted">
      Opt-ins last {CONSENT_VALIDITY_DAYS} days. Your evidence, not a DLT record.
    </p>
    <Disclosure variant="inline" headingLevel={2} title="How this record works">
      <ul className="max-w-3xl space-y-2.5 text-meta leading-relaxed text-ink-muted">
        <Rule
          title={`An opt-in lasts ${CONSENT_VALIDITY_DAYS} days.`}
        >
          After that, ask again before messaging. A check above says when one has lapsed.
        </Rule>
        <Rule title="Nothing is ever deleted.">
          A refusal is a new entry on top of the old one, so the history of who agreed, and
          when, stays intact.
        </Rule>
        <Rule
          title="Agreeing to a call is not agreeing to a message."
        >
          Asking for a callback is not opting in to WhatsApp. Nothing fills this in from
          your campaign lists or call records.
        </Rule>
        <Rule
          title="This is in addition to do-not-call."
        >
          A follow-up still passes the do-not-call and calling-hours checks. Consent
          never replaces them.
        </Rule>
        {/* SEC-COMP §4, TCCCPR 2018 as amended (Second Amendment, 12 Feb 2025): explicit
            consent under Reg. 2(y) is recorded by the Consent Registrar on DLT through
            Digital Consent Acquisition — a registrar function we cannot perform. What
            is captured here is OUR evidence. Saying so is not a disclaimer: a client
            who believes this screen produces registrar-grade consent will use it to
            answer a regulator, and that is the sentence they will be answering with. */}
        <Rule title="This is your evidence, not a DLT record.">
          It is what you would produce if a number is challenged — who agreed, when,
          and on what. It is not the consent recorded on{" "}
          <Term id="dlt" />, which
          Indian telecom rules define separately, and it does not stand in for one.
        </Rule>
      </ul>
    </Disclosure>
    </div>
  );
}

function Rule({ title, children }: { title: string; children: ReactNode }) {
  return (
    <li>
      <span className="font-medium text-ink">{title}</span> {children}
    </li>
  );
}
