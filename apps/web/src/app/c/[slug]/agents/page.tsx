"use client";

import Link from "next/link";
import { use } from "react";

import { Card, EmptyState, ProblemNotice, Skeleton } from "@/components/ui";
import { useAgents, type Agent, type AgentExtractionField } from "@/lib/api/agents";
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
    </div>
  );
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
