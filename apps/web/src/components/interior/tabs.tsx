"use client";

// Adapted from interior.dev (github.com/ddoemonn/interior @3148000), MIT License,
// Copyright (c) 2026 ozzy. Full notice: ./LICENSE.

import { useCallback, useId, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { ScrollRegion } from "@/components/ui";


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
      // Only the selected tab names its panel: both consumers render the selected panel
      // alone, and an `aria-controls` pointing at an element that does not exist is a
      // dangling idref.
      "aria-controls": item.value === value ? `${base}-panel-${item.value}` : undefined,
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

/**
 * PLAIN UNDERLINE TABS (REDESIGN-2): a row of words on a hairline, the selected one in ink
 * with a brand underline. No card around them, no filled strip, no sliding plateau: the
 * founder asked for almost no motion, and a tab switch is a state change the underline
 * already shows. The panel takes its spacing from the caller (`panelClassName`), so a tab
 * row, a form and a list on one screen share one left edge.
 *
 * The behaviour (roving focus, arrow keys, ids) is `useTabs`, unchanged.
 */
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

  return (
    <div className={`w-full ${className}`}>
      {/* On a phone the row scrolls sideways inside a ScrollRegion (focusable and named,
          per tests/responsive.test.ts), so many tabs never widen the page at 360px. */}
      <ScrollRegion
        label={label}
        className="border-b border-line [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        <div {...tabs.tabListProps} aria-label={label} className="flex w-max gap-6">
          {items.map((item, index) => {
            const selected = item.value === tabs.value;
            const tabProps = tabs.getTabProps(item, index);
            return (
              <button
                key={item.value}
                {...tabProps}
                className={`-mb-px flex h-10 shrink-0 items-center border-b-2 text-body outline-none transition-colors duration-(--duration-fast) focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-brand touch:h-11 ${
                  item.disabled
                    ? "cursor-default border-transparent text-ink-faint"
                    : selected
                      ? "border-brand-strong font-medium text-ink"
                      : "border-transparent text-ink-muted hover:text-ink"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      </ScrollRegion>

      {renderPanel ? (
        <div
          key={tabs.value}
          {...tabs.getPanelProps(tabs.value)}
          className={`text-ink outline-none focus-visible:ring-2 focus-visible:ring-brand ${panelClassName}`}
        >
          {renderPanel(tabs.value)}
        </div>
      ) : null}
    </div>
  );
}
