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

import { ProblemNotice, Skeleton } from "@/components/ui";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import type { Agent } from "@/lib/api/agents";
import { usePendingChanges, type PendingState } from "@/lib/api/publishing";
import { useScript, type ScriptOut } from "@/lib/api/script";
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

  return (
    <div className="space-y-6">
      <SetupChecklist agent={agent} slug={slug} pending={pending.data} script={script.data} loading={pending.isLoading || script.isLoading} />
      {pending.error && (
        <ProblemNotice error={pending.error} onRetry={() => void pending.refetch()} />
      )}
      {pending.data && <PendingBanner state={pending.data} />}
      <OpeningNotices agent={agent} />
    </div>
  );
}

/**
 * What is left before the first call. Each item is stated only from a read that ARRIVED:
 * a failed read leaves its item out rather than calling it "to do", because a failed read
 * is not evidence about the account.
 */
function SetupChecklist({
  agent,
  slug,
  pending,
  script,
  loading,
}: {
  agent: Agent;
  slug: string;
  pending: PendingState | undefined;
  script: ScriptOut | undefined;
  loading: boolean;
}) {
  const { href } = useClientRealm();
  const phone = useIsPhone();
  const base = `/c/${slug}/agents/${agent.id}`;
  const working = agent.published && agent.status === "live";

  if (loading) return <Skeleton rows={4} label="Checking what is left to set up" />;

  const items: ChecklistItem[] = [];
  const scriptDone = script ? script.version !== null : undefined;
  if (script) {
    items.push({
      id: "script",
      label: "Write its script",
      state: scriptDone ? "done" : "todo",
      link: scriptDone ? undefined : { href: href(`${base}/script`), label: "Write" },
    });
  }
  if (pending?.voice) {
    const chosen = pending.voice.configured !== null;
    items.push({
      id: "voice",
      label: "Choose a voice",
      state: chosen ? "done" : "todo",
      link: chosen ? undefined : { href: href(`${base}?section=voice`), label: "Choose" },
    });
  }
  if (agent.direction !== "outbound") {
    const numbered = agent.inbound_number_count > 0;
    items.push({
      id: "number",
      label: "Give it a phone number to answer",
      state: numbered ? "done" : "todo",
      link: numbered ? undefined : { href: href(`/c/${slug}/phone-number`), label: "Add" },
    });
  }
  // Older API builds omit the field; with no rates there is nothing to say about credit.
  if (pending && Array.isArray(pending.voice_tier_rates) && pending.voice_tier_rates.length > 0) {
    // A tier with no rate means no open credit lot (`billing/lots.py::TierRate`).
    const credit = pending.voice_tier_rates.some((tier) => tier.inr_per_min !== null);
    items.push({
      id: "credit",
      label: "Add calling credit",
      state: credit ? "done" : "todo",
      link: credit ? undefined : { href: href(`/c/${slug}/billing`), label: "Top up" },
    });
  }
  items.push({
    id: "live",
    label: "Switch it on",
    state: working ? "done" : "todo",
    detail: working ? undefined : "Use Switch on at the top of this page.",
    ...(scriptDone === false && !working
      ? { disabledReason: "An agent with no script cannot be switched on." }
      : {}),
  });

  const allDone = items.every((item) => item.state === "done");
  return (
    <Checklist
      label={allDone ? "Ready for calls" : "Before its first call"}
      items={items}
      collapsible={phone || allDone}
      defaultOpen={!phone && !allDone}
    />
  );
}
