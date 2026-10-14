"use client";

import { useEffect, useId, useState } from "react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
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
  const [draft, setDraft] = useState("");
  const [saved, setSaved] = useState(false);
  const id = useId();

  useEffect(() => {
    if (held.data) setDraft(held.data.max_reply_tokens == null ? "" : String(held.data.max_reply_tokens));
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
          submit(draft.trim() === "" ? null : Number(draft));
        }}
      >
        <div>
          <label htmlFor={`${id}-tokens`} className={FIELD_LABEL}>
            Longest reply, in tokens
          </label>
          <input
            id={`${id}-tokens`}
            aria-describedby={`${id}-hint`}
            className={FIELD}
            type="number"
            inputMode="numeric"
            step="10"
            min={data.min}
            max={data.max}
            placeholder={String(data.default)}
            value={draft}
            disabled={disabled}
            onChange={(event) => {
              setSaved(false);
              setDraft(event.target.value);
            }}
          />
          <span id={`${id}-hint`} className={FIELD_HINT}>
            {`${String(data.min)} to ${String(data.max)}. A reply that reaches it is cut off mid-sentence. Empty uses the platform setting.`}
          </span>
        </div>
        <button type="submit" className={PRIMARY_BUTTON_SM} disabled={disabled || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
        {!inherited && (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={disabled || save.isPending}
            onClick={() => submit(null)}
          >
            Use the platform setting
          </button>
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
