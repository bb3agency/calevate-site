"use client";

import Link from "next/link";
import { use, type ReactNode } from "react";
import {
  Bot,
  CircleAlert,
  Hourglass,
  PhoneCall,
  PhoneIncoming,
  PhoneOutgoing,
  Plus,
  Zap,
} from "lucide-react";

import {
  Card,
  EmptyState,
  PRIMARY_BUTTON,
  ProblemNotice,
  Skeleton,
  formatCallCap,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  useAgentStats,
  useAgents,
  useArchivedAgents,
  type Agent,
  type AgentStats,
} from "@/lib/api/agents";
import { useLanes, type Lane } from "@/lib/api/publishing";
import type { Session } from "@/lib/api/client";
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
 * Your agents (SURFACES §2) — the roster, grouped by whether they are working.
 *
 * ## What this screen is for, and what moved off it
 *
 * It answers ONE question at a glance — which agents are answering calls right now — and
 * hands off everything else to `/c/<slug>/agents/<id>`. It used to be the whole section:
 * a single scrolling page rendering every agent's opening notices, staged changes, voice,
 * call cap and capture fields at full size. Three things were wrong with that and all
 * three get worse as a client grows past one agent:
 *
 * - **It could not answer its own question.** Six full-height cards is a document, not a
 *   status board, and "is my receptionist live?" was four scrolls down someone else's
 *   card.
 * - **It issued one `GET /v1/agents/{id}/pending` PER AGENT on first paint.** The
 *   publishing state is a property of one agent being looked at, and reading it for all
 *   of them to render a marker nobody asked for is N round trips for one sentence. The
 *   roster now renders from `GET /v1/agents` alone; the pending read moved to the detail
 *   screen, where exactly one of them happens.
 * - **There was nowhere to put anything.** Creating an agent, training it and retiring it
 *   have no home on a page that is one long card per agent.
 *
 * ## Grouping
 *
 * Three sections, from `@/lib/agentState.ts`, which is also what the campaign picker and
 * the detail screen read — the "is it live" test exists ONCE (see that file for why
 * `published` is checked before `status`). The archive section renders only when the
 * server actually sends an archived agent, rather than as a permanently empty heading on
 * every account that has never retired one.
 *
 * ## §52
 *
 * Loading is a `Skeleton`, failure is a `ProblemNotice` with a retry, and "you have no
 * agents" is stated only where the server SAID so — a failed read is not evidence about
 * a client's account. The three are mutually exclusive branches, not a ladder that falls
 * through.
 */
export default function AgentsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = useClientSession();
  const { href } = useClientRealm();
  const agents = useAgents(session);

  return (
    <div className="space-y-5 pb-12">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-2xl text-sm text-ink-muted">
          The phone agents working for your business: what each one does, what it says
          about itself, and what it writes down. Open one to train it, change its voice or
          switch what it announces at the start of a call.
        </p>
        {/* The section's one creating control, at the top where a person looks for it —
            and repeated inside the first-run empty state below, which is the other place
            somebody arrives wanting it. A `Link` rather than a button: creating is a
            screen, not a dialog, because it asks enough questions to deserve one. */}
        <Link href={href(`/c/${slug}/agents/new`)} className={PRIMARY_BUTTON}>
          <Plus aria-hidden className="h-4 w-4" />
          New agent
        </Link>
      </div>

      {agents.error && <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />}

      {agents.isLoading ? (
        <Card bodyClassName="p-4">
          <Skeleton rows={6} />
        </Card>
      ) : agents.data ? (
        <Roster agents={agents.data} slug={slug} />
      ) : null}

      {/* The archive is a SECOND request, because `GET /v1/agents` deliberately excludes
          it: history grows without limit while the working roster does not, so a default
          of "everything" would let retired agents push live ones past the page bound. */}
      <Archive slug={slug} />

      {/* The precedence rule §2b asks to be STATED in the UI, and the lane table it
          summarises. Shown once for the whole section rather than per agent: it is a
          property of the platform, not of an agent. Only worth showing next to agents, so
          it renders under an empty list not at all. */}
      {agents.data?.length ? <HowChangesTakeEffect session={session} /> : null}
    </div>
  );
}

/**
 * The roster itself, given an answer that ARRIVED.
 *
 * Takes `Agent[]` rather than the query envelope on purpose: everything below is a claim
 * about the client's account, and a component that cannot see `undefined` cannot make one
 * out of it. The §52 branch is its caller's, once, above.
 *
 * It never receives an archived agent — the endpoint it is fed from excludes them — so the
 * two buckets here are the whole of the working roster. `agentGroup` is still what decides
 * which, because that function is also what the campaign picker and the detail screen read
 * and there must be one answer to "is this working".
 */
function Roster({ agents, slug }: { agents: Agent[]; slug: string }) {
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
function Archive({ slug }: { slug: string }) {
  const session = useClientSession();
  const archived = useArchivedAgents(session);
  const stats = useAgentStats(session);

  if (archived.error) {
    return (
      <ProblemNotice error={archived.error} onRetry={() => void archived.refetch()} />
    );
  }
  // Nothing while it is in flight, and nothing when the server said there is none: an
  // empty archive is not news, and a heading that appears and then vanishes is worse than
  // one that never appeared.
  if (!archived.data?.length) return null;
  return (
    <AgentGroup groupKey="archived" rows={archived.data} slug={slug} stats={stats.data} />
  );
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
 * the whole strip and gives a screen reader one link whose name is the agent's name.
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

/**
 * "Script decides content, rules decide conduct, voice only changes delivery" — and which
 * settings sit on which side of the Apply step.
 *
 * Every word of it comes from `GET /v1/agents/lanes`: the sentence, the reason under each
 * row, and which lane a field is on. The server owns that wording because the server
 * enforces the split, and a screen that paraphrased it is precisely how "voice applies
 * immediately" turns into a support ticket (the API module says so in those words). The
 * only thing decided here is the LABEL — `max_call_duration_s` is our column name, not a
 * sentence to show a clinic owner.
 */
function HowChangesTakeEffect({ session }: { session: Session }) {
  const lanes = useLanes(session);

  if (lanes.error) {
    return <ProblemNotice error={lanes.error} onRetry={() => void lanes.refetch()} />;
  }
  if (!lanes.data) return <Skeleton rows={4} />;

  /**
   * Three buckets, not two. `lane` is a bare `string` on the wire and the server's `Lane`
   * literal has two members TODAY; a split of `staged` versus everything-else would
   * announce a third lane shipped by the API as "applies straight away, nothing to
   * approve" — a promise about a live phone line, made about a value this build has never
   * seen. Unknown fails VISIBLE and claims nothing.
   */
  const waits = lanes.data.lanes.filter((lane) => lane.lane === "staged");
  const immediate = lanes.data.lanes.filter((lane) => lane.lane === "live");
  const unclassified = lanes.data.lanes.filter(
    (lane) => lane.lane !== "staged" && lane.lane !== "live",
  );

  return (
    <Card title="How changes take effect">
      <p className="text-sm font-medium text-ink">{lanes.data.precedence_rule}</p>
      <p className="mt-1 text-sm text-ink-muted">
        Some changes reach live calls the moment they are made; a change to what the agent
        SAYS waits until it is deliberately applied, so nothing a caller hears changes by
        accident.
      </p>

      <div className="mt-5 grid gap-6 sm:grid-cols-2">
        <LaneList
          icon={<Hourglass className="h-3.5 w-3.5" />}
          title="Waits to be applied"
          hint="Made now, live only after your account manager applies it."
          lanes={waits}
        />
        <LaneList
          icon={<Zap className="h-3.5 w-3.5" />}
          title="Applies straight away"
          hint="In force on the next call, with nothing to approve."
          lanes={immediate}
        />
        <LaneList
          icon={<CircleAlert className="h-3.5 w-3.5" />}
          title="Ask your account manager"
          hint="We cannot tell you when these take effect from here."
          lanes={unclassified}
        />
      </div>

      <p className="mt-5 text-xs text-ink-muted">
        Every agent is capped at {formatCallCap(lanes.data.call_cap_default_s)} per call by
        default, and that cap can be set anywhere between{" "}
        {formatCallCap(lanes.data.call_cap_min_s)} and{" "}
        {formatCallCap(lanes.data.call_cap_max_s)}. There is no way to remove it.
      </p>
    </Card>
  );
}

/** Our word for one of the server's field names. Unknown fields degrade to the name
 *  itself rather than disappearing — a lane the client cannot see is worse than an ugly
 *  label, and a new lane ships from the API without a frontend release. */
const FIELD_LABELS: Record<string, string> = {
  script: "What the agent says",
  max_call_duration_s: "Longest a call may run",
  extraction_fields: "What it writes down",
  training: "Knowledge and training",
  voice: "Its voice",
};

function LaneList({
  icon,
  title,
  hint,
  lanes,
}: {
  icon: ReactNode;
  title: string;
  hint: string;
  lanes: Lane[];
}) {
  if (lanes.length === 0) return null;
  return (
    <div>
      <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
          {icon}
        </span>
        {title}
      </h3>
      <p className="mt-1 text-xs text-ink-muted">{hint}</p>
      <ul className="mt-3 space-y-3">
        {lanes.map((lane) => (
          <li key={lane.field}>
            <p className="text-sm font-medium text-ink">
              {/* Fails VISIBLE: an unnamed lane degrades to its own field name rather than
                  vanishing. `lookup` is what makes the `??` reachable — a bare index on a
                  prototype key returns a function, which is not nullish (lib/lookup.ts). */}
              {lookup(FIELD_LABELS, lane.field) ?? humanise(lane.field)}
            </p>
            <p className="text-xs text-ink-muted">{lane.why}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
