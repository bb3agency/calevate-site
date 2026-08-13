"use client";

import Link from "next/link";
import { use, type ReactNode } from "react";
import {
  CircleAlert,
  Hourglass,
  IndianRupee,
  ListChecks,
  PhoneCall,
  PhoneIncoming,
  PhoneOutgoing,
  ShieldCheck,
  Timer,
  Zap,
} from "lucide-react";

import {
  Card,
  EmptyState,
  NOTICE_TONES,
  ProblemNotice,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import { useAgents, type Agent, type AgentExtractionField } from "@/lib/api/agents";
import {
  useLanes,
  usePendingChanges,
  type Lane,
  type PendingChange,
} from "@/lib/api/publishing";
import type { Session } from "@/lib/api/client";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/**
 * Your agents (SURFACES §2) — the roster, plus the §2b two-speed publishing state.
 *
 * Read-only by design (D-21): agent configuration routes through us, because a schema
 * change regenerates prompt hints and needs a regression run. There is no Apply and no
 * Undo here and there must not be one: both are ADMIN-realm routes
 * (`publishing_routes.py`), `agents:write` is held by `operator`/`superadmin` and by
 * NEITHER client role (core/rbac.py), and D-22 refuses every mutating permission to an
 * impersonating operator — so every session that can reach this screen would be refused
 * the click. "You cannot apply what you cannot write": the staged script is authored
 * admin-realm, so a client Apply would publish a draft they had no way to author. The
 * screen names who does it instead. That is also why no `useWriteAccess` call appears
 * below — it gates a control, and the honest answer here is to have none.
 *
 * The migration to the console's design language (globals.css tokens, `Card`, lucide
 * medallions) came with an honesty pass. What was wrong before, in falling order of
 * what it cost:
 *
 * - **The banner could be read as saying callers hear the STAGED script.** "Callers
 *   still hear the version above" sat under a list whose top line is the WAITING
 *   version — the exact inversion `agents/publishing.py` opens by describing, in the
 *   one place a client checks what their phone line is currently saying. Both pointers
 *   are now rendered from `live_version`/`staged_version` as labelled data, so the
 *   distinction is structural rather than a sentence that has to be parsed correctly.
 * - **"Always asked" on a required capture field.** `required` means the post-call
 *   extraction must produce that field (`packages/shared/.../extraction.py`), not that
 *   the agent interrogates every caller for it — and the paragraph two lines below
 *   promised the opposite ("it never reads a form aloud"). One card, two claims.
 * - **Money bypassed `formatINR`.** `₹${state.worst_case_call_cost_inr}` printed the
 *   raw wire string, so ₹1,500.00 rendered as "₹1500.00" and a rate of "6.5" as "₹6.5".
 *   `formatINR` groups Indian-style and never parses the digits (hard rule 7).
 * - **An unknown lane was announced as immediate.** The split was `staged` vs
 *   everything-else, so a lane value this build has never seen would have been promised
 *   to a client as "applies straight away" — the dangerous direction to guess in.
 * - **"What callers hear right now" was said about agents no caller can reach.** An
 *   unpublished agent is not on the calling system at all.
 * - The page rendered its own `<h1>`; the shell prints "Voice agents" from the nav list
 *   (layout.tsx), and two headings saying one thing is where the drift starts.
 *
 * EVERY number and label here is the server's or is absent: the call cap, its bounds,
 * the worst-case cost, the version numbers and the lane table all come from
 * `GET /v1/agents/lanes` and `GET /v1/agents/{id}/pending`. Loading is a `Skeleton`,
 * failure is a `ProblemNotice`, and neither is ever a zero.
 */

/**
 * Direction in the owner's terms, with the icon that carries the meaning. "Inbound" and
 * "outbound" are OUR nouns; a clinic owner thinks "does it pick up, or does it ring
 * people?". The icon replaces the old text glyphs (↓ ↑ ↕) — it is the one place on the
 * card where a picture says the fact faster than the words do.
 */
const DIRECTION_COPY: Record<
  string,
  { Icon: typeof PhoneCall; label: string; hint: string }
> = {
  inbound: {
    Icon: PhoneIncoming,
    label: "Answers calls",
    hint: "Picks up when someone rings your number.",
  },
  outbound: {
    Icon: PhoneOutgoing,
    label: "Makes calls",
    hint: "Dials your customers for campaigns and follow-ups.",
  },
  both: {
    Icon: PhoneCall,
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
 * The one question this screen exists to answer without a phone call to us: is this
 * thing live?
 *
 * "Live" needs BOTH facts to line up — the agent has been created on the calling system
 * (`published`) AND its status says live. That is the same test the prompt publisher
 * applies server-side (`_is_live` in apps/api/agents/prompts.py) and the same one the
 * Leads table calls dialable (`canDial`, which adds "and can dial out at all"), so the
 * three cannot disagree about one agent. `published` is checked first because nothing
 * else matters until it is true: an agent that does not exist on the calling system
 * cannot ring, whatever its status column says.
 *
 * Tones are the design tokens, not a fifth colour table: brand-soft for live (the
 * console's one "this is working" colour) and the neutral surface for the two waits.
 * Paused borrows `NOTICE_TONES.warn` rather than re-picking an amber — it is the one
 * state a client may want to act on, which is exactly what that tone already means
 * everywhere else in this app.
 */
function liveState(agent: Agent): { label: string; tone: string; detail: string } {
  if (!agent.published) {
    return {
      label: "Being set up",
      tone: "border-line bg-app text-ink-muted",
      detail:
        "Not on the calling system yet, so it cannot take or make calls. Your account manager finishes this before your first call.",
    };
  }
  if (agent.status === "paused") {
    return {
      label: "Paused",
      tone: NOTICE_TONES.warn,
      detail: "Switched off for now. No calls are being answered or made by this agent.",
    };
  }
  if (agent.status === "live") {
    return {
      label: "Live",
      tone: "border-brand-soft bg-brand-soft text-brand-strong",
      detail: "On the calling system and working right now.",
    };
  }
  return {
    label: "Ready, not switched on",
    tone: "border-line bg-app text-ink-muted",
    detail: "Built and on the calling system, waiting to be switched on.",
  };
}

export default function AgentsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = useClientSession();
  const agents = useAgents(session);

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        The phone agents working for your business: what each one does, what it says about
        itself, and what it writes down. Your account manager sets these up and makes any
        changes.
      </p>

      {agents.error && <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />}

      {agents.isLoading ? (
        <Card bodyClassName="p-4">
          <Skeleton rows={6} />
        </Card>
      ) : agents.data?.length ? (
        <div className="space-y-5">
          {agents.data.map((agent) => (
            <AgentCard key={agent.id} agent={agent} slug={slug} />
          ))}
        </div>
      ) : agents.data ? (
        /* Only where the server SAID so. A failed request leaves this branch unreached,
           because "you have no agents" is a claim about the client's business and the
           notice above is the whole answer we are entitled to give. */
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
          would train people to stop reading it. Only worth showing next to agents, so it
          renders under an empty list not at all. */}
      {agents.data?.length ? <HowChangesTakeEffect session={session} /> : null}
    </div>
  );
}

function AgentCard({ agent, slug }: { agent: Agent; slug: string }) {
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { href } = useClientRealm();
  const live = liveState(agent);
  // `direction`, `status` and `language_primary` are all bare `string` on `AgentOut` —
  // the API narrowed none of them — so all three are wire values reaching a copy table.
  const direction = lookup(DIRECTION_COPY, agent.direction) ?? {
    Icon: PhoneCall,
    label: agent.direction.replace(/_/g, " "),
    hint: "",
  };
  const status = lookup(STATUS_COPY, agent.status) ?? {
    label: agent.status.replace(/_/g, " "),
    hint: "",
  };
  // Bound to a capitalised name before use: `<direction.Icon />` is legal JSX, but the
  // repo already reads component-from-a-table this way (calls/page.tsx).
  const DirectionIcon = direction.Icon;
  const hasRequired = agent.extraction_fields.some((field) => field.required);

  return (
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

        {/* The four facts a client should never have to ask us for. `status` and "on the
            calling system" are shown separately rather than collapsed into the badge: an
            agent switched on but not yet built is a different wait from one built but not
            switched on, and only we can tell them apart. */}
        <dl className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="What it does" hint={direction.hint}>
            <span className="flex items-center gap-2">
              <DirectionIcon aria-hidden className="h-4 w-4 shrink-0 text-brand" />
              {direction.label}
            </span>
          </Fact>
          <Fact label="Speaks" hint="The language it greets and answers callers in.">
            {lookup(LANGUAGE_NAMES, agent.language_primary) ?? agent.language_primary}
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

        <PublishingPanel agent={agent} />

        {/* Rendered as the sentence it is, not as a config value: this is spoken aloud,
            and reading it in quotes is how a client notices the business name or the
            purpose is wrong. Not framed as their choice — we write it to satisfy the
            disclosure rule — but it is theirs to check. It is READ-ONLY here, which is
            also how hard rule 5 is kept: a screen with no editor has no way to empty a
            line the law requires. */}
        <section>
          <SectionHeading icon={<ShieldCheck className="h-3.5 w-3.5" />}>
            What it says at the start of every call
          </SectionHeading>
          {agent.disclosure_line.trim() ? (
            <blockquote className="mt-2 border-l-2 border-brand pl-3 text-sm italic text-ink">
              “{agent.disclosure_line}”
            </blockquote>
          ) : (
            /* The column is `NOT NULL` with `length(disclosure_line) > 0`
               (agents/models.py, `disclosure_nonempty`) — which whitespace satisfies.
               A blank quote would read as "the agent says nothing", the one failure
               here that must not be silent (hard rule 5). */
            <p
              className={`mt-2 flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES.stop}`}
            >
              <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                This agent has no opening line on file. Tell your account manager before it
                takes a call — every call has to open by announcing itself.
              </span>
            </p>
          )}
          <p className="mt-2 text-xs text-ink-muted">
            Every call opens with this line, spoken under your business name. Callers are
            told they are speaking to an AI assistant before anything else happens. If
            anything in it is wrong, tell your account manager — it cannot be removed.
          </p>
        </section>

        <section>
          <SectionHeading icon={<ListChecks className="h-3.5 w-3.5" />}>
            What it writes down
          </SectionHeading>
          {agent.extraction_fields.length > 0 ? (
            <>
              <ul className="mt-2 divide-y divide-line">
                {agent.extraction_fields.map((field) => (
                  <FieldRow key={field.key} field={field} />
                ))}
              </ul>
              <p className="mt-2 text-xs text-ink-muted">
                These are the columns in your{" "}
                <Link
                  href={href(`/c/${slug}/leads`)}
                  className="font-medium underline underline-offset-2 hover:text-ink"
                >
                  Leads
                </Link>{" "}
                table. The agent fills them in from the conversation — it never reads a
                form aloud, so a caller who answers early is not asked twice.
                {hasRequired && (
                  <>
                    {" "}
                    {/* What `required` actually does: it marks the field REQUIRED in the
                        extraction instruction and, when the call ends without it, the
                        value is dropped and the extraction is recorded as incomplete
                        (packages/shared/.../extraction.py). The old badge said "Always
                        asked", which promised an interrogation this product deliberately
                        does not do — and contradicted the sentence right above it. */}
                    The ones marked <span className="font-medium text-ink">Required</span>{" "}
                    are what the agent is told to capture on every call; a call that ends
                    without one still becomes a lead, with that column left empty.
                  </>
                )}
              </p>
            </>
          ) : (
            <p className="mt-2 text-sm text-ink-muted">
              Nothing extra yet. Calls still turn into leads with the caller name, number
              and a summary — this agent just does not capture any business-specific
              details on top of that.
            </p>
          )}
        </section>
      </div>
    </Card>
  );
}

/**
 * The unsaved-changes banner (§2b) and the cost-runaway guard, from the client's side of
 * the fence.
 *
 * `headline` and `why` are rendered as sent. The server composes them from version
 * NUMBERS (a prompt body carries the client's prices and staff names — hard rule 6), and
 * restating them here would be a second source for one sentence.
 *
 * Takes the whole `agent` rather than an id: `PendingOut` carries `published` and
 * `agent_status` too, and reading THOSE here would give one card two sources for one
 * fact — the badge above says "Being set up" from the roster while this paragraph could
 * say the opposite from a response that landed a second later. The roster row is the
 * card's single source; the pending read supplies only what the roster does not have.
 */
function PublishingPanel({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const pending = usePendingChanges(session, agent.id);

  if (pending.isLoading) return <Skeleton rows={2} />;
  if (pending.error) {
    return <ProblemNotice error={pending.error} onRetry={() => void pending.refetch()} />;
  }
  if (!pending.data) return null;

  const state = pending.data;

  return (
    <div className="space-y-3">
      {state.has_pending ? (
        <div role="status" className={`rounded-card border p-4 text-sm ${NOTICE_TONES.warn}`}>
          <p className="flex items-center gap-2 font-semibold">
            <Hourglass aria-hidden className="h-4 w-4 shrink-0" />
            Changes waiting to go live
          </p>
          <ul className="mt-3 space-y-3">
            {state.pending.map((change) => (
              <PendingRow key={change.field} change={change} />
            ))}
          </ul>
          <p className="mt-3 text-xs">
            {/* NOT "the version above": the line above is the WAITING one, and this
                sentence used to sit under it saying callers hear it. Which pointer is
                which is rendered as data in `PendingRow`; this sentence only says who
                moves it. */}
            Callers keep hearing the live version until your account manager applies the
            change — nothing goes live silently. Ask them to apply it, or to discard it if
            it was not meant to happen.
          </p>
        </div>
      ) : (
        /* The reassuring case is worth a line: an owner who has been told an edit was
           made needs to be able to see that it HAS landed, not just infer it from the
           absence of a warning. It says something different for an agent no caller can
           reach yet — "what callers hear right now" is not a true sentence about an
           agent that is not on the calling system. */
        <p className="text-sm text-ink-muted">
          {agent.published
            ? "Nothing is waiting to go live — what is described on this page is what callers hear right now."
            : "Nothing is waiting to go live. This agent is not on the calling system yet, so no caller hears it at all."}
        </p>
      )}

      {/* The cost-runaway guard, as the question it actually answers: what is the worst
          one call can do to my bill. */}
      <dl className="grid gap-5 rounded-card border border-line bg-app p-4 sm:grid-cols-2">
        <Fact
          label="Longest one call may run"
          icon={<Timer className="h-3.5 w-3.5" />}
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
          icon={<IndianRupee className="h-3.5 w-3.5" />}
          hint={
            state.worst_case_call_cost_inr === null
              ? "Your plan does not quote a per-minute rate, so we cannot put a number on it. Your account manager can."
              : "A call that runs the full limit, at your plan's per-minute rate. Almost every call ends long before this."
          }
        >
          {/* Null is "we cannot say", NOT zero — quoting ₹0.00 for a ten-minute call is
              the one answer that is actively wrong (`publishing.py::_overage_rate`). The
              figure is an exact NUMERIC and stays a STRING all the way here: `formatINR`
              formats the digits and never parses them, because `Number("10159.00")` is
              how ₹10,159.00 becomes ₹10,158.999999999998 (hard rule 7). */}
          {state.worst_case_call_cost_inr === null
            ? "We cannot say yet"
            : formatINR(state.worst_case_call_cost_inr)}
        </Fact>
      </dl>
    </div>
  );
}

/**
 * One staged change, with BOTH pointers named.
 *
 * The two-speed model has exactly one way to be catastrophically misread — showing the
 * staged script as the one callers hear — and `agents/publishing.py` opens by recording
 * that the backend shipped that inversion once already. So the pointers are rendered as
 * labelled DATA (`live_version`, `staged_version`) rather than left to the prose: a
 * sentence can be read the wrong way round, a two-item list under "Callers hear now" and
 * "Waiting to be applied" cannot. It also covers what the server's headline leaves out —
 * `live_version` is null for an agent whose script has never been applied, and the
 * headline simply omits the clause.
 */
function PendingRow({ change }: { change: PendingChange }) {
  return (
    <li className="border-l-2 border-amber-400 pl-3">
      <p className="font-medium">{change.headline}</p>
      <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-wide opacity-70">
            Callers hear now
          </dt>
          <dd className="text-sm font-semibold tabular-nums">
            {change.live_version === null ? "Nothing live yet" : `v${change.live_version}`}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-wide opacity-70">
            Waiting to be applied
          </dt>
          <dd className="text-sm font-semibold tabular-nums">v{change.staged_version}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs">{change.why}</p>
      <p className="mt-1 text-xs opacity-80">Waiting since {formatIST(change.staged_at)}</p>
    </li>
  );
}

/**
 * "Script decides content, rules decide conduct, voice only changes delivery" — and
 * which settings sit on which side of the Apply step.
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
   * Three buckets, not two. `lane` is a bare `string` on the wire and the server's
   * `Lane` literal has two members TODAY; the old split was `staged` versus
   * everything-else, so a third lane shipped by the API would have been announced to a
   * client as "applies straight away, nothing to approve" — a promise about their live
   * phone line, made about a value this build has never seen. Unknown fails VISIBLE and
   * claims nothing, the same direction the campaign hold and the ops queue fail in.
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
      <SectionHeading icon={icon}>{title}</SectionHeading>
      <p className="mt-1 text-xs text-ink-muted">{hint}</p>
      <ul className="mt-3 space-y-3">
        {lanes.map((lane) => (
          <li key={lane.field}>
            <p className="text-sm font-medium text-ink">
              {/* Fails VISIBLE: an unnamed lane degrades to its own field name rather
                  than vanishing, per FIELD_LABELS above. `lookup` is what makes the `??`
                  reachable — a bare index on a prototype key returns a function, which is
                  not nullish, so the fallback never fired (lib/lookup.ts). */}
              {lookup(FIELD_LABELS, lane.field) ?? lane.field.replace(/_/g, " ")}
            </p>
            <p className="text-xs text-ink-muted">{lane.why}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * "10 minutes", "5 min 30 s" — a call cap in the units an owner thinks in.
 *
 * `formatDuration` in components/ui is for how long a call ACTUALLY ran and reads as a
 * stopwatch (`10:00`); a ceiling reads as a sentence. Two formats because they answer two
 * different questions, not because one was forgotten.
 */
function formatCallCap(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes === 0) return `${rest} seconds`;
  if (rest === 0) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  return `${minutes} min ${rest} s`;
}

/**
 * The label over a block, with the medallion the design puts on a section marker.
 *
 * Local to this screen for now — it is the `StatTile` medallion idiom applied to a
 * heading, and the other migrated screens have no sections to head. It belongs in
 * `components/ui.tsx` the moment a second screen wants one.
 */
function SectionHeading({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
        {icon}
      </span>
      {children}
    </h3>
  );
}

/** One labelled fact. `dt`/`dd` because that is exactly what these are. */
function Fact({
  label,
  hint,
  icon,
  children,
}: {
  label: string;
  hint?: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        {icon && (
          <span aria-hidden className="shrink-0 text-brand">
            {icon}
          </span>
        )}
        {label}
      </dt>
      <dd className="mt-1 text-sm font-semibold text-ink">{children}</dd>
      {hint && <dd className="mt-0.5 text-xs text-ink-muted">{hint}</dd>}
    </div>
  );
}

/**
 * One captured field, shown as the CRM column it becomes. The label leads, because that
 * is the word the client sees on the Leads table; the key is not shown at all — it is our
 * storage detail, and two names for one column is one too many.
 */
function FieldRow({ field }: { field: AgentExtractionField }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 py-2.5">
      <span className="text-sm font-medium text-ink">{field.label}</span>
      <span className="rounded bg-app px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
        {/* `ExtractionField.type` IS a generated union, but the union is a compile-time
            claim about a runtime string: the server can widen the enum without this build
            being rebuilt, and then the fallback is the only thing rendering. */}
        {lookup(FIELD_TYPE_COPY, field.type) ?? field.type}
      </span>
      {field.required && (
        <span className="rounded bg-brand-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-strong">
          Required
        </span>
      )}
      {field.description && (
        <span className="w-full text-xs text-ink-muted">{field.description}</span>
      )}
      {field.enum_values?.length ? (
        <span className="w-full text-xs text-ink-muted">
          One of: {field.enum_values.join(" · ")}
        </span>
      ) : null}
    </li>
  );
}
