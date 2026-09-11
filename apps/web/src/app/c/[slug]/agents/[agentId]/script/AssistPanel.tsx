"use client";

/**
 * DRAFT WITH AI — a plain-language description in, a whole structured script out.
 *
 * Split out of `ScriptBuilder.tsx` (UX-DOCTRINE §6). It is DISCLOSED (closed by default)
 * rather than always open, and that is a deliberate application of the disclosure test:
 * an owner uses it once, at the start, and never again — while the editor underneath is
 * what they come back to. `disclosure` is the server's own account of how the draft was
 * written and is rendered verbatim; nothing it produces reaches a call until Save, and
 * nothing reaches a LIVE call until Apply.
 */

import { useState } from "react";
import { Bot, Wand2 } from "lucide-react";

import {
  Card,
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import { useActAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useAssistScript, type CallScript } from "@/lib/api/script";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

export function AssistPanel({
  agentId,
  onDraft,
  disabled,
}: {
  agentId: string;
  onDraft: (script: CallScript) => void;
  disabled: boolean;
}) {
  const session = useClientSession();
  // This tenant's trade, not a clinic's — see `lib/verticalExamples.ts`.
  const eg = useVerticalExamples();
  const [description, setDescription] = useState("");
  const [open, setOpen] = useState(false);
  const assist = useAssistScript(session, agentId);
  /**
   * WHOSE ALLOWANCE THE DRAFT SPENDS. The route is `org:manage` (`script_routes.py:59`),
   * which a view-as operator now HOLDS (D-587) — and the same route then refuses them the
   * named act `billing.ai_assist` before the ownership check (`script_routes.py:229`),
   * because drafting runs the assistant on the CLIENT'S included allowance and support
   * work is never billed to the client. This panel had no gate at all, so an operator was
   * offered a Draft button whose only possible answer was a 403; a `staff` member, who
   * does not hold `org:manage`, was offered the same. Both now read the reason instead.
   */
  const write = useActAccess(
    session,
    "org:manage",
    "billing.ai_assist",
    "draft a script with AI",
  );

  const run = () => {
    assist.mutate(
      { description },
      {
        onSuccess: (r) => onDraft(r.script),
      },
    );
  };

  return (
    <Card
      title="Draft with AI"
      action={
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen((o) => !o)}>
          {open ? "Hide" : "Open"}
        </button>
      }
    >
      {open && (
        <div className="space-y-3">
          <p className="text-sm text-ink-muted">
            Describe your business and how you want calls handled. We will draft an opening
            line, steps and questions for you to review and edit — nothing goes live until you
            save and apply.
          </p>
          <RestrictionNote reason={write.reason} />
          <textarea
            className={FIELD}
            rows={4}
            disabled={!write.allowed}
            value={description}
            aria-label="Business description"
            onChange={(e) => setDescription(e.target.value)}
            placeholder={eg.scriptBrief}
          />
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              disabled={
                !write.allowed || assist.isPending || disabled || description.trim().length < 10
              }
              title={write.reason ?? undefined}
              onClick={run}
            >
              <Wand2 aria-hidden className="h-3.5 w-3.5" />
              {assist.isPending ? "Drafting…" : "Draft my script"}
            </button>
            {disabled && (
              <span className="text-xs text-ink-faint">
                Switch to the structured builder to use AI drafting.
              </span>
            )}
            {assist.data && (
              <span className="inline-flex items-center gap-1.5 text-xs text-ink-muted">
                <Bot aria-hidden className="h-3.5 w-3.5" />
                Draft loaded — review and edit below, then Save.
              </span>
            )}
          </div>
          {assist.data?.disclosure && (
            <NoticeBox tone="neutral" title="How this draft was written">
              {assist.data.disclosure}
            </NoticeBox>
          )}
          {assist.error && <ProblemNotice error={assist.error} />}
        </div>
      )}
    </Card>
  );
}
