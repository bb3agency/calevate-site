"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { PhoneIncoming, PhoneOutgoing } from "lucide-react";

import { Chooser, ChooserItem } from "@/components/console/chooser";
import { IconTile } from "@/components/console/iconTile";
import { TEXT_ACTION } from "@/components/console/section";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
} from "@/components/ui";
import { LANGUAGE_CHOICES, LANGUAGE_NAMES } from "@/lib/agentState";
import { useCreateAgent, useStarter, type AgentLanguage, type StarterJob } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { hasKey } from "@/lib/lookup";

/**
 * PICK A JOB, SEE THE READY AGENT, CREATE IT (founder, REDESIGN-2).
 *
 * Two choices, then a read-back of what the server would make for this business: its
 * opening line, the steps of its script and the details it writes down
 * (`GET /v1/agents/starters`). Creating sends `starter`, and the agent is born a draft with
 * that script saved, so the owner lands on the Script section to review it before
 * publishing. Nothing here is generated in the browser; the preview is the server's.
 */

const JOBS: { job: StarterJob; title: string; line: string; icon: typeof PhoneIncoming }[] = [
  {
    job: "answer_calls",
    title: "Answer my calls",
    line: "It picks up when people ring your number, answers their questions and takes their details.",
    icon: PhoneIncoming,
  },
  {
    job: "call_leads",
    title: "Call my leads",
    line: "It rings the people you give it, follows up on what they asked about and notes what they want.",
    icon: PhoneOutgoing,
  },
];

export function StartFromJob({ slug, onBlank }: { slug: string; onBlank: () => void }) {
  const [job, setJob] = useState<StarterJob | null>(null);
  const chosen = JOBS.find((j) => j.job === job);

  if (!chosen) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-title text-ink">What should your new agent do?</h2>
          <p className="mt-1 text-body text-ink-muted">
            Pick one. It comes ready for your business, and you review everything before anyone
            hears it.
          </p>
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

  return <StarterPreviewStep slug={slug} job={chosen} onBack={() => setJob(null)} />;
}

function StarterPreviewStep({
  slug,
  job,
  onBack,
}: {
  slug: string;
  job: (typeof JOBS)[number];
  onBack: () => void;
}) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const router = useRouter();
  const starter = useStarter(session, job.job);
  const create = useCreateAgent(session);
  /* `org:manage` is what POST /v1/agents requires (the owner's permission). */
  const write = useWriteAccess(session, "org:manage", "create an agent");
  const [typedName, setName] = useState<string | null>(null);
  const [language, setLanguage] = useState<AgentLanguage>("te-IN");
  const preview = starter.data ?? null;
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
        ]
      : [],
    facts: [
      { key: "job", label: "The job chosen", value: job.title },
      ...(preview
        ? [
            { key: "opening_line", label: "How it opens a call", value: preview.opening_line },
            { key: "steps", label: "The steps of its script", value: preview.step_titles.join("; ") },
            { key: "captured", label: "What it writes down", value: preview.captured_details.join(", ") },
          ]
        : []),
    ],
    apply: (items) => {
      for (const item of items) {
        const text = asText(item.value);
        if (item.field_id === "new-agent-name") setName(text);
        else if (item.field_id === "new-agent-language" && hasKey(LANGUAGE_NAMES, text)) setLanguage(text);
      }
    },
    unsaved: typedName !== null || language !== "te-IN",
  });

  const submit = () => {
    setTried(true);
    if (!write.allowed || !preview || nameProblem) return;
    create.mutate(
      {
        name: trimmed,
        // The job decides the direction on the server, so none is sent.
        starter: job.job,
        language_primary: language,
      },
      {
        onSuccess: (agent) =>
          router.push(href(`/c/${slug}/agents/${agent.id}?section=script&from=starter`)),
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
          <p className="mt-1 text-body text-ink-muted">This is the agent you get. You can change any of it.</p>
        </div>
      </div>

      <RestrictionNote reason={write.reason} />

      {starter.isPending ? (
        <Skeleton rows={6} label="Getting your agent ready…" />
      ) : starter.isError ? (
        <ProblemNotice error={starter.error} onRetry={() => void starter.refetch()} />
      ) : preview === null ? (
        <p className="text-body text-ink-muted">
          This job is not available for your account yet. Start from a blank agent instead.
        </p>
      ) : (
        <form
          noValidate
          className="space-y-8"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <section aria-labelledby="starter-opening" className="space-y-2">
            <h3 id="starter-opening" className="text-heading text-ink">
              How it opens a call
            </h3>
            <blockquote className="border-l-2 border-line pl-4 text-body text-ink">
              {preview.opening_line}
            </blockquote>
          </section>

          <section aria-labelledby="starter-steps" className="space-y-2">
            <h3 id="starter-steps" className="text-heading text-ink">
              What it does on a call
            </h3>
            <ol className="list-decimal space-y-1 pl-5 text-body text-ink marker:text-ink-muted">
              {preview.step_titles.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </section>

          {preview.captured_details.length > 0 ? (
            <section aria-labelledby="starter-captured" className="space-y-2">
              <h3 id="starter-captured" className="text-heading text-ink">
                What it writes down
              </h3>
              <ul className="flex flex-wrap gap-2">
                {preview.captured_details.map((detail) => (
                  <li key={detail} className="rounded-full border border-line px-2.5 py-1 text-meta text-ink-muted">
                    {detail}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <div className="space-y-5 border-t border-line pt-6">
            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>Name</span>
              <input
                id="new-agent-name"
                value={name}
                maxLength={80}
                aria-invalid={tried && nameProblem !== null}
                aria-describedby={tried && nameProblem ? "new-agent-name-problem" : undefined}
                onChange={(event) => setName(event.target.value)}
                className={FIELD}
              />
              {tried && nameProblem ? (
                <span id="new-agent-name-problem" role="alert" className="mt-1 block text-meta text-danger">
                  {nameProblem}
                </span>
              ) : (
                <span className={FIELD_HINT}>Only you see this. Callers never hear it.</span>
              )}
            </label>
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
          </div>

          {create.error ? <ProblemNotice error={create.error} /> : null}

          <div className="space-y-2">
            <button type="submit" className={PRIMARY_BUTTON} disabled={!write.allowed || create.isPending}>
              {create.isPending ? "Creating…" : "Create agent"}
            </button>
            <p className="text-meta text-ink-muted">
              It is created as a draft and switched off. Nobody hears it until you publish it.
            </p>
          </div>
        </form>
      )}
    </div>
  );
}
