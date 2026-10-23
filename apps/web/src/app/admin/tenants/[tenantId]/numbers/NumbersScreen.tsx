"use client";

/**
 * THE CLIENT'S PHONE NUMBERS — record one, say which agent answers it, and release one.
 *
 * Primary job, in one sentence: *get this client's number answering an agent.*
 *
 * ## Why the recording form moved here (D-576, OURS-2)
 *
 * It used to live only in `CampaignSetup` — a panel headed "the prerequisites every client
 * campaign stalls on", with the series selector preselected to **160**, a DLT class. An
 * operator onboarding an INBOUND-ONLY client was therefore sent to a CAMPAIGN screen to
 * perform the one step that makes the phone ring, with an outbound-shaped default already
 * chosen for them. Recording a client's connection and attaching it to an agent are the
 * same job, and this is the screen named after it (UX §5: group by what the operator is
 * trying to do, never by API resource; §9 move 4: give it its own route).
 *
 * Nothing was deleted from the campaign screen that a campaign operator still needs: the
 * numbers list and the registrar's `Mark registered` action stay there, because a DLT
 * verdict is registrar paperwork and belongs beside the templates. What left is the second
 * copy of one form — two spellings of one fact is a defect even when both work (UX §5).
 *
 * ## Hierarchy (UX §1)
 *
 * The list is the screen: each row is where an operator says who answers a number, and a
 * number nobody answers says so on its own row. Recording a new number is the header's
 * action and opens in a drawer (the form keeps the screen's only `PRIMARY_BUTTON_LG`).
 * Renting a number in the client's own name happens on the voice platform's panel
 * (`EngineNumbersPanel`).
 *
 * ## Two things this screen must not get wrong
 *
 * 1. **The going-live gate is a legal fact** and the screen prints the server's own
 *    refusal rather than composing a cheerier one.
 * 2. **`agent_id` and `engine_linked` are the two facts between a recorded number and a
 *    ringing phone.** Every row says where it stands on both.
 */

import { EmptySketch } from "@/components/console/emptySketch";
import { useState } from "react";
import { Plus } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { HAIRLINE_LIST } from "@/components/admin/kit";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer } from "@/components/console/drawer";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatPhone,
} from "@/components/ui";
import {
  useProvisionNumber,
  useTenant,
  useTenantAgents,
  type ProvisionNumberBody,
} from "@/lib/api/admin";
import {
  useReleaseNumber,
  useTenantEngineNumbers,
  useTenantNumberCosts,
  type TenantNumberCost,
} from "@/lib/api/numbers";

import { CallLinesPanel } from "./CallLinesPanel";
import { EngineNumbersPanel } from "./EngineNumbersPanel";
import { ForwardingCard } from "./ForwardingCard";
import { NumberRow } from "./NumberRow";
import { WorkspacePanel } from "./WorkspacePanel";

type Series = ProvisionNumberBody["series"];
type Direction = ProvisionNumberBody["direction"];

export function NumbersScreen({ tenantId }: { tenantId: string }) {
  const tenant = useTenant(tenantId);
  const held = useTenantNumberCosts(tenantId);
  // The agents are read through impersonation, the same D-22 split every admin tenant
  // screen uses. The slug arrives with the tenant, so the query is disabled until it does.
  const agents = useTenantAgents(tenant.data ? tenant.data.slug : "");
  const write = useAdminAccess("admin:tenants", "record, attach or release a number");

  const record = useProvisionNumber(tenantId);
  // The drawer closes on success, so the outcome is said in a toast; a refusal stays
  // inside the drawer, above the fields.
  const recordFeedback = useActionFeedback(record, {
    errorDisplay: "inline",
    successToast: (data) => `${formatPhone(data.e164)} recorded`,
  });
  const [e164, setE164] = useState("");
  const numberValid = useFormValidation();
  // **`standard`, NOT `160`.** The series is fixed when the operator issues the number and
  // the server refuses a mismatch by name; what a default decides is which mistake is easy.
  // A client's own published business line — the inbound case this platform's first client
  // is — is `standard`, and a 140/160 preselect quietly proposes a regulated class to
  // somebody recording an ordinary landline.
  const [series, setSeries] = useState<Series>("standard");
  // A number is recorded on the voice platform (D-678): the only provider a call can present
  // is that platform, and the server refuses any other at the dial gate.
  const engineNumbers = useTenantEngineNumbers(tenantId);
  const engineHeld = engineNumbers.data?.managed_in_engine_console === true;
  const engineLabel = engineNumbers.data?.platform ?? "the voice platform";
  // `inbound` matches the server's own default: it is the leg no regulation restricts. A
  // number an agent should also call OUT from must say so here, or the dial gate refuses
  // it as `number_inbound_only` — there is no later control that changes it.
  const [direction, setDirection] = useState<Direction>("inbound");
  const [engineRef, setEngineRef] = useState("");

  const release = useReleaseNumber(tenantId);
  const releaseFeedback = useActionFeedback(release, { errorDisplay: "inline" });
  const [releasing, setReleasing] = useState<TenantNumberCost | null>(null);
  const [recording, setRecording] = useState(false);

  const recordAction = (
    <button type="button" className={PRIMARY_BUTTON} disabled={!write.allowed} onClick={() => setRecording(true)}>
      <Plus aria-hidden className="h-4 w-4" />
      Record a number
    </button>
  );

  return (
    <div className="max-w-4xl space-y-10">
      <PageHeader
        title="Numbers"
        description="Record the client's own connection, then choose which agent answers it."
        actions={recordAction}
      />

      <RestrictionNote reason={write.reason} />

      {/* Only on a voice platform that rents and attaches numbers in its own console;
          renders nothing otherwise. */}
      <EngineNumbersPanel tenantId={tenantId} canWrite={write.allowed} />

      {/* The client's existing published number and its forwarding findings (D-746). */}
      <ForwardingCard tenantId={tenantId} />

      {/* The client's own ThinnestAI workspace (D-693). Only an engine that rents numbers in
          its own console has per-client workspaces, so nothing is asked elsewhere. */}
      {engineHeld && (
        <WorkspacePanel
          tenantId={tenantId}
          canWrite={write.allowed}
          agents={engineNumbers.data?.agents}
        />
      )}

      {/* How many calls this client may have at once (F7): its own workspace is capped at it,
          and a free trial's calls are counted by the dial gate. */}
      <CallLinesPanel tenantId={tenantId} canWrite={write.allowed} />

      {held.error ? (
        <ProblemNotice error={held.error} onRetry={() => held.refetch()} />
      ) : held.isLoading || !held.data ? (
        <Skeleton rows={3} />
      ) : held.data.length === 0 ? (
        <EmptyState
          // No button here: the header already carries the one filled action.
          message="No numbers on this account. Nothing can make their phone ring until one is on file."
          illustration={<EmptySketch kind="numbers" />}
        />
      ) : (
        <ul aria-label="Numbers" className={HAIRLINE_LIST}>
          {held.data.map((number) => (
            <NumberRow
              key={number.id}
              number={number}
              tenantId={tenantId}
              agents={agents.data}
              agentsFailed={Boolean(agents.error)}
              canWrite={write.allowed}
              onRelease={() => setReleasing(number)}
            />
          ))}
        </ul>
      )}

      <Drawer
        open={recording}
        onClose={() => setRecording(false)}
        title="Record a number"
        description="A number already held on the voice platform. Recording it buys nothing."
      >
        <form
          className="space-y-4"
          noValidate
          onSubmit={numberValid.onSubmit(() => {
            if (record.isPending) return;
            record.mutate(
              {
                e164,
                series,
                provider: "thinnest",
                direction,
                // A blank field means "not known yet", which the row's own link control
                // fills in later; it is never sent as an empty handle.
                ...(engineRef.trim() ? { engine_number_ref: engineRef.trim() } : {}),
              },
              {
                onSuccess: () => {
                  setE164("");
                  setEngineRef("");
                  setRecording(false);
                },
              },
            );
          })}
        >
          <p className="text-body text-ink-muted">
            Recording a number here is what lets an agent be put on it.
          </p>
          {record.error && <ProblemNotice error={record.error} />}
          <label className="block">
            <span className={FIELD_LABEL}>The number, with its country code</span>
            <input
              {...numberValid.field("e164", "Enter the number to record.")}
              required
              minLength={8}
              value={e164}
              disabled={!write.allowed}
              onChange={(ev) => setE164(ev.target.value)}
              placeholder="+918041234567"
              className={`font-mono ${FIELD}`}
            />
          </label>
          {numberValid.error("e164")}
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>Series</span>
              <select
                className={FIELD}
                value={series}
                disabled={!write.allowed}
                onChange={(ev) => setSeries(ev.target.value as Series)}
              >
                <option value="standard">standard — an ordinary business line</option>
                <option value="160">160 — service / transactional</option>
                <option value="140">140 — telemarketing / promotional</option>
              </select>
            </label>
            <div className={`${FIELD_HINT} flex items-start gap-1`}>
              <span>It must match the number&apos;s prefix; the server refuses a mismatch.</span>
              <InfoTip label="Series">
                The series is fixed when the operator issues the number, and the campaign
                launch gate matches it against a campaign&apos;s classification — a number
                filed under the wrong one dials the wrong traffic. The server checks it
                against the number&apos;s own prefix and refuses a disagreement rather than
                correcting it.
              </InfoTip>
            </div>
          </div>
          <p className="text-body text-ink-muted">Held on: {engineLabel}</p>
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>Calls on this number</span>
              <select
                className={FIELD}
                value={direction}
                disabled={!write.allowed}
                onChange={(ev) => setDirection(ev.target.value as Direction)}
              >
                <option value="inbound">Incoming only</option>
                <option value="outbound">Outgoing only</option>
                <option value="both">Incoming and outgoing</option>
              </select>
            </label>
            <p className={FIELD_HINT}>
              An agent can call out from this number only if it is recorded for outgoing
              calls. This cannot be changed after recording.
            </p>
          </div>
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>The voice platform&apos;s number id (optional)</span>
              <input
                value={engineRef}
                maxLength={200}
                disabled={!write.allowed}
                onChange={(ev) => setEngineRef(ev.target.value)}
                className={`font-mono ${FIELD}`}
              />
            </label>
            <p className={FIELD_HINT}>
              The id the voice platform gives this number in its number list. No agent can
              answer the number until it is set; you can also add it later on the
              number&apos;s row.
            </p>
          </div>
          <ActionButton
            type="submit"
            variant="primary-lg"
            status={recordFeedback.status}
            successLabel="Recorded"
            className="max-sm:w-full max-sm:justify-center"
            disabled={!write.allowed}
          >
            Record this number
          </ActionButton>
        </form>
      </Drawer>

      {releasing && (
        <ConfirmDialog
          title={`Give ${formatPhone(releasing.e164)} back to the voice platform?`}
          confirmLabel="Release the number"
          pendingLabel="Releasing…"
          status={releaseFeedback.status}
          error={release.error}
          onCancel={() => setReleasing(null)}
          onConfirm={() => release.mutate(releasing.id, { onSuccess: () => setReleasing(null) })}
        >
          <p>
            Any agent answering it stops, the monthly charge stops, and the number goes
            back to the operator — it is not held for us and may not be available again.
            Anything still forwarding to it will reach nobody.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}