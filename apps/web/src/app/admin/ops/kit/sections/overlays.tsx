"use client";

import { useState } from "react";
import { Copy, Pencil, Phone, Trash2 } from "lucide-react";

import type { FeedbackStatus } from "@/components/arc/feedback";
import { Menu, RowMenu } from "@/components/arc/menu";
import { Popover, PopoverClose } from "@/components/arc/popover";
import { Tooltip } from "@/components/arc/tooltip";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer } from "@/components/console/drawer";
import { InfoTip } from "@/components/console/infoTip";
import { ModalDialog } from "@/components/modalDialog";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  QUIET_ICON_BUTTON,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";

import { KitDemo, KitGrid, KitSection } from "../kitLayout";

const ROW_ACTIONS = [
  { id: "open", label: "Open lead", href: "#overlays" },
  { id: "call", label: "Call back", icon: <Phone className="h-4 w-4" />, onSelect: () => undefined },
  { id: "rename", label: "Rename", disabled: true, hint: "Owner only" },
  { id: "delete", label: "Delete lead", tone: "danger" as const, separated: true, onSelect: () => undefined },
];

function ConfirmDemo() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<FeedbackStatus>("idle");
  const confirm = () => {
    setStatus("pending");
    window.setTimeout(() => {
      setStatus("success");
      window.setTimeout(() => {
        setOpen(false);
        setStatus("idle");
      }, 900);
    }, 900);
  };
  return (
    <>
      <button type="button" className={SECONDARY_BUTTON} onClick={() => setOpen(true)}>
        <Trash2 aria-hidden className="h-4 w-4" />
        Remove number
      </button>
      {open && (
        <ConfirmDialog
          title="Remove +91 40 4567 8900?"
          confirmLabel="Remove number"
          pendingLabel="Removing"
          successLabel="Removed"
          status={status}
          error={null}
          onCancel={() => setOpen(false)}
          onConfirm={confirm}
        >
          <p>Calls to this number stop reaching your agents at once. You can buy a new number later, but not this one.</p>
        </ConfirmDialog>
      )}
    </>
  );
}

function DialogDemo() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={SECONDARY_BUTTON} onClick={() => setOpen(true)}>
        Open dialog
      </button>
      {open && (
        <ModalDialog
          title="Send a test call"
          description="We will ring this number from your agent so you can hear it."
          onClose={() => setOpen(false)}
          actions={
            <>
              <button type="button" className={SECONDARY_BUTTON} onClick={() => setOpen(false)}>
                Cancel
              </button>
              <button type="button" className={PRIMARY_BUTTON} onClick={() => setOpen(false)}>
                Call me
              </button>
            </>
          }
        >
          <label className="mt-3 block">
            <span className={FIELD_LABEL}>Your phone</span>
            <input className={FIELD} inputMode="tel" defaultValue="+91 98765 43210" />
          </label>
        </ModalDialog>
      )}
    </>
  );
}

function DrawerDemo() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={SECONDARY_BUTTON} onClick={() => setOpen(true)}>
        Open drawer
      </button>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Priya Sharma"
        description="Lead from the Diwali campaign"
        footer={
          <button type="button" className={PRIMARY_BUTTON} onClick={() => setOpen(false)}>
            Done
          </button>
        }
      >
        <div className="space-y-3 text-body text-ink">
          <p>
            Asked about weekend opening hours and the price of a home visit.
            <InfoTip label="captured details">Details the agent captured during the call, in the lead&apos;s own words.</InfoTip>
          </p>
          <RowMenu label="Priya Sharma" items={ROW_ACTIONS} />
        </div>
      </Drawer>
    </>
  );
}

export function OverlaysSection() {
  return (
    <KitSection
      id="overlays"
      title="Overlays"
      lead="Floating panels sit on the popover layer, above a dialog or drawer they open from. On a phone, dialogs and drawers are bottom sheets with a grab strip."
    >
      <KitGrid>
        <KitDemo label="InfoTip · tap to open help">
          <p className="text-body text-ink">
            Answer rate
            <InfoTip label="answer rate">Calls the agent picked up, out of every call that reached your number this week.</InfoTip>
          </p>
        </KitDemo>
        <KitDemo label="Popover · a small form">
          <Popover
            label="Rename agent"
            align="start"
            className="w-72"
            trigger={
              <button type="button" className={SECONDARY_BUTTON_SM}>
                <Pencil aria-hidden className="h-3.5 w-3.5" />
                Rename
              </button>
            }
          >
            <label className="block">
              <span className={FIELD_LABEL}>Agent name</span>
              <input className={FIELD} defaultValue="Reception" />
            </label>
            <div className="mt-3 flex justify-end">
              <PopoverClose asChild>
                <button type="button" className={SECONDARY_BUTTON_SM}>
                  Done
                </button>
              </PopoverClose>
            </div>
          </Popover>
        </KitDemo>
        <KitDemo label="RowMenu · a row's secondary actions" note="A disabled item keeps its reason; a destructive one is red and still confirms.">
          <div className="flex items-center justify-between rounded-md border border-line px-3 py-2">
            <span className="text-body text-ink">Priya Sharma</span>
            <RowMenu label="Priya Sharma" items={ROW_ACTIONS} />
          </div>
        </KitDemo>
        <KitDemo label="Menu · any trigger">
          <Menu
            label="Export options"
            align="start"
            items={[
              { id: "csv", label: "Download CSV", onSelect: () => undefined },
              { id: "sheet", label: "Send to a Google Sheet", onSelect: () => undefined },
            ]}
            trigger={
              <button type="button" className={SECONDARY_BUTTON_SM}>
                Export
              </button>
            }
          />
        </KitDemo>
        <KitDemo label="Tooltip · icon-only control, pointer devices" note="Repeats the accessible name; never the only place information lives.">
          <Tooltip content="Copy number">
            <button type="button" aria-label="Copy number" className={QUIET_ICON_BUTTON}>
              <Copy aria-hidden className="h-4 w-4" />
            </button>
          </Tooltip>
        </KitDemo>
        <KitDemo label="ModalDialog · centred card, bottom sheet on a phone">
          <DialogDemo />
        </KitDemo>
        <KitDemo label="ConfirmDialog · irreversible action with button states">
          <ConfirmDemo />
        </KitDemo>
        <KitDemo label="Drawer · side panel, bottom sheet on a phone" note="Holds an InfoTip and a RowMenu to show both open above it.">
          <DrawerDemo />
        </KitDemo>
      </KitGrid>
    </KitSection>
  );
}
