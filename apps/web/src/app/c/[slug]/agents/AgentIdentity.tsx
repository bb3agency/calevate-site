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

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NOTICE_BAR,
  NOTICE_BASE,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import { SaveBar } from "@/components/console/saveBar";
import { useFormValidation } from "@/components/formValidation";
import { LANGUAGE_NAMES, isDeleted } from "@/lib/agentState";
import { useAgentLanguageChoices } from "@/lib/api/agentLanguages";
import {
  useUpdateAgent,
  type Agent,
  type AgentDirection,
  type AgentLanguage,
  type AgentUpdateIn,
} from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useRewriteOpeningInLanguage } from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";
import { hasKey, lookup } from "@/lib/lookup";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { DIRECTIONS, DirectionPicker } from "./DirectionChoice";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

export function AgentIdentity({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const languageChoices = useAgentLanguageChoices(session);
  const save = useUpdateAgent(session, agent.id);
  const rewrite = useRewriteOpeningInLanguage(session, agent.id);
  /* The save bar leaves the screen once nothing differs, so its button cannot carry the
     success: that is a toast, except after a main-language change, whose offer below says it. */
  const saveFeedback = useActionFeedback(save, {
    errorDisplay: "inline",
    successToast: (_, vars) =>
      vars.reply_languages && vars.reply_languages[0] !== agent.language_primary ? null : "Changes saved",
  });
  const rewriteFeedback = useActionFeedback(rewrite, { errorDisplay: "inline" });
  /* After a main-language change is saved: the language whose ready-made opening line is
     offered, until the owner takes it or closes the offer (D-838). */
  const [rewriteOffer, setRewriteOffer] = useState<string | null>(null);
  const write = useWriteAccess(session, "org:manage", "change this agent's details");

  /* Each field holds only the owner's EDIT (`null` = untouched) and shows the server's
     value otherwise. Seeded copies went stale when the agent was changed elsewhere (Pip's
     rename, another tab): the screen showed unsaved changes nobody made, and the next save
     wrote the old value back over the newer one. */
  const [nameEdit, setName] = useState<string | null>(null);
  const name = nameEdit ?? agent.name;
  const valid = useFormValidation();
  /* `AgentOut.direction` is the SAME generated union `AgentUpdateIn` accepts (D-440 typed
     both columns), so the current value needs no narrowing on the way in or out. It was
     `string` on both sides until that change, and a widened value would have had to be
     rejected here rather than pre-selected. */
  const [directionEdit, setDirection] = useState<AgentDirection | null>(null);
  const direction = directionEdit ?? agent.direction;
  /* `AgentOut.language_primary` is a bare `str` on the wire while `AgentUpdateIn` accepts
     a closed union, so the stored value is NARROWED on the way in. `null` means "the agent
     speaks a language this build cannot offer" — its own code is still shown as the
     selected option below, and the patch simply never names the field, so opening this
     screen cannot silently change it. */
  const [languageEdit, setLanguage] = useState<AgentLanguage | null>(null);
  const language =
    languageEdit ?? (hasKey(LANGUAGE_NAMES, agent.language_primary) ? agent.language_primary : null);
  /* The other languages it replies in (D-815), in the order the server holds them. The
     main language is always first on the wire, so it is never also one of these. */
  const storedExtras = agent.reply_languages.slice(1);
  const [extrasEdit, setExtras] = useState<AgentLanguage[] | null>(null);
  const extras = extrasEdit ?? storedExtras;
  const clearEdits = () => {
    setName(null);
    setDirection(null);
    setLanguage(null);
    setExtras(null);
  };
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
              options: languageChoices.map((c) => ({ value: c.value, label: c.label })),
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
        Deleted. Bring it back to change these.
      </p>
    );
  }

  return (
    <form
      className="space-y-6"
      noValidate
      onSubmit={valid.onSubmit(() => {
        if (!changed) return;
        const newMain = mainLanguage !== agent.language_primary ? mainLanguage : null;
        save.mutate(patch, {
          onSuccess: () => {
            // The saved values are the server's now; the agent read shows them.
            clearEdits();
            if (newMain !== null) {
              rewrite.reset();
              setRewriteOffer(newMain);
            }
          },
        });
      })}
    >
      <RestrictionNote reason={write.reason} />
      {save.error && <ProblemNotice error={save.error} />}
      {rewriteOffer !== null && (
        <OpeningLineOffer
          language={rewriteOffer}
          rewrite={rewrite}
          rewriteStatus={rewriteFeedback.status}
          canWrite={write.allowed}
          onDismiss={() => setRewriteOffer(null)}
        />
      )}

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
            Only you see this. Callers never hear it.
          </span>
        </label>
        {valid.error("name")}
      </div>

      <fieldset>
        <legend className={FIELD_LABEL}>What it does</legend>
        <DirectionPicker name={`direction-${agent.id}`} value={direction} onChange={setDirection} />
        <p className={FIELD_HINT}>
          On a live agent, this changes which numbers it answers.
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
          {!languageChoices.some((choice) => choice.value === mainLanguage) && (
            <option value={mainLanguage}>{lookup(LANGUAGE_NAMES, mainLanguage) ?? mainLanguage}</option>
          )}
          {languageChoices.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
        <span className={FIELD_HINT}>
          Its notices switch to it. Your script is not translated.
        </span>
      </label>

      <fieldset>
        <legend className={FIELD_LABEL}>It also replies in</legend>
        <div className="mt-2 space-y-2">
          {languageChoices.filter((choice) => choice.value !== mainLanguage).map((choice) => (
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
          Callers who speak these are answered in them.
        </p>
      </fieldset>

      {(changed || save.isPending) && (
        <SaveBar
          label="Save changes"
          status={saveFeedback.status}
          disabled={!write.allowed}
          title={write.reason ?? undefined}
          onCancel={clearEdits}
        />
      )}
    </form>
  );
}

/**
 * The one-click rewrite offered after the main language changed (D-838). The notices are
 * already rewritten by the server; the opening line is the owner's own words, so it is only
 * offered: the ready-made greeting in the new language goes into the script draft, and
 * callers keep the live one until it is put live.
 */
function OpeningLineOffer({
  language,
  rewrite,
  rewriteStatus,
  canWrite,
  onDismiss,
}: {
  language: string;
  rewrite: ReturnType<typeof useRewriteOpeningInLanguage>;
  rewriteStatus: FeedbackStatus;
  canWrite: boolean;
  onDismiss: () => void;
}) {
  const name = hasKey(LANGUAGE_NAMES, language) ? LANGUAGE_NAMES[language] : language;
  if (rewrite.data) {
    return (
      <div role="status" className={`${NOTICE_BASE} ${NOTICE_BAR.ok}`}>
        <p>
          The opening line in your draft is now: “{rewrite.data.opening_line}”. Review it on the
          Script tab, then put it live.
        </p>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDismiss}>
          Done
        </button>
      </div>
    );
  }
  return (
    <div role="status" className={`${NOTICE_BASE} ${NOTICE_BAR.neutral}`}>
      <p>
        Saved. Its notices are now in {name}. Your opening line is unchanged.
      </p>
      {rewrite.error ? <ProblemNotice error={rewrite.error} /> : null}
      <div className="flex flex-wrap gap-2 pt-1">
        <ActionButton
          variant="secondary-sm"
          status={rewriteStatus}
          pendingLabel="Writing it…"
          successLabel="Written"
          disabled={!canWrite}
          onClick={() => rewrite.mutate()}
        >
          {`Use a ready-made opening line in ${name}`}
        </ActionButton>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDismiss}>
          Keep mine
        </button>
      </div>
    </div>
  );
}
