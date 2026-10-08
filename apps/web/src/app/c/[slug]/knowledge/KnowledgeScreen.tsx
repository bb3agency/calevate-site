"use client";

import { useState } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { ProblemNotice, RestrictionNote } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useKbSources, useSubmitKnowledge } from "@/lib/api/kb";

import { AddDocument } from "./AddDocument";
import { KnowledgeDelivery } from "./KnowledgeDelivery";
import { AddKnowledgeForm } from "./AddKnowledgeForm";
import { SourcesList } from "./SourcesList";
import { StaffCurationSwitch, SubmissionConsequence } from "./permissions";
import { useKnowledgeCopilot } from "./copilot";

/**
 * Client-side knowledge (FLOWS §7).
 *
 * The knowledge belongs to the BUSINESS, not to one agent (D-689): every agent on the
 * account answers from the same facts, documents and pages. So nothing here asks which
 * agent to teach, and nothing waits for an agent to exist — what is added before the
 * first agent is published reaches it when it is.
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
 * Submitting is `kb:write` — held by the OWNER role, by a `staff` member whose owner has
 * switched curation on, and (since D-587) by a view-as operator, whose submission goes for
 * review like any other. Anyone else gets the reason beside the disabled control rather
 * than a 403 after the click. Reading (`agents:read`) stays open, which is the other half
 * of "view as client": support can see the knowledge base they are being asked about.
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
  const submit = useSubmitKnowledge(session);

  /**
   * SUBMITTING IS `kb:write` AND NOTHING ELSE — the act is on the other route.
   *
   * ⚠ THIS BRIEFLY ASKED `useActAccess(..., "kb.self_approve", ...)` AND THAT WAS ONE
   * REFUSAL TOO MANY. The withheld act sits on `POST /v1/kb/uploads/{id}/confirm`
   * (`apps/api/kb/uploads.py:722`), the APPROVAL; this form posts `POST /v1/kb/sources`,
   * which takes a view-as operator's submission and files it for review with
   * `auto_approve=False` (`kb/routes.py:266`, `uploads.may_self_approve`). Refusing it
   * here disabled a write the server accepts — and "a knowledge base with a stale price"
   * is one of the four support jobs D-587 names as its reason for existing. The gate on
   * the approval lives in `UploadList.ExtractedText`, where that button is.
   *
   * Reading what an agent knows is `agents:read` and stays open, which is the other half
   * of "view as client": support can see the knowledge base they are being asked about.
   */
  const write = useWriteAccess(
    session,
    "kb:write",
    "add knowledge to this account",
  );

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
  const curationWrite = useWriteAccess(
    session,
    "org:manage",
    "change who may add knowledge",
  );

  const [name, setName] = useState("");
  const [body, setBody] = useState("");

  useKnowledgeCopilot({ name, setName, body, setBody });

  return (
    <div className="space-y-6 pb-12">
      {/* WHAT THIS SCREEN MAY PROMISE: approved facts are compiled into the agent's own
          prompt at publish time, so the copy says "part of what it already knows" rather
          than anything retrieval-shaped (`tests/knowledgeApproval.test.tsx` pins it). */}
      <PageHeader
        description="Your business knowledge — every one of your agents answers from it. What you add goes to all your agents once it has been read, without anyone approving it, and becomes part of what the agent already knows when it picks up — hours, address, prices, the questions you get asked every day."
      />

      <RestrictionNote reason={write.reason} />

      {sources.error && (
        <ProblemNotice error={sources.error} onRetry={() => sources.refetch()} />
      )}
      {submit.error && <ProblemNotice error={submit.error} />}

      {/* THE DROP ZONE: everything a client can teach, in one place at the top — a file or
          a photo, a web page, or a fact typed in. */}
      <section
        aria-label="Add to your business knowledge"
        className="space-y-4 rounded-card border border-line bg-surface p-4 sm:p-5"
      >
        <SubmissionConsequence />
        <div className="grid gap-6 lg:grid-cols-2 lg:gap-8">
          <AddDocument allowed={write.allowed} reason={write.reason} />
          <div className="lg:border-l lg:border-line lg:pl-8">
            <AddKnowledgeForm
              name={name}
              onName={setName}
              body={body}
              onBody={setBody}
              submit={submit}
              canWrite={write.allowed}
              reason={write.reason}
            />
          </div>
        </div>
      </section>

      {/* Whether what was added has reached the phone — the question a client arrives
          with when the agent has not caught up (`apps/api/kb/delivery.py`). */}
      <KnowledgeDelivery />

      <SourcesList sources={sources} />

      <StaffCurationSwitch write={curationWrite} />
    </div>
  );
}
