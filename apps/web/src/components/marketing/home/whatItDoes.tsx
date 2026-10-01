import type { ReactNode } from "react";

import { Band, Chapter, HOME } from "./band";
import {
  AnsweringVignette,
  AnswersVignette,
  AppointmentsVignette,
  FollowUpVignette,
  QualificationVignette,
  ToolsVignette,
} from "./mockups/capabilityVignettes";
import { CallDetailMock } from "./mockups/featureMockups";
import { MockStage } from "./mockups/stage";

/**
 * CHAPTER 3 — what it does: one opened call, then six jobs, each led by what it does FOR
 * YOU and shown on the screen where it happens. `standard` weight rather than `anchor`:
 * a feature list is what a buyer reads AFTER they have accepted the promise. The
 * mechanism sentence is visible rather than behind a "Learn more" disclosure — with a
 * picture of the job beside it, two sentences no longer need hiding.
 *
 * The shipped surface behind each, in order:
 *  1. inbound answering — `apps/api/agents/models.py:43` (`AgentDirection`), 24/7 default
 *     per `apps/api/agents/business_hours.py`;
 *  2. outbound follow-up — `apps/api/campaigns/service.py` + the retry ladder in
 *     `apps/workers/campaign_dispatch.py:1147`; contacts are PASTED — the CAMPAIGN screens
 *     take no file. The ground is the CAMPAIGN screens specifically: the console does have
 *     a file input (`app/c/[slug]/knowledge/AddDocument.tsx`, D-534), so "no file input
 *     anywhere in this console" is not available as a reason;
 *  3. qualification — `apps/api/crm/schemas.py:29`, `apps/workers/pipeline.py:179`;
 *  4. appointments and callbacks — the `calendar` action kind
 *     (`apps/api/actions/models.py:53`, `apps/api/actions/calendar.py`, gated by
 *     `calendar_configured()` — hence "once your Google account is connected"), and the
 *     in-call callback tool (`apps/voice-runtime/tool_routes.py:268` →
 *     `apps/api/callbacks/service.py`), which needs nothing connected;
 *  5. delivery — the signed outbound webhook (`X-Calevate-Signature` over
 *     `{timestamp}.{body}`, `apps/api/integrations/service.py:176`), the Sheets leg
 *     (`apps/workers/sheets_sync.py`) and the CSV export (`apps/api/crm/routes.py:1017`);
 *  6. knowledge — the facts a person approves are compiled into the agent's own prompt at
 *     publish time (`apps/api/agents/t0.py`, `apps/api/kb/service.py::approve_source`), and
 *     THAT IS NO LONGER THE WHOLE OF IT. Re-read 15 Sep 2026: `POST /v1/kb/sources` is
 *     still text-only (`kb/service.py:77`), but `POST /v1/kb/uploads` takes a document or
 *     a link (D-534), and `PIPECAT_CAPABILITIES.knowledge_base` is `True` with an
 *     in-process pack search registered as a call tool (`docs/PIPECAT-MIGRATION.md` §8.1).
 *     `docs/TRD.md:802` still says
 *     "in-call retrieval is T0 and nothing else"; `docs/` is authoritative, so the conflict
 *     is FLAGGED rather than resolved here. The card's copy is UNDERSTATED as a result
 *     rather than false, and understating is the safe direction on a CPA 2019
 *     representation — it is left for whoever re-writes this chapter with the docs set
 *     reconciled.
 */

/**
 * Each card's picture is a piece of the console doing that job (`mockups/
 * capabilityVignettes.tsx`) — not an icon in a tile, which says nothing a reader would
 * miss. Spans vary so the grid reads as six different jobs rather than one card six times.
 */
const CAPABILITIES: readonly {
  title: string;
  benefit: string;
  body: string;
  figure: ReactNode;
  span: string;
}[] = [
  {
    title: "Answering",
    benefit: "Nobody rings out, whatever time it is",
    body:
      "It picks up, answers from what you approved, and writes down what they wanted. An " +
      "agent runs at every hour unless you tell it otherwise.",
    figure: <AnsweringVignette />,
    span: "lg:col-span-4",
  },
  {
    title: "Follow-up",
    benefit: "Every enquiry gets a first attempt",
    body:
      "Paste in a list, or let a web enquiry become a call on its own. No-answers are " +
      "retried on a ladder, and it stops the moment you pause it.",
    figure: <FollowUpVignette />,
    span: "lg:col-span-2",
  },
  {
    title: "Qualification",
    benefit: "Your team talks to qualified prospects first",
    body:
      "Each caller comes back on a fixed set of stages, not a note somebody has to " +
      "interpret. A hot lead alerts you while they are still thinking about it.",
    figure: <QualificationVignette />,
    span: "lg:col-span-2",
  },
  {
    title: "Appointments",
    benefit: "Callers leave the call with a time",
    body:
      "The agent can book a callback during the call, and can put an appointment straight " +
      "into your calendar once your Google account is connected.",
    figure: <AppointmentsVignette />,
    span: "lg:col-span-2",
  },
  {
    title: "Your own tools",
    benefit: "Your leads don’t get trapped inside Calevate",
    body:
      "Send them to your CRM or a Google Sheet, or download the lot as a spreadsheet. " +
      "Every delivery is logged and failures are retried.",
    figure: <ToolsVignette />,
    span: "lg:col-span-2",
  },
  {
    title: "Your answers",
    benefit: "It answers from what you approved, and nothing else",
    body:
      "Your prices, timings and the questions you get asked every day are built into the " +
      "agent before it takes a call, so the answer comes back straight away. Nothing " +
      "reaches a caller until a person approves it.",
    figure: <AnswersVignette />,
    span: "lg:col-span-6",
  },
];

export function WhatItDoes() {
  return (
    <Chapter tone="app">
      <Band
        id="capabilities"
        eyebrow="What it does"
        weight="standard"
        split
        title="One AI receptionist. Several jobs."
        lede="Each of these is one thing off your team’s plate, shown on the screen where it happens."
      >
        <MockStage
          label="Illustration of an opened call: the Telugu conversation on one side; the summary, the captured details and the key points written from it on the other."
          className={`${HOME.contentGap} mx-auto max-w-5xl`}
        >
          <CallDetailMock />
        </MockStage>

        <div className={`mt-10 grid ${HOME.itemGap} sm:mt-14 sm:grid-cols-2 lg:grid-cols-6`}>
          {CAPABILITIES.map(({ title, benefit, body, figure, span }) => (
            <section
              key={title}
              className={`flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card ${
                span === "lg:col-span-6" ? "lg:flex-row" : ""
              } ${HOME.panelLift} ${span}`}
            >
              <div className={`p-5 sm:p-7 ${span === "lg:col-span-6" ? "lg:w-1/2 lg:self-center" : ""}`}>
                <span className="text-base font-medium text-brand-strong">{title}</span>
                <h3 className={`mt-1.5 ${HOME.itemTitle} font-semibold text-balance text-ink`}>{benefit}</h3>
                <p className={`mt-2 max-w-xl text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</p>
              </div>
              <MockStage
                className={`mt-auto border-t border-line bg-app/70 p-4 sm:p-6 ${
                  span === "lg:col-span-6" ? "lg:mt-0 lg:w-1/2 lg:border-t-0 lg:border-l" : ""
                }`}
              >
                {figure}
              </MockStage>
            </section>
          ))}
        </div>
      </Band>
    </Chapter>
  );
}
