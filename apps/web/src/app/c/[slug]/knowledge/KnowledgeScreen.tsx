"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { QuestionsToAnswer } from "@/components/improvement/QuestionsToAnswer";
import { Tabs } from "@/components/interior/tabs";
import { ProblemNotice, RestrictionNote, formatCount } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useKbNotes } from "@/lib/api/kb";
import { QUESTION_PARAM, useTeachQuestions } from "@/lib/api/teachQuestions";

import { AddArea } from "./AddArea";
import { WhatItKnows } from "./WhatItKnows";
import { StaffCurationSwitch } from "./permissions";

/**
 * "What your agents know" (D-874): the business's knowledge (FLOWS §7), shared by every
 * agent of the business (D-689). The route keeps its old path, `/c/{slug}/knowledge`, so
 * every link, bookmark and copilot route that names it still lands here.
 *
 * One Add area at the top (write it, send a file, save a link), then two views: everything
 * the agents were given, grouped by kind with each item's plain status, and the questions
 * they need answered (D-893), the same list as an agent's Training tab, account-wide. A link
 * with `?question=pricing` opens that view on that question.
 *
 * The screen renders no `<h1>`: the shell prints the page title from the nav list.
 *
 * Adding is `kb:write`: the owner, `staff` whose owner switched curation on
 * (`apps/api/kb/curation.py`; `/v1/me` reports the effective set), and a view-as operator,
 * whose additions wait for review. Anyone else gets the reason beside the disabled control.
 */
export function KnowledgeScreen() {
  const session = useClientSession();
  const notes = useKbNotes(session);
  const questions = useTeachQuestions(session);
  const params = useSearchParams();
  const [focus, setFocus] = useState(params.get(QUESTION_PARAM));

  /**
   * TEACHING IS `kb:write` AND NOTHING ELSE. Reading what an agent knows is `agents:read`
   * and stays open, which is the other half of "view as client": support can see what the
   * agents were given while they are asked about it.
   */
  const write = useWriteAccess(session, "kb:write", "teach your agents on this account");

  /**
   * THE OWNER'S SWITCH: may this account's `staff` members add things here at all.
   * Reading it is `org:read`; changing it is `org:manage`, so this disables the control for
   * everyone else, including a view-as operator (D-22).
   */
  const curationWrite = useWriteAccess(session, "org:manage", "change who may add things here");

  const [tab, setTab] = useState(
    focus !== null || params.get("tab") === "questions" ? "questions" : "knows",
  );

  // A count only from a read that answered: while it is out or after it failed, the tab
  // says nothing about how many there are, and its panel says why.
  const open = questions.isSuccess && questions.data.open_count > 0 ? questions.data.open_count : null;

  return (
    <div className="max-w-4xl space-y-8 pb-12">
      <PageHeader description="What your agents tell callers. All agents share it." />

      <RestrictionNote reason={write.reason} />
      {notes.error && <ProblemNotice error={notes.error} onRetry={() => notes.refetch()} />}

      <AddArea allowed={write.allowed} reason={write.reason} />

      <Tabs
        label="What your agents know"
        items={[
          { value: "knows", label: "What they know" },
          {
            value: "questions",
            label: open ? `Questions to answer · ${formatCount(open)}` : "Questions to answer",
          },
        ]}
        value={tab}
        onValueChange={setTab}
        panelClassName="pt-6"
        renderPanel={(current) =>
          current === "questions" ? (
            <QuestionsToAnswer focus={focus} />
          ) : (
            <WhatItKnows
              canWrite={write.allowed}
              notes={notes}
              onAnswerQuestions={(key) => {
                setFocus(key);
                setTab("questions");
              }}
            />
          )
        }
      />

      <div className="border-t border-line pt-6">
        <StaffCurationSwitch write={curationWrite} />
      </div>
    </div>
  );
}
