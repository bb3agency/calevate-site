"use client";

import { EmptyState } from "@/components/console/emptyState";
import { HAIRLINE_LIST } from "@/components/admin/kit";
import { Section } from "@/components/console/section";
import { MonoValue, ProblemNotice, Skeleton, formatIST, type NoticeTone } from "@/components/ui";
import { useTenantKbDelivery, type AgentDelivery } from "@/lib/api/admin";
import { lookup } from "@/lib/lookup";

import { StatusPill } from "@/components/admin/kit";

/**
 * WHAT THIS CLIENT'S PHONE IS ACTUALLY ANSWERING FROM — the other half of the queue above.
 *
 * ## Why an operator needs this and the queue is not enough
 *
 * `KnowledgeQueue` ends at Publish. Publishing does not guarantee the agent heard about
 * it: `kb/pack.refresh_published_pack` survives a storage failure ON PURPOSE — the
 * client's authored record is not allowed to be vetoed by a derived artefact — so it
 * keeps the old pointer, alerts, and returns. Every screen then shows the new words and
 * the phone goes on quoting the old ones. An operator who worked this client's queue to
 * empty had no way to see that, and the client's complaint ("I asked you to fix the
 * price, it is still saying the old one") reads as a publish that never happened.
 *
 * ## Why it is the CLIENT's read and not an operator view of its own
 *
 * `useTenantKbDelivery` fetches `/v1/kb/delivery` through the impersonated session — the
 * same bytes the client is looking at on their own Knowledge screen. A parallel
 * operator-realm query computing the same verdict is how the two come to disagree during
 * exactly the conversation where that matters most. The operator gets MORE of it than the
 * client does (the full pack id, the pending count on every row, not just the unhappy
 * ones) because they are diagnosing rather than being reassured, but it is one answer.
 *
 * ## No lever, and the reason
 *
 * There is deliberately no "rebuild" button. `not_delivered` self-heals the moment
 * anything on that agent is published again, and the existing Publish control in the
 * queue above IS that retry — a second button here would be a second way to do one thing,
 * on a screen whose whole job is telling the operator which one to press.
 */
export function KnowledgeDeliveryPanel({ slug }: { slug: string }) {
  const delivery = useTenantKbDelivery(slug);

  if (delivery.isLoading) {
    return (
      <Section title="Agents using this knowledge">
        <Skeleton rows={3} />
      </Section>
    );
  }

  if (delivery.error || !delivery.data) {
    return (
      <Section title="Agents using this knowledge">
        <ProblemNotice
          error={
            delivery.error ??
            new Error("We could not read what this client's agents are answering from.")
          }
          onRetry={() => void delivery.refetch()}
        />
      </Section>
    );
  }

  const { items, not_delivered_count } = delivery.data;

  return (
    <Section
      title="Agents using this knowledge"
      info="The client's knowledge is shared by all its agents. This is what each agent is answering callers out of, against what the client has published. Approving and publishing do not guarantee the frozen knowledge reached the agent — this is where that shows."
      action={
        not_delivered_count > 0 ? (
          <StatusPill tone="stop">{not_delivered_count} stale</StatusPill>
        ) : undefined
      }
    >
      {items.length === 0 ? (
        <EmptyState message="No live agents, so there is nothing for knowledge to reach." />
      ) : (
        <ul className={HAIRLINE_LIST}>
          {items.map((row) => (
            <Row key={row.agent_id} row={row} />
          ))}
        </ul>
      )}
    </Section>
  );
}

/**
 * The operator's wording, which is NOT the client's.
 *
 * The client's card says "Getting ready" and "Not live" — what to do. An operator is
 * diagnosing, so these name the MECHANISM: which sweep owes work, and whether anything is
 * coming. `apps/api/kb/delivery.py` is the single definition both render.
 */
const STATE: Record<AgentDelivery["state"], { label: string; note: string; tone: NoticeTone }> = {
  live: {
    label: "In sync",
    note: "the pack matches what is published",
    tone: "ok",
  },
  preparing: {
    label: "Gloss pending",
    note: "the gloss sweep still owes this agent work and will rebuild (:12 and :42)",
    tone: "neutral",
  },
  not_delivered: {
    label: "Stale",
    note: "nothing is queued, so no sweep is coming — the pack failed to build or store",
    tone: "stop",
  },
  no_knowledge: {
    label: "Nothing published",
    note: "no corpus and no pointer; the agent answers not_found, correctly",
    tone: "neutral",
  },
};

function Row({ row }: { row: AgentDelivery }) {
  // `lookup`, not `STATE[row.state]`: the union is the generated schema's, so a state the
  // API gains before this file is updated degrades rather than crashing the panel.
  const state = lookup(STATE, row.state) ?? STATE.no_knowledge;

  return (
    <li className="py-3 sm:px-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 truncate text-body font-medium text-ink">{row.agent_name}</span>
        <StatusPill tone={state.tone}>{state.label}</StatusPill>
      </div>
      <p className="mt-1 text-meta text-ink-muted">{state.note}</p>
      <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-meta text-ink-muted">
        <div className="flex gap-1.5">
          <dt>Live facts</dt>
          <dd className="tabular-nums text-ink">{row.live_chunks}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Awaiting gloss</dt>
          <dd className="tabular-nums text-ink">{row.awaiting_translation}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>Reached the agent</dt>
          {/* `formatIST` renders an em dash for null, which is the honest answer for a
              pack recorded before migration f4b18c7d2e59 — and for one never recorded. */}
          <dd className="text-ink">{formatIST(row.last_reached_at)}</dd>
        </div>
      </dl>
      {row.pack_id ? (
        <p className="mt-1.5 text-meta text-ink-muted">
          {/* The FULL id for an operator, unlike the client's card: this is the object key
              in the bucket (`pack_object_key`), so a truncated one cannot be looked up. */}
          Pack <MonoValue className="text-ink-muted">{row.pack_id}</MonoValue>
        </p>
      ) : null}
    </li>
  );
}
