"use client";

import { useState } from "react";

import { ProblemNotice, RestrictionNote } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useAgents } from "@/lib/api/agents";
import { useKbSources, useSubmitKnowledge } from "@/lib/api/kb";

import { AddDocument } from "./AddDocument";
import { AddKnowledgeForm } from "./AddKnowledgeForm";
import { SubmittedList } from "./SubmittedList";
import { UploadList } from "./UploadList";
import { StaffCurationSwitch, SubmissionConsequence } from "./permissions";
import { useKnowledgeCopilot } from "./copilot";

/**
 * Client-side knowledge (FLOWS §7).
 *
 * The screen is deliberately honest about the approval gate rather than hiding it: a
 * submission shows as "in review" and the copy says why. A client who does not know
 * their change is queued will submit it three more times, and the agent speaks under
 * their PE registration — the wait is a feature they should understand, not a delay
 * they should have to discover.
 *
 * The route is chrome and this is the screen (UX-DOCTRINE §6). The four subjects are
 * their own modules: `AddKnowledgeForm` (type a fact), `AddDocument` (send a file or a
 * page), `UploadList` and `SubmittedList` (what have I taught it), and `permissions`
 * (who may add, and what happens to what they add). What stays here is the state the
 * assistant declares and the two panels share.
 *
 * The screen renders no `<h1>`: the shell prints the page title from the nav list
 * (layout.tsx), and a second "Knowledge base" beside it is a visible duplicate.
 *
 * Submitting is `kb:write`, and an impersonating operator is refused it (D-22) — so the
 * control is disabled WITH the reason rather than left to answer 403. Reading
 * (`agents:read`) stays open, which is the whole point of "view as client": support can
 * see the knowledge base they are being asked about.
 *
 * **`staff` HOLDING `kb:write` IS AN ACCOUNT-BY-ACCOUNT ANSWER.** Since the founder's
 * "give the staff perms allowing option to owner", a staff member holds it exactly when
 * their own owner has switched staff curation on (`apps/api/kb/curation.py`), and
 * `/v1/me` reports the EFFECTIVE set — so `useWriteAccess` enables the form for them with
 * no special case here. The switch itself is `StaffCurationSwitch` in `permissions.tsx`.
 */
export function KnowledgeScreen() {
  const session = useClientSession();
  const sources = useKbSources(session);
  const agents = useAgents(session);
  const submit = useSubmitKnowledge(session);

  /**
   * D-22 read-only. Submitting is `kb:write` (kb/routes.py) — a MUTATING permission,
   * so an impersonating operator is refused it even though the `operator` role holds
   * it outright. Reading what an agent knows is `agents:read` and stays open, which is
   * the whole point of "view as client": support can see the knowledge base they are
   * being asked about, they just cannot add to it wearing the client's face.
   */
  const write = useWriteAccess(session, "kb:write", "add knowledge to this account");

  /**
   * THE OWNER'S SWITCH: may this account's `staff` members curate knowledge at all.
   *
   * Off for every account until an owner turns it on. Reading it is `org:read` so a staff
   * member is TOLD why the form above is closed to them; changing it is `org:manage`, so
   * `curationWrite` disables the control for everyone else — including a view-as operator,
   * because flipping a permission switch is itself a mutation (D-22).
   *
   * NOTE the interaction with `write` above and why nothing here duplicates it: `/v1/me`
   * reports the EFFECTIVE permission set, so a staff member in a switched-on account
   * already receives `kb:write` and `useWriteAccess` enables the form on its own. This
   * control decides the switch; it does not gate the form.
   */
  const curationWrite = useWriteAccess(session, "org:manage", "change who may add knowledge");

  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [agentId, setAgentId] = useState("");

  // Knowledge belongs to ONE agent. Silently posting it against `agents[0]` means a
  // client with two agents teaches the wrong one and waits for an answer the right
  // one will never give — so the choice is shown whenever there is one.
  const agentOptions = agents.data ?? [];
  const selectedAgentId = agentId || agentOptions[0]?.id || "";

  /**
   * Agent id → name, for the rows. Built from the SAME query the picker uses, so the
   * two halves of the screen cannot disagree about what an agent is called; read through
   * `lookup` because `agent_id` is a server string and `Object.fromEntries` produces an
   * object that inherits `Object.prototype` (src/lib/lookup.ts).
   */
  const agentNames: Record<string, string> = Object.fromEntries(
    agentOptions.map((agent) => [agent.id, agent.name]),
  );

  useKnowledgeCopilot({
    name,
    setName,
    body,
    setBody,
    selectedAgentId,
    setAgentId,
    agentOptions,
  });

  /**
   * There is nothing to teach — as a FACT from the server, not as "the list is empty
   * right now". While `/v1/agents` is in flight or has failed, `agentOptions` is also
   * empty, and telling a client they have no agents on the strength of a request that
   * never landed is the same lie as an empty state over a failed fetch.
   */
  const hasNoAgents = Boolean(agents.data) && agentOptions.length === 0;

  return (
    <div className="space-y-5 pb-12">
      {/* WHAT THIS SCREEN MAY PROMISE (`docs/TRD.md:948`): in-call retrieval is T0 and
          nothing else — approved facts are compiled into the agent's own prompt at
          publish time (`apps/api/agents/t0.py`). The agent does not read a document and
          does not look anything up while a caller is on the line, so the copy says
          "part of what it already knows" rather than anything retrieval-shaped. It is
          the faster arrangement, not the poorer one, and it is written that way.
          `tests/knowledgeApproval.test.tsx` pins the sentence and bans the shapes. */}
      <p className="text-sm text-ink-muted">
        What your agent knows. Everything you add is reviewed by your account manager,
        and once it is approved it becomes part of what the agent already knows when it
        picks up — hours, address, prices, the questions you get asked every day.
      </p>

      <RestrictionNote reason={write.reason} />

      <SubmissionConsequence />

      <StaffCurationSwitch write={curationWrite} />

      {sources.error && <ProblemNotice error={sources.error} onRetry={() => sources.refetch()} />}
      {/* Without this the form simply refused to submit and never said why: no agent
          list means no agent to teach, and the disabled button looked like a bug. */}
      {agents.error && <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />}
      {submit.error && <ProblemNotice error={submit.error} />}

      <div className="grid gap-5 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <AddKnowledgeForm
            agentOptions={agentOptions}
            selectedAgentId={selectedAgentId}
            onAgentId={setAgentId}
            hasNoAgents={hasNoAgents}
            name={name}
            onName={setName}
            body={body}
            onBody={setBody}
            submit={submit}
            canWrite={write.allowed}
            reason={write.reason}
          />

          {/* THE DOOR THE FOUNDER FOUND MISSING, beside the text form and not instead of
              it: "where is a client able to upload files or docs or links?". A short
              correction is still fastest typed; a price list is not. */}
          <div className="mt-5">
            <AddDocument
              agentId={selectedAgentId}
              agentName={agentOptions.length === 1 ? (agentOptions[0]?.name ?? null) : null}
              allowed={write.allowed}
              reason={write.reason}
            />
          </div>
        </div>

        {/* ONE right-hand column holding both lists, rather than two grid children.
            As siblings of the grid, "Submitted" would drop to a second row and sit under
            the form on the left instead of under the documents it belongs beside — and
            the two panels are one answer to one question ("what have I taught it"). */}
        <div className="space-y-5 lg:col-span-7">
          <UploadList agentNames={agentNames} />
          <SubmittedList agentNames={agentNames} sources={sources} />
        </div>
      </div>
    </div>
  );
}
