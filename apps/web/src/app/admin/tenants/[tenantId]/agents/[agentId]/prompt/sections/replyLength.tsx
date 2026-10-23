"use client";

import { useEffect, useId, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NumberField } from "@/components/arc/number-field";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import { useReplyLength, useSetReplyLength } from "@/lib/api/replyLength";

/**
 * Reply length: the longest reply this agent may give, in tokens (D-769). Operators only; a
 * client never sees it. A reply that reaches it is cut off where it stands, so the hint says
 * so. Empty inherits the console's setting, which the panel names.
 */
export function ReplyLengthPanel({
  tenantId,
  agentId,
  write,
}: {
  tenantId: string;
  agentId: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const held = useReplyLength(tenantId, agentId);
  const save = useSetReplyLength(tenantId, agentId);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const [draft, setDraft] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);
  const id = useId();

  useEffect(() => {
    if (held.data) setDraft(held.data.max_reply_tokens ?? null);
  }, [held.data]);

  if (held.isLoading) return <Skeleton rows={1} />;
  if (held.error || !held.data) {
    return (
      <ProblemNotice
        error={held.error ?? new Error("This agent's reply length could not be read just now.")}
        onRetry={() => void held.refetch()}
      />
    );
  }
  const data = held.data;
  const disabled = !write.allowed;
  const inherited = data.max_reply_tokens == null;
  const submit = (value: number | null) => {
    setSaved(false);
    save.mutate({ max_reply_tokens: value }, { onSuccess: () => setSaved(true) });
  };

  return (
    <section aria-labelledby={`${id}-heading`} className="mt-8 space-y-3">
      <h3 id={`${id}-heading`} className="text-heading text-ink">
        Reply length
      </h3>
      <p className="max-w-prose text-body text-ink-muted">
        {inherited
          ? `Replies are held to ${String(data.effective)} tokens, the platform setting.`
          : `Replies are held to ${String(data.effective)} tokens, set for this agent. The platform setting is ${String(data.default)}.`}
      </p>
      <RestrictionNote reason={write.reason} />
      <form
        className="flex max-w-xl flex-wrap items-end gap-2"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit(draft);
        }}
      >
        <NumberField
          label="Longest reply, in tokens"
          hint={`${String(data.min)} to ${String(data.max)}. A reply that reaches it is cut off mid-sentence. Empty uses the platform setting.`}
          value={draft}
          onChange={(next) => {
            setSaved(false);
            setDraft(next);
          }}
          optional
          unit="tokens"
          min={data.min}
          max={data.max}
          step={1}
          largeStep={10}
          disabled={disabled}
          className="w-64"
        />
        <ActionButton
          type="submit"
          variant="primary-sm"
          status={save.variables?.max_reply_tokens !== null ? saveFeedback.status : "idle"}
          pendingLabel="Saving…"
          successLabel="Saved"
          disabled={disabled}
        >
          Save
        </ActionButton>
        {!inherited && (
          <ActionButton
            variant="secondary-sm"
            status={save.variables?.max_reply_tokens === null ? saveFeedback.status : "idle"}
            disabled={disabled}
            onClick={() => submit(null)}
          >
            Use the platform setting
          </ActionButton>
        )}
        {saved && (
          <span role="status" className="text-meta text-ink-muted">
            Saved. A live agent uses it from its next call.
          </span>
        )}
      </form>
      {save.error && <ProblemNotice error={save.error} />}
    </section>
  );
}
