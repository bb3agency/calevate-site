"use client";

/**
 * ONE AGENT'S WORKSPACE — the reference implementation of docs/UX-DOCTRINE.md.
 *
 * ## What was wrong, in one sentence
 *
 * This screen was a flat stack of nine equally-weighted `Card`s — status, lifecycle,
 * identity, model, "what it says", extraction, knowledge gaps, actions, training — in
 * which the SCRIPT, the thing an owner edits most and the thing the product actually is,
 * was a small text link inside the fifth of them. Everything had the same weight, so
 * nothing was primary, and the most important control was the hardest to find.
 *
 * ## The three bands, and why a thing is in the band it is in (doctrine §3)
 *
 * The test is FREQUENCY × CONSEQUENCE, applied out loud:
 *
 * 1. **PRIMARY — the script.** Highest frequency, highest consequence. Its own hero, its
 *    own route, the screen's only `PRIMARY_BUTTON_LG`. See `ScriptCallout`.
 * 2. **FOREGROUND — visible with no click.** What callers hear right now (the staged /
 *    live pointers, the voice, the cost ceiling); whether it is switched on; the two
 *    opening notices; what it writes down; what it does not know yet and what it knows.
 *    These are read on most visits, and the notices are read on none — they are here
 *    because §8 forbids putting a compliance obligation behind a disclosure at all.
 * 3. **DISCLOSED — one click, closed by default.** What it can do mid-call (integration
 *    plumbing, set up once), its name/direction/language, and which AI model it thinks
 *    with. Rare, and each is a self-contained job.
 *
 * NOTHING WAS DELETED AND NOTHING BECAME UNREACHABLE. Every control that existed before is
 * still here, still writes to the same endpoint, and is at most one click further away —
 * "maximum control, minimum complexity" is a statement about ARRANGEMENT, not about
 * feature count (doctrine §9).
 *
 * ## Which controls exist here, and why the rest are facts instead
 *
 * D-21 draws the control boundary and this screen is built on it rather than around it.
 * What a client may genuinely change, each a real write to a real client-realm endpoint:
 * whether it is working at all (D-440); what it is — name, direction, language; the two
 * opening notices (`PATCH /v1/agents/{id}/disclosure`, `org:manage` — D-163); which AI
 * model it thinks with; what it captures; what it knows (`POST /v1/kb/sources`,
 * `kb:write`); and — since the founder's approved decision — its SCRIPT, in the structured
 * builder, where every save stages and nothing reaches a live call until it is applied.
 * The voice remains ours (an ear test), and is shown as a fact with who moves it, never as
 * a disabled input with no explanation: "a button that would 403 is worse than no button
 * at all" is this repo's rule.
 *
 * ## The one guarantee that is not a setting at all
 *
 * A caller who asks "am I talking to a person?" or "is this recorded?" is always answered
 * truthfully. That is appended server-side to every prompt by `compose_engine_prompt` and
 * re-verified against the engine on every publish and every drift sweep — no column,
 * config row or client-authored script can withdraw it. It is stated in the SERVER's own
 * words (`truthful_answer_rule`), above the two switches rather than under them — see
 * `panels/openingNotices.tsx` for why the order matters.
 */

import Link from "next/link";
import { PlugZap, Settings2, ToggleLeft } from "lucide-react";

import { Card, Disclosure, Fact, ProblemNotice, Skeleton } from "@/components/ui";
import { STATUS_COPY, humanise } from "@/lib/agentState";
import { useAgent, type Agent } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { KnowledgeGaps } from "../../KnowledgeGaps";
import { Actions } from "../actions/Actions";
import { liveState } from "../AgentBadge";
import { AgentIdentity } from "../AgentIdentity";
import { AgentLifecycle } from "../AgentLifecycle";
import { AgentModel } from "../AgentModel";
import { ExtractionList } from "../panels/extraction";
import { OpeningNotices } from "../panels/openingNotices";
import { PublishingPanel } from "../panels/publishing";
import { TrainingPanel } from "../panels/training";
import { ScriptCallout } from "./ScriptCallout";

/** The screen, from the route's params. §52: the three states are branches, not a ladder. */
export function AgentWorkspace({ slug, agentId }: { slug: string; agentId: string }) {
  const session = useClientSession();
  const agent = useAgent(session, agentId);

  return (
    <>
      {agent.error && <ProblemNotice error={agent.error} onRetry={() => void agent.refetch()} />}
      {agent.isLoading ? (
        <Card bodyClassName="p-4">
          <Skeleton rows={8} />
        </Card>
      ) : agent.data ? (
        <AgentDetail agent={agent.data} slug={slug} />
      ) : null}
    </>
  );
}

/**
 * The workspace, given an agent that ARRIVED.
 *
 * Takes `Agent` rather than the query envelope: every sentence below is a claim about this
 * client's agent, and a component that cannot see `undefined` cannot make one out of it.
 */
function AgentDetail({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const session = useClientSession();

  return (
    <div className="space-y-5">
      <AgentHeader agent={agent} />

      {/* BAND 1 — the one thing this screen is for. */}
      <ScriptCallout slug={slug} agentId={agent.id} published={agent.published} />

      {/* BAND 2 — foreground. Read on most visits, or too important to hide. */}
      <Card title="What callers hear right now">
        <PublishingPanel agent={agent} />
      </Card>

      <Card title="Switching it on and off">
        <AgentLifecycle agent={agent} />
      </Card>

      {/* NOT a disclosure, and this is a rule rather than a preference: a client can switch
          either announcement off, so both switches and the guarantee they do NOT reach must
          be readable without a click (doctrine §8). */}
      <Card title="What it says about itself">
        <OpeningNotices agent={agent} />
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

      <Card title="What it knows">
        <TrainingPanel agent={agent} />
      </Card>

      {/* BAND 3 — set once, then rarely touched. Closed by default, one click away, and
          each one says in its closed state what is inside it. */}
      <Disclosure
        title="What it can do during a call"
        subtitle="Send a WhatsApp, look something up, book a slot — and the saved credentials they use."
        icon={<PlugZap className="h-4 w-4" />}
      >
        <Actions agentId={agent.id} session={session} />
      </Disclosure>

      <Disclosure
        title="What it is"
        subtitle="Its name, which way its calls go, and the language it speaks. Changing what it does can stop it answering your numbers."
        icon={<Settings2 className="h-4 w-4" />}
      >
        <AgentIdentity agent={agent} />
      </Disclosure>

      {/* Renders nothing at all on an API build that does not report a model — see
          `AgentModel`. A disclosure headed "The model it thinks with" containing a shrug is
          worse than no disclosure. */}
      <AgentModel agent={agent} slug={slug} />
    </div>
  );
}

/**
 * WHO THIS AGENT IS AND WHETHER IT IS WORKING — the page header, deliberately not a Card.
 *
 * A `Card` is a container for a PANEL: a bounded job with its own controls. The page's own
 * identity is not one of those, and wrapping it in the same chrome as the nine panels
 * below is exactly what made every block on this screen look equally important. Material's
 * own guidance makes the same call about homogeneous content — a card's chrome surrounds
 * the data and makes a reader jump from box to box instead of scanning down (m3.material.io
 * cards guidance; that host is EGRESS-BLOCKED from this session, so this is REPORTED from a
 * web-search reading on 25 Aug 2026 rather than read at source). Doctrine §1 ("Kill the
 * everything-is-a-Card default") carries the decision test.
 *
 * `status` and "on the calling system" stay SEPARATE rather than collapsed into the badge:
 * an agent switched on but not yet built is a different wait from one built but not
 * switched on, and only we can tell them apart.
 */
function AgentHeader({ agent }: { agent: Agent }) {
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
    <header>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink">{agent.name}</h1>
        <span
          className={`inline-flex shrink-0 items-center rounded-full border px-3 py-1 text-xs font-semibold ${live.tone}`}
        >
          {live.label}
        </span>
      </div>
      <p className="mt-1 max-w-2xl text-sm text-ink-muted">{live.detail}</p>

      <dl className="mt-4 grid gap-5 rounded-card border border-line bg-app p-4 sm:grid-cols-2">
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
    </header>
  );
}
