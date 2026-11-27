"use client";

/**
 * THE OPENING NOTICES, AS THIS AGENT FOLLOWS THEM (D-1021).
 *
 * The AI notice and the recording notice are one switch each for the whole account, set on
 * Settings, Call notices: every agent, line and campaign of the client follows them. So this
 * agent's page shows where they stand and gives one button to change them, rather than a
 * switch of its own that would only look like it governed this agent.
 *
 * The truthful-answer guarantee (the server's first sentence of it) sits above the two
 * states, as it does above the switches on Call notices: two "off" positions must never read
 * as "it may pass for a person".
 */

import Link from "next/link";

import { SECONDARY_BUTTON_SM } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";
import { splitPromise } from "@/lib/truthfulAnswer";

export function OpeningNotices({ agent }: { agent: Agent }) {
  const { session, href } = useClientRealm();
  const onOff = (on: boolean) => (on ? "on" : "off");
  const promise = splitPromise(agent.truthful_answer_rule).lead;
  return (
    <section aria-labelledby="opening-notices-heading" className="max-w-3xl">
      <h3 id="opening-notices-heading" className="text-heading text-ink">
        What it says at the start of every call
      </h3>
      {promise && <p className="mt-1 text-body text-ink">{promise}</p>}
      <p className="mt-1 text-meta text-ink-muted">
        Says it is an AI: {onOff(agent.ai_disclosure_enabled)}. Says the call is recorded:{" "}
        {onOff(agent.recording_notice_enabled)}. Set once for all your calls.
      </p>
      <Link
        href={href(`/c/${session.orgSlug}/settings/call-notices`)}
        className={`mt-2 inline-flex ${SECONDARY_BUTTON_SM}`}
      >
        Change for all calls
      </Link>
    </section>
  );
}
