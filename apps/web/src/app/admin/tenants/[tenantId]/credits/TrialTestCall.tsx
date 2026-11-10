"use client";

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { FIELD, NoticeBox, ProblemNotice, Skeleton, formatPhone } from "@/components/ui";
import { resetIfSettled } from "@/app/admin/resetIfSettled";
import { adminSession, useTenant, useTenantAgents } from "@/lib/api/admin";
import { normalizePhone } from "@/lib/phoneNumber";
import { useTrialTestCall } from "@/lib/api/trials";

import { Field, describedBy } from "./fields";

/**
 * An operator's test call for a client on a trial: one of the client's agents rings a
 * number the operator types, through the client's own test-call path and dial gate.
 *
 * Only agents the gate admits are offered: `live`, or `paused` (ready, not taking calls),
 * the two states `compliance/service.dial_refusal_for_agent_status(trial_call=True)`
 * lets through. Anything else the gate still refuses, in its own words, below the button.
 *
 * The number is checked with `normalizePhone` (the browser's mirror of the server's
 * `normalize_phone`) and must be Indian, because the gate refuses every other country.
 */

const DIALLABLE: ReadonlySet<string> = new Set(["live", "paused"]);

function numberProblem(raw: string): string | null {
  if (raw.trim() === "") return null;
  const phone = normalizePhone(raw);
  return phone !== null && phone.startsWith("+91")
    ? null
    : "Enter an Indian mobile or phone number, such as 98765 43210 or +91 98765 43210.";
}

export function TrialTestCall({ tenantId, clientName }: { tenantId: string; clientName: string }) {
  const tenant = useTenant(tenantId);
  const agents = useTenantAgents(tenant.data?.slug ?? "");
  const call = useTrialTestCall(adminSession(), tenantId);
  const feedback = useActionFeedback(call, { errorDisplay: "inline" });
  const [agentId, setAgentId] = useState("");
  const [number, setNumber] = useState("");
  const [confirming, setConfirming] = useState(false);

  if (agents.isLoading || !tenant.data) return <Skeleton rows={2} label="Loading agents" />;
  if (agents.error) {
    return <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />;
  }
  const ready = (agents.data ?? []).filter((agent) => DIALLABLE.has(agent.status));
  if (ready.length === 0) {
    return (
      <p className="text-body text-ink-muted">
        No agent of {clientName} is ready yet. An agent can make a test call once it is ready
        or taking calls.
      </p>
    );
  }

  const phone = normalizePhone(number);
  const problem = numberProblem(number);
  const agent = ready.find((one) => one.id === agentId);
  const canCall = agent !== undefined && phone !== null && problem === null;

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!canCall || call.isPending) return;
        resetIfSettled(call);
        setConfirming(true);
      }}
    >
      <Field
        label="Agent"
        id="trial-call-agent"
        hint="Only agents that are ready or taking calls are listed."
        error={null}
      >
        <select
          id="trial-call-agent"
          value={agentId}
          onChange={(event) => {
            setAgentId(event.target.value);
            resetIfSettled(call);
          }}
          aria-describedby={describedBy("trial-call-agent", false)}
          className={FIELD}
        >
          <option value="">Choose an agent…</option>
          {ready.map((one) => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
      </Field>

      <Field
        label="Number to ring"
        id="trial-call-number"
        hint="Your own phone. Indian numbers only."
        error={problem}
      >
        <input
          id="trial-call-number"
          type="tel"
          inputMode="tel"
          autoComplete="off"
          value={number}
          maxLength={20}
          placeholder="+91 98765 43210"
          onChange={(event) => {
            setNumber(event.target.value);
            resetIfSettled(call);
          }}
          aria-invalid={problem !== null}
          aria-describedby={describedBy("trial-call-number", problem !== null)}
          className={`font-mono ${FIELD}`}
        />
      </Field>

      {call.data?.status === "queued" && (
        <NoticeBox tone="ok" title="Calling now">
          <p className="mt-1">
            The phone should ring in a few seconds. The minutes used update when the call
            ends.
          </p>
        </NoticeBox>
      )}
      {call.data && call.data.status !== "queued" && (
        <NoticeBox tone="warn" title="This test call was not placed">
          <p className="mt-1">{call.data.blocked_reason ?? "The call was not allowed."}</p>
        </NoticeBox>
      )}

      <ActionButton
        type="submit"
        variant="secondary"
        status={confirming ? "idle" : feedback.status}
        pendingLabel="Calling…"
        successLabel="Done"
        disabled={!canCall}
      >
        Make a test call
      </ActionButton>

      {confirming && agent && phone && (
        <ConfirmDialog
          title={`Ring ${formatPhone(phone)} from ${agent.name}?`}
          confirmLabel="Ring the phone"
          pendingLabel="Calling…"
          status={feedback.status}
          error={call.error}
          onCancel={() => {
            if (!call.isPending) setConfirming(false);
          }}
          onConfirm={() =>
            call.mutate(
              { agent_id: agent.id, number: phone },
              { onSuccess: () => setConfirming(false) },
            )
          }
        >
          <p>
            A real phone rings now. The call uses {clientName}&apos;s free test-call minutes
            and counts toward today&apos;s test calls, the same as one the client makes.
          </p>
        </ConfirmDialog>
      )}
    </form>
  );
}
