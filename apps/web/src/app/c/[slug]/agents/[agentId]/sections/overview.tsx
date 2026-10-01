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

import { useSyncExternalStore } from "react";

import { ProblemNotice, Skeleton, formatINR } from "@/components/ui";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import type { Agent } from "@/lib/api/agents";
import { useAgreementsReadiness, type LegalReadiness } from "@/lib/api/agreements";
import { usePendingChanges, type PendingState } from "@/lib/api/publishing";
import { useScript, type ScriptOut } from "@/lib/api/script";
import { useWallet, walletState, type Wallet } from "@/lib/api/wallet";
import { useClientRealm, useClientSession } from "@/lib/api/session";

import { OpeningNotices } from "../../panels/openingNotices";
import { PendingBanner } from "../../panels/publishing";

const PHONE = "(max-width: 639px)";

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const query = window.matchMedia(PHONE);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** True on a phone-width viewport; false on the server and in a browser without matchMedia. */
function useIsPhone(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(PHONE).matches : false),
    () => false,
  );
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

  return (
    <div className="space-y-6">
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
    // The count is the agent row's own (`inbound_number_count`). A number is arranged by
    // the account manager — the client realm cannot buy one (`number_purchase_is_operator_led`)
    // — so the row says whose step it is rather than offering an Add that cannot add.
    const numbered = agent.inbound_number_count > 0;
    items.push({
      id: "number",
      label: "Give it a phone number to answer",
      state: numbered ? "done" : "waiting",
      ...(numbered
        ? {}
        : {
            detail: "Your account manager arranges the number.",
            link: { href: href(`/c/${slug}/phone-number`), label: "Details" },
          }),
    });
  }

  if (wallet.data) {
    const credit = walletState(wallet.data);
    // An account that is not prepaid is billed by invoice, so credit is not its step.
    if (credit !== "not-prepaid") {
      const stopped = credit === "stopped";
      items.push({
        id: "credit",
        label: "Add calling credit",
        state: stopped ? "todo" : "done",
        detail: stopped
          ? "Calls have stopped until credit is added."
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
    detail: working ? undefined : "Use Switch on at the top of this page.",
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
