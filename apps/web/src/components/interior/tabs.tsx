"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";

import { ScrollRegion } from "@/components/ui";

const INDICATOR = { type: "spring", stiffness: 620, damping: 42, mass: 0.35 } as const;

const useIsoLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

const PANEL = { type: "spring", stiffness: 460, damping: 38, mass: 0.8 } as const;

export type TabItem = {
  value: string;
  label: string;
  disabled?: boolean;
};

export type TabsActivation = "automatic" | "manual";
export type UseTabsOptions = {
  items: TabItem[];
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  activation?: TabsActivation;
};

export function useTabs({
  items,
  value: controlled,
  defaultValue,
  onValueChange,
  activation = "automatic",
}: UseTabsOptions) {
  const base = useId();
  const nodes = useRef(new Map<string, HTMLButtonElement>());
  const direction = useRef(1);

  const [internal, setInternal] = useState(
    () => defaultValue ?? items.find((i) => !i.disabled)?.value ?? items[0]?.value ?? "",
  );

  const value = controlled ?? internal;

  const emit = useRef(onValueChange);
  emit.current = onValueChange;

  const select = useCallback(
    (next: string) => {
      if (next === value) return;
      const from = items.findIndex((i) => i.value === value);
      const to = items.findIndex((i) => i.value === next);
      direction.current = to < from ? -1 : 1;
      if (controlled === undefined) setInternal(next);
      emit.current?.(next);
    },
    [controlled, items, value],
  );

  const focusAt = useCallback(
    (i: number) => {
      const item = items[i];
      if (!item) return;
      nodes.current.get(item.value)?.focus();
    },
    [items],
  );

  const nextEnabled = useCallback(
    (from: number, dir: number) => {
      const n = items.length;
      let i = from < 0 ? 0 : from;
      for (let k = 0; k < n; k += 1) {
        i = (i + dir + n) % n;
        if (!items[i].disabled) return i;
      }
      return from;
    },
    [items],
  );

  const endStop = useCallback(
    (dir: number) => {
      const n = items.length;
      if (dir > 0) {
        for (let i = 0; i < n; i += 1) if (!items[i].disabled) return i;
      } else {
        for (let i = n - 1; i >= 0; i -= 1) if (!items[i].disabled) return i;
      }
      return 0;
    },
    [items],
  );

  const getTabProps = useCallback(
    (item: TabItem, index: number) => ({
      id: `${base}-tab-${item.value}`,
      role: "tab" as const,
      type: "button" as const,
      "aria-selected": item.value === value,
      "aria-controls": `${base}-panel-${item.value}`,
      "aria-disabled": item.disabled ? (true as const) : undefined,
      tabIndex: item.value === value ? 0 : -1,
      ref: (node: HTMLButtonElement | null) => {
        if (node) nodes.current.set(item.value, node);
        else nodes.current.delete(item.value);
      },
      onClick: () => {
        if (!item.disabled) select(item.value);
      },
      onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const to = nextEnabled(index, e.key === "ArrowRight" ? 1 : -1);
          focusAt(to);
          if (activation === "automatic") select(items[to].value);
          return;
        }
        if (e.key === "Home" || e.key === "End") {
          e.preventDefault();
          const to = endStop(e.key === "Home" ? 1 : -1);
          focusAt(to);
          if (activation === "automatic") select(items[to].value);
          return;
        }
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          if (!item.disabled) select(item.value);
        }
      },
    }),
    [activation, base, endStop, focusAt, items, nextEnabled, select, value],
  );

  const getPanelProps = useCallback(
    (panelValue: string) => ({
      id: `${base}-panel-${panelValue}`,
      role: "tabpanel" as const,
      "aria-labelledby": `${base}-tab-${panelValue}`,
      tabIndex: 0,
    }),
    [base],
  );

  const tabListProps = {
    role: "tablist" as const,
    "aria-orientation": "horizontal" as const,
  };

  return {
    value,
    select,
    direction: direction.current,
    tabListProps,
    getTabProps,
    getPanelProps,
  };
}

export type UseTabsReturn = ReturnType<typeof useTabs>;

export type TabsProps = {
  items: TabItem[];
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  activation?: TabsActivation;
  renderPanel?: (value: string) => ReactNode;
  label?: string;
  panelClassName?: string;
  className?: string;
};

export function Tabs({
  items,
  value,
  defaultValue,
  onValueChange,
  activation = "automatic",
  renderPanel,
  label = "Tabs",
  panelClassName = "",
  className = "",
}: TabsProps) {
  const tabs = useTabs({ items, value, defaultValue, onValueChange, activation });
  const reduced = useReducedMotion();

  const rowRef = useRef<HTMLDivElement | null>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [plateau, setPlateau] = useState({ x: 0, width: 0, ready: false });

  const selectedIndex = items.findIndex((item) => item.value === tabs.value);

  useIsoLayoutEffect(() => {
    const node = tabRefs.current[selectedIndex];
    if (!node) return;

    const read = () => {
      setPlateau((prev) =>
        prev.x === node.offsetLeft &&
        prev.width === node.offsetWidth &&
        prev.ready
          ? prev
          : { x: node.offsetLeft, width: node.offsetWidth, ready: true },
      );
    };

    read();
    const row = rowRef.current;
    if (!row) return;
    const observer = new ResizeObserver(read);
    observer.observe(row);
    return () => observer.disconnect();
  }, [selectedIndex, items]);

  return (
    <div
      className={`w-full overflow-hidden rounded-[12px] border border-line bg-surface shadow-[0_1px_2px_rgba(28,25,23,0.06),0_4px_10px_-8px_rgba(28,25,23,0.45)] dark:shadow-[0_1px_6px_rgba(0,0,0,0.45)] ${className}`}
    >
      {/* Mobile: the tab row scrolls horizontally inside a ScrollRegion (role=region +
          tabIndex + name — keyboard-reachable, per tests/responsive.test.ts) so many tabs
          never overflow the page at 360px. The tablist row is `w-max` so it can exceed the
          region and scroll; the plateau indicator is an absolute child positioned by
          offsetLeft, so it stays under its tab as the row scrolls. */}
      <ScrollRegion
        label={label}
        className="border-b border-line bg-app [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
      <div
        {...tabs.tabListProps}
        ref={rowRef}
        aria-label={label}
        className="relative flex w-max gap-1 px-1 pt-1"
      >
        <motion.span
          layout
          aria-hidden
          style={{
            borderTopLeftRadius: 8,
            borderTopRightRadius: 8,
            borderBottomLeftRadius: 0,
            borderBottomRightRadius: 0,
            left: plateau.x,
            width: plateau.width,
            opacity: plateau.ready ? 1 : 0,
          }}
          className="absolute bottom-[-1px] top-1 bg-surface"
          transition={reduced ? { duration: 0 } : INDICATOR}
        >
          <motion.span
            layout
            aria-hidden
            style={{ borderTopLeftRadius: 8, borderTopRightRadius: 8 }}
            transition={reduced ? { duration: 0 } : INDICATOR}
            className="absolute inset-0 border border-b-0 border-line"
          />
        </motion.span>

        {items.map((item, index) => {
          const selected = item.value === tabs.value;
          return (
            <button
              key={item.value}
              {...tabs.getTabProps(item, index)}
              ref={(node) => {
                tabRefs.current[index] = node;
              }}
              className={`relative flex h-8 shrink-0 items-center justify-center rounded-t-[8px] px-3.5 text-[12.5px] outline-none transition-colors duration-150 after:pointer-events-none after:absolute after:inset-0 after:rounded-t-[8px] after:content-[''] focus-visible:after:shadow-[inset_0_0_0_1px_#16a05d] dark:focus-visible:after:shadow-[inset_0_0_0_1px_#22c55e] ${
                item.disabled
                  ? "cursor-default text-ink-faint"
                  : selected
                    ? "text-ink"
                    : "text-ink-muted hover:bg-ink/[0.04] hover:text-ink"
              }`}
            >
              <span className="relative grid place-items-center leading-[1.4]">
                <span aria-hidden className="invisible col-start-1 row-start-1 font-medium">
                  {item.label}
                </span>
                <span
                  className={`col-start-1 row-start-1 ${selected ? "font-medium" : ""}`}
                >
                  {item.label}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      </ScrollRegion>

      {renderPanel ? (
        <motion.div
          key={tabs.value}
          custom={tabs.direction}
          {...tabs.getPanelProps(tabs.value)}
          initial={reduced ? false : { opacity: 0, x: tabs.direction * 12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={reduced ? { duration: 0 } : PANEL}
          className={`rounded-[11px] text-[13.5px] leading-relaxed text-ink outline-none focus-visible:shadow-[inset_0_0_0_1px_#16a05d] dark:focus-visible:shadow-[inset_0_0_0_1px_#22c55e] ${panelClassName}`}
        >
          {renderPanel(tabs.value)}
        </motion.div>
      ) : null}
    </div>
  );
}
