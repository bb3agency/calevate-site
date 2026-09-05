/**
 * "Stop listening to calls. Start working leads." — the product, made tangible.
 *
 * ## Why this is the section the page was missing
 *
 * Everything else on the page describes a capability. This shows the SCREEN, which is the
 * only thing that answers the question a buyer is actually asking: what does my employee
 * open tomorrow morning instead of thirty unexplained missed calls? A visitor who looks at
 * one table and thinks "so that is what I get" has understood the product; nine paragraphs
 * about extraction schemas do not do that.
 *
 * ## It is a MOCK-UP of a shipped screen, and it says so
 *
 * Not a screenshot — a screenshot of an empty pre-launch console would show nothing, and a
 * screenshot with invented rows presented as real data would be a fabrication. This is
 * hand-built markup, captioned as illustrative, holding data that is obviously an example.
 * There is no client #1 in production (ROADMAP M2), so no row here is anybody's customer.
 *
 * ## Every column and every value maps to something the product really writes
 *
 *  - the rows themselves: a call becomes a lead row through the post-call pipeline
 *    (`apps/workers/pipeline.py`), and the COLUMNS are the client's own extraction schema
 *    (`apps/api/crm/columns.py` — one registry, shared by the table and the CSV export);
 *  - "Interested" / "Hot" / "Contacted" are three of the six real statuses, which are a
 *    fixed enum rather than free text (`apps/api/crm/schemas.py:29`);
 *  - the timestamps in the detail panel are KEY MOMENTS, computed once in the post-call
 *    pipeline so a listen costs nothing (`apps/workers/moments.py`);
 *  - "Recording kept 90 days" is the floor the database itself enforces
 *    (`RECORDING_FLOOR_DAYS = 90`, `apps/workers/retention.py:119`);
 *  - "Sent to your CRM" is the signed outbound webhook (`X-Calevate-Signature` over
 *    `{timestamp}.{body}`, `apps/api/integrations/service.py:176`,
 *    `apps/workers/outbound_webhooks.py`) and the Sheets leg
 *    (`apps/workers/sheets_sync.py`, once the client's Google account is connected).
 *
 * ## Layout
 *
 * The table scrolls inside its own container rather than letting the page scroll
 * sideways — a marketing page that overflows horizontally on a phone is the one layout
 * defect a reader blames on the product.
 */

import { CalendarCheck, FileAudio, Share2 } from "lucide-react";

import { ScrollRegion } from "@/components/ui";

type Status = "Hot" | "Interested" | "Contacted";

const ROWS: readonly {
  name: string;
  requirement: string;
  status: Status;
  next: string;
}[] = [
  { name: "Priya", requirement: "Root canal", status: "Interested", next: "Booked — Tue 6:00pm" },
  { name: "Ramesh", requirement: "Braces, for his daughter", status: "Hot", next: "Wants a call back today" },
  { name: "Anitha", requirement: "Cleaning + check-up", status: "Contacted", next: "Asked for Saturday" },
  { name: "Kiran", requirement: "Asked about fees only", status: "Contacted", next: "No follow-up needed" },
];

/** The status pill. Colour is never the ONLY signal — the word is the status. */
function StatusPill({ status }: { status: Status }) {
  const tone =
    status === "Hot"
      ? "bg-brand-strong text-white"
      : status === "Interested"
        ? "bg-brand-soft text-brand-strong"
        : "bg-black/5 text-ink-muted dark:bg-white/10";
  return (
    <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>
      {status}
    </span>
  );
}

export function LeadInbox() {
  return (
    <figure className="mt-10 sm:mt-12">
      <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr] lg:items-start">
        {/* --- The list ------------------------------------------------------- */}
        <div className="overflow-hidden rounded-2xl border border-line bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3.5 sm:px-5">
            <h3 className="text-sm font-semibold text-ink">Your leads</h3>
            <p className="text-xs text-ink-faint">Today · 4 new enquiries</p>
          </div>
          {/* The table scrolls itself (see this file's header), and `ScrollRegion` is what
              makes that scroll reachable from a keyboard — role=region + tabIndex=0 + an
              accessible name, in one place rather than seventeen ad-hoc waivers.
              `tests/responsive.test.ts` enforces it over every `overflow-x-auto` in the
              tree, which is how this was caught rather than shipped. */}
          <ScrollRegion label="Your leads, as a table">
            <table className="w-full min-w-[34rem] border-collapse text-left">
              <caption className="sr-only">
                An illustration of the leads screen: four example enquiries with what each
                caller wanted, how interested they were, and what happens next.
              </caption>
              <thead>
                <tr className="border-b border-line text-[11px] tracking-wide text-ink-faint uppercase">
                  <th scope="col" className="px-4 py-2.5 font-semibold sm:px-5">Lead</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">What they want</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Interest</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold sm:px-5">Next step</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {ROWS.map((row) => (
                  <tr key={row.name}>
                    <th scope="row" className="px-4 py-3.5 text-sm font-semibold text-ink sm:px-5">
                      {row.name}
                    </th>
                    <td className="px-4 py-3.5 text-sm text-ink-muted">{row.requirement}</td>
                    <td className="px-4 py-3.5">
                      <StatusPill status={row.status} />
                    </td>
                    <td className="px-4 py-3.5 text-sm text-ink-muted sm:px-5">{row.next}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
          <p className="border-t border-line px-4 py-3 text-xs text-ink-faint sm:px-5">
            You choose the columns. They are the questions you said you needed answered.
          </p>
        </div>

        {/* --- One lead, opened ----------------------------------------------- */}
        <div className="rounded-2xl border border-line bg-surface p-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-base font-semibold text-ink">Priya</h3>
            <StatusPill status="Interested" />
          </div>
          <dl className="mt-4 space-y-2.5 border-t border-line pt-4">
            {[
              ["Requirement", "Root canal"],
              ["Preferred time", "Tuesday, 6:00pm"],
              ["Language", "Telugu"],
              ["Came from", "Inbound call, 8:42pm"],
            ].map(([term, detail]) => (
              <div key={term} className="flex items-baseline justify-between gap-4">
                <dt className="text-xs tracking-wide text-ink-faint uppercase">{term}</dt>
                <dd className="text-sm font-medium text-ink">{detail}</dd>
              </div>
            ))}
          </dl>
          <ul className="mt-5 space-y-2.5 border-t border-line pt-4">
            {[
              {
                icon: FileAudio,
                text: "Jump to 1:12 — where the slot was agreed. Recordings kept at least 90 days.",
              },
              {
                icon: CalendarCheck,
                text: "Appointment written into your calendar, once your Google account is connected.",
              },
              {
                icon: Share2,
                text: "Sent on to your CRM, or to a Google Sheet.",
              },
            ].map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-2.5 text-sm text-ink-muted">
                <Icon
                  aria-hidden
                  className="mt-0.5 h-4 w-4 shrink-0 text-brand-strong dark:text-brand-bright"
                />
                {text}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <figcaption className="mt-4 text-xs text-ink-faint">
        An illustration of the leads screen, drawn with example enquiries. Nobody in it is a
        real customer, and no figure here is a measurement.
      </figcaption>
    </figure>
  );
}
