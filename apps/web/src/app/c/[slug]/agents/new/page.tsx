"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, ShieldCheck, Sparkles } from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NOTICE_TONES,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCallCap,
} from "@/components/ui";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import {
  useCreateAgent,
  type Agent,
  type AgentDirection,
  type AgentLanguage,
} from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useLanes } from "@/lib/api/publishing";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { hasKey } from "@/lib/lookup";

import { DirectionPicker } from "../DirectionChoice";

/**
 * Build an agent (D-440).
 *
 * ## What this form is allowed to ask, and what it deliberately does not
 *
 * Four fields, and they are the four `lifecycle.create_agent` takes: a name, which way its
 * calls go, the language it speaks, and how long one of its calls may run. Everything
 * else a person might expect on a "create agent" form is absent ON PURPOSE, and each
 * absence is a rule rather than a gap:
 *
 * - **No disclosure wording.** `create_agent` writes both sentences itself from the
 *   language templates with both toggles ON, and there is no argument to it that can
 *   produce an agent with no AI disclosure on file — which is what the dial gate reads and
 *   what the truthful answer needs something to say. The create form is the one place a
 *   client is not yet thinking about TRAI, and the compliance floor is not theirs to get
 *   wrong. The panel below states what the agent will be born saying, so nobody discovers
 *   it on a recording.
 * - **No script.** A new agent is a DRAFT with nothing to say, and that is the point of
 *   the state: `publish_agent` refuses an agent with no prompt version by name
 *   (`agent_has_no_script`), so it cannot be switched on until the script is written with
 *   your account manager. Seeding a placeholder would be a phone line saying something
 *   nobody wrote.
 * - **No capture columns and no voice.** Both are admin-realm (D-21): a schema change
 *   regenerates prompt hints and needs a regression run, and a voice change is an ear test
 *   we have to do. Offering either here would be a control that could only ever 403.
 *
 * ## §52 and the failure paths
 *
 * The call-cap bounds are the SERVER's (`GET /v1/agents/lanes`) — the input is not
 * rendered until they arrive, because a minimum and a maximum this build invented are two
 * numbers a client would be refused on. A creation that fails renders the API's own
 * problem with its remediation; a creation that succeeds does not bounce the browser
 * somewhere, it says what was made and what has to happen next, because "created" and
 * "able to take calls" are different facts and the gap between them is the thing a first
 * -time owner most needs explained.
 */
export default function NewAgentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = useClientSession();
  const { href } = useClientRealm();
  const lanes = useLanes(session);
  const create = useCreateAgent(session);

  /**
   * D-22 read-only, and the permission is the one the ROUTE requires — `org:manage`, the
   * OWNER's. `agents:write` is the neighbouring name and is the wrong one: it is admin-only
   * and neither client role holds it, so gating on it would disable this button for exactly
   * the person it was built for. An operator who followed "view as client" holds every read
   * on this screen and no write, so the button is disabled WITH the reason rather than left
   * to answer 403 after the click.
   */
  const write = useWriteAccess(session, "org:manage", "create an agent");

  const [name, setName] = useState("");
  const [direction, setDirection] = useState<AgentDirection>("inbound");
  const [language, setLanguage] = useState<AgentLanguage>("te-IN");
  const [capMinutes, setCapMinutes] = useState("");
  const [created, setCreated] = useState<Agent | null>(null);

  return (
    <div className="space-y-5 pb-12">
      <Link
        href={href(`/c/${slug}/agents`)}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        All agents
      </Link>

      {created ? (
        <CreatedPanel agent={created} slug={slug} />
      ) : (
        <>
          <RestrictionNote reason={write.reason} />
          {create.error && <ProblemNotice error={create.error} />}
          {lanes.error && (
            <ProblemNotice error={lanes.error} onRetry={() => void lanes.refetch()} />
          )}

          <Card title="Build an agent">
            <form
              className="space-y-6"
              onSubmit={(event) => {
                event.preventDefault();
                create.mutate(
                  {
                    name,
                    direction,
                    language_primary: language,
                    // Blank means "use the standard limit" — `null`, never 0 and never
                    // unlimited. The server resolves NULL to the platform default.
                    max_call_duration_s: capMinutes === "" ? null : Number(capMinutes) * 60,
                  },
                  { onSuccess: (agent) => setCreated(agent) },
                );
              }}
            >
              <label className="block max-w-sm">
                <span className={FIELD_LABEL}>What do you want to call it?</span>
                <input
                  required
                  minLength={2}
                  maxLength={80}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="e.g. Front desk"
                  className={FIELD}
                />
                <span className={FIELD_HINT}>
                  Only you see this name — it is how you tell your agents apart here and on
                  your call log. Callers never hear it.
                </span>
              </label>

              <fieldset>
                <legend className={FIELD_LABEL}>What should it do?</legend>
                <DirectionPicker name="direction" value={direction} onChange={setDirection} />
                <p className={FIELD_HINT}>
                  You can have several agents answering at once — each picks up its own
                  number, so an after-hours line and a sales line run side by side.
                </p>
              </fieldset>

              <label className="block max-w-sm">
                <span className={FIELD_LABEL}>What language does it speak?</span>
                <select
                  value={language}
                  /* NARROWED, never cast: `event.target.value` is a `string` and
                     `AgentCreateIn.language_primary` is a closed union. `hasKey` is the
                     repo's one way of turning the first into the second (src/lib/lookup.ts),
                     and it reads `Object.hasOwn` so a value of "constructor" is absent
                     rather than present-but-wrong. */
                  onChange={(event) => {
                    if (hasKey(LANGUAGE_NAMES, event.target.value)) {
                      setLanguage(event.target.value);
                    }
                  }}
                  className={FIELD}
                >
                  {Object.entries(LANGUAGE_NAMES).map(([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
                <span className={FIELD_HINT}>
                  The language it greets and answers callers in, and the language the two
                  things it announces at the start of a call are written in. You can change
                  it later on the agent&apos;s own screen.
                </span>
              </label>

              <CallCapField
                lanes={lanes}
                value={capMinutes}
                onChange={setCapMinutes}
              />

              <ComplianceFloor />

              <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
                <button
                  type="submit"
                  disabled={!write.allowed || create.isPending || name.trim().length < 2}
                  /* The reason travels WITH the control as well as sitting at the top of
                     the screen: a dead button whose explanation is off-screen on a phone is
                     the 403 this pattern exists to avoid shipping. */
                  title={write.reason ?? undefined}
                  className={PRIMARY_BUTTON}
                >
                  <Sparkles aria-hidden className="h-4 w-4" />
                  {create.isPending ? "Building…" : "Build this agent"}
                </button>
                <span className="text-xs text-ink-muted">
                  It is created switched off. Nothing rings anyone until it has a script and
                  you switch it on.
                </span>
              </div>
            </form>
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * The cost-runaway guard (SURFACES §2b), asked at creation in minutes.
 *
 * Every bound is the server's. The field does not render until `GET /v1/agents/lanes`
 * answers, because a minimum and a maximum this build invented are two numbers a client
 * would be refused on with no way to know why — and a blank input over a failed read would
 * silently create the agent on the platform default while looking like a choice.
 */
function CallCapField({
  lanes,
  value,
  onChange,
}: {
  lanes: ReturnType<typeof useLanes>;
  value: string;
  onChange: (next: string) => void;
}) {
  if (lanes.isLoading) return <Skeleton rows={2} />;
  // The refusal is rendered by the caller, above; there is nothing honest to put here.
  if (!lanes.data) return null;
  const { call_cap_default_s, call_cap_min_s, call_cap_max_s } = lanes.data;
  return (
    <label className="block max-w-sm">
      <span className={FIELD_LABEL}>Longest one call may run (optional)</span>
      <input
        type="number"
        inputMode="numeric"
        min={Math.ceil(call_cap_min_s / 60)}
        max={Math.floor(call_cap_max_s / 60)}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={String(Math.round(call_cap_default_s / 60))}
        className={FIELD}
      />
      <span className={FIELD_HINT}>
        In minutes. Leave it blank for the standard {formatCallCap(call_cap_default_s)}. It
        can be anywhere between {formatCallCap(call_cap_min_s)} and{" "}
        {formatCallCap(call_cap_max_s)}, and there is no way to remove it — it is what stops
        one stuck call running up a bill.
      </span>
    </label>
  );
}

/**
 * What every agent is born with, said before it is built rather than discovered after.
 *
 * Each sentence here is enforced server-side and can be pointed at: both notice lines are
 * written by `create_agent` from the language templates and are NOT NULL with non-empty
 * CHECK constraints (hard rule 5); both toggles start TRUE at the INSERT; and the truthful
 * answer is appended to every prompt by `compose_engine_prompt` and re-verified against
 * the engine on every publish and every drift sweep, so no column, config row or script
 * can withdraw it. Nothing on this panel is a claim this screen made up.
 */
function ComplianceFloor() {
  return (
    <div className={`rounded-card border p-4 ${NOTICE_TONES.neutral}`}>
      <p className="flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck aria-hidden className="h-4 w-4 shrink-0" />
        What it will say about itself
      </p>
      <ul className="mt-2 space-y-1.5 text-sm">
        <li>
          It starts every call by saying it is an AI assistant and that the call is being
          recorded. Both sentences are written for you in the language you chose.
        </li>
        <li>
          You can switch either announcement off later, per agent, on the agent&apos;s own
          screen — the two are separate obligations and are separately switchable.
        </li>
        <li>
          Whatever those switches say, it always answers honestly when a caller asks
          whether it is an AI or whether the call is recorded. That one cannot be switched
          off by you, by us, or by anything written in its script.
        </li>
      </ul>
    </div>
  );
}

/**
 * Created — and the gap between "created" and "taking calls", stated.
 *
 * The browser is deliberately not bounced to the new agent: a draft agent's screen is
 * mostly absences, and arriving on it with no explanation reads as a broken creation. This
 * says what exists now, what has to happen next, and offers both destinations.
 */
function CreatedPanel({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  return (
    <Card title={`${agent.name} is ready to be written`}>
      <div className="space-y-4">
        <p className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES.ok}`}>
          <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            The agent exists on your account as a draft. It is not on the calling system, so
            it is not answering or dialling anyone.
          </span>
        </p>

        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            What happens next
          </p>
          <ol className="mt-2 space-y-2 text-sm text-ink-muted">
            <li>
              <span className="font-medium text-ink">1. Its script gets written.</span> What
              it says, what it does when a caller asks for something you do not offer, how it
              books. Your account manager writes it with you.
            </li>
            <li>
              <span className="font-medium text-ink">2. You teach it what it knows.</span>{" "}
              Opening hours, prices, the questions callers actually ask — you can start
              adding those on its screen right now.
            </li>
            <li>
              <span className="font-medium text-ink">3. You switch it on.</span> That puts it
              on the calling system and it starts taking calls.
            </li>
          </ol>
        </div>

        <div className="flex flex-wrap gap-3">
          <Link href={href(`/c/${slug}/agents/${agent.id}`)} className={PRIMARY_BUTTON}>
            Open {agent.name}
            <ArrowRight aria-hidden className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </Card>
  );
}
