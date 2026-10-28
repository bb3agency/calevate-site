"use client";

import { formatCount } from "@/components/ui";

/**
 * A row of counted figures: the number large, its noun small under it. A `<dl>` because
 * each is one key and one value; `flex-col-reverse` puts the number on top while the DOM
 * keeps `dt` before `dd`, as a description list requires. Used where a sentence of counts
 * ("3 calls, 12 transcript turns and 1 CRM record") used to be, so the figures scan.
 */
export function CountChips({ counts }: { counts: [label: string, value: number][] }) {
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {counts.map(([label, value]) => (
        <div key={label} className="flex flex-col-reverse rounded-md border border-line px-3 py-2">
          <dt className="text-meta text-ink-muted">{label}</dt>
          <dd className="text-[18px] font-semibold tabular-nums text-ink">{formatCount(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
