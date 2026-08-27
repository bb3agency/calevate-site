"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
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
import { useClientSession } from "@/lib/api/session";
import { hasKey } from "@/lib/lookup";

import { DIRECTIONS, DirectionPicker } from "../DirectionChoice";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { CallCapField, ComplianceFloor } from "./BuildAgentForm";
import { CreatedPanel } from "./CreatedPanel";

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
 *   (`agent_has_no_script`), so it cannot be switched on until its script is written in the
 *   builder — which is why "Write its script" is the primary action on the created panel
 *   below. Seeding a placeholder would be a phone line saying something nobody wrote.
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
export function BuildAgent({ slug }: { slug: string }) {
  const session = useClientSession();
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

  /*
   * THE BUILD-AN-AGENT FORM, DECLARED TO THE SCREEN ASSISTANT.
   *
   * Four loose `useState` scalars, so `apply` is four typed setter calls — the same path
   * every control on this form already takes, and nothing here goes near the DOM (the
   * direction picker is `sr-only` radios inside cards, which is precisely the shape
   * `lib/copilot/dom.ts` exists to warn about).
   *
   * Both enums are narrowed by a LOOKUP rather than a cast, for the reason the language
   * `onChange` beside them already states: `hasKey` is this repo's one way of turning a
   * string into a closed union, so a model naming a language this build does not ship
   * changes nothing instead of putting an unsubmittable value in the control.
   *
   * `null` once the agent exists — the success panel has no form on it, and a launcher
   * over a screen with nothing to fill in is the failure the dock refuses to ship.
   */
  useCopilotSurface(
    created !== null
      ? null
      : {
          route: `/c/${slug}/agents/new`,
          title: "Build an agent",
          realm: "client",
          fields: [
            {
              id: "new-agent-name",
              label: "What do you want to call it?",
              type: "text",
              value: name,
              help: "2-80 characters. Only the client sees it — callers never hear it.",
            },
            {
              id: "new-agent-direction",
              label: "What should it do?",
              type: "select",
              value: direction,
              options: DIRECTIONS.map((option) => ({
                value: option.value,
                label: `${option.label} — ${option.hint}`,
              })),
            },
            {
              id: "new-agent-language",
              label: "What language does it speak?",
              type: "select",
              value: language,
              options: Object.entries(LANGUAGE_NAMES).map(([code, label]) => ({
                value: code,
                label,
              })),
            },
            {
              id: "new-agent-cap",
              label: "Longest a single call may run (minutes)",
              type: "number",
              value: capMinutes,
              help: "Blank means the standard limit. It is a safety limit, not a target.",
            },
          ],
          apply: (items) => {
            for (const item of items) {
              const text = asText(item.value);
              if (item.field_id === "new-agent-name") setName(text);
              else if (item.field_id === "new-agent-cap") setCapMinutes(text);
              else if (item.field_id === "new-agent-language" && hasKey(LANGUAGE_NAMES, text)) {
                setLanguage(text);
              } else if (item.field_id === "new-agent-direction") {
                const option = DIRECTIONS.find((row) => row.value === item.value);
                if (option) setDirection(option.value);
              }
            }
          },
        },
  );

  return (
    <>
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
                  /* The copilot field id, which is what the "filled" outline is drawn
                     on. The wrapping label already associates the two. */
                  id="new-agent-name"
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
                  id="new-agent-language"
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
    </>
  );
}
