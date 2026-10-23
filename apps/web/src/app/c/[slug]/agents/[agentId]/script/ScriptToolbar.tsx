"use client";

/**
 * THE SCRIPT TAB'S TOP LINE — whether callers hear this draft, whether the owner's work is
 * saved, and the one action that matters: "Put it live", shown only while callers hear
 * something different from the draft.
 *
 * There is no Save button. The draft saves itself; the line beside the pill says so in
 * words, and says why when it cannot. No version numbers are shown anywhere. History, the
 * full instructions, the flow picture and hand-writing sit in "More options" (D-825); asking
 * Pip has its own panel beside the steps. The room-left meter appears only once the script
 * is near the limit (`ROOM_SHOWN_FROM`): below it there is nothing for the owner to do.
 *
 * Also here: the "full instructions" drawer, the exact text the calling system reads.
 */

import { PRIMARY_BUTTON, formatCount, formatIST, type NoticeTone } from "@/components/ui";
import { UsageMeter } from "@/components/arc/usage-meter";
import { Drawer } from "@/components/console/drawer";
import { RowMenu, type RowMenuItem } from "@/components/arc/menu";
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
  save,
  room,
  unpublished,
  canWrite,
  writeReason,
  publishing,
  live,
  menu,
  onPublish,
}: {
  save: SaveState;
  room: Room | null;
  unpublished: boolean;
  canWrite: boolean;
  writeReason: string | null;
  publishing: boolean;
  /** Whether callers hear this draft, in a word or two. */
  live: { text: string; tone: NoticeTone };
  menu: RowMenuItem[];
  onPublish: () => void;
}) {
  const warn = save.kind === "held" || save.kind === "conflict" || save.kind === "failed";
  const tooLong = room !== null && room.used > room.limit;
  const showRoom = room !== null && room.used >= room.limit * ROOM_SHOWN_FROM;
  return (
    <StickyPageBar>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-60 items-center gap-2">
          <StatusPill tone={live.tone}>{live.text}</StatusPill>
          <p role="status" className={`truncate text-meta ${warn ? "text-warn" : "text-ink-muted"}`}>
            {saveLine(save)}
          </p>
        </div>
        {showRoom && room && <RoomLeft used={room.used} limit={room.limit} />}
        <div className="ml-auto flex items-center gap-2">
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

/** The room-left meter shows from this share of the limit; below it there is nothing to act on. */
export const ROOM_SHOWN_FROM = 0.85;

/**
 * How much of the calling system's instructions box the script leaves free. The number is
 * the server's (`POST .../script/preview`), which counts the platform's own rules too.
 */
export function RoomLeft({ used, limit }: { used: number; limit: number }) {
  const left = limit - used;
  return (
    <UsageMeter
      variant="inline"
      label="Room left in the instructions"
      used={used}
      limit={limit}
      usedText={formatCount(used)}
      caption={left < 0 ? `Cut ${formatCount(-left)} letters` : `${formatCount(left)} letters left`}
      valueText={left < 0 ? `${formatCount(-left)} letters over` : `${formatCount(left)} letters left`}
      overTone="danger"
      className="max-sm:w-full"
    />
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
