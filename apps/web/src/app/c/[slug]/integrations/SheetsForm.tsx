"use client";

import { useState } from "react";

import {
  Card,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { ApiProblem, type Session } from "@/lib/api/client";
import type { WriteAccess } from "@/lib/api/hooks";
import {
  SHEETS_UNAVAILABLE_CODE,
  useCreateSheetsEndpoint,
  type OutboundEvent,
} from "@/lib/api/integrations";

import { EventChoices, INPUT } from "./EventChoices";

const SUBMIT = PRIMARY_BUTTON;


/**
 * "You cannot send to a Google Sheet from this account" — rendered ONCE, for the two
 * different moments the screen can learn it.
 *
 * One component, because two copies of this card is how the pre-emptive state and the
 * post-refusal state start telling a client two different stories about one fact. The
 * words differ, and only the words: when the server has spoken they are the SERVER's
 * (`title`/`detail` and `remediation` verbatim), and when it has only sent a boolean they
 * are ours, saying the same thing.
 *
 * Deliberately NOT an error: `tone="neutral"`, no `role="alert"`, no retry. This is a
 * founder/ops decision, and "try again" is not the remediation for a capability the
 * deployment does not have. Deliberately NOT a disabled button either — a dead control
 * costs a client a support ticket to learn what one sentence tells them, which is the
 * argument the verification screen's "Where your calling number comes from" card already
 * makes.
 */
export function SheetsUnavailable({
  headline,
  remediation,
  footnote,
}: {
  headline: string;
  remediation: string;
  footnote: string;
}) {
  return (
    <Card title="Send events to a Google Sheet">
      <NoticeBox tone="neutral" title={headline}>
        <p className="mt-1">{remediation}</p>
        <p className="mt-2 text-xs opacity-80">{footnote}</p>
      </NoticeBox>
    </Card>
  );
}

/**
 * Deliver events to a Google Sheet — D-23's second transport, reachable from a screen at
 * last.
 *
 * THE REFUSAL IS STILL THE INTERESTING PART. `create_sheets_endpoint` checks
 * `sheets_delivery_available()` before it writes anything, and on a deployment with no
 * Google service account it refuses with `sheets_delivery_unavailable`. That is a
 * FOUNDER/OPS decision — the route's own argument is that a checkbox for a transport that
 * cannot deliver recreates the "silently never delivers" defect the sheets work removed —
 * and it is the state EVERY deployment is in today.
 *
 * Three ways to render it were on the table:
 *
 * 1. Hide the form until a capability flag says otherwise.
 * 2. Disable the button with a locally-written reason. That is a second copy of a server
 *    rule, and the copy is what drifts.
 * 3. Offer it, and when the server refuses, REPLACE the form with the server's own words.
 *
 * This screen used to do (3) alone, because (1) had nothing to read: no endpoint published
 * `sheets_delivery_available`, so hiding would have been a guess. It now does (1) AND (3),
 * and they are not two answers to one question — they are the answers to two:
 *
 * - (1) decides whether to OFFER the form, from the server's own selector on
 *   `EndpointOptions`. Where the capability is false this component is not rendered at
 *   all; the page puts `SheetsUnavailable` in its place.
 * - (3) below stays because the capability is a HINT and never the check. It is read once
 *   and cached for half an hour, so an operator turning Sheets off mid-session leaves this
 *   screen optimistic and wrong — and the server refuses anyway, which is what the branch
 *   below renders. Deleting it would make the screen's optimism the check.
 *
 * (2) is still refused. Every OTHER refusal this route can produce — an unparseable sheet
 * reference, an event with no column layout — keeps the form on screen and renders through
 * `ProblemNotice`, because those the client can fix in the field they are looking at.
 */
export function SheetsForm({
  session,
  catalogue,
  write,
}: {
  session: Session;
  catalogue: string[];
  write: WriteAccess;
}) {
  const create = useCreateSheetsEndpoint(session);
  const [spreadsheet, setSpreadsheet] = useState("");
  const valid = useFormValidation();
  const [worksheet, setWorksheet] = useState("");
  const [events, setEvents] = useState<OutboundEvent[]>(["lead.created"]);

  // The one refusal that is a statement about the DEPLOYMENT rather than about this
  // request, read off the problem's stable machine code rather than off its prose.
  //
  // Reachable only when the published capability said `true` and the server disagreed —
  // a capability read before an operator switched Sheets off, or a console talking to a
  // deployment that changed under it. Rare, and kept precisely because it is the seam
  // where the server, not this screen, is proved to be the authority.
  const unavailable =
    create.error instanceof ApiProblem && create.error.code === SHEETS_UNAVAILABLE_CODE
      ? create.error
      : null;

  if (unavailable) {
    return (
      <SheetsUnavailable
        headline={unavailable.message}
        remediation={
          unavailable.remediation ??
          "Set up a delivery to your own system above instead, or ask us to enable Google Sheets for your account."
        }
        footnote="Nothing was created, so there is nothing to undo. Reload this page once we have told you Sheets is switched on for your account."
      />
    );
  }

  return (
    <Card title="Send events to a Google Sheet">
      <p className="-mt-2 text-xs text-ink-faint">
        We append a row per event. Share the sheet with the Google account we give you —
        until we connect it on our side, deliveries appear as failures below.
      </p>
      {create.error && (
        <div className="mt-3">
          <ProblemNotice error={create.error} />
        </div>
      )}
      {create.data && (
        <div className="mt-3">
          <NoticeBox tone={create.data.credential_attached ? "ok" : "warn"} title="Sheet added">
            <p className="mt-1">
              Writing to sheet <code>{create.data.spreadsheet_id}</code>, tab{" "}
              <strong>{create.data.worksheet}</strong>.{" "}
              {create.data.credential_attached
                ? "The Google connection is ready, so the next event lands in it."
                : "We haven't connected to Google yet, so deliveries will be recorded as failures until we connect it — that is us, not you."}
            </p>
          </NoticeBox>
        </div>
      )}
      <form
        className="mt-3 space-y-3"
        noValidate
        onSubmit={valid.onSubmit(() => {
          create.mutate(
            {
              spreadsheet,
              events,
              // An empty tab name is not a tab name. The server strips it to the same
              // effect; sending null says what we mean.
              worksheet: worksheet.trim() === "" ? null : worksheet.trim(),
            },
            { onSuccess: () => setSpreadsheet("") },
          );
        })}
      >
        {/* The hint sits OUTSIDE the label on purpose. A `<label>` wrapping both the
            field and a sentence of guidance makes the whole paragraph the field's
            accessible name, which is what a screen reader then announces on focus. The
            visible label stays one short phrase; the guidance is a sibling. */}
        <label className="block">
          <span className={FIELD_LABEL}>Which sheet?</span>
          <input
            {...valid.field("spreadsheet", "Paste the sheet address, or its id.")}
            required
            value={spreadsheet}
            disabled={!write.allowed}
            onChange={(e) => setSpreadsheet(e.target.value)}
            placeholder="https://docs.google.com/spreadsheets/d/…"
            className={INPUT}
          />
        </label>
        {valid.error("spreadsheet")}
        <p className="-mt-2 text-xs text-ink-faint">
          Paste the address bar while the sheet is open, or just the document id.
        </p>
        <label className="block">
          <span className={FIELD_LABEL}>Which tab? (optional)</span>
          <input
            value={worksheet}
            disabled={!write.allowed}
            onChange={(e) => setWorksheet(e.target.value)}
            maxLength={100}
            placeholder="Leads"
            className={INPUT}
          />
        </label>
        <EventChoices
          catalogue={catalogue}
          selected={events}
          disabled={!write.allowed}
          onToggle={(event, on) =>
            setEvents((current) =>
              on ? [...current, event] : current.filter((x) => x !== event),
            )
          }
        />
        <button
          type="submit"
          disabled={!write.allowed || create.isPending || !spreadsheet || events.length === 0}
          className={SUBMIT}
        >
          {create.isPending ? "Adding…" : "Add sheet"}
        </button>
      </form>
    </Card>
  );
}
