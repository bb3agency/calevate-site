"use client";

/**
 * A LIST of disclosed sections — an FAQ, a set of technical details — built from `ui.tsx`'s
 * `Disclosure`, which stays the console's one disclosure mechanism (native `<details>`).
 *
 * What this adds over writing several `Disclosure`s: one group name so that, when
 * `exclusive`, opening a section closes the one that was open (native `<details name>`;
 * browsers without it simply leave several open, which is harmless), one heading level for
 * the whole list, and one way to say which section starts open.
 *
 * Arc's `accordion` (on `@radix-ui/react-accordion`) is not used: native `<details>`
 * already gives keyboard operation, announced state and find-in-page into closed sections,
 * which a script-driven accordion hides from the browser's search.
 */

import { useId, type ReactNode } from "react";

import { Disclosure } from "@/components/ui";

export type AccordionItem = {
  id: string;
  title: string;
  /** The closed state's information scent: what is inside, in a few words. */
  subtitle?: ReactNode;
  content: ReactNode;
};

export function Accordion({
  items,
  exclusive = true,
  defaultOpenId,
  variant = "inline",
  headingLevel = 3,
  className,
}: {
  items: AccordionItem[];
  /** Opening one closes the others. Turn off when readers compare sections side by side. */
  exclusive?: boolean;
  defaultOpenId?: string;
  variant?: "card" | "inline";
  headingLevel?: 2 | 3 | 4;
  className?: string;
}) {
  const group = useId();
  return (
    <div className={variant === "card" ? `space-y-2 ${className ?? ""}` : className}>
      {items.map((item) => (
        <Disclosure
          key={item.id}
          name={exclusive ? group : undefined}
          title={item.title}
          subtitle={item.subtitle}
          defaultOpen={item.id === defaultOpenId}
          variant={variant}
          headingLevel={headingLevel}
        >
          {item.content}
        </Disclosure>
      ))}
    </div>
  );
}
