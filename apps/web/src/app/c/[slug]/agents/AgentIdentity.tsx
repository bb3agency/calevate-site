"use client";

/**
 * The three fields that describe WHAT an agent is — its name, which way its calls go, and
 * the language it speaks.
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
import { Save } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { LANGUAGE_NAMES, isDeleted } from "@/lib/agentState";
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

import { DirectionPicker } from "./DirectionChoice";

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

  if (isDeleted(agent)) {
    return (
      <p className="text-sm text-ink-muted">
        This agent is deleted, so its details are kept exactly as they were — they are part
        of the record of what it did. Bring it back first if you want to change them.
      </p>
    );
  }

  /**
   * ONLY what moved. The API treats an omitted field as "leave this alone", which is what
   * stops two edits on one screen racing each other into a read-modify-write — and it
   * refuses a body that names nothing (`agent_update_empty`), which is why the button is
   * dead until something differs.
   */
  const patch: AgentUpdateIn = {};
  if (name.trim() && name !== agent.name) patch.name = name.trim();
  if (direction !== agent.direction) patch.direction = direction;
  if (language !== null && language !== agent.language_primary) patch.language_primary = language;
  const changed = Object.keys(patch).length > 0;

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
            Only you see this — it is how you tell your agents apart here and on your call
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
        <span className={FIELD_LABEL}>Language</span>
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
          {Object.entries(LANGUAGE_NAMES).map(([code, label]) => (
            <option key={code} value={code}>
              {label}
            </option>
          ))}
        </select>
        <span className={FIELD_HINT}>
          The language it greets and answers callers in. Its script and the two things it
          announces at the start of a call are written in this language.
        </span>
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={!write.allowed || !changed || save.isPending}
          title={write.reason ?? undefined}
          className={PRIMARY_BUTTON}
        >
          <Save aria-hidden className="h-4 w-4" />
          {save.isPending ? "Saving…" : "Save changes"}
        </button>
        {!changed && !save.isPending && (
          <span className="text-xs text-ink-muted">Nothing has been changed yet.</span>
        )}
      </div>
    </form>
  );
}
