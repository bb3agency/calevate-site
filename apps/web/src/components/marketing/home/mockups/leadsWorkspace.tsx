import { Search } from "lucide-react";

import { Avatar, Chip, Panel, StatusPill, Window, type LeadStatus } from "./kit";
import { MockStage } from "./stage";

/**
 * The leads screen at full size, for an illustrative property office in Vijayawada: the
 * list with the office's own captured columns, and one lead opened beside it.
 *
 * Drawn from the console: the list is `app/c/[slug]/leads` (search placeholder, the
 * "What did they ask for?" box, Columns, the CSV export, Owner); the captured columns are
 * the real-estate template's (`scripts/seed.py`: "Budget (lakhs)", "Location", "BHK",
 * "Site visit"); the opened lead is `leads/[leadId]` — "Stage", "Owner", and a "History"
 * whose event titles are the ones `apps/api/crm/service.py` writes ("Call placed",
 * "Moved to hot", "Assigned to …"). This template has no `urgency` field, so the automatic
 * hot-lead alert cannot fire for it: a person moves the lead to hot here.
 */

type PropertyLead = {
  name: string;
  status: LeadStatus;
  budget: string;
  location: string;
  bhk: string;
  visit: string;
  owner: string;
};

const LEADS: readonly PropertyLead[] = [
  { name: "Lakshmi Prasanna", status: "hot", budget: "65", location: "Benz Circle", bhk: "2BHK", visit: "Yes", owner: "Ramesh" },
  { name: "Venkat Rao", status: "interested", budget: "90", location: "Patamata", bhk: "3BHK", visit: "Yes", owner: "Unassigned" },
  { name: "Harika Ch", status: "contacted", budget: "45", location: "Gunadala", bhk: "2BHK", visit: "No", owner: "Ramesh" },
  { name: "Farzana Begum", status: "won", budget: "55", location: "Labbipet", bhk: "2BHK", visit: "Yes", owner: "Divya" },
  { name: "Srinivas M", status: "new", budget: "120", location: "Poranki", bhk: "4BHK+", visit: "—", owner: "Unassigned" },
  { name: "Teja Kumar", status: "lost", budget: "30", location: "Kanuru", bhk: "1BHK", visit: "No", owner: "Divya" },
];

const HISTORY: readonly { title: string; when: string; by: string }[] = [
  { title: "Assigned to Ramesh", when: "10:47 AM", by: "Divya" },
  { title: "Moved to hot", when: "10:46 AM", by: "Divya" },
  { title: "Call completed", when: "10:45 AM", by: "Calevate" },
];

function Row({ lead, highlight }: { lead: PropertyLead; highlight?: boolean }) {
  return (
    <span className={`flex items-center gap-3 px-4 py-2.5 text-[12px] ${highlight ? "bg-amber-50 dark:bg-amber-950/40" : ""}`}>
      <span className="flex min-w-0 flex-1 items-center gap-2 sm:w-36 sm:flex-none sm:shrink-0">
        <Avatar name={lead.name} className="h-6 w-6" />
        <span className="truncate font-semibold text-ink">{lead.name}</span>
      </span>
      <span className="w-20 shrink-0">
        <StatusPill status={lead.status} />
      </span>
      <span className="hidden w-24 shrink-0 text-right font-mono text-ink tabular-nums sm:block">{lead.budget}</span>
      <span className="hidden min-w-0 flex-1 truncate text-ink sm:block">{lead.location}</span>
      <span className="hidden w-14 shrink-0 text-ink-muted md:block">{lead.bhk}</span>
      <span className="hidden w-16 shrink-0 text-ink-muted md:block">{lead.visit}</span>
      <span className="hidden w-24 shrink-0 truncate text-ink-muted xl:block">{lead.owner}</span>
    </span>
  );
}

export function LeadsWorkspace() {
  return (
    <MockStage
      label="Illustration of the leads screen for a property office: callers listed with their stage, budget, location, flat size and whether they want a site visit, and one hot lead opened to show its history."
      className="relative mt-12 sm:mt-16 lg:grid lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start lg:gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]"
    >
      <Window
        title="Leads"
        className="mk-rise"
        actions={
          <>
            <Chip className="hidden sm:inline-flex">Columns</Chip>
            <Chip>Export CSV</Chip>
          </>
        }
      >
        <span className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          <span className="flex min-w-0 flex-1 items-center gap-2 rounded-md bg-surface px-2.5 py-1 text-[12px] ring-1 ring-line sm:max-w-xs">
            <Search className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
            <span className="shrink-0 text-ink-faint">What did they ask for?</span>
            <span className="truncate font-medium text-ink">3BHK near Benz Circle</span>
          </span>
          <span className="hidden items-center gap-1.5 md:flex">
            <Chip tone="brand">All</Chip>
            <Chip>hot</Chip>
            <Chip>Assigned to me</Chip>
          </span>
          <span className="ml-auto text-[11px] text-ink-muted">214 leads</span>
        </span>
        <span className="flex items-center gap-3 border-b border-line bg-app/60 px-4 py-2 text-[11px] font-semibold text-ink-muted">
          <span className="min-w-0 flex-1 sm:w-36 sm:flex-none sm:shrink-0">Name</span>
          <span className="w-20 shrink-0">Status</span>
          <span className="hidden w-24 shrink-0 text-right whitespace-nowrap sm:block">Budget (lakhs)</span>
          <span className="hidden min-w-0 flex-1 truncate sm:block">Location</span>
          <span className="hidden w-14 shrink-0 md:block">BHK</span>
          <span className="hidden w-16 shrink-0 md:block">Site visit</span>
          <span className="hidden w-24 shrink-0 xl:block">Owner</span>
        </span>
        <span className="block divide-y divide-line">
          {LEADS.map((lead, i) => (
            <span key={lead.name} className={i < 5 ? `mk-rise mk-s${i + 1} block` : "block"}>
              <Row lead={lead} highlight={i === 0} />
            </span>
          ))}
        </span>
      </Window>

      {/* The opened lead: a side sheet beside the list on a desktop, under it on a phone. A grid
          column rather than an absolute sheet, so the stage grows to the taller of the two and
          the sheet cannot hang into the band below. */}
      <Panel
        elevation="overlay"
        className="mk-rise mk-s4 relative mt-4 p-5 lg:mt-14"
      >
        <span className="flex items-center gap-3">
          <Avatar name="Lakshmi Prasanna" tone="brand" className="h-10 w-10 text-[12px]" />
          <span className="flex min-w-0 flex-col">
            <span className="truncate text-[15px] font-semibold text-ink">Lakshmi Prasanna</span>
            <span className="font-mono text-[11px] text-ink-muted">+91 98XXX XX506</span>
          </span>
        </span>
        <span className="mt-4 grid grid-cols-1 gap-2 min-[360px]:grid-cols-2">
          <span className="flex flex-col gap-1 rounded-lg border border-line bg-app/60 px-3 py-2">
            <span className="text-[11px] text-ink-muted">Stage</span>
            <StatusPill status="hot" className="self-start" />
          </span>
          <span className="flex flex-col gap-1 rounded-lg border border-line bg-app/60 px-3 py-2">
            <span className="text-[11px] text-ink-muted">Owner</span>
            <span className="text-[12px] font-semibold text-ink">Ramesh</span>
          </span>
        </span>
        <span className="mt-3 flex flex-col gap-1.5 rounded-lg border border-line px-3 py-2.5 text-[12px]">
          {(
            [
              ["Budget (lakhs)", "65"],
              ["Location", "Benz Circle"],
              ["BHK", "2BHK"],
              ["Site visit", "Yes — Saturday"],
            ] as const
          ).map(([label, value]) => (
            <span key={label} className="flex items-center justify-between gap-3">
              <span className="text-ink-muted">{label}</span>
              <span className="font-semibold text-ink">{value}</span>
            </span>
          ))}
        </span>

        <span className="mt-5 block text-[12px] font-semibold text-ink">History</span>
        <span className="mt-2 flex flex-col">
          {HISTORY.map(({ title, when, by }) => (
            <span key={title} className="relative flex items-start gap-3 border-l border-line py-1.5 pl-4">
              <span className="absolute top-3 -left-[4px] h-[7px] w-[7px] rounded-full bg-surface ring-2 ring-brand" />
              <span className="flex min-w-0 flex-col">
                <span className="text-[12px] font-medium text-ink">{title}</span>
                <span className="text-[11px] text-ink-muted">
                  {when} · {by}
                </span>
              </span>
            </span>
          ))}
        </span>
      </Panel>
    </MockStage>
  );
}
