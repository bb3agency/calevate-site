"use client";

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { useFormValidation } from "@/components/formValidation";
import { PasswordInput } from "@/components/passwordInput";
import { FIELD_HINT, FIELD_LABEL, NoticeBox, ProblemNotice } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import type { WriteAccess } from "@/lib/api/hooks";
import { useCreateLeadSquaredEndpoint } from "@/lib/api/integrations";

import { INPUT } from "./EventChoices";

/**
 * SEND LEADS AND CALL RESULTS TO LEADSQUARED (D-942) — one form, three things to paste from
 * one LeadSquared screen, and an optional field for call results.
 *
 * Its primary job is connecting: the keys are sealed on save and never shown again. A
 * call result needs a LeadSquared field to land in, so the call box is offered only once
 * one is named, and the server refuses the combination anyway.
 */
export function LeadSquaredForm({ session, write }: { session: Session; write: WriteAccess }) {
  const create = useCreateLeadSquaredEndpoint(session);
  const feedback = useActionFeedback(create, { errorDisplay: "inline" });
  const valid = useFormValidation();
  const [host, setHost] = useState("");
  const [accessKey, setAccessKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [outcomeField, setOutcomeField] = useState("");
  const accessTrack = valid.track("accessKey", "Paste the access key.");
  const secretTrack = valid.track("secretKey", "Paste the secret key.");

  if (create.isSuccess) {
    return (
      <NoticeBox tone="ok" title="LeadSquared connected">
        New leads now go to {create.data.api_host}.
      </NoticeBox>
    );
  }

  const field = outcomeField.trim();
  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={valid.onSubmit(() =>
        create.mutate({
          api_host: host.trim(),
          access_key: accessKey.trim(),
          secret_key: secretKey.trim(),
          events: field ? ["lead.created", "call.completed"] : ["lead.created"],
          fields: field ? { [field]: "outcome" } : {},
        }),
      )}
    >
      {create.error ? <ProblemNotice error={create.error} /> : null}
      <p className={FIELD_HINT}>In LeadSquared: My Profile → Settings → API and Webhooks.</p>
      <div>
        <label className="block">
          <span className={FIELD_LABEL}>API host</span>
          <input
            {...valid.field("host", "Paste the host from LeadSquared.")}
            required
            value={host}
            disabled={!write.allowed}
            onChange={(e) => setHost(e.target.value)}
            placeholder="api-in21.leadsquared.com"
            className={INPUT}
            autoComplete="off"
          />
        </label>
        {valid.error("host")}
      </div>
      <div>
        <span className={FIELD_LABEL}>Access key</span>
        <PasswordInput
          inputRef={accessTrack.ref}
          onInput={accessTrack.onInput}
          required
          aria-label="LeadSquared access key"
          reveals="access key"
          value={accessKey}
          disabled={!write.allowed}
          onChange={(e) => setAccessKey(e.target.value)}
        />
        {valid.error("accessKey")}
      </div>
      <div>
        <span className={FIELD_LABEL}>Secret key</span>
        <PasswordInput
          inputRef={secretTrack.ref}
          onInput={secretTrack.onInput}
          required
          aria-label="LeadSquared secret key"
          reveals="secret key"
          value={secretKey}
          disabled={!write.allowed}
          onChange={(e) => setSecretKey(e.target.value)}
        />
        {valid.error("secretKey")}
        <span className={FIELD_HINT}>Sealed when you save. We never show either key again.</span>
      </div>
      <label className="block">
        <span className={FIELD_LABEL}>Field for call results (optional)</span>
        <input
          value={outcomeField}
          disabled={!write.allowed}
          onChange={(e) => setOutcomeField(e.target.value)}
          placeholder="mx_Call_Outcome"
          className={`${INPUT} font-mono`}
          autoComplete="off"
        />
        <span className={FIELD_HINT}>
          {field ? "Each call's result is written here." : "Leave empty to send new leads only."}
        </span>
      </label>
      <ActionButton
        type="submit"
        status={feedback.status}
        disabled={!write.allowed}
        pendingLabel="Connecting…"
        successLabel="Connected"
      >
        Connect LeadSquared
      </ActionButton>
    </form>
  );
}
