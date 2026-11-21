"use client";

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Field } from "@/components/arc/field";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD, FIELD_LABEL, ProblemNotice, RestrictionNote } from "@/components/ui";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import { useAgentLanguageChoices } from "@/lib/api/agentLanguages";
import { useCreateAgent, type AgentLanguage } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useBusinessLanguage } from "@/lib/businessCapabilities";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { hasKey } from "@/lib/lookup";

import { ComplianceFloor } from "./BuildAgentForm";
import { NEW_AGENT } from "../../_ui/copy";
import { AGENT_NAME_MAX_CHARS } from "@/lib/textLimits";

/**
 * STEP 1 OF A NEW AGENT: ITS NAME AND LANGUAGE (founder, 16 Nov 2026: name, voice, done).
 *
 * An agent is staff with no script of its own, so nothing here asks what it will say or
 * which job it does: that is written on the Inbound line or campaign it is given at the end.
 * It is made able to do both (`both`), so either job can use it; "which way it calls" and the
 * longest call are behind the quiet link to the blank flow. The server writes both notice
 * sentences in its language with both switches off (D-669), and the floor below says so
 * before the agent exists.
 */

/** What the next steps need of the agent just made. */
export type CreatedAgent = { id: string; name: string };

/** The name a new agent starts with until the owner types another. */
const DEFAULT_NAME = "Front desk";

export function NameStep({
  slug,
  onMore,
  onCreated,
}: {
  slug: string;
  onMore: () => void;
  onCreated: (agent: CreatedAgent) => void;
}) {
  const session = useClientSession();
  // The languages the server offers this account, and its starting one (null until they
  // are in, so the picker never settles on a language the account was not offered).
  const languageChoices = useAgentLanguageChoices(session);
  const startLanguage = useBusinessLanguage();
  const [picked, setLanguage] = useState<AgentLanguage | null>(null);
  const language = picked ?? startLanguage;
  const [typedName, setName] = useState<string | null>(null);
  const name = typedName ?? DEFAULT_NAME;
  const trimmed = name.trim();
  const nameProblem = trimmed.length < 2 ? "Give this agent a name of at least two characters." : null;
  const [tried, setTried] = useState(false);
  const create = useCreateAgent(session);
  const createFeedback = useActionFeedback(create, { errorDisplay: "inline" });
  /* `org:manage` is what POST /v1/agents requires (the owner's permission). */
  const write = useWriteAccess(session, "org:manage", "create an agent");

  useCopilotSurface({
    route: `/c/${slug}/agents/new`,
    title: "New agent",
    realm: "client",
    fields: [
      {
        id: "new-agent-name",
        label: "Name",
        type: "text",
        value: name,
        help: "2-80 characters. Only the client sees it; callers never hear it.",
      },
      {
        id: "new-agent-language",
        label: "Language",
        type: "select",
        value: language ?? "",
        options: languageChoices.map(({ value, label }) => ({ value, label })),
      },
    ],
    facts: [
      {
        key: "what_is_next",
        label: "What comes after",
        value: "its voice, then giving it a job: an Inbound line or a campaign, where its script is written",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        const text = asText(item.value);
        if (item.field_id === "new-agent-name") setName(text);
        else if (item.field_id === "new-agent-language" && hasKey(LANGUAGE_NAMES, text)) setLanguage(text);
      }
    },
    unsaved: typedName !== null || language !== startLanguage,
  });

  const submit = () => {
    setTried(true);
    // A created agent moves the flow on to its voice: a second press would make a second one.
    if (!write.allowed || nameProblem || language === null || create.isPending || create.isSuccess) return;
    create.mutate(
      { name: trimmed, direction: "both", language_primary: language },
      { onSuccess: (agent) => onCreated({ id: agent.id, name: agent.name }) },
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-title text-ink">Your new agent</h2>
        <p className="mt-1 text-body text-ink-muted">{NEW_AGENT.nameStepHint}</p>
      </div>
      <RestrictionNote reason={write.reason} />
      <form
        noValidate
        className="space-y-6"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="space-y-5">
          <Field
            id="new-agent-name"
            className="max-w-sm"
            label="Name"
            hint={NEW_AGENT.nameHint}
            error={tried ? nameProblem : null}
          >
            {(control) => (
              <input
                {...control}
                value={name}
                maxLength={AGENT_NAME_MAX_CHARS}
                onChange={(event) => setName(event.target.value)}
                className={FIELD}
              />
            )}
          </Field>
          <label className="block max-w-sm">
            <span className={FIELD_LABEL}>Language</span>
            <select
              id="new-agent-language"
              value={language ?? ""}
              onChange={(event) => {
                if (hasKey(LANGUAGE_NAMES, event.target.value)) setLanguage(event.target.value);
              }}
              className={FIELD}
            >
              {languageChoices.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {choice.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <ComplianceFloor />
        {create.error ? <ProblemNotice error={create.error} /> : null}
        <div className="space-y-2">
          <ActionButton
            type="submit"
            status={createFeedback.status}
            disabled={!write.allowed || language === null || create.isSuccess}
            pendingLabel="Creating…"
            successLabel="Created"
          >
            Create agent
          </ActionButton>
          <p className="text-meta text-ink-muted">{NEW_AGENT.createdOff}</p>
        </div>
      </form>
      <button type="button" className={TEXT_ACTION} onClick={onMore}>
        {NEW_AGENT.moreChoices}
      </button>
    </div>
  );
}
