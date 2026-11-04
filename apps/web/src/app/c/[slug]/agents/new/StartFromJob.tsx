"use client";

import { useState } from "react";
import { PhoneIncoming, PhoneOutgoing, Zap } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Field } from "@/components/arc/field";
import { Chooser, ChooserItem } from "@/components/console/chooser";
import { IconTile } from "@/components/console/iconTile";
import { TEXT_ACTION } from "@/components/console/section";
import {
  FIELD,
  FIELD_LABEL,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import { LANGUAGE_CHOICES, LANGUAGE_NAMES } from "@/lib/agentState";
import {
  useCreateAgent,
  useStarters,
  type AgentLanguage,
  type StarterJob,
} from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { hasKey } from "@/lib/lookup";

import { NEW_AGENT } from "../../_ui/copy";

/**
 * STEP 1 OF THE NEW-AGENT FLOW: PICK A JOB, NAME IT, CREATE IT (founder, 3 Nov 2026).
 *
 * No plan is shown before the agent exists: the whole script, steps and details included, is
 * written for this business right after creation, and the owner reviews it on the flow's
 * Script step (`./ScriptStep.tsx`). `GET /v1/agents/starters` supplies only the suggested name. The
 * opening line is the owner's to type here; left empty, it is written for this business
 * (D-965). Creating sends `starter`; the agent is born a draft.
 */

/** `AgentCreateIn.opening_line`'s limit (`call_rules.OPENING_LINE_MAX_CHARS`). */
const OPENING_MAX_CHARS = 120;

export const JOBS: { job: StarterJob; title: string; line: string; icon: typeof PhoneIncoming }[] = [
  {
    job: "answer_calls",
    title: "Answer my calls",
    line: "Picks up, answers questions, takes details.",
    icon: PhoneIncoming,
  },
  {
    job: "call_new_leads",
    title: "Call new leads instantly",
    line: "Rings each new enquiry within minutes.",
    icon: Zap,
  },
  {
    job: "call_leads",
    title: "Run calling campaigns",
    line: "Rings your list and follows up.",
    icon: PhoneOutgoing,
  },
];

/** The language a new agent starts in unless the owner picks another (Telugu-first, BRD §1). */
const DEFAULT_LANGUAGE: AgentLanguage = "te-IN";

/** What the next steps need of the agent just made. */
export type CreatedAgent = { id: string; name: string };

export function StartFromJob({
  slug,
  onBlank,
  onCreated,
}: {
  slug: string;
  onBlank: () => void;
  onCreated: (agent: CreatedAgent) => void;
}) {
  const [job, setJob] = useState<StarterJob | null>(null);
  const chosen = JOBS.find((j) => j.job === job);

  if (!chosen) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-title text-ink">What should your new agent do?</h2>
          <p className="mt-1 text-body text-ink-muted">{NEW_AGENT.jobsHint}</p>
        </div>
        <Chooser label="Jobs an agent can do">
          {JOBS.map((j) => (
            <ChooserItem
              key={j.job}
              title={j.title}
              description={j.line}
              icon={<IconTile icon={j.icon} />}
              onSelect={() => setJob(j.job)}
            />
          ))}
        </Chooser>
        <button type="button" className={TEXT_ACTION} onClick={onBlank}>
          Start from a blank agent instead
        </button>
      </div>
    );
  }

  return <StarterPreviewStep slug={slug} job={chosen} onBack={() => setJob(null)} onCreated={onCreated} />;
}

function StarterPreviewStep({
  slug,
  job,
  onBack,
  onCreated,
}: {
  slug: string;
  job: (typeof JOBS)[number];
  onBack: () => void;
  onCreated: (agent: CreatedAgent) => void;
}) {
  const session = useClientSession();
  const [language, setLanguage] = useState<AgentLanguage>(DEFAULT_LANGUAGE);
  const [opening, setOpening] = useState("");
  const starter = useStarters(session);
  const create = useCreateAgent(session);
  const createFeedback = useActionFeedback(create, { errorDisplay: "inline" });
  /* `org:manage` is what POST /v1/agents requires (the owner's permission). */
  const write = useWriteAccess(session, "org:manage", "create an agent");
  const [typedName, setName] = useState<string | null>(null);
  const preview = starter.data?.starters.find((s) => s.job === job.job) ?? null;
  const name = typedName ?? preview?.name_suggestion ?? "";
  const trimmed = name.trim();
  const nameProblem = trimmed.length < 2 ? "Give this agent a name of at least two characters." : null;
  const [tried, setTried] = useState(false);

  useCopilotSurface({
    route: `/c/${slug}/agents/new`,
    title: `New agent: ${job.title}`,
    realm: "client",
    fields: preview
      ? [
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
            value: language,
            options: LANGUAGE_CHOICES.map(({ value, label }) => ({ value, label })),
          },
          {
            id: "new-agent-opening",
            label: "How it opens a call (optional; empty means written for the business)",
            type: "text",
            value: opening,
          },
        ]
      : [],
    facts: [
      { key: "job", label: "The job chosen", value: job.title },
      ...(preview
        ? [
            {
              key: "opening_line",
              label: "How it opens a call",
              value: opening.trim() || "written for this business after it is created",
            },
          ]
        : []),
    ],
    apply: (items) => {
      for (const item of items) {
        const text = asText(item.value);
        if (item.field_id === "new-agent-name") setName(text);
        else if (item.field_id === "new-agent-language" && hasKey(LANGUAGE_NAMES, text)) setLanguage(text);
        else if (item.field_id === "new-agent-opening") setOpening(text.slice(0, OPENING_MAX_CHARS));
      }
    },
    unsaved: typedName !== null || language !== DEFAULT_LANGUAGE || opening !== "",
  });

  const submit = () => {
    setTried(true);
    // A created agent moves the flow on to its voice: a second press would make a second one.
    if (!write.allowed || !preview || nameProblem || create.isPending || create.isSuccess) return;
    create.mutate(
      {
        name: trimmed,
        // The job decides the direction on the server, so none is sent.
        starter: job.job,
        language_primary: language,
        ...(opening.trim() ? { opening_line: opening.trim() } : {}),
      },
      {
        onSuccess: (agent) => onCreated({ id: agent.id, name: agent.name }),
      },
    );
  };

  return (
    <div className="space-y-8">
      <button type="button" className={TEXT_ACTION} onClick={onBack}>
        ← Pick a different job
      </button>
      <div className="flex items-start gap-4">
        <IconTile icon={job.icon} />
        <div>
          <h2 className="text-title text-ink">{job.title}</h2>
          <p className="mt-1 text-body text-ink-muted">We write its script for your business once you create it.</p>
        </div>
      </div>

      <RestrictionNote reason={write.reason} />

      {starter.isPending ? (
        <Skeleton rows={6} label="Getting your agent ready…" />
      ) : starter.isError ? (
        <ProblemNotice error={starter.error} onRetry={() => void starter.refetch()} />
      ) : preview === null ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-body text-ink-muted">{NEW_AGENT.jobUnavailable}</p>
          <button type="button" className={SECONDARY_BUTTON} onClick={onBack}>
            Pick another job
          </button>
        </div>
      ) : (
        <form
          noValidate
          className="space-y-8"
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
              hint="Only you see this. Callers never hear it."
              error={tried ? nameProblem : null}
            >
              {(control) => (
                <input
                  {...control}
                  value={name}
                  maxLength={80}
                  onChange={(event) => setName(event.target.value)}
                  className={FIELD}
                />
              )}
            </Field>
            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>Language</span>
              <select
                id="new-agent-language"
                value={language}
                onChange={(event) => {
                  if (hasKey(LANGUAGE_NAMES, event.target.value)) setLanguage(event.target.value);
                }}
                className={FIELD}
              >
                {LANGUAGE_CHOICES.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
            </label>
            <Field
              id="new-agent-opening"
              className="max-w-xl"
              label="How it opens a call (optional)"
              hint="Leave empty and we write one for your business."
            >
              {(control) => (
                <textarea
                  {...control}
                  rows={2}
                  value={opening}
                  maxLength={OPENING_MAX_CHARS}
                  onChange={(event) => setOpening(event.target.value)}
                  className={FIELD}
                />
              )}
            </Field>
          </div>

          {create.error ? <ProblemNotice error={create.error} /> : null}

          <div className="space-y-2">
            <ActionButton
              type="submit"
              status={createFeedback.status}
              disabled={!write.allowed || create.isSuccess}
              pendingLabel="Creating…"
              successLabel="Created"
            >
              Create agent
            </ActionButton>
            <p className="text-meta text-ink-muted">
              Starts switched off. Callers hear it once you switch it on.
            </p>
          </div>
        </form>
      )}
    </div>
  );
}
