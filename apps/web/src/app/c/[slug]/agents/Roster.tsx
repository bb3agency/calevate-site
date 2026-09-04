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
import { useState } from "react";
import {
  Bot,
  PhoneCall,
  PhoneIncoming,
  PhoneOutgoing,
  Plus,
  PowerOff,
  Trash2,
} from "lucide-react";

import {
  Card,
  DANGER_BUTTON,
  EmptyState,
  MonoValue,
  NOTICE_TONES,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  useAgentLifecycle,
  useAgentStats,
  useArchivedAgents,
  type Agent,
  type AgentStats,
} from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { agentOwnModel } from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { LiveBadge } from "./AgentBadge";
import { MOVE_COPY } from "./AgentLifecycle";
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
          action={
            <Link
              href={href(`/c/${slug}/agents/new`)}
              className={PRIMARY_BUTTON}
            >
              <Plus aria-hidden className="h-4 w-4" />
              Build your first agent
            </Link>
          }
        />
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
      <AgentGroup
        groupKey="active"
        rows={active}
        slug={slug}
        stats={stats.data}
      />
      <AgentGroup
        groupKey="inactive"
        rows={inactive}
        slug={slug}
        stats={stats.data}
      />
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
    return (
      <ProblemNotice
        error={archived.error}
        onRetry={() => void archived.refetch()}
      />
    );
  }
  // Nothing while it is in flight, and nothing when the server said there is none: an
  // empty archive is not news, and a heading that appears and then vanishes is worse than
  // one that never appeared.
  if (!archived.data?.length) return null;
  return (
    <AgentGroup
      groupKey="archived"
      rows={archived.data}
      slug={slug}
      stats={stats.data}
    />
  );
}

/**
 * What each section is, in the owner's words rather than in our status column's.
 *
 * ONE SHORT LINE, OR NONE (D-527). The founder's note on this screen was that there is too
 * much to read, and a heading that has already said the thing does not need a paragraph
 * repeating it: "Working right now" needs no gloss at all, and the three sentences that
 * used to sit under it (parallel answering, per-number bindings, after-hours lines) are
 * platform facts a person reads once, not status a person scans. The EMPTY strings are the
 * opposite case and stay whole — "nothing is answering your calls" is the most important
 * sentence this screen can say, and it is read exactly when it is true.
 */
const GROUP_COPY: Record<
  AgentGroupKey,
  { title: string; hint?: string; empty: string }
> = {
  active: {
    title: "Working right now",
    empty:
      "Nothing is answering your calls. An agent has to be built and switched on to pick up.",
  },
  inactive: {
    title: "Not working",
    hint: "Being built, or switched off. None of these takes a call.",
    empty: "Every agent you have is working.",
  },
  archived: {
    title: "Deleted",
    hint: "They take no calls. Their call history stays in your call log, and you can bring one back.",
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
      {copy.hint && (
        <p className="border-b border-line px-4 py-3 text-xs text-ink-muted sm:px-6">
          {copy.hint}
        </p>
      )}
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-ink-muted sm:px-6">{copy.empty}</p>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((agent) => (
            <AgentRow
              key={agent.id}
              agent={agent}
              slug={slug}
              groupKey={groupKey}
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
  groupKey,
  stats,
}: {
  agent: Agent;
  slug: string;
  groupKey: AgentGroupKey;
  stats: AgentStats | undefined;
}) {
  const { href } = useClientRealm();
  /* Whether this row's Delete is OPEN lives here rather than in `RowDelete`, so the panel
     can be a sibling of the row strip instead of a flex item inside it — and so the
     mutation and the permission read below it are mounted only for the row somebody is
     actually deleting, not once per agent on every paint. */
  const [deleting, setDeleting] = useState(false);
  const direction = lookup(DIRECTION_COPY, agent.direction);
  const DirectionIcon = lookup(DIRECTION_ICONS, agent.direction) ?? Bot;
  const language =
    lookup(LANGUAGE_NAMES, agent.language_primary) ?? agent.language_primary;
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
      {/* The link and the delete control are SIBLINGS, not nested: a `<button>` inside an
          `<a>` is invalid HTML and gives a screen reader one control that is two. The link
          still takes the whole strip a finger aims at (`flex-1`), so "one target per row"
          holds for the row's own purpose — opening it — and the destructive control is the
          deliberate second target, which is the one place UX-DOCTRINE §4 asks for one. */}
      <div className="flex items-center">
        <Link
          href={href(`/c/${slug}/agents/${agent.id}`)}
          className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-2 px-4 py-4 hover:bg-black/5 sm:px-6 dark:hover:bg-white/5"
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
            <DirectionIcon aria-hidden className="h-4 w-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-ink">
              {agent.name}
            </span>
            <span className="block text-xs text-ink-muted">
              {direction?.label ?? humanise(agent.direction)} · Speaks{" "}
              {language}
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
                {stats.last_call_at !== null && (
                  <> · last used {formatIST(stats.last_call_at)}</>
                )}
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
        {/* THE FOUNDER'S RULE IS THAT THIS IS ON EVERY AGENT (D-527), whether it is working
            or not — so it is not conditioned on the agent's state, only on the row being a
            live one. A deleted agent has no Delete because it is already deleted; bringing
            it back is on its own screen, where the rest of its life is. */}
        {groupKey !== "archived" && (
          <button
            type="button"
            onClick={() => setDeleting((open) => !open)}
            aria-expanded={deleting}
            /* The visible word is inside the accessible name (WCAG 2.5.3): six rows each
               offering a control called only "Delete" is a list a screen-reader user
               cannot navigate, and a name that dropped the visible word would break voice
               control. */
            aria-label={`Delete ${agent.name}`}
            className={`${SECONDARY_BUTTON_SM} mr-4 shrink-0 sm:mr-6`}
          >
            <Trash2 aria-hidden className="h-3.5 w-3.5" />
            Delete
          </button>
        )}
      </div>
      {deleting && (
        <RowDelete agent={agent} onClose={() => setDeleting(false)} />
      )}
    </li>
  );
}

/**
 * DELETING ONE AGENT FROM THE ROSTER — the confirm, or the one thing to do first.
 *
 * ## Why the control exists here at all
 *
 * The founder asked for it in these words: *"a delete option should be provided for every
 * agent regardless of it is working or not and if it is working it cannot be deleted
 * unless it is decommissioned (i mean deactivated as not working)"*. Both halves are the
 * design. The affordance is on every row, because an owner who is finished with an agent
 * should not have to open it to find that out; and a WORKING agent is refused, because a
 * delete beside every row is one click from ending a phone line a business is running on.
 *
 * ## The refusal is offered as a step, not as a wall
 *
 * `agentGroup` decides "is it working", which is the same predicate the groups above use
 * and the same one the copilot is told — a second test here is the drift this repo treats
 * as a defect even when both spellings agree. When it says yes, the panel does not just
 * say no: it offers Switch off, which is the move the server will accept, and the panel
 * then becomes the delete confirm on the next render because the agent has changed group.
 * That is the whole two-step, on one screen, without the person navigating anywhere.
 *
 * ## The words are the detail screen's words
 *
 * `MOVE_COPY.archive.confirm` — imported, not retyped. What deleting an agent does to a
 * client's account is one fact, and a roster that summarised it in its own words is how
 * one of the two copies quietly stops saying that the call history is kept.
 *
 * The server enforces all of this independently (`agents/lifecycle.archive_agent` refuses
 * a live agent with `agent_is_live`); this is the half that means a person never meets
 * that refusal by surprise.
 */
function RowDelete({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const session = useClientSession();
  const move = useAgentLifecycle(session, agent.id);
  /* `org:manage`, the owner's own permission — the same read the detail screen's lifecycle
     panel makes, and for the same reason: a viewer is shown why, not a button that 403s. */
  const write = useWriteAccess(session, "org:manage", "delete an agent");
  const working = agentGroup(agent) === "active";
  const copy = MOVE_COPY.archive.confirm;

  return (
    /* `role="status"`, polite: this panel appears because the person pressed Delete, so it
       does not need to interrupt — but a consequence that exists only as newly-painted
       pixels is one a screen-reader user is asked to confirm without having been told.
       Same call as the detail screen's confirm panel. */
    <div
      role="status"
      className={`border-t border-line px-4 py-3 text-xs sm:px-6 ${NOTICE_TONES.warn}`}
    >
      {move.error && <ProblemNotice error={move.error} />}
      <RestrictionNote reason={write.reason} />

      {working ? (
        <>
          <p className="font-semibold">{agent.name} is working right now</p>
          <p className="mt-1">
            It has to be switched off before it can be deleted. Switching it off
            stops it answering and dialling, and releases the numbers it picks
            up.
          </p>
        </>
      ) : (
        <>
          <p className="font-semibold">Delete {agent.name}?</p>
          <ul className="mt-2 list-inside list-disc space-y-1">
            {copy?.points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {working ? (
          <button
            type="button"
            onClick={() => move.mutate("deactivate")}
            disabled={!write.allowed || move.isPending}
            title={write.reason ?? undefined}
            className={SECONDARY_BUTTON}
          >
            <PowerOff aria-hidden className="h-4 w-4" />
            {move.isPending ? "Switching off…" : "Switch it off"}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => move.mutate("archive")}
            disabled={!write.allowed || move.isPending}
            title={write.reason ?? undefined}
            className={DANGER_BUTTON}
          >
            <Trash2 aria-hidden className="h-4 w-4" />
            {move.isPending ? "Deleting…" : `Delete ${agent.name}`}
          </button>
        )}
        <button type="button" onClick={onClose} className={SECONDARY_BUTTON}>
          Keep it
        </button>
      </div>
    </div>
  );
}
