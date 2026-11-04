"use client";

/**
 * AN ACTION SET UP TO RUN AFTER THE CALL, and where that work lives now.
 *
 * New actions run during the call only: after-call work is a Follow-up, and call results
 * reach a sheet or the client's own system from Integrations. An older after-call action
 * keeps running until its owner moves it, so nothing a client relied on stops silently.
 *
 * The move is never automatic. Setting up the Follow-up or the destination and leaving
 * this action on would send twice, so the notice says to switch this one off after, and
 * that switch is the one at the top of the view. A CRM record has no Integrations
 * destination, so its move is one button that keeps it and runs it during the call.
 */

import Link from "next/link";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NoticeBox, ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { useUpdateAction, type ActionTool } from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";

import { afterCallHome } from "./jobs";
import { KINDS, fromParam, toParam } from "./params";

export function AfterCallMove({
  tool,
  agentId,
  session,
}: {
  tool: ActionTool;
  agentId: string;
  session: Session;
}) {
  const { href } = useClientRealm();
  const update = useUpdateAction(session, agentId);
  const feedback = useActionFeedback(update, { errorDisplay: "inline" });
  const home = afterCallHome(tool);
  const kind = KINDS.find((k) => k === tool.kind);

  if (home === "during_call" && kind !== undefined) {
    return (
      <NoticeBox
        tone="info"
        title="This runs after each call"
        action={
          <ActionButton
            type="button"
            status={feedback.status}
            successLabel="Moved"
            onClick={() =>
              update.mutate({
                toolId: tool.id,
                body: {
                  kind,
                  provider: tool.provider,
                  name: tool.name,
                  description: tool.description,
                  trigger: "during_call",
                  pre_call_message: tool.pre_call_message,
                  credential_id: tool.credential_id,
                  params: tool.params.map((p) => toParam(fromParam(p))),
                  config: tool.config,
                },
              })
            }
          >
            Run it during the call
          </ActionButton>
        }
      >
        Actions now run while the caller is on the line.
        {update.isError ? <ProblemNotice error={update.error} /> : null}
      </NoticeBox>
    );
  }

  const integrations = home === "integrations";
  return (
    <NoticeBox
      tone="info"
      title="This runs after each call"
      action={
        <Link
          className={SECONDARY_BUTTON_SM}
          href={href(`/c/${session.orgSlug}/${integrations ? "integrations" : "follow-ups"}`)}
        >
          {integrations ? "Set it up in Integrations" : "Make a Follow-up"}
        </Link>
      }
    >
      {integrations ? "Call results now go out from Integrations." : "After-call steps now live in Follow-ups."}{" "}
      Then turn this one off, so nothing is sent twice.
    </NoticeBox>
  );
}
