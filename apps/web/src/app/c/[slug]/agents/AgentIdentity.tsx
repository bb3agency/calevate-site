"use client";

/**
 * The fields that describe WHAT an agent is — its name, which way its calls go, and the
 * languages it replies in (its main language first, D-815).
 *
 * ## Why these three are a client's and the rest of the configuration is not
 *
 * D-21's boundary is about what an agent SAYS and what it CAPTURES: a script change or an
 * extraction-schema change regenerates prompt hints and needs a regression run against
 * real calls, so both route through us. None of the three below does. They are the
 * object's own description, and they are exactly what `lifecycle.update_agent` accepts.
 *
 * ## Two things the server does that this form must not describe as a column write
 *
 * - **A LIVE agent is republished in the same transaction.** All three ride on
 *   `AgentConfig` and reach the vendor's agent object, so the row write happens first and
 *   the engine push second — a vendor failure rolls the row back with it, and our record
 *   never claims a configuration the engine was not sent. That is why saving on a live
 *   agent can fail, and why the failure is rendered rather than swallowed.
 * - **Direction rings a phone.** Republishing runs `route_inbound_numbers`, which BINDS
 *   this agent's numbers when it answers inbound and RELEASES them when it does not — so
 *   moving a "both" agent to outbound genuinely stops it picking up. The hint says so,
 *   because a client who thinks this only changes a label will change it on a Friday.
 *
 * A DELETED (archived) agent is refused by the server (`agent_archived`), on the grounds that
 * editing what a retired agent *is* changes a record somebody may be reading as evidence
 * of what it was. So the form is not rendered at all for one — a disabled form whose
 * every input is dead is worse than a sentence saying why there is none.
 */

import { useState } from "react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  ProblemNotice,
  RestrictionNote,
} from "@/components/ui";
import { SaveBar } from "@/components/console/saveBar";
import { useFormValidation } from "@/components/formValidation";
import { LANGUAGE_CHOICES, LANGUAGE_NAMES, isDeleted } from "@/lib/agentState";
import {
  useUpdateAgent,
  type Agent,
  type AgentDirection,
  type AgentLanguage,
  type AgentUpdateIn,
} from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { hasKey } from "@/lib/lookup";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { DIRECTIONS, DirectionPicker } from "./DirectionChoice";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

export function AgentIdentity({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const save = useUpdateAgent(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change this agent's details");

  const [name, setName] = useState(agent.name);
  const valid = useFormValidation();
  /* `AgentOut.direction` is the SAME generated union `AgentUpdateIn` accepts (D-440 typed
     both columns), so the current value needs no narrowing on the way in or out. It was
     `string` on both sides until that change, and a widened value would have had to be
     rejected here rather than pre-selected. */
  const [direction, setDirection] = useState<AgentDirection>(agent.direction);
  /* `AgentOut.language_primary` is a bare `str` on the wire while `AgentUpdateIn` accepts
     a closed union, so the stored value is NARROWED on the way in. `null` means "the agent
     speaks a language this build cannot offer" — its own code is still shown as the
     selected option below, and the patch simply never names the field, so opening this
     screen cannot silently change it. */
  const [language, setLanguage] = useState<AgentLanguage | null>(
    hasKey(LANGUAGE_NAMES, agent.language_primary) ? agent.language_primary : null,
  );
  /* The other languages it replies in (D-815), in the order the server holds them. The
     main language is always first on the wire, so it is never also one of these. */
  const storedExtras = agent.reply_languages.slice(1);
  const [extras, setExtras] = useState<AgentLanguage[]>(storedExtras);
  const mainLanguage = language ?? agent.language_primary;
  const shownExtras = extras.filter((tag) => tag !== mainLanguage);

  useCopilotSurface(
    isDeleted(agent)
      ? null
      : {
          route: "/c/{slug}/agents/{id}",
          title: "Agent: what it is",
          realm: "client",
          fields: [
            { id: "agent-name", label: "Name (only you see it)", type: "text", value: name },
            {
              id: "agent-direction",
              label: "What it does",
              type: "select",
              value: direction,
              options: DIRECTIONS.map((d) => ({ value: d.value, label: d.label })),
              help: "Changing this on a switched-on agent changes which numbers it answers.",
            },
            {
              id: "agent-language",
              label: "Language",
              type: "select",
              value: language ?? agent.language_primary,
              options: LANGUAGE_CHOICES.map((c) => ({ value: c.value, label: c.label })),
            },
          ],
          facts: [{ key: "agent_id", label: "Agent id", value: agent.id }],
          apply: (items) => {
            for (const item of items) {
              const value = asText(item.value);
              if (item.field_id === "agent-name" && value.trim()) setName(value);
              const dir = DIRECTIONS.find((d) => d.value === value);
              if (item.field_id === "agent-direction" && dir) setDirection(dir.value);
              if (item.field_id === "agent-language" && hasKey(LANGUAGE_NAMES, value)) setLanguage(value);
            }
          },
        },
  );

  /**
   * ONLY what moved. The API treats an omitted field as "leave this alone", which is what
   * stops two edits on one screen racing each other into a read-modify-write — and it
   * refuses a body that names nothing (`agent_update_empty`), which is why there is no
   * save until something differs.
   */
  const patch: AgentUpdateIn = {};
  if (name.trim() && name !== agent.name) patch.name = name.trim();
  if (direction !== agent.direction) patch.direction = direction;
  const languagesMoved =
    mainLanguage !== agent.language_primary || shownExtras.join() !== storedExtras.join();
  if (languagesMoved) patch.reply_languages = [mainLanguage, ...shownExtras];
  const changed = Object.keys(patch).length > 0;
  useUnsavedGuard(changed && !isDeleted(agent));

  if (isDeleted(agent)) {
    return (
      <p className="text-sm text-ink-muted">
        This agent is deleted, so its details are kept exactly as they were, as part
        of the record of what it did. Bring it back first if you want to change them.
      </p>
    );
  }

  return (
    <form
      className="space-y-6"
      noValidate
      onSubmit={valid.onSubmit(() => {
        if (!changed) return;
        save.mutate(patch);
      })}
    >
      <RestrictionNote reason={write.reason} />
      {save.error && <ProblemNotice error={save.error} />}

      {/* The message sits outside the wrapping `<label>`: enclosed, it would be read
          back as part of the field's name instead of as its description. */}
      <div className="max-w-sm">
        <label className="block">
          <span className={FIELD_LABEL}>Name</span>
          <input
            {...valid.field("name", "Give this agent a name.")}
            required
            minLength={2}
            maxLength={80}
            value={name}
            onChange={(event) => setName(event.target.value)}
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            Only you see this. It is how you tell your agents apart here and on your call
            log. Callers never hear it.
          </span>
        </label>
        {valid.error("name")}
      </div>

      <fieldset>
        <legend className={FIELD_LABEL}>What it does</legend>
        <DirectionPicker name={`direction-${agent.id}`} value={direction} onChange={setDirection} />
        <p className={FIELD_HINT}>
          This is not just a label. If it is switched on, changing this takes effect on your
          phone line: an agent that no longer answers calls stops picking up the numbers it
          was answering.
        </p>
      </fieldset>

      <label className="block max-w-sm">
        <span className={FIELD_LABEL}>Main language</span>
        <select
          value={language ?? agent.language_primary}
          onChange={(event) => {
            if (hasKey(LANGUAGE_NAMES, event.target.value)) setLanguage(event.target.value);
          }}
          className={FIELD}
        >
          {/* The current value is offered even when it is not one this build names, so a
              language added or retired by the API is not silently changed by opening this
              screen. Choosing it back is a no-op: `language` stays null and the patch never
              names the field. */}
          {language === null && (
            <option value={agent.language_primary}>{agent.language_primary}</option>
          )}
          {LANGUAGE_CHOICES.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
        <span className={FIELD_HINT}>
          The language it greets callers in, and the one it falls back to when it cannot
          tell which language a caller is speaking. Its script and the two things it
          announces at the start of a call are written in this language.
        </span>
      </label>

      <fieldset>
        <legend className={FIELD_LABEL}>It also replies in</legend>
        <div className="mt-2 space-y-2">
          {LANGUAGE_CHOICES.filter((choice) => choice.value !== mainLanguage).map((choice) => (
            <label key={choice.value} className="flex items-center gap-2 text-sm text-ink touch:min-h-11">
              <input
                type="checkbox"
                checked={shownExtras.includes(choice.value)}
                onChange={(event) =>
                  setExtras(
                    event.target.checked
                      ? [...shownExtras, choice.value]
                      : shownExtras.filter((tag) => tag !== choice.value),
                  )
                }
              />
              {choice.label}
            </label>
          ))}
        </div>
        <p className={FIELD_HINT}>
          A caller who speaks one of these is answered in it. Leave them all unticked and it
          answers in its main language only.
        </p>
      </fieldset>

      {(changed || save.isPending) && (
        <SaveBar
          label="Save changes"
          saving={save.isPending}
          disabled={!write.allowed}
          title={write.reason ?? undefined}
          onCancel={() => {
            setName(agent.name);
            setDirection(agent.direction);
            setLanguage(hasKey(LANGUAGE_NAMES, agent.language_primary) ? agent.language_primary : null);
            setExtras(storedExtras);
          }}
        />
      )}
    </form>
  );
}
