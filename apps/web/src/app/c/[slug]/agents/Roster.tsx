"use client";

/**
 * THE ROSTER — every agent, grouped by whether it is working, one row you can open.
 *
 * Split out of the route module (UX-DOCTRINE §6: the roster page was 503 lines carrying
 * the screen, the three groups, the row and a platform explainer). This file is the list
 * itself; the explainer is `./LaneGuide.tsx`.
 *
 * ## Grouping
 *
 * Three sections, from `@/lib/agentState.ts`, which is also what the campaign picker and
 * the detail screen read — the "is it live" test exists ONCE (see that file for why
 * `published` is checked before `status`). The archive section renders only when the
 * server actually sends an archived agent, rather than as a permanently empty heading on
 * every account that has never retired one.
 */

import Link from "next/link";
import { Bot, PhoneCall, PhoneIncoming, PhoneOutgoing, Plus } from "lucide-react";

import {
  Card,
  EmptyState,
  MonoValue,
  PRIMARY_BUTTON,
  ProblemNotice,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  useAgentStats,
  useArchivedAgents,
  type Agent,
  type AgentStats,
} from "@/lib/api/agents";
import { agentOwnModel } from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { LiveBadge } from "./AgentBadge";
import {
  DIRECTION_COPY,
  LANGUAGE_NAMES,
  agentGroup,
  humanise,
  type AgentGroupKey,
} from "@/lib/agentState";

/**
 * The roster itself, given an answer that ARRIVED.
 *
 * Takes `Agent[]` rather than the query envelope on purpose: everything below is a claim
 * about the client's account, and a component that cannot see `undefined` cannot make one
 * out of it. The §52 branch is its caller's, once, on the route.
 *
 * It never receives an archived agent — the endpoint it is fed from excludes them — so the
 * two buckets here are the whole of the working roster. `agentGroup` is still what decides
 * which, because that function is also what the campaign picker and the detail screen read
 * and there must be one answer to "is this working".
 */
export function Roster({ agents, slug }: { agents: Agent[]; slug: string }) {
  const { href } = useClientRealm();
  const session = useClientSession();
  /* A THIRD request, and deliberately not awaited alongside the roster: it aggregates
     `calls`, the biggest table a tenant owns, while the roster reads a handful of small
     rows. The list paints as soon as it can and the activity numbers fill in when they
     arrive — a row simply carries no activity line until its figures exist, which is why
     nothing here coalesces a missing stat to zero. */
  const stats = useAgentStats(session);

  if (agents.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No agents yet"
          hint="An agent is a phone line that answers for you — it picks up, has the conversation, and writes down what was said. Build your first one and it will show up here before it takes a single call."
        />
        <div className="mt-4 flex justify-center">
          <Link href={href(`/c/${slug}/agents/new`)} className={PRIMARY_BUTTON}>
            <Plus aria-hidden className="h-4 w-4" />
            Build your first agent
          </Link>
        </div>
      </Card>
    );
  }

  const active = agents.filter((agent) => agentGroup(agent) === "active");
  const inactive = agents.filter((agent) => agentGroup(agent) !== "active");

  return (
    <div className="space-y-5">
      {/* Both sections always render, because "nothing is answering your calls" is the
          most important thing this screen can say and an absent heading says it to
          nobody. */}
      <AgentGroup groupKey="active" rows={active} slug={slug} stats={stats.data} />
      <AgentGroup groupKey="inactive" rows={inactive} slug={slug} stats={stats.data} />
    </div>
  );
}

/**
 * The archive — its own query, its own states, and NO heading until there is one to head.
 *
 * A section titled "Archived" that renders empty on every account that has never retired
 * an agent is a heading people learn to skip, so it appears only once the server has SENT
 * a retired agent. The failure is the case that needs care: rendering nothing on a failed
 * read would make "you have no archive" and "we could not read your archive" the same
 * screen, so the refusal is rendered on its own.
 */
export function Archive({ slug }: { slug: string }) {
  const session = useClientSession();
  const archived = useArchivedAgents(session);
  const stats = useAgentStats(session);

  if (archived.error) {
    return <ProblemNotice error={archived.error} onRetry={() => void archived.refetch()} />;
  }
  // Nothing while it is in flight, and nothing when the server said there is none: an
  // empty archive is not news, and a heading that appears and then vanishes is worse than
  // one that never appeared.
  if (!archived.data?.length) return null;
  return <AgentGroup groupKey="archived" rows={archived.data} slug={slug} stats={stats.data} />;
}

/** What each section is, in the owner's words rather than in our status column's. */
const GROUP_COPY: Record<AgentGroupKey, { title: string; hint: string; empty: string }> = {
  active: {
    title: "Working right now",
    hint: "On the calling system and switched on. Several can run at once — each answers its own numbers, so an after-hours line and a sales line pick up in parallel.",
    empty:
      "Nothing is answering your calls at the moment. An agent has to be built on the calling system and switched on before it can pick up.",
  },
  inactive: {
    title: "Not working",
    hint: "Built, being built, or deliberately switched off. None of these takes a call.",
    empty: "Every agent you have is working.",
  },
  archived: {
    title: "Archived",
    hint: "Retired agents. They take no calls and cannot be put on a campaign; the calls they already handled stay in your call log.",
    empty: "",
  },
};

function AgentGroup({
  groupKey,
  rows,
  slug,
  stats,
}: {
  groupKey: AgentGroupKey;
  rows: Agent[];
  slug: string;
  stats: AgentStats[] | undefined;
}) {
  const copy = GROUP_COPY[groupKey];
  return (
    <Card
      title={copy.title}
      action={
        <span className="rounded-full border border-line bg-app px-2.5 py-1 text-xs font-semibold tabular-nums text-ink-muted">
          {rows.length}
        </span>
      }
      bodyClassName="p-0"
    >
      <p className="border-b border-line px-4 py-3 text-xs text-ink-muted sm:px-6">
        {copy.hint}
      </p>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-ink-muted sm:px-6">{copy.empty}</p>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((agent) => (
            <AgentRow
              key={agent.id}
              agent={agent}
              slug={slug}
              /* `find`, not an index built from ids: the key would be a server string and
                 a keyed object inherits `Object.prototype` (src/lib/lookup.ts). A roster is
                 bounded at 200 rows, so the scan is not a cost worth a hazard. */
              stats={stats?.find((row) => row.agent_id === agent.id)}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

/** The direction icon, which is the one place a picture says the fact faster than words. */
const DIRECTION_ICONS: Record<string, typeof PhoneCall> = {
  inbound: PhoneIncoming,
  outbound: PhoneOutgoing,
  both: PhoneCall,
};

/**
 * One agent, as a row you can open.
 *
 * The whole row is the link. An "Open" affordance in the corner is a 20px target on a
 * phone and reads as the only clickable thing; making the row the anchor gives the finger
 * the whole strip and gives a screen reader one link whose name is the agent's name. It is
 * also why there is no second link to the script builder here: a nested anchor is invalid
 * HTML, and the row's destination is the workspace where the script is the first thing on
 * the page (UX-DOCTRINE §4 — one target per row).
 *
 * THE SECOND LINE IS ONLY WHAT WE KNOW. `inbound_number_count` is on the roster row and is
 * always shown for an agent that answers; the call figures come from a different request
 * and are simply absent until it lands. Nothing here coalesces a missing figure to zero —
 * "this agent has taken 0 calls" is a claim about a client's business, and a request still
 * in flight is not evidence for it.
 */
function AgentRow({
  agent,
  slug,
  stats,
}: {
  agent: Agent;
  slug: string;
  stats: AgentStats | undefined;
}) {
  const { href } = useClientRealm();
  const direction = lookup(DIRECTION_COPY, agent.direction);
  const DirectionIcon = lookup(DIRECTION_ICONS, agent.direction) ?? Bot;
  const language = lookup(LANGUAGE_NAMES, agent.language_primary) ?? agent.language_primary;
  /**
   * WHICH AGENTS HAVE BEEN TAKEN OFF THE ACCOUNT DEFAULT — the one model fact a roster
   * can answer that a detail screen cannot.
   *
   * `/c/[slug]/settings/models` tells an owner that "one agent can be put on a different
   * model from the rest", and until this line nothing said WHICH. That is a money
   * question: a per-agent override is a per-agent price (`plans.llm_model_surcharge`,
   * D-455 — the surcharge applies to the minutes the client's own choice upgraded), and
   * the busiest agent on the dearest model is the combination nobody sets deliberately.
   *
   * Only the OVERRIDE is shown. Printing the effective model on every row would put the
   * same identifier on all of them, which is a column of noise that hides the one row that
   * differs — the opposite of what a scan is for.
   */
  const ownModel = agentOwnModel(agent);

  return (
    <li>
      <Link
        href={href(`/c/${slug}/agents/${agent.id}`)}
        className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-4 hover:bg-black/5 sm:px-6 dark:hover:bg-white/5"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
          <DirectionIcon aria-hidden className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-ink">{agent.name}</span>
          <span className="block text-xs text-ink-muted">
            {direction?.label ?? humanise(agent.direction)} · Speaks {language}
            {/* HOW MANY LINES IT ANSWERS IN PARALLEL — the honest per-agent deployment
                fact, and the only one: inbound is a per-number binding at the engine, so
                an agent bound to three numbers picks up three calls at once. Outbound
                concurrency is an account-level pool shared by every campaign, so there is
                no per-agent number that could be true and this row invents none. */}
            {agent.direction !== "outbound" && (
              <>
                {" · "}
                {agent.inbound_number_count === 1
                  ? "Answers 1 number"
                  : `Answers ${formatCount(agent.inbound_number_count)} numbers`}
              </>
            )}
            {/* The server's own identifier, not a friendly name: it is what the settings
                screen and the invoice line both print, and a roster that renamed it would
                leave an owner unable to match this row to the charge. */}
            {ownModel !== null && (
              <>
                {" · "}Its own AI model: <MonoValue>{ownModel}</MonoValue>
              </>
            )}
          </span>
          {stats && (
            <span className="block text-xs text-ink-faint">
              {formatCount(stats.calls_total)}{" "}
              {stats.calls_total === 1 ? "call" : "calls"} handled
              {stats.last_call_at !== null && <> · last used {formatIST(stats.last_call_at)}</>}
            </span>
          )}
          {agent.archived_at !== null && (
            <span className="block text-xs text-ink-faint">
              Retired {formatIST(agent.archived_at)}
            </span>
          )}
        </span>
        <LiveBadge agent={agent} />
      </Link>
    </li>
  );
}
