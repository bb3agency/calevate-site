"use client";

import Link from "next/link";
import { use } from "react";

import { Card, EmptyState, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { useAgents, type Agent, type AgentExtractionField } from "@/lib/api/agents";
import {
  useLanes,
  usePendingChanges,
  type Lane,
  type PendingChange,
} from "@/lib/api/publishing";
import type { Session } from "@/lib/api/client";
import { useClientRealm, useClientSession } from "@/lib/api/session";

/**
 * Direction in the owner's terms, with a glyph that reads at a glance. "Inbound"
 * and "outbound" are OUR nouns; a clinic owner thinks "does it pick up, or does it
 * ring people?".
 */
const DIRECTION_COPY: Record<string, { glyph: string; label: string; hint: string }> = {
  inbound: {
    glyph: "↓",
    label: "Answers calls",
    hint: "Picks up when someone rings your number.",
  },
  outbound: {
    glyph: "↑",
    label: "Makes calls",
    hint: "Dials your customers for campaigns and follow-ups.",
  },
  both: {
    glyph: "↕",
    label: "Answers and makes calls",
    hint: "Picks up incoming calls and dials out for campaigns.",
  },
};

/** Only three languages ship today (admin/new); an unknown code falls back to itself. */
const LANGUAGE_NAMES: Record<string, string> = {
  "te-IN": "Telugu",
  "hi-IN": "Hindi",
  "en-IN": "English (India)",
};

const STATUS_COPY: Record<string, { label: string; hint: string }> = {
  draft: { label: "Draft", hint: "Still being put together by your account manager." },
  live: { label: "Switched on", hint: "Cleared to take calls." },
  paused: { label: "Paused", hint: "Switched off for now, on purpose." },
};

const FIELD_TYPE_COPY: Record<AgentExtractionField["type"], string> = {
  text: "Text",
  number: "Number",
  bool: "Yes / no",
  enum: "One of a set list",
  date: "Date",
};

/**
 * The one question this screen exists to answer without a phone call to us: is
 * this thing live?
 *
 * "Live" needs BOTH facts to line up — the agent has been created on the calling
 * system (`published`) AND its status says live. That is the same test the prompt
 * publisher applies server-side (`_is_live` in apps/api/agents/prompts.py), so the
 * badge here cannot say something the backend would disagree with. `published` is
 * checked first because nothing else matters until it is true: an agent that does
 * not exist on the calling system cannot ring, whatever its status column says.
 */
function liveState(agent: Agent): { label: string; tone: string; detail: string } {
  if (!agent.published) {
    return {
      label: "Being set up",
      tone: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
      detail:
        "Not on the calling system yet, so it cannot take or make calls. Your account manager finishes this before your first call.",
    };
  }
  if (agent.status === "paused") {
    return {
      label: "Paused",
      tone: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
      detail: "Switched off for now. No calls are being answered or made by this agent.",
    };
  }
  if (agent.status === "live") {
    return {
      label: "Live",
      tone: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
      detail: "On the calling system and working right now.",
    };
  }
  return {
    label: "Ready, not switched on",
    tone: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
    detail: "Built and on the calling system, waiting to be switched on.",
  };
}

/**
 * Your agents (SURFACES §2).
 *
 * Read-only by design (D-21): agent configuration routes through us, because a
 * schema change regenerates prompt hints and needs a regression run. So this screen
 * shows the record and names who changes it — it does not grow disabled buttons or
 * "coming soon" affordances, which only teach a client that the page is broken.
 *
 * The disclosure line is here because the client is legally the Principal Entity
 * (SEC-COMP §1): the agent announces itself under THEIR business name, so they have
 * to be able to read the sentence it says, verbatim, without asking us for it.
 */
export default function AgentsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = useClientSession();
  const agents = useAgents(session);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Your agents</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          The phone agents working for your business: what each one does, what it says
          about itself, and what it writes down. Your account manager sets these up and
          makes any changes.
        </p>
      </div>

      {agents.error && <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />}

      {agents.isLoading ? (
        <Skeleton rows={6} />
      ) : agents.data?.length ? (
        <div className="space-y-4">
          {agents.data.map((agent) => (
            <AgentCard key={agent.id} agent={agent} slug={slug} />
          ))}
        </div>
      ) : agents.data ? (
        <Card>
          <EmptyState
            title="No agent set up yet"
            hint="Your account manager builds your first agent during onboarding. It will show up here — everything it says and everything it captures — before it takes a single call."
          />
        </Card>
      ) : null}

      {/* The precedence rule §2b asks to be STATED in the UI, and the lane table it
          summarises. Shown once for the whole screen rather than per agent: it is a
          property of the platform, not of an agent, and repeating it under every card
          would train people to stop reading it. Only worth showing next to agents,
          so it renders under an empty list not at all. */}
      {agents.data?.length ? <HowChangesTakeEffect session={session} /> : null}
    </div>
  );
}

/**
 * "Script decides content, rules decide conduct, voice only changes delivery" — and
 * which settings sit on which side of the Apply step.
 *
 * Every word of it comes from `GET /v1/agents/lanes`: the sentence, the reason under
 * each row, and which lane a field is on. The server owns that wording because the
 * server enforces the split, and a screen that paraphrased it is precisely how "voice
 * applies immediately" turns into a support ticket (the API module says so in those
 * words). The only thing decided here is the LABEL — `max_call_duration_s` is our
 * column name, not a sentence to show a clinic owner.
 */
function HowChangesTakeEffect({ session }: { session: Session }) {
  const lanes = useLanes(session);

  if (lanes.error) {
    return <ProblemNotice error={lanes.error} onRetry={() => lanes.refetch()} />;
  }
  if (!lanes.data) return <Skeleton rows={4} />;

  const waits = lanes.data.lanes.filter((lane) => lane.lane === "staged");
  const immediate = lanes.data.lanes.filter((lane) => lane.lane !== "staged");

  return (
    <Card title="How changes take effect">
      <p className="text-sm font-medium text-slate-900 dark:text-slate-50">
        {lanes.data.precedence_rule}
      </p>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
        Some changes reach live calls the moment they are made; a change to what the
        agent SAYS waits until it is deliberately applied, so nothing a caller hears
        changes by accident.
      </p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <LaneList
          title="Waits to be applied"
          hint="Made now, live only after your account manager applies it."
          lanes={waits}
        />
        <LaneList
          title="Applies straight away"
          hint="In force on the next call, with nothing to approve."
          lanes={immediate}
        />
      </div>

      <p className="mt-4 text-xs text-slate-500">
        Every agent can be capped at {formatCallCap(lanes.data.call_cap_default_s)} per call
        by default, and that cap can be set anywhere between{" "}
        {formatCallCap(lanes.data.call_cap_min_s)} and{" "}
        {formatCallCap(lanes.data.call_cap_max_s)}. There is no way to remove it.
      </p>
    </Card>
  );
}

/** Our word for one of the server's field names. Unknown fields degrade to the name
 *  itself rather than disappearing — a lane the client cannot see is worse than an
 *  ugly label, and a new lane ships from the API without a frontend release. */
const FIELD_LABELS: Record<string, string> = {
  script: "What the agent says",
  max_call_duration_s: "Longest a call may run",
  extraction_fields: "What it writes down",
  training: "Knowledge and training",
  voice: "Its voice",
};

function LaneList({
  title,
  hint,
  lanes,
}: {
  title: string;
  hint: string;
  lanes: Lane[];
}) {
  if (lanes.length === 0) return null;
  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">{title}</h3>
      <p className="mt-0.5 text-xs text-slate-500">{hint}</p>
      <ul className="mt-2 space-y-2">
        {lanes.map((lane) => (
          <li key={lane.field}>
            <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
              {FIELD_LABELS[lane.field] ?? lane.field.replace(/_/g, " ")}
            </p>
            <p className="text-xs text-slate-500">{lane.why}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * "10 minutes", "5 min 30 s" — a call cap in the units an owner thinks in.
 *
 * `formatDuration` in components/ui is for how long a call ACTUALLY ran and reads as
 * a stopwatch (`10:00`); a ceiling reads as a sentence. Two formats because they
 * answer two different questions, not because one was forgotten.
 */
function formatCallCap(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes === 0) return `${rest} seconds`;
  if (rest === 0) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  return `${minutes} min ${rest} s`;
}

function AgentCard({ agent, slug }: { agent: Agent; slug: string }) {
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { href } = useClientRealm();
  const live = liveState(agent);
  const direction = DIRECTION_COPY[agent.direction] ?? {
    glyph: "•",
    label: agent.direction.replace(/_/g, " "),
    hint: "",
  };
  const status = STATUS_COPY[agent.status] ?? {
    label: agent.status.replace(/_/g, " "),
    hint: "",
  };

  return (
    <Card
      title={agent.name}
      action={
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${live.tone}`}
        >
          {live.label}
        </span>
      }
    >
      <div className="space-y-5">
        <p className="text-sm text-slate-600 dark:text-slate-400">{live.detail}</p>

        {/* The four facts a client should never have to ask us for. `status` and
            "on the calling system" are shown separately rather than collapsed into
            the badge: an agent switched on but not yet built is a different wait
            from one built but not switched on, and only we can tell them apart. */}
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="What it does" hint={direction.hint}>
            <span aria-hidden className="mr-1 text-slate-400">
              {direction.glyph}
            </span>
            {direction.label}
          </Fact>
          <Fact label="Speaks" hint="The language it greets and answers callers in.">
            {LANGUAGE_NAMES[agent.language_primary] ?? agent.language_primary}
          </Fact>
          <Fact label="Status" hint={status.hint}>
            {status.label}
          </Fact>
          <Fact
            label="On the calling system"
            hint={
              agent.published
                ? "Built and connected, so it can be switched on."
                : "Until this is done, the agent cannot ring anyone."
            }
          >
            {agent.published ? "Connected" : "Not yet"}
          </Fact>
        </dl>

        <PublishingPanel agentId={agent.id} />

        {/* Rendered as the sentence it is, not as a config value: this is spoken
            aloud, and reading it in quotes is how a client notices the business
            name or the purpose is wrong. Not framed as their choice — we write it
            to satisfy the disclosure rule — but it is theirs to check. */}
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">
            What it says at the start of every call
          </h3>
          <blockquote className="mt-1.5 border-l-2 border-slate-300 pl-3 text-sm italic text-slate-700 dark:border-slate-700 dark:text-slate-300">
            “{agent.disclosure_line}”
          </blockquote>
          <p className="mt-1.5 text-xs text-slate-500">
            Every call opens with this line, spoken under your business name. Callers are
            told they are speaking to an AI assistant before anything else happens. If
            anything in it is wrong, tell your account manager — it cannot be removed.
          </p>
        </div>

        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">
            What it writes down
          </h3>
          {agent.extraction_fields.length > 0 ? (
            <>
              <ul className="mt-2 divide-y divide-slate-100 dark:divide-slate-800">
                {agent.extraction_fields.map((field) => (
                  <FieldRow key={field.key} field={field} />
                ))}
              </ul>
              <p className="mt-2 text-xs text-slate-500">
                These are the columns in your{" "}
                <Link href={href(`/c/${slug}/leads`)} className="underline underline-offset-2">
                  Leads
                </Link>{" "}
                table. The agent fills them in from the conversation — it never reads a
                form aloud, so a caller who answers early is not asked twice.
              </p>
            </>
          ) : (
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              Nothing extra yet. Calls still turn into leads with the caller name, number
              and a summary — this agent just does not capture any business-specific
              details on top of that.
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

/**
 * The unsaved-changes banner (§2b) and the cost-runaway guard, from the client's side
 * of the fence.
 *
 * Two things it deliberately does NOT have: an Apply button and an Undo button. Both
 * routes are ADMIN realm with the tenant in the path
 * (`apps/api/agents/publishing_routes.py`: "you cannot apply what you cannot write" —
 * the staged script is authored through an admin-realm endpoint, so a client Apply
 * would publish a draft they had no way to write). A control whose only outcome is a
 * refusal is a trap, and this app has said so twice already — `agents.ts` on agent
 * edits, `usage/page.tsx` on a pay button that cannot charge. What the client gets
 * instead is the true state and the name of the person who changes it.
 *
 * `headline` and `why` are rendered as sent. The server composes them from version
 * NUMBERS (a prompt body carries the client's prices and staff names — hard rule 6),
 * and restating them here would be a second source for one sentence.
 */
function PublishingPanel({ agentId }: { agentId: string }) {
  const session = useClientSession();
  const pending = usePendingChanges(session, agentId);

  if (pending.isLoading) return <Skeleton rows={2} />;
  if (pending.error) {
    return <ProblemNotice error={pending.error} onRetry={() => pending.refetch()} />;
  }
  if (!pending.data) return null;

  const state = pending.data;

  return (
    <div className="space-y-3">
      {state.has_pending ? (
        <div
          role="status"
          className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
        >
          <p className="font-medium">Changes waiting to go live</p>
          <ul className="mt-2 space-y-2">
            {state.pending.map((change) => (
              <PendingRow key={change.field} change={change} />
            ))}
          </ul>
          <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">
            Callers still hear the version above until your account manager applies the
            change — nothing goes live silently. Ask them to apply it, or to discard it
            if it was not meant to happen.
          </p>
        </div>
      ) : (
        /* The reassuring case is worth a line: an owner who has been told an edit was
           made needs to be able to see that it HAS landed, not just infer it from the
           absence of a warning. */
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Nothing is waiting to go live — what is described on this page is what callers
          hear right now.
        </p>
      )}

      {/* The cost-runaway guard, as the question it actually answers: what is the
          worst one call can do to my bill. */}
      <dl className="grid gap-4 rounded-lg border border-slate-200 p-3 sm:grid-cols-2 dark:border-slate-800">
        <Fact
          label="Longest one call may run"
          hint={
            state.call_cap_is_platform_default
              ? "The standard limit we put on every agent."
              : "Set specifically for this agent."
          }
        >
          {formatCallCap(state.effective_call_cap_s)}
        </Fact>
        <Fact
          label="Most one call can cost you"
          hint={
            state.worst_case_call_cost_inr === null
              ? "Your plan does not quote a per-minute rate, so we cannot put a number on it. Your account manager can."
              : "A call that runs the full limit, at your plan's per-minute rate. Almost every call ends long before this."
          }
        >
          {/* Null is "we cannot say", NOT zero — quoting ₹0.00 for a ten-minute call
              is the one answer that is actively wrong (`publishing.py::_overage_rate`).
              The figure is an exact NUMERIC and stays a STRING: `Number()` here is how
              ₹10,159.00 becomes ₹10,158.999999999998 (hard rule 7). */}
          {state.worst_case_call_cost_inr === null
            ? "We cannot say yet"
            : `₹${state.worst_case_call_cost_inr}`}
        </Fact>
      </dl>
    </div>
  );
}

function PendingRow({ change }: { change: PendingChange }) {
  return (
    <li>
      <p className="font-medium">{change.headline}</p>
      <p className="mt-0.5 text-xs text-amber-800 dark:text-amber-300">{change.why}</p>
      <p className="mt-0.5 text-xs text-amber-800/80 dark:text-amber-300/80">
        Waiting since {formatIST(change.staged_at)}
      </p>
    </li>
  );
}

/** One labelled fact. `dt`/`dd` because that is exactly what these are. */
function Fact({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-slate-900 dark:text-slate-50">{children}</dd>
      {hint && <dd className="mt-0.5 text-xs text-slate-500">{hint}</dd>}
    </div>
  );
}

/**
 * One captured field, shown as the CRM column it becomes. The label leads, because
 * that is the word the client sees on the Leads table; the key is not shown at all
 * — it is our storage detail, and two names for one column is one too many.
 */
function FieldRow({ field }: { field: AgentExtractionField }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 py-2">
      <span className="text-sm font-medium text-slate-800 dark:text-slate-200">{field.label}</span>
      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-400">
        {FIELD_TYPE_COPY[field.type] ?? field.type}
      </span>
      {field.required && (
        <span className="rounded bg-slate-900 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white dark:bg-slate-100 dark:text-slate-900">
          Always asked
        </span>
      )}
      {field.description && (
        <span className="w-full text-xs text-slate-500">{field.description}</span>
      )}
      {field.enum_values?.length ? (
        <span className="w-full text-xs text-slate-500">
          One of: {field.enum_values.join(" · ")}
        </span>
      ) : null}
    </li>
  );
}
