"use client";

import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Field } from "@/components/arc/field";
import { FIELD, PRIMARY_BUTTON, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { useAgent, useSetExtractionSchema, type Agent, type AgentExtractionField } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useLeadFields } from "@/lib/api/leadFields";
import { useClientSession } from "@/lib/api/session";

import { slugifyKey } from "../panels/extractionDraft";
import { SetupStep, SkipButton } from "./setupStep";

/**
 * STEP 4: WHAT IT WRITES DOWN FOR EACH LEAD. The details every lead carries (the business's
 * own names for the core, `GET /v1/lead-fields`) and this agent's own, as chips. Removing or
 * adding one is the "What it notes" tab's write (`PUT /v1/agents/{id}/extraction-schema`) with
 * the version read, so a list written elsewhere meanwhile is refused rather than overwritten.
 * Type, required and the reason for each stay on that tab; an added detail is plain text.
 *
 * The server drafts an agent's own details from its script after the script is written, so
 * an empty list is read again for a while before it is shown as empty for good.
 */

/** How often, and for how long, an empty list is read again. */
const EMPTY_POLL_MS = 5000;
const EMPTY_POLL_FOR_MS = 60_000;

/** A detail's key: `extractionDraft`'s rule for a new variable. */
const KEY_RE = /^[a-z][a-z0-9_]{0,39}$/;

export function NotesStep({
  agentId,
  onNext,
  onSkip,
  onBack,
}: {
  agentId: string;
  onNext: () => void;
  onSkip: () => void;
  onBack: () => void;
}) {
  const session = useClientSession();
  const agent = useAgent(session, agentId);
  const empty = agent.data?.extraction_fields.length === 0;
  const refetch = agent.refetch;
  useEffect(() => {
    void refetch();
  }, [refetch]);
  useEffect(() => {
    if (!empty) return;
    const timer = setInterval(() => void refetch(), EMPTY_POLL_MS);
    const stop = setTimeout(() => clearInterval(timer), EMPTY_POLL_FOR_MS);
    return () => {
      clearInterval(timer);
      clearTimeout(stop);
    };
  }, [empty, refetch]);

  let body;
  if (agent.isLoading) body = <Skeleton rows={3} />;
  else if (agent.error || !agent.data) {
    body = (
      <ProblemNotice error={agent.error ?? new Error("Couldn't load your agent.")} onRetry={() => void refetch()} />
    );
  } else body = <NotesEditor agent={agent.data} />;

  return (
    <SetupStep
      title="What it writes down"
      hint="For each lead, from the conversation. Never read out."
      onBack={onBack}
      actions={
        <>
          <button type="button" onClick={onNext} className={PRIMARY_BUTTON}>
            Continue
          </button>
          <SkipButton onSkip={onSkip} />
        </>
      }
    >
      <CoreDetails />
      {body}
    </SetupStep>
  );
}

/** The details every lead carries, whatever the agent: not removable here. */
function CoreDetails() {
  const session = useClientSession();
  const lead = useLeadFields(session);
  let chips;
  if (lead.isLoading) chips = <Skeleton rows={1} />;
  else if (lead.error || !lead.data) {
    chips = <ProblemNotice error={lead.error ?? new Error("Couldn't load them.")} onRetry={() => void lead.refetch()} />;
  } else {
    chips = (
      <ul className="flex flex-wrap gap-2">
        {lead.data.core_fields.map((field) => (
          <li key={field.key} className={`${CHIP} bg-ink/[0.04] text-ink-muted`}>
            {field.label}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div>
      <h3 className="mb-2 text-heading text-ink">On every lead</h3>
      {chips}
    </div>
  );
}

const CHIP = "inline-flex min-h-8 items-center gap-1 rounded-full border border-line px-3 text-meta";

function NotesEditor({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const save = useSetExtractionSchema(session, agent.id);
  const feedback = useActionFeedback(save, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change what this agent notes");
  const [label, setLabel] = useState("");
  const [tried, setTried] = useState(false);
  const fields = agent.extraction_fields;
  const busy = save.isPending;

  const trimmed = label.trim();
  const key = slugifyKey(trimmed);
  const problem =
    trimmed.length < 2
      ? "Name the detail, at least two letters."
      : !KEY_RE.test(key)
        ? "Start it with a letter (a–z)."
        : fields.some((field) => field.key === key || field.label.toLowerCase() === trimmed.toLowerCase())
          ? "It already writes this down."
          : null;

  const send = (next: AgentExtractionField[], onDone?: () => void) =>
    save.mutate(
      { fields: next, expected_version: agent.extraction_schema_version },
      { onSuccess: () => onDone?.() },
    );

  const add = () => {
    setTried(true);
    if (!write.allowed || problem || busy) return;
    send(
      [...fields, { key, label: trimmed, type: "text", required: false, reason: "", enum_values: null }],
      () => {
        setLabel("");
        setTried(false);
      },
    );
  };

  return (
    <div>
      <h3 className="mb-2 text-heading text-ink">For this agent</h3>
      <RestrictionNote reason={write.reason} />
      {fields.length === 0 ? (
        <p className="text-body text-ink-muted">Nothing extra yet. Add what matters to you.</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {fields.map((field) => (
            <li key={field.key} className={`${CHIP} bg-surface text-ink`}>
              {field.label}
              <button
                type="button"
                aria-label={`Remove ${field.label}`}
                disabled={!write.allowed || busy}
                onClick={() => send(fields.filter((other) => other.key !== field.key))}
                className="press -mr-1.5 grid h-6 w-6 place-items-center rounded-full text-ink-muted hover:bg-ink/[0.06] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50 touch:h-11 touch:w-11"
              >
                <X aria-hidden className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {save.error ? (
        <div className="mt-3">
          <ProblemNotice error={save.error} />
        </div>
      ) : null}
      <form
        noValidate
        className="mt-4 flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          add();
        }}
      >
        <Field
          id="new-agent-note"
          label="Add a detail"
          className="min-w-0 flex-1 basis-48"
          error={tried ? problem : null}
        >
          {(control) => (
            <input
              {...control}
              value={label}
              maxLength={80}
              onChange={(event) => setLabel(event.target.value)}
              className={FIELD}
            />
          )}
        </Field>
        <ActionButton
          type="submit"
          variant="secondary"
          status={feedback.status}
          disabled={!write.allowed}
          pendingLabel="Saving…"
          successLabel="Saved"
        >
          <Plus aria-hidden className="h-4 w-4" />
          Add
        </ActionButton>
      </form>
    </div>
  );
}
