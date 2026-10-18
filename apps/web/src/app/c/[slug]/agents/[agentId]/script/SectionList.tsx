"use client";

/**
 * THE CALL AS NUMBERED STEPS — the script's main view at every width (D-825); the flow
 * picture is the occasional alternative on a desktop.
 *
 * Each card says the step's name, what the agent does there and its example line, in that
 * order; a step opens in place under its card (`editor`), so the owner never leaves the
 * list to change one.
 *
 * The number on each card IS its place in `script.stages`; reordering here renumbers the
 * canvas too, because both read that one array. Three ways to move a card, so nobody is
 * left out: drag the handle (touch or mouse), arrow keys on the focused handle, or the
 * visible earlier/later buttons. Each move is announced.
 *
 * Dragging is done with pointer events rather than HTML5 drag-and-drop, which does not fire
 * on touch screens. Only the handle takes `touch-action: none`, so the page still scrolls
 * when a thumb lands anywhere else on a card.
 */

import { useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { ArrowDown, ArrowUp, CircleAlert, GripVertical } from "lucide-react";

import { QUIET_ICON_BUTTON } from "@/components/ui";
import type { ScriptContext } from "@/lib/api/script";

import type { Issue, Section } from "./scriptModel";
import { thenLabel } from "./sectionParts";

export function SectionList({
  sections,
  context,
  issues,
  selected,
  readOnly,
  onOpen,
  onMove,
  editor,
}: {
  sections: Section[];
  context: ScriptContext | null;
  issues: Issue[];
  selected: string | null;
  readOnly: boolean;
  /** Opens a step, or closes it when it is the open one. */
  onOpen: (id: string) => void;
  onMove: (from: number, to: number) => void;
  /** The open step's editor, drawn under its card. */
  editor?: ReactNode;
}) {
  const [announce, setAnnounce] = useState("");
  const [drag, setDrag] = useState<{ id: string; from: number; over: number; dy: number } | null>(null);
  const items = useRef(new Map<string, HTMLLIElement>());
  const startY = useRef(0);

  const move = (from: number, to: number) => {
    if (to < 0 || to >= sections.length || from === to) return;
    onMove(from, to);
    const name = sections[from].name.trim() || "Untitled step";
    setAnnounce(`${name} moved to number ${to + 1} of ${sections.length}.`);
  };

  /** The slot the pointer is over, from the cards' midpoints. */
  /** The place the dragged card would take: how many other cards sit above the pointer. */
  const slotAt = (clientY: number, dragged: string): number => {
    let above = 0;
    for (const s of sections) {
      if (s.id === dragged) continue;
      const box = items.current.get(s.id)?.getBoundingClientRect();
      if (box && clientY > box.top + box.height / 2) above += 1;
    }
    return above;
  };

  const onHandleDown = (e: ReactPointerEvent<HTMLButtonElement>, id: string, index: number) => {
    if (readOnly || e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    startY.current = e.clientY;
    setDrag({ id, from: index, over: index, dy: 0 });
  };
  const onHandleMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (!drag) return;
    setDrag({ ...drag, dy: e.clientY - startY.current, over: slotAt(e.clientY, drag.id) });
  };
  const onHandleUp = () => {
    if (!drag) return;
    const { from, over } = drag;
    setDrag(null);
    move(from, over);
  };

  return (
    <div>
      <p aria-live="polite" className="sr-only">
        {announce}
      </p>
      <ol className="space-y-2" aria-label="Steps of the call, in order">
        {sections.map((section, index) => {
          const own = issues.filter((i) => i.section === section.id);
          const dragging = drag?.id === section.id;
          const shift =
            drag && !dragging
              ? index > drag.from && index <= drag.over
                ? "-translate-y-2"
                : index < drag.from && index >= drag.over
                  ? "translate-y-2"
                  : ""
              : "";
          return (
            <li
              key={section.id}
              ref={(el) => {
                if (el) items.current.set(section.id, el);
                else items.current.delete(section.id);
              }}
              style={dragging ? { transform: `translateY(${drag.dy}px)` } : undefined}
              className={`relative rounded-card border bg-surface transition-transform duration-(--duration-fast) ease-out ${
                dragging ? "z-raised border-brand shadow-overlay" : selected === section.id ? "border-brand" : "border-line"
              } ${shift}`}
            >
              <div className="flex">
              <div className="flex w-12 shrink-0 flex-col items-center gap-1 border-r border-line py-3">
                <span className="text-heading tabular-nums text-ink" aria-hidden>
                  {index + 1}
                </span>
                {!readOnly && (
                  <button
                    type="button"
                    className={`${QUIET_ICON_BUTTON} cursor-grab touch-none select-none active:cursor-grabbing`}
                    aria-label={`Move ${section.name.trim() || "Untitled step"}, number ${index + 1}. Use the up and down arrow keys.`}
                    onPointerDown={(e) => onHandleDown(e, section.id, index)}
                    onPointerMove={onHandleMove}
                    onPointerUp={onHandleUp}
                    onPointerCancel={() => setDrag(null)}
                    onKeyDown={(e) => {
                      if (e.key === "ArrowUp") {
                        e.preventDefault();
                        move(index, index - 1);
                      } else if (e.key === "ArrowDown") {
                        e.preventDefault();
                        move(index, index + 1);
                      }
                    }}
                  >
                    <GripVertical aria-hidden className="h-4 w-4" />
                  </button>
                )}
              </div>
              <button
                type="button"
                aria-expanded={selected === section.id}
                onClick={() => onOpen(section.id)}
                className="min-w-0 flex-1 px-4 py-3 text-left hover:bg-ink/[0.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
              >
                <SectionSummary sections={sections} index={index} context={context} issues={own} />
              </button>
              {!readOnly && (
                <div className="flex shrink-0 flex-col justify-center gap-1 pr-1">
                  <button
                    type="button"
                    className={QUIET_ICON_BUTTON}
                    aria-label={`Move ${section.name.trim() || "Untitled step"} earlier`}
                    disabled={index === 0}
                    onClick={() => move(index, index - 1)}
                  >
                    <ArrowUp aria-hidden className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className={QUIET_ICON_BUTTON}
                    aria-label={`Move ${section.name.trim() || "Untitled step"} later`}
                    disabled={index === sections.length - 1}
                    onClick={() => move(index, index + 1)}
                  >
                    <ArrowDown aria-hidden className="h-4 w-4" />
                  </button>
                </div>
              )}
              </div>
              {selected === section.id && editor ? (
                <div className="border-t border-line px-4 py-4 sm:pl-16">{editor}</div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * What a card says, in up to three short lines so the call scans top to bottom: the name,
 * what it does (one line), and the example line as the caller would hear it. Where it goes
 * next is said only when it is not simply the next step; the rest is in the editor.
 */
function SectionSummary({
  sections,
  index,
  context,
  issues,
}: {
  sections: Section[];
  index: number;
  context: ScriptContext | null;
  issues: Issue[];
}) {
  const s = sections[index];
  const jumps = s.otherwise !== "" || s.branches.length > 0;
  return (
    <span className="block space-y-1">
      <span className="flex items-center gap-2">
        <span className="truncate text-body font-semibold text-ink">{s.name.trim() || "Untitled step"}</span>
        {s.mode === "say" && <span className="shrink-0 text-meta text-ink-muted">Exact words</span>}
      </span>
      <span className="line-clamp-2 block text-meta text-ink-muted">
        {s.instruction.trim() || "Nothing written yet."}
      </span>
      {s.sounds_like.trim() ? (
        <span className="block truncate text-meta italic text-ink">&ldquo;{s.sounds_like.trim()}&rdquo;</span>
      ) : null}
      {jumps ? (
        <span className="block truncate text-meta text-ink-muted">
          {s.branches.length ? "Otherwise" : "Then"}: {thenLabel(sections, index, context)}
          {s.branches.length > 0 && ` · ${s.branches.length} other ${s.branches.length === 1 ? "way" : "ways"} out`}
        </span>
      ) : null}
      {issues.length > 0 && (
        <span className="flex items-center gap-1 text-meta text-danger">
          <CircleAlert aria-hidden className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{issues[0].message}</span>
        </span>
      )}
    </span>
  );
}
