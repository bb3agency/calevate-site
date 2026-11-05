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

import { ActionButton } from "@/components/arc/feedback";
import { formatCount, formatIST, type NoticeTone } from "@/components/ui";
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
  const blocked = publishBlock({ save, tooLong });
  return (
    <StickyPageBar>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-60 items-center gap-2">
          <StatusPill tone={live.tone}>{live.text}</StatusPill>
          <p role="status" className={`min-w-0 break-words text-meta ${warn ? "text-warn" : "text-ink-muted"}`}>
            {saveLine(save)}
          </p>
        </div>
        {showRoom && room && <RoomLeft used={room.used} limit={room.limit} />}
        <div className="ml-auto flex items-center gap-2">
          {unpublished && (
            // A column, so the waiting reason sits under the button rather than beside it.
            <div className="flex flex-col items-end gap-1 max-sm:flex-1 max-sm:items-stretch">
              <ActionButton
                status={publishing ? "pending" : "idle"}
                pendingLabel="Putting it live…"
                disabled={!canWrite}
                title={writeReason ?? undefined}
                waitingFor={canWrite ? blocked : null}
                onClick={onPublish}
              >
                Put it live
              </ActionButton>
            </div>
          )}
          {menu.length > 0 && <RowMenu label="this script" items={menu} />}
        </div>
      </div>
    </StickyPageBar>
  );
}

/**
 * Why "Put it live" is greyed out, in the words shown under it, or null when it may be
 * pressed. A save still on its way would race the publish's version check, so the button
 * waits for it and comes back when the save line says "Draft saved".
 */
export function publishBlock({ save, tooLong }: { save: SaveState; tooLong: boolean }): string | null {
  if (save.kind === "saving") return "Waiting for your draft to save";
  if (save.kind === "held") return "Finish the marked parts first.";
  if (save.kind === "conflict") return "Choose which draft to keep first.";
  if (tooLong) return "Shorten the script first.";
  return null;
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
      description="Your script plus the rules every agent follows."
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
