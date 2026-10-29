"use client";

import Link from "next/link";
import { useState } from "react";

import { ModalDialog } from "@/components/modalDialog";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { canDialOut } from "@/lib/agentState";
import { ApiProblem } from "@/lib/api/client";
import { useAgents } from "@/lib/api/agents";
import type { FollowUpStep, FollowUpStepEditIn, FollowUpWaitIn } from "@/lib/api/followUps";
import { useClientRealm } from "@/lib/api/session";
import { useWhatsAppTemplates } from "@/lib/api/whatsapp";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { currentWait, type WaitUnit } from "../followUpCopy";

export type EditMode = "wait" | "template" | "agent";

const TITLES: Record<EditMode, string> = {
  wait: "Change the wait",
  template: "Change the message",
  agent: "Change who calls",
};

/** The longest wait before a first call, in minutes (the server's own bound: 0..1440). */
const CALL_WAIT_MAX_MINUTES = 1440;
/** A wait step's bounds on the server: a minute to 30 days. */
const WAIT_MAX_MINUTES = 30 * 1440;

/** One unit, as the PATCH `wait` takes it (`{minutes?, hours?, days?}`). */
function waitIn(unit: WaitUnit, amount: number): FollowUpWaitIn {
  if (unit === "days") return { days: amount };
  if (unit === "hours") return { hours: amount };
  return { minutes: amount };
}

/**
 * One small edit to one step: its wait, its WhatsApp message (from the account's approved
 * ones) or the agent that calls. The choices are read from the account, never typed, so
 * nothing here can name an agent or a message that does not exist. Closes only on success.
 */
export function StepEditDialog({
  step,
  mode,
  pending,
  error,
  onClose,
  onSave,
}: {
  step: FollowUpStep;
  mode: EditMode;
  pending: boolean;
  error: unknown;
  onClose: () => void;
  onSave: (edit: FollowUpStepEditIn) => void;
}) {
  const [value, setValue] = useState<FollowUpStepEditIn | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);

  const save = () => {
    if (invalid) return;
    if (value) onSave(value);
    else onClose();
  };

  return (
    <ModalDialog
      title={TITLES[mode]}
      description={<span className="block font-medium text-ink">{step.summary}</span>}
      onClose={onClose}
      actions={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={pending}>
            Cancel
          </button>
          <button type="button" className={PRIMARY_BUTTON} onClick={save} disabled={pending || Boolean(invalid)}>
            {pending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <form
        className="mt-4 space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        {mode === "wait" ? (
          <WaitFields step={step} onChange={setValue} onInvalid={setInvalid} />
        ) : mode === "template" ? (
          <TemplateField step={step} onChange={setValue} />
        ) : (
          <AgentField step={step} onChange={setValue} />
        )}
        {invalid && (
          <p role="alert" className="text-meta text-danger">
            {invalid}
          </p>
        )}
        <ProblemNotice error={error} />
        {error instanceof ApiProblem && error.code === "follow_up_edit_invalid" && (
          <AskAssistant label={`Ask ${ASSISTANT_NAME} to change it`} prompt={`Change this step: “${step.summary}”. `} />
        )}
      </form>
    </ModalDialog>
  );
}

function WaitFields({
  step,
  onChange,
  onInvalid,
}: {
  step: FollowUpStep;
  onChange: (edit: FollowUpStepEditIn) => void;
  onInvalid: (message: string | null) => void;
}) {
  const start = currentWait(step);
  const [amount, setAmount] = useState(String(start.amount));
  const [unit, setUnit] = useState<WaitUnit>(start.unit);
  const units: WaitUnit[] = step.kind === "call" ? ["minutes", "hours"] : ["minutes", "hours", "days"];

  const update = (nextAmount: string, nextUnit: WaitUnit) => {
    setAmount(nextAmount);
    setUnit(nextUnit);
    const n = Number(nextAmount);
    if (!/^\d+$/.test(nextAmount.trim())) {
      onInvalid("Enter a whole number.");
      return;
    }
    const minutes = nextUnit === "days" ? n * 1440 : nextUnit === "hours" ? n * 60 : n;
    if (step.kind === "call" && minutes > CALL_WAIT_MAX_MINUTES) {
      onInvalid("Wait at most a day before the first call.");
      return;
    }
    if (step.kind === "wait" && (minutes < 1 || minutes > WAIT_MAX_MINUTES)) {
      onInvalid("Wait between a minute and 30 days.");
      return;
    }
    onInvalid(null);
    onChange({ step_id: step.id, remove: false, wait: waitIn(nextUnit, n) });
  };

  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="block w-28">
        <span className={FIELD_LABEL}>Wait</span>
        <input
          className={FIELD}
          inputMode="numeric"
          value={amount}
          onChange={(event) => update(event.target.value, unit)}
        />
      </label>
      <label className="block w-36">
        <span className={FIELD_LABEL}>Unit</span>
        <select className={FIELD} value={unit} onChange={(event) => update(amount, event.target.value as WaitUnit)}>
          {units.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function TemplateField({
  step,
  onChange,
}: {
  step: FollowUpStep;
  onChange: (edit: FollowUpStepEditIn) => void;
}) {
  const { session, href } = useClientRealm();
  const templates = useWhatsAppTemplates(session);
  const [chosen, setChosen] = useState(step.kind === "whatsapp" ? step.template_id : "");
  if (templates.isPending) return <Skeleton rows={1} label="Loading your approved messages" />;
  if (templates.error || !templates.data) {
    return <ProblemNotice error={templates.error} onRetry={() => void templates.refetch()} />;
  }
  const approved = templates.data.filter((template) => template.status === "approved");
  if (approved.length === 0) {
    return (
      <p className="text-body text-ink-muted">
        No approved messages yet.{" "}
        <Link href={href(`/c/${session.orgSlug}/integrations`)} className="font-medium text-brand-strong underline dark:text-brand-bright">
          Add one
        </Link>
      </p>
    );
  }
  return (
    <label className="block">
      <span className={FIELD_LABEL}>Message</span>
      <select
        className={FIELD}
        value={chosen}
        onChange={(event) => {
          setChosen(event.target.value);
          if (event.target.value) onChange({ step_id: step.id, remove: false, template_id: event.target.value });
        }}
      >
        {!approved.some((template) => template.id === chosen) && <option value="">Choose a message</option>}
        {approved.map((template) => (
          <option key={template.id} value={template.id}>
            {template.name.replaceAll("_", " ")} · {template.language}
          </option>
        ))}
      </select>
    </label>
  );
}

function AgentField({
  step,
  onChange,
}: {
  step: FollowUpStep;
  onChange: (edit: FollowUpStepEditIn | null) => void;
}) {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  // No agent of its own (null) means the lead's own agent calls: the agent that took the lead.
  const current = step.kind === "call" ? (step.agent_id ?? null) : null;
  const [chosen, setChosen] = useState(current ?? "");
  if (agents.isPending) return <Skeleton rows={1} label="Loading your agents" />;
  if (agents.error || !agents.data) {
    return <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />;
  }
  // Agents that can place calls, plus the current one so the select never lies about it.
  const callers = agents.data.filter((agent) => canDialOut(agent) || agent.id === current);
  if (callers.length === 0) {
    return <p className="text-body text-ink-muted">No agent can make calls yet.</p>;
  }
  return (
    <label className="block">
      <span className={FIELD_LABEL}>Agent</span>
      <select
        className={FIELD}
        value={chosen}
        onChange={(event) => {
          setChosen(event.target.value);
          onChange(event.target.value ? { step_id: step.id, remove: false, agent_id: event.target.value } : null);
        }}
      >
        {current === null ? (
          <option value="">The lead’s own agent</option>
        ) : (
          !callers.some((agent) => agent.id === chosen) && <option value="">Choose an agent</option>
        )}
        {callers.map((agent) => (
          <option key={agent.id} value={agent.id}>
            {agent.name}
          </option>
        ))}
      </select>
    </label>
  );
}
