"use client";

import Link from "next/link";
import { use } from "react";
import { Plus } from "lucide-react";

import { Card, PRIMARY_BUTTON, ProblemNotice, Skeleton } from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { agentGroup } from "@/lib/agentState";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { HowChangesTakeEffect } from "./LaneGuide";
import { Archive, Roster } from "./Roster";

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
 * ## What this file is now (UX-DOCTRINE §6)
 *
 * The route module, and almost nothing else: the intro, the one creating control, the §52
 * branches, and three children. The list is `./Roster.tsx`; the platform explainer, which
 * was the biggest block on the screen and is read once in a lifetime, is `./LaneGuide.tsx`
 * and is now DISCLOSED rather than always open.
 *
 * ## §52
 *
 * Loading is a `Skeleton`, failure is a `ProblemNotice` with a retry, and "you have no
 * agents" is stated only where the server SAID so — a failed read is not evidence about
 * a client's account. The three are mutually exclusive branches, not a ladder that falls
 * through.
 */
export default function AgentsPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const session = useClientSession();
  const { href } = useClientRealm();
  const agents = useAgents(session);
  const roster = agents.data ?? [];

  /*
   * THE ROSTER, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * The counts, not the rows. `agentGroup` is the same predicate `Roster.tsx` groups by,
   * so the assistant's "nothing is answering your calls" and the screen's cannot disagree
   * — a second test here would be the drift this repo treats as a defect even when both
   * spellings happen to agree today.
   *
   * The ARCHIVE is deliberately absent: it is a second request made inside `<Archive/>`,
   * and a count this component would have to re-fetch to state. A screen describes what it
   * renders; the copilot's own `agents` read tool is what answers a question about the rest.
   */
  useCopilotSurface({
    route: "/c/{slug}/agents",
    title: "Your agents",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: agents.data
          ? "the roster below has loaded"
          : agents.error
            ? "the roster failed to load, so no agent is listed"
            : "still loading",
      },
      ...(agents.data
        ? [
            {
              key: "agents_total",
              label: "Agents on the working roster",
              value: String(roster.length),
            },
            {
              key: "agents_working",
              label:
                "Agents working right now (on the calling system and switched on)",
              value: String(
                roster.filter((agent) => agentGroup(agent) === "active").length,
              ),
            },
            {
              key: "agents_not_working",
              label: "Agents not working (being built, or switched off)",
              value: String(
                roster.filter((agent) => agentGroup(agent) !== "active").length,
              ),
            },
            {
              key: "agent_directions",
              label: "How many answer, call out, or both",
              value: (["inbound", "outbound", "both"] as const)
                .map(
                  (direction) =>
                    `${direction}: ${roster.filter((agent) => agent.direction === direction).length}`,
                )
                .join(", "),
            },
          ]
        : []),
    ],
    apply: noFill,
  });

  return (
    <div className="space-y-5 pb-12">
      <div className="flex flex-wrap items-start justify-between gap-3">
        {/* ONE LINE (D-527). The founder's note on this screen was that there is too much
            to read; the page already carries an "Agents" heading from the layout and a New
            agent button beside it, and a paragraph enumerating what an agent's own screen
            can do is read by nobody who is here to see which agent is working. What the
            line keeps is the only thing the heading does not say: that a row opens. */}
        <p className="max-w-2xl text-sm text-ink-muted">
          Open one to change what it says, teach it, or switch it on and off.
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

      {agents.error && (
        <ProblemNotice
          error={agents.error}
          onRetry={() => void agents.refetch()}
        />
      )}

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
