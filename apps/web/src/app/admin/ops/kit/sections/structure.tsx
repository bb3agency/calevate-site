"use client";

import { useState } from "react";
import Link from "next/link";
import { CalendarClock, MessageCircle, PhoneCall, Tag } from "lucide-react";

import { AnnouncementBar } from "@/components/arc/announcement-bar";
import { ButtonGroup, SplitButton } from "@/components/arc/button-group";
import type { FeedbackStatus } from "@/components/arc/feedback";
import { FilterToolbar, SelectionBar } from "@/components/arc/filter-toolbar";
import { HoverCard } from "@/components/arc/hover-card";
import { NotificationCenter } from "@/components/arc/notification-center";
import { SwipeActions } from "@/components/arc/swipe-actions";
import { ConfirmDialog } from "@/components/confirmDialog";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { Drawer } from "@/components/console/drawer";
import { PageHeader } from "@/components/console/pageHeader";
import { ModalDialog } from "@/components/modalDialog";
import { FIELD_INLINE, FilterChip, PRIMARY_BUTTON, SECONDARY_BUTTON, formatDuration } from "@/components/ui";

import { KitDemo, KitGrid, KitSection } from "../kitLayout";

type Lead = { id: string; name: string; phone: string; status: string; lastCall: number };

const LEADS: Lead[] = [
  { id: "l1", name: "Priya Reddy", phone: "+91 98765 43210", status: "Hot", lastCall: 192 },
  { id: "l2", name: "Venkat Rao", phone: "+91 98765 43211", status: "Follow-up", lastCall: 64 },
  { id: "l3", name: "Lakshmi Devi", phone: "+91 98765 43212", status: "New", lastCall: 0 },
];

const COLUMNS: DataColumn<Lead>[] = [
  { id: "name", header: "Name", cell: (row) => row.name, sort: { value: (row) => row.name } },
  { id: "phone", header: "Phone", cell: (row) => row.phone, hideBelow: "sm" },
  { id: "status", header: "Status", cell: (row) => row.status, sort: { value: (row) => row.status } },
  {
    id: "call",
    header: "Last call",
    align: "right",
    cell: (row) => (row.lastCall ? formatDuration(row.lastCall) : "—"),
    sort: { value: (row) => row.lastCall, kind: "number" },
  },
];

/** A stand-in for a mutation's state, so each face can be shown on demand. */
function useFakeAction(outcome: "success" | "error" = "success") {
  const [status, setStatus] = useState<FeedbackStatus>("idle");
  const run = () => {
    setStatus("pending");
    window.setTimeout(() => {
      setStatus(outcome);
      window.setTimeout(() => setStatus("idle"), 2000);
    }, 900);
  };
  return { status, run };
}

const NOTIFICATIONS = [
  {
    id: "n1",
    title: "Priya Reddy is ready to book",
    detail: "Asked for a callback after 6 pm today.",
    at: "2026-10-24T09:12:00Z",
    href: "#structure",
    tone: "default" as const,
  },
  {
    id: "n2",
    title: "A call to Venkat Rao failed",
    detail: "The line was busy twice. Try again later or send a WhatsApp follow-up.",
    at: "2026-10-24T08:40:00Z",
    href: "#structure",
    tone: "danger" as const,
  },
  {
    id: "n3",
    title: "Credit is running low",
    detail: "About 40 minutes of calls left.",
    at: "2026-10-23T17:05:00Z",
    href: "#structure",
    tone: "warn" as const,
  },
];

export function StructureSection() {
  const [modal, setModal] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const confirmAction = useFakeAction();
  const callBack = useFakeAction();
  const markStatus = useFakeAction();
  const later = useFakeAction("error");
  const resolve = useFakeAction();
  const [announcement, setAnnouncement] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(["l2"]));
  const [hotOnly, setHotOnly] = useState(true);
  const [agent, setAgent] = useState<string | null>("Reception");

  return (
    <KitSection
      id="structure"
      title="Structure and overlays"
      lead="Dialogs and sheets, the top-bar bell, row gestures, page and list chrome. Every action here shows its own pending and result."
    >
      <KitGrid>
        <KitDemo
          label="ModalDialog / ConfirmDialog"
          note="A centred dialog from 640px; a bottom sheet with a grab strip below it. Drag the strip down to close on a phone."
        >
          <div className="flex flex-wrap gap-2">
            <button type="button" className={SECONDARY_BUTTON} onClick={() => setModal(true)}>
              Open a dialog
            </button>
            <button type="button" className={SECONDARY_BUTTON} onClick={() => setConfirm(true)}>
              Confirm a removal
            </button>
          </div>
          {modal ? (
            <ModalDialog
              title="Send a test call?"
              description="We will ring your own number once from Reception so you can hear the opening line."
              onClose={() => setModal(false)}
              actions={
                <>
                  <button type="button" className={SECONDARY_BUTTON} onClick={() => setModal(false)}>
                    Not now
                  </button>
                  <button type="button" className={PRIMARY_BUTTON} onClick={() => setModal(false)}>
                    Ring me
                  </button>
                </>
              }
            />
          ) : null}
          {confirm ? (
            <ConfirmDialog
              title="Remove Venkat Rao from this campaign?"
              confirmLabel="Remove"
              pendingLabel="Removing…"
              successLabel="Removed"
              status={confirmAction.status}
              error={null}
              onCancel={() => setConfirm(false)}
              onConfirm={confirmAction.run}
            >
              <p>He will not be called again by this campaign. His lead and past calls stay.</p>
            </ConfirmDialog>
          ) : null}
        </KitDemo>

        <KitDemo label="Drawer" note="A side drawer from 640px, a bottom sheet below. Unsaved typing asks before it closes, from the strip too.">
          <button type="button" className={SECONDARY_BUTTON} onClick={() => setDrawer(true)}>
            Open the lead drawer
          </button>
          <Drawer
            open={drawer}
            onClose={() => setDrawer(false)}
            title="Priya Reddy"
            description="Hot lead, last called today at 2:42 pm"
            footer={
              <button type="button" className={PRIMARY_BUTTON} onClick={() => setDrawer(false)}>
                Done
              </button>
            }
          >
            <label className="block text-meta text-ink-muted">
              Note
              <textarea className={`${FIELD_INLINE} mt-1 w-full`} rows={4} defaultValue="Wants a slot on Saturday morning." />
            </label>
          </Drawer>
        </KitDemo>

        <KitDemo label="NotificationCenter · items, empty, failed">
          <div className="flex items-center gap-3">
            <NotificationCenter
              heading="Needs attention"
              label="Needs attention: 3 items"
              state="ready"
              count={3}
              items={NOTIFICATIONS}
              seeAll={{ href: "#structure", label: "Open everything that needs you" }}
            />
            <NotificationCenter heading="Needs attention" label="Needs attention" state="ready" count={0} items={[]} />
            <NotificationCenter
              heading="Needs attention"
              label="Needs attention: we couldn't check for new items."
              state="error"
              items={[]}
              onRetry={() => undefined}
            />
          </div>
        </KitDemo>

        <KitDemo label="HoverCard" note="Desktop only: rest the pointer on the name. On a phone the link just opens the lead.">
          <HoverCard
            label="Preview of Priya Reddy"
            trigger={
              <Link href="#structure" className="font-medium text-brand-strong underline-offset-2 hover:underline">
                Priya Reddy
              </Link>
            }
          >
            <p className="font-semibold">Priya Reddy</p>
            <p className="text-ink-muted">Hot · last call 3 min 12 s, today 2:42 pm</p>
            <p className="mt-1 text-ink-muted">Asked for a Saturday morning slot.</p>
          </HoverCard>
        </KitDemo>

        <KitDemo label="AnnouncementBar · info, warn, critical" wide>
          <div className="space-y-2">
            {announcement ? (
              <AnnouncementBar
                title="Calls on 26 October may take a few seconds longer to connect."
                detail="We are moving to a faster network between 2 and 3 am."
                action={{ href: "#structure", label: "Read more" }}
                onDismiss={() => setAnnouncement(false)}
              />
            ) : (
              <button type="button" className={SECONDARY_BUTTON} onClick={() => setAnnouncement(true)}>
                Show the announcement again
              </button>
            )}
            <AnnouncementBar tone="warn" title="Only 12 free minutes left." detail="Add credit to keep your agents answering." action={{ href: "#structure", label: "Add credit" }} />
            <AnnouncementBar tone="critical" title="Outbound calling is paused for every account." detail="Inbound calls are answered as usual." />
          </div>
        </KitDemo>

        <KitDemo
          label="SwipeActions"
          note="On a phone: swipe right for Call back, left for the rest. With a mouse or keyboard the same actions are in the ⋯ menu."
          wide
        >
          <ul className="divide-y divide-line overflow-hidden rounded-card border border-line">
            {LEADS.map((lead) => (
              <li key={lead.id}>
                <SwipeActions
                  label={lead.name}
                  primary={{
                    id: "call",
                    label: "Call back",
                    icon: <PhoneCall className="h-4 w-4" />,
                    onSelect: callBack.run,
                    status: callBack.status,
                  }}
                  secondary={[
                    { id: "status", label: "Mark status", icon: <Tag className="h-4 w-4" />, onSelect: markStatus.run, status: markStatus.status },
                    { id: "later", label: "Call later", icon: <CalendarClock className="h-4 w-4" />, onSelect: later.run, status: later.status },
                    {
                      id: "whatsapp",
                      label: "WhatsApp",
                      icon: <MessageCircle className="h-4 w-4" />,
                      onSelect: () => undefined,
                      disabled: true,
                      hint: "No consent on record",
                    },
                  ]}
                >
                  <div className="px-3 py-3">
                    <p className="text-body font-medium text-ink">{lead.name}</p>
                    <p className="text-meta text-ink-muted">
                      {lead.status} · {lead.phone}
                    </p>
                  </div>
                </SwipeActions>
              </li>
            ))}
          </ul>
        </KitDemo>

        <KitDemo label="ButtonGroup · SplitButton" note="One button on a phone, three from 640px; the rest fold into ⋯." wide>
          <div className="flex flex-wrap items-center gap-3">
            <ButtonGroup
              label="Call actions"
              moreLabel="More actions for this call"
              actions={[
                { id: "call", label: "Call back", onSelect: callBack.run, status: callBack.status, successLabel: "Calling" },
                { id: "resolve", label: "Mark resolved", onSelect: resolve.run, status: resolve.status, successLabel: "Resolved" },
                { id: "lead", label: "Open lead", href: "#structure" },
                { id: "report", label: "Report a problem", onSelect: () => undefined },
              ]}
            />
            <SplitButton
              onClick={callBack.run}
              status={callBack.status}
              successLabel="Calling"
              menuLabel="More ways to call back"
              items={[
                { id: "later", label: "Call back later", onSelect: later.run },
                { id: "other", label: "Call from another number", onSelect: () => undefined },
              ]}
            >
              Call back
            </SplitButton>
          </div>
        </KitDemo>

        <KitDemo label="PageHeader · meta and grouped actions" wide>
          <PageHeader
            title="Call with Priya Reddy"
            meta={
              <>
                <span>24 Oct, 2:42 pm</span>
                <span>3 min 12 s</span>
                <span>Reception</span>
              </>
            }
            actions={
              <ButtonGroup
                label="Call actions"
                moreLabel="More actions for this call"
                actions={[
                  { id: "call", label: "Call back", onSelect: callBack.run, status: callBack.status },
                  { id: "resolve", label: "Mark resolved", onSelect: resolve.run, status: resolve.status },
                  { id: "lead", label: "Open lead", href: "#structure" },
                ]}
              />
            }
          />
        </KitDemo>

        <KitDemo label="FilterToolbar · DataTable with selection · SelectionBar" wide>
          <div className="space-y-3">
            <FilterToolbar
              search={<input aria-label="Search leads" placeholder="Name or last digits" className={`${FIELD_INLINE} w-full sm:w-56`} />}
              filters={
                <>
                  <FilterChip label="Hot only" active={hotOnly} onClick={() => setHotOnly((was) => !was)} />
                  <FilterChip label="Reception" active={agent === "Reception"} onClick={() => setAgent((was) => (was ? null : "Reception"))} />
                </>
              }
              tools={
                <button type="button" className={SECONDARY_BUTTON}>
                  Export
                </button>
              }
              active={[
                ...(hotOnly ? [{ id: "hot", label: "Status: Hot", onRemove: () => setHotOnly(false) }] : []),
                ...(agent ? [{ id: "agent", label: `Agent: ${agent}`, onRemove: () => setAgent(null) }] : []),
              ]}
              onClearAll={() => {
                setHotOnly(false);
                setAgent(null);
              }}
              count={{ shown: 3, total: 340, noun: "lead" }}
            />
            <DataTable
              label="Leads"
              rows={LEADS}
              columns={COLUMNS}
              getRowId={(row) => row.id}
              selection={{ selected, onChange: setSelected, rowLabel: (row) => `Select ${row.name}`, allLabel: "Select every lead shown" }}
            />
            <DataTable
              label="Leads (none match)"
              rows={[]}
              columns={COLUMNS}
              getRowId={(row) => row.id}
              empty={<p className="text-center text-body text-ink-muted">No leads match these filters.</p>}
            />
            <SelectionBar count={selected.size} noun="lead" onClear={() => setSelected(new Set())}>
              <button type="button" className={SECONDARY_BUTTON}>
                Mark status
              </button>
            </SelectionBar>
          </div>
        </KitDemo>
      </KitGrid>
    </KitSection>
  );
}
