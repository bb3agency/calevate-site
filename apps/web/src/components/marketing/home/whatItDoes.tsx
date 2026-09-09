import {
  ArrowRight,
  CalendarCheck,
  Database,
  Filter,
  PhoneIncoming,
  PhoneOutgoing,
  Webhook,
} from "lucide-react";

import { Reveal } from "@/components/marketing/motion";
import { CARD, GRID } from "@/components/marketing/pageShell";

import { Band, Chapter } from "./band";

/**
 * CHAPTER 3 — what it does. Six jobs, benefit first, mechanism behind a disclosure.
 *
 * Unchanged in substance from band 05, and deliberately so: the rule the founder set is
 * that every card leads with what it does FOR YOU and the "how" is one `<details>` away.
 * That is the reason this chapter is `standard` weight rather than `anchor` — it is the
 * feature list, and a feature list is what a buyer reads AFTER they have accepted the
 * promise, not the thing that persuades them.
 *
 * The shipped surface behind each, in order:
 *  1. inbound answering — `apps/api/agents/models.py:43` (`AgentDirection`), 24/7 default
 *     per `apps/api/agents/business_hours.py`;
 *  2. outbound follow-up — `apps/api/campaigns/service.py` + the retry ladder in
 *     `apps/workers/campaign_dispatch.py:1147`; contacts are PASTED (there is no file input
 *     anywhere in this console, `grep 'type="file"' apps/web/src` returns nothing);
 *  3. qualification — `apps/api/crm/schemas.py:29`, `apps/workers/pipeline.py:179`;
 *  4. appointments and callbacks — the `calendar` action kind
 *     (`apps/api/actions/models.py:53`, `apps/api/actions/calendar.py`, gated by
 *     `calendar_configured()` — hence "once your Google account is connected"), and the
 *     in-call callback tool (`apps/voice-runtime/tool_routes.py:268` →
 *     `apps/api/callbacks/service.py`), which needs nothing connected;
 *  5. delivery — the signed outbound webhook (`X-Calevate-Signature` over
 *     `{timestamp}.{body}`, `apps/api/integrations/service.py:176`), the Sheets leg
 *     (`apps/workers/sheets_sync.py`) and the CSV export (`apps/api/crm/routes.py:1017`);
 *  6. knowledge — T0 and nothing else (`docs/TRD.md:948`): the facts a person approves are
 *     compiled into the agent's own prompt at publish time (`apps/api/agents/t0.py`,
 *     `apps/api/kb/service.py:437::approve_source`). There is no document upload —
 *     `POST /v1/kb/sources` takes TEXT and refuses `url`/`file` (`apps/api/kb/routes.py:44`)
 *     — so the card may not offer one, and says the better true thing instead.
 */

const CAPABILITIES: readonly {
  icon: typeof PhoneIncoming;
  title: string;
  benefit: string;
  detail: string;
}[] = [
  {
    icon: PhoneIncoming,
    title: "Answering",
    benefit: "Nobody rings out, whatever time it is",
    detail:
      "It picks up, answers what callers ask from what you approved, and writes down what " +
      "they wanted. An agent runs at every hour unless you tell it otherwise, and your " +
      "dashboard counts how many enquiries arrived after you closed.",
  },
  {
    icon: PhoneOutgoing,
    title: "Follow-up",
    benefit: "Every enquiry gets a first attempt",
    detail:
      "Paste in a list, or let a web enquiry become a call on its own. It works through " +
      "them in order, retries the no-answers on a ladder, and stops the moment you pause it.",
  },
  {
    icon: Filter,
    title: "Qualification",
    benefit: "Your team talks to qualified prospects first",
    detail:
      "Each caller comes back marked contacted, interested or hot — a fixed set of stages, " +
      "not a note somebody has to read and interpret. A hot lead alerts you while the " +
      "person is still thinking about it.",
  },
  {
    icon: CalendarCheck,
    title: "Appointments",
    benefit: "Callers leave the call with a time",
    detail:
      "The agent can book a callback during the call, and can put an appointment straight " +
      "into your calendar once your Google account is connected.",
  },
  {
    icon: Webhook,
    title: "Your own tools",
    benefit: "Your leads don’t get trapped inside Calevate",
    detail:
      "Send them to your CRM or a Google Sheet and keep the workflow your team already " +
      "has, or download the lot as a spreadsheet. Every delivery is logged and failures " +
      "are retried.",
  },
  {
    icon: Database,
    title: "Your answers",
    benefit: "It answers from what you approved, and nothing else",
    detail:
      "Your prices, timings and the questions you get asked every day are built into the " +
      "agent before it takes a call, so the answer comes back straight away. Nothing " +
      "reaches a caller until a person approves it.",
  },
];

export function WhatItDoes() {
  return (
    <Chapter tone="app">
      <Band
        id="capabilities"
        eyebrow="What it does"
        weight="standard"
        title="One AI receptionist. Several jobs."
        lede="Each of these is one thing off your team’s plate. Open a card if you want to know exactly how it works."
      >
        <div className={`${GRID} sm:grid-cols-2 lg:grid-cols-3`}>
          {CAPABILITIES.map(({ icon: Icon, title, benefit, detail }, index) => (
            <Reveal
              as="section"
              key={title}
              delay={(index % 3) * 0.06}
              className={`group ${CARD} transition-colors hover:border-brand/40`}
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                <Icon aria-hidden className="h-5 w-5" />
              </span>
              <p className="mt-5 text-xs font-semibold tracking-[0.14em] text-ink-faint uppercase">
                {title}
              </p>
              <h3 className="mt-1.5 text-[17px] font-semibold text-balance text-ink">
                {benefit}
              </h3>
              {/* The mechanism, one keystroke away. `<details>` rather than a built
                  accordion for the reason the FAQ records: it is the platform's own
                  disclosure widget, keyboard-operable and announced with no script at all —
                  and this page's rule is that it is finished without its bundle. */}
              <details className="mt-3">
                <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong [&::-webkit-details-marker]:hidden dark:text-brand-bright">
                  Learn more
                  <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                </summary>
                <p className="mt-2 text-sm text-pretty text-ink-muted">{detail}</p>
              </details>
            </Reveal>
          ))}
        </div>
      </Band>
    </Chapter>
  );
}
