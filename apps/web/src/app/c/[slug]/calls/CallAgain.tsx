"use client";

import { useState } from "react";
import { PhoneOutgoing } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Field } from "@/components/arc/field";
import { RadioGroup } from "@/components/arc/radio-group";
import { PlanCard } from "@/components/copilot/PlanCard";
import { ModalDialog } from "@/components/modalDialog";
import { FIELD, NoticeBox, ProblemNotice, SECONDARY_BUTTON, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { Session } from "@/lib/api/client";
import { useProposePlan } from "@/lib/copilot/plans";

/**
 * "CALL THEM AGAIN" — the Calls screen's retry of unanswered calls (D-893 L1, item 4).
 *
 * Shown when the log is narrowed to calls nobody answered. It does not dial: it asks the
 * server for the same plan Pip's `calls_place_bulk` makes (`POST /v1/copilot/plans`), over
 * the people whose LATEST call went unanswered — someone who answered a later call is not
 * rung again. The plan card then says who, the estimate, and who is left out and why
 * (do-not-call, consent, calling rules), and one Approve runs it as a campaign, so calling
 * hours, pacing and retries apply. Nothing here can bypass the gate: the plan re-asks it
 * for every person when it runs.
 *
 * How these people agreed to be called is ASKED, never defaulted: it is a statement the
 * business makes about its own records, and the launch gate holds them to it.
 */

/** What the server's `consent_source` accepts for a dialling plan, in the owner's words. */
const CONSENT = [
  { value: "inbound_enquiry", label: "They contacted us first" },
  { value: "existing_customer", label: "They are our customers" },
  { value: "web_form_optin", label: "They filled in a form on our website" },
  { value: "offline_form_optin", label: "They signed a form in person" },
] as const;

const KINDS = [
  { value: "service", label: "About something they asked for", hint: "Following up an enquiry or a booking." },
  { value: "promotional", label: "To offer something new", hint: "Needs your promotional calling registration." },
] as const;

/** The Calls screen's filters that carry over to "whose latest call", as the leads lens. */
export type CallAgainScope = {
  direction?: "inbound" | "outbound";
  fromDay?: string;
  toDay?: string;
  testCalls: boolean;
};

export function CallAgain({
  session,
  scope,
  dialers,
}: {
  session: Session;
  scope: CallAgainScope;
  /** The agents that can place calls now (`canDialOut`); undefined while they load. */
  dialers: Agent[] | undefined;
}) {
  const [open, setOpen] = useState(false);
  const [planId, setPlanId] = useState<string | null>(null);

  if (planId) {
    return <PlanCard session={session} planId={planId} onDismiss={() => setPlanId(null)} />;
  }
  return (
    <>
      <NoticeBox
        tone="neutral"
        title="Ring the ones who did not answer"
        action={
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => setOpen(true)}
            disabled={!dialers?.length}
          >
            <PhoneOutgoing aria-hidden className="h-4 w-4" />
            Call them again
          </button>
        }
      >
        {dialers && dialers.length === 0
          ? "None of your agents places calls right now, so nobody can be called again."
          : "People whose latest call was not answered. You see who and the cost before anyone is rung."}
      </NoticeBox>
      {open && dialers && dialers.length > 0 ? (
        <CallAgainDialog
          session={session}
          scope={scope}
          dialers={dialers}
          onClose={() => setOpen(false)}
          onPlanned={(id) => {
            setOpen(false);
            setPlanId(id);
          }}
        />
      ) : null}
    </>
  );
}

function CallAgainDialog({
  session,
  scope,
  dialers,
  onClose,
  onPlanned,
}: {
  session: Session;
  scope: CallAgainScope;
  dialers: Agent[];
  onClose: () => void;
  onPlanned: (planId: string) => void;
}) {
  const propose = useProposePlan(session);
  const feedback = useActionFeedback(propose, { errorDisplay: "inline" });
  const [agentId, setAgentId] = useState(dialers[0].id);
  const [kind, setKind] = useState<string | null>("service");
  const [consent, setConsent] = useState("");
  const [tried, setTried] = useState(false);

  const submit = () => {
    setTried(true);
    if (!consent || !kind) return;
    propose.mutate(
      {
        tool: "calls_place_bulk",
        args: {
          lens: {
            last_outcome: "missed",
            ...(scope.direction ? { direction: scope.direction } : {}),
            ...(scope.fromDay ? { last_call_from: scope.fromDay } : {}),
            ...(scope.toDay ? { last_call_to: scope.toDay } : {}),
            ...(scope.testCalls ? {} : { test_calls: false }),
          },
          lead_ids: null,
          agent_id: agentId,
          classification: kind,
          consent_source: consent,
        },
      },
      { onSuccess: (plan) => onPlanned(plan.id) },
    );
  };

  return (
    <ModalDialog
      title="Call them again"
      description="Your agent rings each person whose latest call was not answered, inside calling hours. Next you see who, the cost and who is left out, and nothing happens until you approve."
      onClose={onClose}
      actions={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={feedback.status === "pending"}>
            Cancel
          </button>
          <ActionButton status={feedback.status} pendingLabel="Preparing…" successLabel="Ready" onClick={submit}>
            Show me the plan
          </ActionButton>
        </>
      }
    >
      <form
        className="mt-4 space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field label="Who calls">
          {(control) => (
            <select {...control} value={agentId} onChange={(event) => setAgentId(event.target.value)} className={FIELD}>
              {dialers.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <RadioGroup
          label="What the calls are about"
          options={KINDS.map((k) => ({ value: k.value, label: k.label, hint: k.hint }))}
          value={kind}
          onChange={setKind}
        />
        <Field
          label="How did these people agree to be called?"
          hint="Your answer is kept with the calls."
          error={tried && !consent ? "Choose how they agreed to be called." : null}
        >
          {(control) => (
            <select {...control} value={consent} onChange={(event) => setConsent(event.target.value)} className={FIELD}>
              <option value="">Choose one</option>
              {CONSENT.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <ProblemNotice error={propose.error} />
      </form>
    </ModalDialog>
  );
}
