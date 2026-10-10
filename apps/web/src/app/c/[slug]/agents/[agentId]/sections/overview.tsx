"use client";

/**
 * OVERVIEW — what is left before this agent's first call, anything waiting to go live, and
 * the opening notices.
 *
 * The notices are HERE and nowhere else: this is the section that opens first, so the
 * truthful-answer guarantee and the two switches under it are never behind a section switch
 * (doctrine §8 rule 7, D-657). On a phone the checklist folds to its "N of M done" summary
 * so they are on the first screen.
 */

import { useState } from "react";

import { ProblemNotice, Skeleton, formatINR } from "@/components/ui";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import type { Agent } from "@/lib/api/agents";
import { useAgreementsReadiness, type LegalReadiness } from "@/lib/api/agreements";
import { usePendingChanges, type PendingState } from "@/lib/api/publishing";
import { useScript, type ScriptOut } from "@/lib/api/script";
import { activeTrial, trialEndsAt, useWallet, walletState, type Wallet } from "@/lib/api/wallet";
import { useCalls } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { useMediaQuery } from "@/lib/useMediaQuery";

import { LatestCalls } from "../../../LatestCalls";
import { OpeningNotices } from "../../panels/openingNotices";
import { PendingBanner } from "../../panels/publishing";
import { TryIt } from "./tryIt";

const PHONE = "(max-width: 639px)";

/** True on a phone-width viewport; false on the server and in a browser without matchMedia. */
function useIsPhone(): boolean {
  return useMediaQuery(PHONE);
}

export function Overview({ agent, slug }: { agent: Agent; slug: string }) {
  const session = useClientSession();
  const pending = usePendingChanges(session, agent.id);
  const script = useScript(session, agent.id);
  // Switching on is a publish, and publish refuses an account with unaccepted agreements
  // (`legal/service.assert_agreements_accepted`), so it is on the list.
  const agreements = useAgreementsReadiness(session);
  // Credit is the wallet's own answer — the same read and the same `walletState` the
  // dashboard's credit tile uses — never inferred from the voice tier rates.
  const wallet = useWallet(session);
  const { href } = useClientRealm();
  // ITS LAST CALLS (founder, REDESIGN-2): what this agent has actually been doing, the
  // first thing an owner checks after "is it live".
  const recent = useCalls(session, { agent_id: agent.id, limit: 5 });
  // The test-call number lives here so the one declaration below can offer it as a field.
  const [testNumber, setTestNumber] = useState("");
  const trial = wallet.data ? activeTrial(wallet.data) : null;
  const onTrial = trial !== null && trial.test_calls_only === true;

  // OVERVIEW, DECLARED TO THE ASSISTANT. It is the section that opens first, so this is
  // what the assistant sees on an agent unless another section is open.
  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: `Agent: ${agent.name}`,
    realm: "client",
    fields: onTrial
      ? [
          {
            id: "agent-test-call-number",
            label: "Your phone number for a test call",
            type: "text",
            value: testNumber,
            personal: "phone",
          },
        ]
      : [],
    facts: [
      { key: "agent_id", label: "Agent id", value: agent.id },
      { key: "name", label: "Agent name", value: agent.name },
      { key: "status", label: "Status", value: agent.status },
      { key: "published", label: "Callers hear the latest version", value: agent.published ? "yes" : "no" },
      { key: "direction", label: "Calls it handles", value: agent.direction },
      { key: "ai_disclosure_enabled", label: "Says it is an AI at the start", value: agent.ai_disclosure_enabled ? "yes" : "no" },
      { key: "recording_notice_enabled", label: "Says the call is recorded at the start", value: agent.recording_notice_enabled ? "yes" : "no" },
      { key: "script_opening_line", label: "Opening line (its greeting, from the script)", value: agent.script_opening_line.trim() || "none written" },
      { key: "first_words", label: "What callers hear first", value: agent.first_words.trim() || "nothing yet" },
      {
        key: "pending",
        label: "Changes waiting to go live",
        value: pending.data ? (pending.data.has_pending ? "yes" : "none") : pending.error ? "could not be read" : "still loading",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id === "agent-test-call-number") setTestNumber(asText(item.value));
      }
    },
  });

  return (
    <div className="space-y-10">
      <SetupChecklist
        agent={agent}
        slug={slug}
        pending={pending}
        script={script}
        agreements={agreements}
        wallet={wallet}
      />
      {pending.error && (
        <ProblemNotice error={pending.error} onRetry={() => void pending.refetch()} />
      )}
      {pending.data && <PendingBanner state={pending.data} />}
      <OpeningNotices agent={agent} />
      <TryIt agent={agent} slug={slug} onTrial={onTrial} number={testNumber} onNumber={setTestNumber} />
      <LatestCalls
        recent={recent}
        allHref={href(`/c/${slug}/calls`)}
        callHref={(id) => href(`/c/${slug}/calls/${id}`)}
      />
    </div>
  );
}

/** One read's three answers, as the checklist needs them. */
type Read<T> = { data: T | undefined; isLoading: boolean; isError: boolean };

/** The row for a read that did not arrive: unknown, said as unknown, never "to do". */
function unknown(id: string, label: string): ChecklistItem {
  return {
    id,
    label,
    state: "waiting",
    detail: "We could not check this just now. Reload to try again.",
  };
}

/**
 * What is left before the first call. Each item is stated from a read that ARRIVED; a read
 * that failed makes its row say so, because a failed read is not evidence about the
 * account either way.
 */
function SetupChecklist({
  agent,
  slug,
  pending,
  script,
  agreements,
  wallet,
}: {
  agent: Agent;
  slug: string;
  pending: Read<PendingState>;
  script: Read<ScriptOut>;
  agreements: Read<LegalReadiness>;
  wallet: Read<Wallet>;
}) {
  const { href } = useClientRealm();
  const phone = useIsPhone();
  const base = `/c/${slug}/agents/${agent.id}`;
  const working = agent.published && agent.status === "live";

  if (pending.isLoading || script.isLoading || agreements.isLoading || wallet.isLoading) {
    return <Skeleton rows={4} label="Checking what is left to set up" />;
  }

  const items: ChecklistItem[] = [];

  const scriptDone = script.data ? script.data.version !== null : undefined;
  if (script.data) {
    items.push({
      id: "script",
      label: "Write its script",
      state: scriptDone ? "done" : "todo",
      link: scriptDone ? undefined : { href: href(`${base}/script`), label: "Write" },
    });
  } else {
    items.push(unknown("script", "Write its script"));
  }

  // The greeting is the script's own line, never a notice (D-708): an agent whose script has
  // none opens on nothing once its notices are off, and cannot make calls on some platforms.
  if (script.data && scriptDone && !script.data.is_freeform) {
    const greets = script.data.script.opening_line.trim() !== "";
    items.push({
      id: "opening",
      label: "Give it an opening line",
      state: greets ? "done" : "todo",
      ...(greets
        ? {}
        : {
            detail: "The greeting it opens every call with, after any notices you switched on.",
            link: { href: href(`${base}/script`), label: "Write" },
          }),
    });
  }

  if (pending.data?.voice) {
    const chosen = pending.data.voice.configured !== null;
    items.push({
      id: "voice",
      label: "Choose a voice",
      state: chosen ? "done" : "todo",
      link: chosen ? undefined : { href: href(`${base}?section=voice`), label: "Choose" },
    });
  } else if (pending.isError) {
    items.push(unknown("voice", "Choose a voice"));
  }

  if (agent.direction !== "outbound") {
    // The count is the agent row's own (`inbound_number_count`). One pricing model for
    // every client (D-707): the client buys its own number from Numbers once it has paid
    // and its business is verified, so a test-calls-only trial is pointed at Billing first.
    const numbered = agent.inbound_number_count > 0;
    const onTrial = wallet.data ? activeTrial(wallet.data)?.test_calls_only === true : false;
    items.push({
      id: "number",
      label: "Give it a phone number to answer",
      state: numbered ? "done" : onTrial ? "waiting" : "todo",
      ...(numbered
        ? {}
        : onTrial
          ? {
              detail: "Numbers open once you add calling credit and verify your business.",
              link: { href: href(`/c/${slug}/billing`), label: "Add credit" },
            }
          : {
              detail: "Buy a number on the Numbers page once your business is verified.",
              link: { href: href(`/c/${slug}/phone-number`), label: "Get a number" },
            }),
    });
  }

  if (wallet.data) {
    const credit = walletState(wallet.data);
    // An account that is not prepaid is billed by invoice, so credit is not its step.
    if (credit !== "not-prepaid") {
      const stopped = credit === "stopped";
      const trial = activeTrial(wallet.data);
      items.push({
        id: "credit",
        label: "Add calling credit",
        state: stopped ? "todo" : "done",
        detail: stopped
          ? "Calls have stopped until credit is added."
          : trial !== null
            ? `Free trial: calls are on us until ${trialEndsAt(trial)}.`
            : `${formatINR(wallet.data.balance_inr)} left`,
        link: stopped ? { href: href(`/c/${slug}/billing`), label: "Top up" } : undefined,
      });
    }
  } else {
    items.push(unknown("credit", "Add calling credit"));
  }

  if (agreements.data) {
    // `outstanding_documents` is counted by the same `outstanding_slugs` the publish
    // refusal reads, so this item and the refusal cannot disagree.
    const accepted = agreements.data.outstanding_documents === 0;
    items.push({
      id: "agreements",
      label: "Accept the agreements",
      state: accepted ? "done" : "todo",
      link: accepted ? undefined : { href: href(`/c/${slug}/agreements`), label: "Review" },
    });
  } else {
    items.push(unknown("agreements", "Accept the agreements"));
  }

  const agreementsOutstanding =
    agreements.data !== undefined && agreements.data.outstanding_documents > 0;
  items.push({
    id: "live",
    label: "Switch it on",
    state: working ? "done" : "todo",
    detail: working ? undefined : "Use the Taking calls switch at the top of this page.",
    ...(scriptDone === false && !working
      ? { disabledReason: "An agent with no script cannot be switched on." }
      : agreementsOutstanding && !working
        ? { disabledReason: "It cannot be switched on until the agreements are accepted." }
        : {}),
  });

  const allDone = items.every((item) => item.state === "done");
  return (
    <Checklist
      label={allDone ? "Ready for calls" : working ? "Still to set up" : "Before its first call"}
      items={items}
      collapsible={phone || allDone}
      defaultOpen={!phone && !allDone}
    />
  );
}
