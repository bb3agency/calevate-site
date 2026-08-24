"use client";

import { useState } from "react";
import {
  ClipboardCheck,
  Copy,
  HelpCircle,
  MicOff,
  ShieldAlert,
} from "lucide-react";

import {
  Card,
  EmptyState,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  Skeleton,
  formatCount,
} from "@/components/ui";
import { useCallerNotice, type CallerNotice } from "@/lib/api/callerNotice";
import { useClientSession } from "@/lib/api/session";

/**
 * The privacy notice a client owes their OWN callers (LEGAL-SURFACE F-8, D-179).
 *
 * The endpoint behind this shipped complete and reachable by nothing, which on this
 * particular surface is worse than an unbuilt feature: DPDP Rule 3 makes the notice the
 * CLIENT's obligation, while every fact it must state — which fields their agents
 * extract, how long each record is kept, which agents announce themselves — lives in our
 * database and on our screens. So the party who owes the notice could not see what it had
 * to say, and wrote it from memory or not at all.
 *
 * ## It is a DRAFT and the screen never lets that out of sight
 *
 * The disclaimer is rendered ABOVE the document and is also inside the markdown the
 * client copies, because a warning that lives only in the envelope stops travelling the
 * moment the text is pasted into a website. Both copies come from the server's
 * `DRAFT_WARNING` — this screen does not compose a second wording of it.
 *
 * ## The prose is not rebuilt here
 *
 * `notice_markdown` arrives rendered and is handed over verbatim. Re-deriving it from
 * `collected` and `retention` in the browser would put the wording — the part an advocate
 * reviews — outside the thing that was reviewed, and would give one legal document two
 * spellings. The structured lists ARE re-rendered, because a table a client can scan is
 * not the same artefact as the paragraph they publish.
 *
 * ## Two lists that are absences, and why they are named rather than counted
 *
 * `ai_disclosure_off` and `recording_notice_off` are the agents whose opening
 * announcements are switched off (D-163). With an announcement off, the obligation does
 * not disappear — it MOVES, onto this notice — so the client needs to know which agent,
 * not how many. An agent always answers truthfully when a caller asks outright, and that
 * is enforced server-side and cannot be withdrawn; the toggle only governs what is
 * VOLUNTEERED. The copy says exactly that, because "recording notice off" read alone
 * suggests a product that hides recording, which is not what it does.
 *
 * ## No `useWriteAccess` gate
 *
 * There is nothing to write. The endpoint asks for `org:read` precisely so a read-only
 * "view as client" support session (D-22) can open it while a client is on the phone
 * asking how to write their notice — gating the screen on write access would close the
 * case it was built for.
 */
export default function CallerNoticePage() {
  const session = useClientSession();
  const notice = useCallerNotice(session);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-ink">Your privacy notice</h1>
        <p className="max-w-3xl text-sm text-ink-muted">
          Indian data-protection law requires you to tell your callers, item by
          item, what you collect from them and how long you keep it. This is a
          draft, built from the details your agents collect, how long you keep
          each kind of record, and what your agents announce at the start of a call.
        </p>
      </header>

      {notice.isLoading ? (
        <Card title="Draft notice">
          <Skeleton rows={6} label="Loading your privacy notice" />
        </Card>
      ) : notice.isError ? (
        <ProblemNotice error={notice.error} />
      ) : notice.data ? (
        <NoticeBody notice={notice.data} />
      ) : null}
    </div>
  );
}

function NoticeBody({ notice }: { notice: CallerNotice }) {
  return (
    <div className="space-y-6">
      {/* The disclaimer is the server's sentence, rendered before anything it qualifies. */}
      <NoticeBox
        tone="warn"
        icon={<ShieldAlert aria-hidden className="h-4 w-4" />}
        title="This is a draft, not legal advice"
      >
        {notice.disclaimer}
      </NoticeBox>

      <Card
        title="What you collect"
        action={
          <span className="text-xs text-ink-faint">
            {formatCount(notice.collected.length)} items
          </span>
        }
      >
        {notice.collected.length === 0 ? (
          <EmptyState
            title="Nothing itemised yet"
            hint="Once an agent is live and set up to collect details from calls, every detail it captures appears here."
          />
        ) : (
          <ul className="divide-y divide-line">
            {notice.collected.map((item) => (
              <li
                key={`${item.what}::${item.why}`}
                className="py-3 first:pt-0 last:pb-0"
              >
                <p className="text-sm font-medium text-ink">{item.what}</p>
                <p className="mt-0.5 text-sm text-ink-muted">{item.why}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="How long you keep it">
        {notice.retention.length === 0 ? (
          <EmptyState
            title="Nothing set yet"
            hint="How long each kind of record is kept is set up with you when your account is created."
          />
        ) : (
          <ul className="divide-y divide-line">
            {notice.retention.map((line) => (
              <li
                key={line.what}
                className="flex items-baseline justify-between gap-4 py-3 first:pt-0 last:pb-0"
              >
                <span className="text-sm text-ink">{line.what}</span>
                <span className="text-sm tabular-nums text-ink-muted">
                  {formatCount(line.days)} days
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <AnnouncementsOff notice={notice} />

      {notice.open_questions.length > 0 ? (
        <Card title="Only you can answer these">
          <p className="mb-3 text-sm text-ink-muted">
            The draft leaves these blank. They are facts about your business
            that we do not hold.
          </p>
          <ul className="space-y-2">
            {notice.open_questions.map((question) => (
              <li key={question} className="flex gap-2 text-sm text-ink">
                <HelpCircle
                  aria-hidden
                  className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint"
                />
                <span>{question}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <DraftDocument markdown={notice.notice_markdown} />
    </div>
  );
}

/**
 * The two announcement lists, rendered only when they are non-empty.
 *
 * Rendered TOGETHER rather than as two cards because a client reads them as one question
 * — "what does my notice have to carry that my agents do not say out loud?" — and they
 * are separate obligations under separate regimes (D-163), so they are separately
 * labelled inside it.
 */
function AnnouncementsOff({ notice }: { notice: CallerNotice }) {
  const groups = [
    {
      key: "ai",
      label: "These agents do not announce that they are AI",
      agents: notice.ai_disclosure_off,
    },
    {
      key: "recording",
      label: "These agents do not announce that the call is recorded",
      agents: notice.recording_notice_off,
    },
  ].filter((group) => group.agents.length > 0);

  if (groups.length === 0) return null;

  return (
    <Card title="Announcements your agents do not make">
      {/* Stated before the lists, because "disclosure off" read alone describes a product
          that conceals — and this one cannot. The truthful answer is enforced server-side
          on every published agent and no setting withdraws it. */}
      <p className="mb-3 text-sm text-ink-muted">
        Every agent still answers truthfully whenever a caller asks whether they
        are speaking to an AI or whether the call is recorded — that cannot be
        switched off. These settings govern only what is said unprompted at the
        start of a call, so where one is off, your written notice is where the
        obligation lands.
      </p>
      <div className="space-y-4">
        {groups.map((group) => (
          <div key={group.key}>
            <p className="flex items-center gap-2 text-xs font-medium text-ink-muted">
              <MicOff aria-hidden className="h-3.5 w-3.5" />
              {group.label}
            </p>
            <ul className="mt-1.5 flex flex-wrap gap-1.5">
              {group.agents.map((name) => (
                <li
                  key={name}
                  className="rounded-md bg-surface-muted px-2 py-1 text-sm text-ink"
                >
                  {name}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  );
}

/**
 * The document itself, as the server rendered it, with a copy button.
 *
 * Shown as PLAIN TEXT rather than parsed into HTML on purpose. What the client needs is
 * the source they paste into their own site or hand to their advocate; rendering it would
 * mean this screen decides how the document looks, and the thing on the clipboard would
 * no longer be the thing on the screen.
 */
function DraftDocument({ markdown }: { markdown: string }) {
  const [copied, setCopied] = useState(false);

  // `navigator.clipboard` is absent in insecure contexts and in the test environment, so
  // failure is a state the button reports rather than an exception that reaches the page.
  // The textarea below is the fallback that always works: the text is selectable.
  const copy = () => {
    void navigator.clipboard
      ?.writeText(markdown)
      .then(() => setCopied(true))
      .catch(() => setCopied(false));
  };

  return (
    <Card
      title="The draft"
      action={
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={copy}>
          {copied ? (
            <ClipboardCheck aria-hidden className="h-3.5 w-3.5" />
          ) : (
            <Copy aria-hidden className="h-3.5 w-3.5" />
          )}
          {copied ? "Copied" : "Copy"}
        </button>
      }
    >
      <p className="mb-3 text-sm text-ink-muted">
        Give this to your advocate to review before you publish it.
      </p>
      <ScrollRegion
        label="Draft privacy notice"
        className="max-h-96 overflow-y-auto"
      >
        <pre className="whitespace-pre-wrap break-words font-mono text-xs text-ink">
          {markdown}
        </pre>
      </ScrollRegion>
    </Card>
  );
}
