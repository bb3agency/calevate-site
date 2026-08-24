"use client";

import Link from "next/link";
import { use } from "react";
import { ArrowLeft, MessageSquareQuote, PlugZap, ToggleLeft } from "lucide-react";

import { Card, ProblemNotice, Skeleton } from "@/components/ui";
import { STATUS_COPY, humanise } from "@/lib/agentState";
import { useAgent, type Agent } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { KnowledgeGaps } from "../../KnowledgeGaps";
import { liveState } from "../AgentBadge";
import { AgentIdentity } from "../AgentIdentity";
import { AgentLifecycle } from "../AgentLifecycle";
import { AgentModel } from "../AgentModel";
import {
  ExtractionList,
  Fact,
  OpeningNotices,
  PublishingPanel,
  SectionHeading,
  TrainingPanel,
} from "../panels";

/**
 * ONE agent — what it does, what it says, what it captures, and what it knows.
 *
 * The roster answers "which of my agents is working"; this screen answers everything
 * else, for one of them. It is where an owner comes after being told an edit was made, and
 * where they teach the agent something new.
 *
 * ## Which controls exist here, and why the rest are facts instead
 *
 * D-21 draws the control boundary and this screen is built on it rather than around it.
 * What a client may genuinely change, each a real write to a real client-realm endpoint:
 *
 * - **Whether it is working at all** (D-440) — switch on, switch off, archive, restore.
 * - **What it is** — its name, which way its calls go, the language it speaks.
 * - **The two opening notices** (`PATCH /v1/agents/{id}/disclosure`, `org:manage`) — D-163.
 *   The client is the Principal Entity, so which notices their agent VOLUNTEERS is theirs.
 * - **Which AI model it thinks with** (`llm_model` on the same PATCH, `org:manage`) —
 *   inherited from the organisation default or overridden for this one agent. It is on
 *   this side of D-21's line because it is a PRICE: every option carries what a minute of
 *   a five-minute call costs on it, and the client pays that.
 * - **What the agent knows** (`POST /v1/kb/sources`, `kb:write`) — a reviewed fact, which
 *   cannot change what the agent is instructed to do.
 *
 * What is NOT here is what D-21 actually reserves: the SCRIPT and the CAPTURE COLUMNS,
 * because changing either regenerates prompt hints and needs a regression run against real
 * calls — plus the voice, which is an ear test. Those are shown as FACTS with the reason
 * and who moves them, never as a disabled input with no explanation: "a button that would
 * 403 is worse than no button at all" is this repo's rule, and a control that silently
 * vanishes leaves a client unable to act and unable to ask why.
 *
 * ## The one guarantee that is not a setting at all
 *
 * A caller who asks "am I talking to a person?" or "is this recorded?" is always answered
 * truthfully. That is appended server-side to every prompt by `compose_engine_prompt` and
 * re-verified against the engine on every publish and every drift sweep — no column,
 * config row or client-authored script can withdraw it. It is stated on this screen as a
 * fact, in the SERVER's own words (`truthful_answer_rule`), above the two switches rather
 * than under them — see `panels.tsx::OpeningNotices` for why the order matters.
 */
export default function AgentDetailPage({
  params,
}: {
  params: Promise<{ slug: string; agentId: string }>;
}) {
  const { slug, agentId } = use(params);
  const session = useClientSession();
  const { href } = useClientRealm();
  const agent = useAgent(session, agentId);

  return (
    <div className="space-y-5 pb-12">
      <Link
        href={href(`/c/${slug}/agents`)}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        All agents
      </Link>

      {agent.error && <ProblemNotice error={agent.error} onRetry={() => void agent.refetch()} />}

      {agent.isLoading ? (
        <Card bodyClassName="p-4">
          <Skeleton rows={8} />
        </Card>
      ) : agent.data ? (
        <AgentDetail agent={agent.data} slug={slug} />
      ) : null}
    </div>
  );
}

/**
 * The screen, given an agent that ARRIVED.
 *
 * Takes `Agent` rather than the query envelope: every sentence below is a claim about this
 * client's agent, and a component that cannot see `undefined` cannot make one out of it.
 */
function AgentDetail({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const live = liveState(agent);
  // Read through `lookup` (src/lib/lookup.ts) rather than indexed directly. This used to
  // say the API had narrowed `AgentOut.status` nowhere; it does now (a four-member union
  // since D-440), and the indirection is kept for the reason it survives the narrowing:
  // `status` arrives from the wire, so a fifth state the server adds before this table
  // learns it must render as itself rather than crash the screen.
  const status = lookup(STATUS_COPY, agent.status) ?? {
    label: humanise(agent.status),
    hint: "",
  };

  return (
    <div className="space-y-5">
      <Card
        title={agent.name}
        action={
          <span
            className={`inline-flex shrink-0 items-center rounded-full border px-3 py-1 text-xs font-semibold ${live.tone}`}
          >
            {live.label}
          </span>
        }
      >
        <div className="space-y-6">
          <p className="text-sm text-ink-muted">{live.detail}</p>

          {/* `status` and "on the calling system" are shown SEPARATELY rather than
              collapsed into the badge: an agent switched on but not yet built is a
              different wait from one built but not switched on, and only we can tell them
              apart. What it does and what it speaks are not repeated here — they are the
              inputs of "What it is" below, where their current values are already on
              screen, and two spellings of one fact is where the drift starts. */}
          <dl className="grid gap-5 sm:grid-cols-2">
            <Fact label="Status" icon={<ToggleLeft className="h-3.5 w-3.5" />} hint={status.hint}>
              {status.label}
            </Fact>
            <Fact
              label="On the calling system"
              icon={<PlugZap className="h-3.5 w-3.5" />}
              hint={
                agent.published
                  ? "Built and connected, so it can be switched on."
                  : "Until this is done, the agent cannot ring anyone."
              }
            >
              {agent.published ? "Connected" : "Not yet"}
            </Fact>
          </dl>

          <PublishingPanel agent={agent} />
        </div>
      </Card>

      <Card title="Switching it on and off">
        <AgentLifecycle agent={agent} />
      </Card>

      <Card title="What it is">
        <AgentIdentity agent={agent} />
      </Card>

      {/* Renders nothing at all on an API build that does not report a model — see
          `AgentModel`. A card headed "The model it thinks with" containing a shrug is
          worse than no card. */}
      <AgentModel agent={agent} slug={slug} />

      <Card title="What it says">
        <div className="space-y-6">
          <ScriptNote slug={slug} agentId={agent.id} />
          <OpeningNotices agent={agent} />
        </div>
      </Card>

      <Card title="What it captures">
        <ExtractionList
          agent={agent}
          leadsHref={
            <Link
              href={href(`/c/${slug}/leads`)}
              className="font-medium underline underline-offset-2 hover:text-ink"
            >
              Leads
            </Link>
          }
        />
      </Card>

      {/* The same urgent surface as the dashboard home, scoped to THIS agent — the
          questions it could not answer on real calls, teachable in place. */}
      <KnowledgeGaps agentId={agent.id} />

      <TrainingPanel agent={agent} />
    </div>
  );
}

/**
 * The script: now client-authored in the structured builder, still applied deliberately.
 *
 * ⚠ THIS SUPERSEDES THE OLD "authored with your account manager" COPY on the founder's
 * approved decision that the structured builder is the primary authoring model. The panel
 * links into `/c/{slug}/agents/{agentId}/script` (the builder), which STAGES every edit —
 * a change still never reaches a live call until it is deliberately applied, which is the
 * §2b two-speed guarantee D-21's regression concern is really about. `PublishingPanel`
 * above is where a WAITING version shows, with both version pointers as data.
 */
function ScriptNote({ slug, agentId }: { slug: string; agentId: string }) {
  const { href } = useClientRealm();
  return (
    <section>
      <SectionHeading icon={<MessageSquareQuote className="h-3.5 w-3.5" />}>
        Its script
      </SectionHeading>
      <p className="mt-2 text-sm text-ink-muted">
        The script decides what the agent says and how it handles a call — your prices, your
        staff, what to do when someone asks for something you do not offer. Build it as an
        opening line, steps and questions, or let AI draft it from a description. A change
        never reaches a live call until you apply it, so nothing a caller hears moves by
        accident.
      </p>
      <Link
        href={href(`/c/${slug}/agents/${agentId}/script`)}
        className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-brand hover:text-brand-deep"
      >
        <MessageSquareQuote aria-hidden className="h-4 w-4" />
        Open the script builder
      </Link>
    </section>
  );
}
