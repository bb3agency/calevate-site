"use client";

import { useState } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { Tabs } from "@/components/interior/tabs";
import { ProblemNotice, RestrictionNote } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useKbSources } from "@/lib/api/kb";

import { AddDocument } from "./AddDocument";
import { KnowledgeDelivery } from "./KnowledgeDelivery";
import { SourcesList } from "./SourcesList";
import { TeachBox } from "./TeachBox";
import { WhatItKnows } from "./WhatItKnows";
import { WhereItStruggled } from "./WhereItStruggled";
import { StaffCurationSwitch, SubmissionConsequence } from "./permissions";

/**
 * Client-side knowledge (FLOWS §7), shared by every agent of the business (D-689).
 *
 * One teach box at the top (type, photo or file, or say it; sorted into facts and rules for
 * review, founder decision 9), then three peer views: what the agents know (pinned facts
 * first), where they struggled on real calls (founder decision 11), and files and pages.
 *
 * The screen renders no `<h1>`: the shell prints the page title from the nav list.
 *
 * Adding is `kb:write`: the owner, `staff` whose owner switched curation on
 * (`apps/api/kb/curation.py`; `/v1/me` reports the effective set), and a view-as operator,
 * whose additions wait for review. Anyone else gets the reason beside the disabled control.
 */
export function KnowledgeScreen() {
  const session = useClientSession();
  const sources = useKbSources(session);

  /**
   * TEACHING IS `kb:write` AND NOTHING ELSE. Reading what an agent knows is `agents:read`
   * and stays open, which is the other half of "view as client": support can see the
   * knowledge base they are being asked about.
   */
  const write = useWriteAccess(session, "kb:write", "add knowledge to this account");

  /**
   * THE OWNER'S SWITCH: may this account's `staff` members curate knowledge at all.
   * Reading it is `org:read`; changing it is `org:manage`, so this disables the control for
   * everyone else, including a view-as operator (D-22).
   */
  const curationWrite = useWriteAccess(session, "org:manage", "change who may add knowledge");

  const [tab, setTab] = useState("knows");
  const [answering, setAnswering] = useState<{
    gapId: string | null;
    question: string;
    key: number;
  } | null>(null);

  return (
    <div className="max-w-4xl space-y-8 pb-12">
      <PageHeader description="What your agents know about your business, shared by every one of your agents. What you add reaches them without anyone approving it." />

      <RestrictionNote reason={write.reason} />
      {sources.error && <ProblemNotice error={sources.error} onRetry={() => sources.refetch()} />}

      <TeachBox allowed={write.allowed} reason={write.reason} answering={answering} />

      {/* Whether what was added has reached the phone (`apps/api/kb/delivery.py`). */}
      <KnowledgeDelivery />

      {/* Three peer views of one knowledge base (D-655). */}
      <Tabs
        label="Your business knowledge"
        items={[
          { value: "knows", label: "What it knows" },
          { value: "struggled", label: "Where it struggled" },
          { value: "files", label: "Files and pages" },
        ]}
        value={tab}
        onValueChange={setTab}
        panelClassName="pt-6"
        renderPanel={(current) =>
          current === "struggled" ? (
            <WhereItStruggled
              canWrite={write.allowed}
              onAddAnswer={(struggle) =>
                setAnswering({
                  gapId: struggle.gap_id ?? null,
                  question: struggle.question ?? struggle.topic,
                  key: Date.now(),
                })
              }
            />
          ) : current === "files" ? (
            <div className="space-y-10">
              <SubmissionConsequence />
              <AddDocument allowed={write.allowed} reason={write.reason} />
              <SourcesList sources={sources} only="files" />
            </div>
          ) : (
            <WhatItKnows canWrite={write.allowed} sources={sources} />
          )
        }
      />

      <StaffCurationSwitch write={curationWrite} />
    </div>
  );
}
