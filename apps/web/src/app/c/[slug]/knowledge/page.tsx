"use client";

import { useState, type ComponentType } from "react";
import {
  Archive,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleHelp,
  Clock,
  Send,
  XCircle,
} from "lucide-react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useAgents } from "@/lib/api/agents";
import { useKbChunks, useKbSources, useSubmitKnowledge } from "@/lib/api/kb";
import { lookup } from "@/lib/lookup";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

/**
 * Client-side knowledge (FLOWS §7).
 *
 * The screen is deliberately honest about the approval gate rather than hiding it: a
 * submission shows as "in review" and the copy says why. A client who does not know
 * their change is queued will submit it three more times, and the agent speaks under
 * their PE registration — the wait is a feature they should understand, not a delay
 * they should have to discover.
 *
 * Restyled to the console's design language (globals.css tokens, `Card`, lucide icons as
 * affordances) WITHOUT changing what it fetches or what it submits. The badge ladder is
 * untouched and is the load-bearing part of the screen — see `sourceBadge` below. What
 * else changed is what the screen was quietly not saying:
 *
 * - **A failed `/v1/agents` left a dead form with no explanation.** The submit button is
 *   disabled without an agent to teach, and nothing said why — so the one client whose
 *   agent list failed to load saw a form that simply refused to work. The agents query's
 *   error now renders, and an account with no agents at all is told so in words.
 * - **The preview rendered an empty box while it was loading, and again when it failed.**
 *   `(chunks.data ?? []).map(...)` cannot tell those two from "this submission has no
 *   answers in it", and the third reading is the one a client takes: that the text they
 *   pasted arrived empty. Loading is a skeleton, failure is a refusal, and only the
 *   server's own empty list is rendered as emptiness.
 * - **The rows never said WHICH agent a source teaches**, though the form insists on the
 *   choice and `list_sources` returns every agent's sources in one list. A client with
 *   two agents could not tell whether the answer they were waiting on belonged to the
 *   receptionist or to the outbound agent.
 *
 * The screen renders no `<h1>`: the shell prints the page title from the nav list
 * (layout.tsx), and a second "Knowledge base" beside it is a visible duplicate.
 *
 * Submitting is `kb:write`, which `staff` does not hold and which an impersonating
 * operator is refused (D-22) — so the control is disabled WITH the reason rather than
 * left to answer 403. Reading (`agents:read`) stays open, which is the whole point of
 * "view as client": support can see the knowledge base they are being asked about.
 */

interface StatusCopy {
  label: string;
  /** Badge palette. Semantic rather than branded — this is a verdict, not navigation. */
  tone: string;
  icon: ComponentType<{ className?: string }>;
}

/** A state we cannot name, and the archived state, share the quietest treatment. */
const NEUTRAL_BADGE = "bg-black/5 text-ink-muted dark:bg-white/10";

const STATUS_COPY: Record<string, StatusCopy> = {
  pending_approval: {
    label: "In review",
    tone: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
    icon: Clock,
  },
  approved: {
    label: "Approved, not live yet",
    tone: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
    icon: CheckCircle2,
  },
  rejected: {
    label: "Not accepted",
    tone: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
    icon: XCircle,
  },
  archived: {
    label: "Replaced by a newer version",
    tone: NEUTRAL_BADGE,
    icon: Archive,
  },
};

export default function KnowledgePage() {
  const session = useClientSession();
  // This tenant's trade, not a clinic's — see `lib/verticalExamples.ts`.
  const eg = useVerticalExamples();
  const sources = useKbSources(session);
  const agents = useAgents(session);
  const submit = useSubmitKnowledge(session);

  /**
   * D-22 read-only. Submitting is `kb:write` (kb/routes.py) — a MUTATING permission,
   * so an impersonating operator is refused it even though the `operator` role holds
   * it outright. Reading what an agent knows is `agents:read` and stays open, which is
   * the whole point of "view as client": support can see the knowledge base they are
   * being asked about, they just cannot add to it wearing the client's face.
   */
  const write = useWriteAccess(session, "kb:write", "add knowledge to this account");

  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [agentId, setAgentId] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const chunks = useKbChunks(session, selected);

  // Knowledge belongs to ONE agent. Silently posting it against `agents[0]` means a
  // client with two agents teaches the wrong one and waits for an answer the right
  // one will never give — so the choice is shown whenever there is one.
  const agentOptions = agents.data ?? [];
  const selectedAgentId = agentId || agentOptions[0]?.id || "";

  /**
   * Agent id → name, for the rows. Built from the SAME query the picker uses, so the
   * two halves of the screen cannot disagree about what an agent is called; read through
   * `lookup` because `agent_id` is a server string and `Object.fromEntries` produces an
   * object that inherits `Object.prototype` (src/lib/lookup.ts).
   */
  const agentNames: Record<string, string> = Object.fromEntries(
    agentOptions.map((agent) => [agent.id, agent.name]),
  );

  /**
   * There is nothing to teach — as a FACT from the server, not as "the list is empty
   * right now". While `/v1/agents` is in flight or has failed, `agentOptions` is also
   * empty, and telling a client they have no agents on the strength of a request that
   * never landed is the same lie as an empty state over a failed fetch.
   */
  /*
   * THE "TEACH IT SOMETHING" FORM, DECLARED TO THE SCREEN ASSISTANT.
   *
   * Three loose `useState` scalars, so `apply` is three setter calls — no DOM, no draft
   * object to thread. The agent picker is offered as a `select` over the SAME query the
   * control renders from, so the assistant cannot name an agent this account does not
   * have; a value outside the list is dropped rather than written, because the picker
   * would render blank and the submit would post an id nobody chose.
   *
   * This is the screen where a fill is most obviously worth having: the body is a page of
   * prose about a business, and "write the cancellation policy from what is in the
   * intake sheet" is the whole job.
   */
  useCopilotSurface({
    route: "/c/{slug}/knowledge",
    title: "Teach your agent something",
    realm: "client",
    fields: [
      {
        id: "kb-title",
        label: "Title",
        type: "text",
        value: name,
        help: "What this note is about — shown in the list, not read to callers.",
      },
      {
        id: "kb-body",
        label: "What it should know",
        type: "textarea",
        value: body,
        help: "Prose, in the language the agent answers in. Once it is approved it becomes part of what the agent already knows when it picks up.",
      },
      {
        id: "kb-agent",
        label: "Which agent learns this",
        type: "select",
        value: selectedAgentId,
        options: agentOptions.map((agent) => ({ value: agent.id, label: agent.name })),
        help: "Knowledge belongs to one agent.",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id === "kb-title") setName(asText(item.value));
        else if (item.field_id === "kb-body") setBody(asText(item.value));
        else if (
          item.field_id === "kb-agent" &&
          agentOptions.some((agent) => agent.id === item.value)
        ) {
          setAgentId(asText(item.value));
        }
      }
    },
  });

  const hasNoAgents = Boolean(agents.data) && agentOptions.length === 0;

  return (
    <div className="space-y-5 pb-12">
      {/* WHAT THIS SCREEN MAY PROMISE (`docs/TRD.md:948`): in-call retrieval is T0 and
          nothing else — approved facts are compiled into the agent's own prompt at
          publish time (`apps/api/agents/t0.py`). The agent does not read a document and
          does not look anything up while a caller is on the line, so the copy says
          "part of what it already knows" rather than anything retrieval-shaped. It is
          the faster arrangement, not the poorer one, and it is written that way.
          `tests/knowledgeApproval.test.tsx` pins the sentence and bans the shapes. */}
      <p className="text-sm text-ink-muted">
        What your agent knows. Everything you add is reviewed by your account manager,
        and once it is approved it becomes part of what the agent already knows when it
        picks up — hours, address, prices, the questions you get asked every day.
      </p>

      <RestrictionNote reason={write.reason} />

      {sources.error && <ProblemNotice error={sources.error} onRetry={() => sources.refetch()} />}
      {/* Without this the form simply refused to submit and never said why: no agent
          list means no agent to teach, and the disabled button looked like a bug. */}
      {agents.error && <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />}
      {submit.error && <ProblemNotice error={submit.error} />}

      <div className="grid gap-5 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <Card title="Add knowledge">
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (!selectedAgentId) return;
                submit.mutate(
                  { agentId: selectedAgentId, name, body },
                  {
                    onSuccess: () => {
                      setName("");
                      setBody("");
                    },
                  },
                );
              }}
            >
              {hasNoAgents && (
                <p className="rounded-lg border border-line bg-app px-3 py-2 text-xs text-ink-muted">
                  There is no agent on this account yet, so there is nothing to teach.
                  Your account manager sets the first one up with you.
                </p>
              )}

              {agentOptions.length > 1 ? (
                <label className="block">
                  <span className="text-xs font-medium text-ink-muted">
                    Which agent should know this
                  </span>
                  <select
                    value={selectedAgentId}
                    onChange={(e) => setAgentId(e.target.value)}
                    className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink"
                  >
                    {agentOptions.map((agent) => (
                      <option key={agent.id} value={agent.id}>
                        {agent.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                /* One agent is still a choice the client should be able to check —
                   the submission is filed against it either way. */
                agentOptions.length === 1 && (
                  <p className="text-xs text-ink-muted">
                    Goes to{" "}
                    <span className="font-semibold text-ink">{agentOptions[0]?.name}</span>.
                  </p>
                )
              )}

              <input
                /* The copilot field id — what the "filled" outline is drawn on. The
                   control is named by its own `aria-label`, so nothing else needs it. */
                id="kb-title"
                required
                minLength={2}
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-label="What this knowledge is about"
                placeholder={`What is this about? e.g. ${eg.knowledgeTitle}`}
                className="w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint"
              />
              <textarea
                id="kb-body"
                required
                minLength={10}
                rows={8}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                aria-label="What the agent should say"
                placeholder={
                  "Write it the way you would tell a new receptionist.\n\n" +
                  "Leave a blank line between topics. Short related topics are grouped " +
                  "into one answer; long ones are split."
                }
                className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint"
              />
              {/* Chunking is paragraph-aware, so telling the client that changes how
                  they write — and what they write is what the agent carries verbatim,
                  so better input is the only lever there is. */}
              <p className="text-xs text-ink-muted">
                Submitting a topic that already exists creates a new version; the previous
                one stays until this is approved.
              </p>
              <button
                type="submit"
                disabled={!write.allowed || submit.isPending || !selectedAgentId || body.length < 10}
                /* The reason travels WITH the control as well as sitting at the top of
                   the screen: `RestrictionNote` is above the fold on a phone only by
                   luck, and a dead button with the explanation off-screen is the 403 we
                   are trying not to ship. */
                title={write.reason ?? undefined}
                className="flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-strong px-4 py-2 text-sm font-semibold text-white hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Send className="h-3.5 w-3.5" />
                {submit.isPending ? "Submitting…" : "Submit for review"}
              </button>
            </form>
          </Card>
        </div>

        {/* A failed first load gets NO card. An empty panel headed "Submitted" is the
            same sentence as "nothing submitted", drawn instead of written, and on this
            screen that sentence tells a client their queued change is not queued. The
            notice above is the whole answer. `sources.data` survives a failed REFETCH,
            and those rows are real — so the guard is on the data, not on the error. */}
        {sources.isLoading ? (
          <div className="lg:col-span-7">
            <Card title="Submitted">
              <Skeleton rows={4} />
            </Card>
          </div>
        ) : !sources.data ? null : (
          <div className="lg:col-span-7">
            <Card title="Submitted" bodyClassName="p-2">
              {sources.data.length ? (
                <ul className="divide-y divide-line">
                  {sources.data.map((source) => {
                    // WHICH agent this teaches, or nothing. Absent rather than guessed
                    // while the agent list is loading or has failed: a source attributed
                    // to the wrong agent is worse than one attributed to none.
                    const agentName = lookup(agentNames, source.agent_id);
                    const open = selected === source.id;
                    return (
                      <li key={source.id} className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                          <span className="text-sm font-semibold text-ink">{source.name}</span>
                          <span className="text-xs tabular-nums text-ink-faint">
                            v{source.version}
                          </span>
                          <SourceBadge source={source} />
                          <span className="ml-auto flex items-center gap-2 text-xs text-ink-faint">
                            <span className="tabular-nums">
                              {formatCount(source.chunks)}{" "}
                              {source.chunks === 1 ? "answer" : "answers"}
                            </span>
                            {agentName && <span className="truncate">{agentName}</span>}
                            {source.published_at && (
                              <span className="whitespace-nowrap">
                                Published {formatIST(source.published_at)}
                              </span>
                            )}
                          </span>
                          <button
                            type="button"
                            onClick={() => setSelected(open ? null : source.id)}
                            aria-expanded={open}
                            className="flex items-center gap-1 rounded-md border border-line px-2 py-1.5 text-xs font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
                          >
                            {open ? (
                              <ChevronUp className="h-3 w-3" />
                            ) : (
                              <ChevronDown className="h-3 w-3" />
                            )}
                            {open ? "Hide" : "Preview"}
                          </button>
                        </div>

                        {open && (
                          <div className="mt-3 rounded-lg border border-line bg-app p-3">
                            {/* Answers that used to look identical: still fetching, no
                                answer at all, and "the server says there is nothing in
                                here". Only the last is emptiness; the others read to a
                                client as text that arrived blank. "No answer" is a failed
                                read AND a paused query (offline: not loading, `error ===
                                null`, `data === undefined`) — `chunks.data?.length` alone
                                collapsed the paused case into the emptiness sentence, so
                                the refusal owns both non-answers (§52). */}
                            {chunks.isLoading ? (
                              <Skeleton rows={2} />
                            ) : chunks.error || !chunks.data ? (
                              <ProblemNotice
                                error={chunks.error ?? new Error("This preview could not be loaded.")}
                                onRetry={() => void chunks.refetch()}
                              />
                            ) : chunks.data.length ? (
                              <div className="space-y-2">
                                {chunks.data.map((chunk) => (
                                  <div
                                    key={chunk.idx}
                                    className="rounded-md border border-line bg-surface p-2 text-xs text-ink-muted"
                                  >
                                    <p>{chunk.content}</p>
                                    {/* THE GLOSS, AND IT IS LABELLED AS A MACHINE'S WORK.
                                        It is a SEARCH AID, not something the agent says:
                                        it exists so a caller who asks in Telugu typed in
                                        English letters can still be found the answer
                                        above. Showing it unlabelled beside the client's
                                        own approved words would read as their words, so
                                        the label is part of the feature rather than
                                        decoration. */}
                                    {chunk.gloss ? (
                                      <p className="mt-2 border-t border-line pt-2 text-ink-faint">
                                        <span className="font-medium">
                                          Auto-translated for search
                                        </span>{" "}
                                        — not spoken by your agent. {chunk.gloss}
                                      </p>
                                    ) : null}
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p className="text-xs text-ink-muted">
                                There is nothing in this submission for the agent to say.
                              </p>
                            )}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState
                  title="Nothing submitted yet"
                  hint="Add your opening hours, services and prices first — those are what callers ask about."
                />
              )}
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * THE two-step ladder this screen exists for (FLOWS §7), and the one thing in this file
 * that must not be simplified:
 *
 *     is_active  →  "Live"       (a caller hears this now)
 *     otherwise  →  status copy  ("In review", "Approved, not live yet", …)
 *
 * `approved` is NOT `live`. Between them sit the version bump and the T0 recompile that
 * splices the fact into the agent's own prompt (FLOWS §7), either of which can still be
 * outstanding — so a badge keyed on `status === "approved"` tells a client the agent is
 * saying something no caller will hear, and they stop chasing the publish. Both fields
 * are on every row, so `tsc` catches nothing here; tests/knowledgeApproval.test.tsx does.
 *
 * There is no engine-side KB sync in that list, and there used to be: the engine's
 * built-in knowledge base is off and `attach_kb` refuses
 * (`apps/api/engine/bolna.py:2484,3536`). Publishing means the prompt, and nothing else.
 *
 * `SourceOut.status` is plain `string` on the wire, so the copy lookup fails VISIBLE: an
 * unnameable status renders as itself, because a client whose submission is stuck in an
 * unfamiliar state still has to see that it is stuck and quote the word to support.
 * `lookup` rather than a bare index — `STATUS_COPY["constructor"]` is the `Object`
 * function, which `??` does not treat as missing, so the badge rendered with `undefined`
 * copy and a stringified function for its class list (lib/lookup.ts).
 */
function SourceBadge({ source }: { source: { status: string; is_active: boolean } }) {
  if (source.is_active) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2 py-0.5 text-xs font-semibold text-brand-strong">
        {/* The design's live-state pip (globals.css), not an icon: "on air" is a state,
            and the pip is what the console uses for one everywhere else. */}
        <span className="h-1.5 w-1.5 rounded-full bg-brand-bright" />
        Live
      </span>
    );
  }
  const copy = lookup(STATUS_COPY, source.status) ?? {
    label: source.status,
    tone: NEUTRAL_BADGE,
    icon: CircleHelp,
  };
  const Icon = copy.icon;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${copy.tone}`}
    >
      <Icon className="h-3 w-3" />
      {copy.label}
    </span>
  );
}
