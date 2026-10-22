"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useId, useMemo } from "react";
import { ArrowRight, Wrench } from "lucide-react";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { PageHeader } from "@/components/console/pageHeader";
import { TEXT_ACTION } from "@/components/console/section";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { focusMain } from "@/components/copilot/workspace/AssistantWorkspace";
import { PipMark } from "@/components/illustration/pip";
import { ProgressBar } from "@/components/interior/progress-bar";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { useAgents, type Agent } from "@/lib/api/agents";
import { useCalls, useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useKnows } from "@/lib/api/teach";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { pipLocked, usePipConsent } from "@/lib/copilot/conversation";
import { fallbackSurface } from "@/lib/copilot/fallback";
import { resolveDestination } from "@/lib/copilot/navigate";
import { useCopilotSurface, useCopilotSurfaceHolder, type SurfaceHolder } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import {
  GREETING_MAX_CHARS,
  charCount,
  firstAgentOf,
  hintFor,
  introFor,
  jobOf,
  nextPiece,
  piecesOf,
  quickRepliesFor,
  type Piece,
  type PinnedAnswer,
} from "@/lib/firstAgent";

import { StartFromJob } from "../new/StartFromJob";
import { AgentTakingShape } from "./AgentTakingShape";
import { FirstCall } from "./FirstCall";

/** The route this screen declares to Pip; the server's first-agent guide is keyed on it. */
export const FIRST_AGENT_ROUTE = "/c/{slug}/agents/first";

type Door = "pip" | "manual";

/**
 * BUILD YOUR FIRST AGENT (D-854, founder 22 Oct 2026).
 *
 * Two doors: a chat with Pip, which asks one thing at a time and builds the agent from the
 * answers, or the ready-made job form the Agents screen already has. Either way the card on
 * the right fills in as each piece lands and the meter climbs; the finale is the agent
 * ringing the owner's own phone.
 *
 * WHERE THE OWNER IS COMES FROM THE SERVER, NOT FROM A SAVED GAME. The agent row, the pinned
 * facts and the agent's calls are the state (`lib/firstAgent.ts`); the address only carries
 * which door and which agent, so a reload, another device or a half-finished visit lands in
 * the same place.
 *
 * Pip is off until the account's owner turns it on (D-788): the chat's first panel is that
 * consent, in one tick and one press. Someone who cannot turn it on, and a session viewing the
 * account as an operator, is offered the hand-built door with the reason in one line.
 */
export function FirstAgentScreen({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const named = params.get("agent");
  const asked = params.get("with");
  const agents = useAgents(session);
  const knows = useKnows(session);
  const consent = usePipConsent(session);
  const write = useWriteAccess(session, "org:manage", "build an agent");
  const agent = firstAgentOf(agents.data, named);
  const calls = useCalls(session, { agent_id: agent?.id, limit: 1 }, agent !== null);

  const answers = useMemo<PinnedAnswer[]>(
    () =>
      (knows.data?.facts ?? [])
        .filter((fact) => fact.pinned && (fact.question ?? "").trim() !== "")
        .map((fact) => ({ question: fact.question ?? "", answer: fact.text })),
    [knows.data],
  );
  const pieces = piecesOf({ agent, answers, calls: calls.data });
  const next = nextPiece(pieces);
  const loaded = agents.data !== undefined && knows.data !== undefined;

  /* Pip can run here when the account has it on, or when this person can turn it on. */
  const pipOff = session.impersonateOrg
    ? `${ASSISTANT_NAME} isn't available while you view this account, so it is built by hand.`
    : consent.data && pipLocked(consent.data) && !consent.data.can_accept
      ? `${ASSISTANT_NAME} is off for this account until its owner turns it on. You can build your agent yourself in the meantime.`
      : null;
  const door = chooseDoor(asked, pipOff !== null, agent !== null);

  const go = useCallback(
    (to: Door, agentId?: string) => {
      const query = new URLSearchParams(params.toString());
      query.set("with", to);
      if (agentId) query.set("agent", agentId);
      router.replace(href(`${pathname}?${query.toString()}`), { scroll: false });
    },
    [href, params, pathname, router],
  );

  useCopilotSurface({
    route: FIRST_AGENT_ROUTE,
    title: "Build your first agent",
    realm: "client",
    fields: [],
    facts: surfaceFacts(agent, answers, pieces, loaded),
    apply: noFill,
  });
  const declared = useCopilotSurfaceHolder();
  const holder = useMemo<SurfaceHolder>(() => {
    const surface = fallbackSurface(FIRST_AGENT_ROUTE, "client");
    return { read: () => surface };
  }, []);
  const onNavigate = useCallback(
    (destination: { route: string }) => {
      const path = resolveDestination(destination.route, slug);
      if (path === null) return;
      router.push(href(path));
      focusMain();
    },
    [href, router, slug],
  );

  const done = pieces.filter((piece) => piece.done).length;

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        title="Build your first agent"
        description="A few quick answers and it is ready. At the end, it rings your phone so you hear it."
        back={{ href: href(`/c/${slug}/agents`), label: "Agents" }}
        actions={
          <Link href={href(`/c/${slug}`)} className={TEXT_ACTION}>
            Skip for now
          </Link>
        }
      />

      <div className="max-w-xl space-y-2">
        {/* Nothing is counted until the reads answer: a meter at "1 of 9" over an account
            whose agent has not loaded yet would be a claim the screen has not earned. */}
        <ProgressBar
          value={loaded ? done : null}
          max={pieces.length}
          label={
            !loaded
              ? "Your first agent"
              : done === 1
                ? `Account created · 1 of ${pieces.length} done`
                : `${done} of ${pieces.length} done`
          }
          pendingLabel="Checking"
          completeLabel="Your agent is built"
        />
        {loaded ? (
          <p className="flex items-start gap-2 text-meta text-ink-muted">
            <PipMark size={18} className="mt-px shrink-0" />
            <span>{hintFor(next?.id ?? null)}</span>
          </p>
        ) : null}
      </div>

      <RestrictionNote reason={write.allowed ? null : write.reason} />

      {agents.isError ? (
        <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />
      ) : knows.isError ? (
        /* The questions piece is counted from this read; without it the card would say
           "none pinned" about an account whose answers simply did not load. */
        <ProblemNotice error={knows.error} onRetry={() => void knows.refetch()} />
      ) : !loaded || write.unknown ? (
        <Skeleton rows={6} label="Getting your agent ready…" />
      ) : !write.allowed ? null : door === null ? (
        <Doors pipOff={pipOff} onPick={(to) => go(to)} />
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)]">
          <div className="min-w-0 space-y-3">
            {door === "pip" ? (
              <>
                <CopilotPanel
                  session={session}
                  holder={declared ?? holder}
                  realm="client"
                  labelledBy="first-agent-pip"
                  placement="page"
                  onNavigate={onNavigate}
                  quickReplies={quickRepliesFor(next?.id ?? null)}
                  intro={introFor(next, agent?.name ?? null)}
                />
                <span id="first-agent-pip" className="sr-only">
                  {ASSISTANT_NAME}, building your first agent with you
                </span>
                <button type="button" className={TEXT_ACTION} onClick={() => go("manual", agent?.id)}>
                  I&apos;ll set it up myself
                </button>
              </>
            ) : (
              <ManualDoor
                slug={slug}
                agent={agent}
                pieces={pieces}
                pipOff={pipOff}
                onCreated={(created) => go("manual", created.id)}
                onPip={() => go("pip", agent?.id)}
              />
            )}
          </div>
          <aside className="min-w-0 lg:sticky lg:top-4" aria-label="Your agent as it takes shape">
            <AgentTakingShape
              agent={agent}
              answers={answers}
              pieces={pieces}
              loaded={loaded}
              footer={<FirstCall agent={agent} calls={calls.data} />}
            />
          </aside>
        </div>
      )}
    </div>
  );
}

/**
 * Which door is open: the one the address names, else Pip once an agent exists (the owner
 * is mid-build), else neither, so the two doors are offered. With Pip unavailable the
 * hand-built door is the only one that opens.
 */
export function chooseDoor(asked: string | null, pipOff: boolean, hasAgent: boolean): Door | null {
  if (asked === "manual") return "manual";
  if (pipOff) return asked === "pip" || hasAgent ? "manual" : null;
  if (asked === "pip" || hasAgent) return "pip";
  return null;
}

/** The two ways in, Pip first. A door that cannot open says why instead of disappearing. */
function Doors({ pipOff, onPick }: { pipOff: string | null; onPick: (door: Door) => void }) {
  const pipId = useId();
  const handId = useId();
  return (
    <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
      <button
        type="button"
        disabled={pipOff !== null}
        aria-describedby={pipId}
        onClick={() => onPick("pip")}
        className="press group flex flex-col items-start gap-3 rounded-card border border-brand/50 bg-surface p-5 text-left shadow-card transition-[border-color,box-shadow] duration-(--duration-fast) hover:border-brand hover:shadow-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:border-line disabled:shadow-none"
      >
        <PipMark size={36} />
        <span className="text-heading text-ink">Build it with {ASSISTANT_NAME}</span>
        <span id={pipId} className="text-meta text-ink-muted">
          {pipOff ?? `${ASSISTANT_NAME} asks a few quick questions and builds it while you watch. About five minutes.`}
        </span>
        {pipOff === null ? (
          <span className="mt-auto inline-flex items-center gap-1 text-meta font-medium text-brand-strong">
            Start
            <ArrowRight aria-hidden className="h-3.5 w-3.5 transition-transform duration-(--duration-fast) group-hover:translate-x-0.5 motion-reduce:transition-none" />
          </span>
        ) : null}
      </button>
      <button
        type="button"
        aria-describedby={handId}
        onClick={() => onPick("manual")}
        className="press group flex flex-col items-start gap-3 rounded-card border border-line bg-surface p-5 text-left transition-[border-color,box-shadow] duration-(--duration-fast) hover:border-ink/30 hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        <span aria-hidden className="flex h-9 w-9 items-center justify-center rounded-full border border-line text-ink-muted">
          <Wrench className="h-4 w-4" />
        </span>
        <span className="text-heading text-ink">I&apos;ll set it up myself</span>
        <span id={handId} className="text-meta text-ink-muted">
          Pick its job, get a ready agent for your business, then change anything you like.
        </span>
      </button>
    </div>
  );
}

/** The hand-built door: the Agents screen's own job form, then what is left, piece by piece. */
function ManualDoor({
  slug,
  agent,
  pieces,
  pipOff,
  onCreated,
  onPip,
}: {
  slug: string;
  agent: Agent | null;
  pieces: readonly Piece[];
  pipOff: string | null;
  onCreated: (agent: Agent) => void;
  onPip: () => void;
}) {
  const { href } = useClientRealm();
  const router = useRouter();
  const switchToPip =
    pipOff === null ? (
      <button type="button" className={TEXT_ACTION} onClick={onPip}>
        Build it with {ASSISTANT_NAME} instead
      </button>
    ) : (
      <p className="text-meta text-ink-muted">{pipOff}</p>
    );
  if (agent === null) {
    return (
      <div className="space-y-4">
        <StartFromJob
          slug={slug}
          onBlank={() => router.push(href(`/c/${slug}/agents/new`))}
          onCreated={onCreated}
        />
        {switchToPip}
      </div>
    );
  }
  const base = `/c/${slug}/agents/${agent.id}`;
  const LINKS: Partial<Record<Piece["id"], { href: string; label: string; detail?: string }>> = {
    voice: { href: href(`${base}?section=voice`), label: "Choose" },
    greeting: {
      href: href(`${base}?section=script`),
      label: "Write",
      detail: `Under ${GREETING_MAX_CHARS} characters, ending with a question.`,
    },
    questions: { href: href(`/c/${slug}/knowledge`), label: "Add answers", detail: "Pin the three things callers ask most." },
    notes: { href: href(`${base}?section=script`), label: "Choose" },
  };
  const items: ChecklistItem[] = pieces
    .filter((piece) => piece.id !== "account" && piece.id !== "ready" && piece.id !== "call")
    .map((piece) => {
      const link = LINKS[piece.id];
      return {
        id: piece.id,
        label: piece.label,
        state: piece.done ? "done" : "todo",
        detail: piece.done ? undefined : link?.detail,
        link: piece.done || !link ? undefined : { href: link.href, label: link.label },
      };
    });
  return (
    <div className="space-y-4">
      <Checklist label={`Finish ${agent.name}`} headingLevel={2} items={items} />
      <p className="text-meta text-ink-muted">
        Each link opens {agent.name}&apos;s own page. Come back here when you are done; the card keeps up.
      </p>
      {switchToPip}
    </div>
  );
}

/** What Pip is told about this screen: the pieces and the agent's current values, by name. */
function surfaceFacts(
  agent: Agent | null,
  answers: readonly PinnedAnswer[],
  pieces: readonly Piece[],
  loaded: boolean,
) {
  if (!loaded) return [{ key: "state", label: "What is on screen", value: "still loading" }];
  const facts = [
    {
      key: "pieces",
      label: "Pieces of the first agent (done or to do)",
      value: pieces.map((piece) => `${piece.label}: ${piece.done ? "done" : "to do"}`).join("; "),
    },
  ];
  if (agent === null) {
    facts.push({ key: "agent", label: "The agent being built", value: "none yet" });
    return facts;
  }
  const opening = agent.script_opening_line.trim();
  facts.push(
    { key: "agent_id", label: "The agent's id", value: agent.id },
    { key: "agent_name", label: "Its name", value: agent.name },
    { key: "agent_job", label: "Its job", value: jobOf(agent) },
    { key: "agent_language", label: "Its main language", value: agent.language_primary },
    { key: "agent_voice", label: "Its voice id", value: agent.engine_voice_id ?? "the default, not chosen yet" },
    {
      key: "opening_line",
      label: `Its opening line (${charCount(opening)} characters)`,
      value: opening || "none written yet",
    },
    {
      key: "pinned_answers",
      label: "Questions callers ask, already pinned",
      value: answers.map((answer) => answer.question).join("; ") || "none yet",
    },
    {
      key: "notes_down",
      label: "What it notes down",
      value: agent.extraction_fields.map((field) => field.label).join(", ") || "nothing yet",
    },
    { key: "ready", label: "Ready to try", value: agent.published ? "yes" : "no" },
  );
  return facts;
}
