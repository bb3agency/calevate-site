"use client";

import { type ReactNode } from "react";

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
    <section aria-labelledby="consent-rules-heading" className="border-t border-line pt-5">
      <h2 id="consent-rules-heading" className="text-heading text-ink">
        How this record works
      </h2>
      <ul className="mt-3 max-w-3xl space-y-2.5 text-meta leading-relaxed text-ink-muted">
        <Rule
          title={`An opt-in lasts ${CONSENT_VALIDITY_DAYS} days.`}
        >
          After that it stops authorising messages and someone has to ask again. A
          check above will say so rather than quietly failing on the day it lapses.
        </Rule>
        <Rule title="Nothing is ever deleted.">
          Recording a refusal adds a new entry that supersedes the earlier one, so the
          history of what someone agreed to — and when — stays intact.
        </Rule>
        <Rule
          title="Agreeing to a call is not agreeing to a message."
        >
          Someone who asked to be called back has not opted in to WhatsApp, and
          nothing here fills that in for them. It is a separate purpose, and nothing
          backfills it from your campaign lists or your call records.
        </Rule>
        <Rule
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
        <Rule title="This is your evidence, not a DLT record.">
          It is what you would produce if a number is challenged — who agreed, when,
          and on what. It is not the consent recorded on{" "}
          <Term id="dlt" />, which
          Indian telecom rules define separately, and it does not stand in for one.
        </Rule>
      </ul>
    </section>
  );
}

function Rule({ title, children }: { title: string; children: ReactNode }) {
  return (
    <li>
      <span className="font-medium text-ink">{title}</span> {children}
    </li>
  );
}
