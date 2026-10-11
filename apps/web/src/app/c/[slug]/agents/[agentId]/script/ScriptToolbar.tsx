"use client";

/**
 * THE BUILDER'S TOP LINE — where the owner is, whether their work is saved, how much room
 * the script has left, and the one action that matters: "Put it live", shown only while
 * callers hear something different from the draft.
 *
 * There is no Save button. The draft saves itself; the line under the title says so in
 * words, and says why when it cannot. The pill beside the title says whether callers hear
 * this draft. No version numbers are shown anywhere. History sits in the ⋯ menu with the
 * other occasional actions, so the bar holds two buttons: the helper and the one primary.
 *
 * Also here: the "full instructions" drawer, the exact text the calling system reads.
 */

import Link from "next/link";
import { ArrowLeft, Sparkles } from "lucide-react";

import { PRIMARY_BUTTON, SECONDARY_BUTTON, formatCount, formatIST, type NoticeTone } from "@/components/ui";
import { Drawer } from "@/components/console/drawer";
import { RowMenu, type RowMenuItem } from "@/components/console/rowMenu";
import { StatusPill } from "@/components/console/statusPill";
import { StickyPageBar } from "@/components/console/stickyPageBar";

import type { PartLength } from "@/components/heldBackNotice";
import type { PreviewOut } from "@/lib/api/script";

import type { SaveState } from "./scriptDraft";

/** How full the calling system's instructions box is, from the server's preview. */
export interface Room {
  used: number;
  limit: number;
  /** The server's sentence when the script is over the box, or null. */
  tooLong: string | null;
  /** The script's longest sections, to shorten first. */
  longest: PartLength[];
}

export function roomFrom(preview: PreviewOut): Room | null {
  if (!preview.instructions_limit || preview.instructions_chars === undefined) return null;
  return {
    used: preview.instructions_chars,
    limit: preview.instructions_limit,
    tooLong: preview.too_long ?? null,
    longest: (preview.script_parts ?? [])
      .filter((part) => part.key !== "fence")
      .slice(0, 3)
      .map(({ label, chars }) => ({ label, chars })),
  };
}

export function saveLine(state: SaveState): string {
  switch (state.kind) {
    case "clean":
      return state.savedAt ? `Draft saved ${formatIST(state.savedAt)}` : "No changes";
    case "waiting":
    case "saving":
      return "Saving…";
    case "held":
      return state.reason;
    case "conflict":
      return "Changed somewhere else";
    case "failed":
      return "Could not save. Check your connection.";
    case "read-only":
      return "View only";
  }
}

export function ScriptToolbar({
  backHref,
  agentName,
  save,
  room,
  unpublished,
  canWrite,
  writeReason,
  publishing,
  helperOpen,
  live,
  menu,
  onPublish,
  onHelper,
}: {
  backHref: string;
  agentName: string;
  save: SaveState;
  room: Room | null;
  unpublished: boolean;
  canWrite: boolean;
  writeReason: string | null;
  publishing: boolean;
  helperOpen: boolean;
  /** Whether callers hear this draft, in a word or two. */
  live: { text: string; tone: NoticeTone };
  menu: RowMenuItem[];
  onPublish: () => void;
  onHelper: () => void;
}) {
  const warn = save.kind === "held" || save.kind === "conflict" || save.kind === "failed";
  const tooLong = room !== null && room.used > room.limit;
  return (
    <StickyPageBar>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-60 items-center gap-3">
          <Link
            href={backHref}
            aria-label={`Back to ${agentName}`}
            className="press flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <ArrowLeft aria-hidden className="h-4 w-4" />
          </Link>
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="truncate text-heading text-ink">Script</h2>
              <StatusPill tone={live.tone}>{live.text}</StatusPill>
            </div>
            <p role="status" className={`truncate text-meta ${warn ? "text-warn" : "text-ink-muted"}`}>
              {agentName} · {saveLine(save)}
            </p>
          </div>
        </div>
        {room && <RoomLeft used={room.used} limit={room.limit} />}
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <button
            type="button"
            onClick={onHelper}
            aria-pressed={helperOpen}
            className={`${SECONDARY_BUTTON} max-sm:flex-1`}
          >
            <Sparkles aria-hidden className="h-4 w-4" />
            AI helper
          </button>
          {unpublished && (
            <button
              type="button"
              className={`${PRIMARY_BUTTON} max-sm:flex-1`}
              disabled={
                !canWrite || publishing || save.kind === "held" || save.kind === "conflict" || tooLong
              }
              title={
                writeReason ??
                (save.kind === "held"
                  ? "Finish the marked parts first."
                  : tooLong
                    ? "Shorten the script first."
                    : undefined)
              }
              onClick={onPublish}
            >
              {publishing ? "Putting it live…" : "Put it live"}
            </button>
          )}
          {menu.length > 0 && <RowMenu label="this script" items={menu} />}
        </div>
      </div>
    </StickyPageBar>
  );
}

/**
 * How much of the calling system's instructions box the script leaves free. The number is
 * the server's (`POST .../script/preview`), which counts the platform's own rules too.
 */
export function RoomLeft({ used, limit }: { used: number; limit: number }) {
  const left = limit - used;
  const share = Math.min(1, Math.max(0, used / limit));
  const tone = left < 0 ? "bg-danger" : left < limit * 0.1 ? "bg-warn" : "bg-brand";
  return (
    <div className="flex min-w-0 items-center gap-2 max-sm:w-full">
      <div
        role="meter"
        aria-label="Room left in the instructions"
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={Math.min(used, limit)}
        aria-valuetext={left < 0 ? `${formatCount(-left)} letters over` : `${formatCount(left)} letters left`}
        className="h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-ink/[0.08]"
      >
        <div className={`h-full ${tone}`} style={{ width: `${share * 100}%` }} />
      </div>
      <span className={`text-meta tabular-nums ${left < 0 ? "text-danger" : "text-ink-muted"}`}>
        {left < 0 ? `Cut ${formatCount(-left)} letters` : `${formatCount(left)} letters left`}
      </span>
    </div>
  );
}

export function CompiledPrompt({ text, onClose }: { text: string; onClose: () => void }) {
  return (
    <Drawer
      open
      onClose={onClose}
      title="What the agent reads"
      description="Your script with the rules every agent follows, exactly as sent."
      width="lg"
      initialFocus="container"
    >
      {/* Focusable because it scrolls vertically and no key scrolls a non-focusable element. */}
      <pre
        role="region"
        aria-label="The full instructions"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a region that scrolls must take focus, or no key can scroll it
        tabIndex={0}
        className="max-h-[60dvh] overflow-auto whitespace-pre-wrap rounded-md border border-line bg-ink/[0.03] p-3 text-xs text-ink"
      >
        {text}
      </pre>
    </Drawer>
  );
}
