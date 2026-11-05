"use client";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Disclosure, formatCountOf } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useUseCallInstructions, type KbUpload } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";

/**
 * WHAT A FILE TELLS THE AGENT TO DO ON A CALL ("ask whether now is a good time"). These are
 * kept out of what the agents look up, because an instruction that is only found when a
 * caller's question happens to match it is not followed; they belong in the call script.
 * One button hands them to the script as a suggestion the owner reviews on the Script page,
 * so nothing reaches a live agent from here.
 *
 * `agent` names the one agent whose script it goes to (the agent's Training tab); without
 * it, every agent gets the suggestion (the Knowledge page).
 */
export function CallInstructions({ upload, agent }: { upload: KbUpload; agent?: { id: string; name: string } }) {
  const session = useClientSession();
  // A script change is the owner's (`org:manage`, as on the Script page).
  const write = useWriteAccess(session, "org:manage", "change call scripts");
  const items = upload.call_instructions ?? [];
  if (items.length === 0) return null;
  const count = formatCountOf(items.length, "call instruction");
  return (
    <div className="space-y-3 rounded-lg border border-line p-4">
      <p className="text-body text-ink">
        {count} in {upload.name}. Not used as facts.
      </p>
      <Disclosure variant="inline" headingLevel={4} title="See them">
        <ul className="divide-y divide-line">
          {items.map((item, index) => (
            <li key={`${index}-${item.section ?? ""}`} className="py-2">
              {item.section ? <p className="text-meta font-medium text-ink-muted">{item.section}</p> : null}
              <p className="whitespace-pre-line text-body text-ink [overflow-wrap:anywhere]">{item.text}</p>
            </li>
          ))}
        </ul>
      </Disclosure>
      {write.allowed ? <UseButton upload={upload} agent={agent} /> : null}
    </div>
  );
}

function UseButton({ upload, agent }: { upload: KbUpload; agent?: { id: string; name: string } }) {
  const session = useClientSession();
  const send = useUseCallInstructions(session);
  const feedback = useActionFeedback(send, {
    errorDisplay: "toast",
    successToast: agent ? `Suggestion on ${agent.name}'s Script page soon` : "Suggestion on each Script page soon",
  });
  return (
    <ActionButton
      variant="secondary-sm"
      status={feedback.status}
      pendingLabel="Sending…"
      successLabel="Sent"
      onClick={() => feedback.run({ uploadId: upload.id, agentId: agent?.id })}
    >
      {agent ? `Use in ${agent.name}'s script` : "Use in call scripts"}
    </ActionButton>
  );
}
