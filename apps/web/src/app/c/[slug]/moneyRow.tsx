import type { ReactNode } from "react";

/**
 * A row of the home screen's money block while its figure is loading or has failed: the
 * row's own label, then the skeleton or the refusal, on the same flush-left edge and
 * vertical rhythm as the `Metric` it stands in for. A padded `Card` here indented the
 * pending row 16px past its loaded neighbours, so the column jumped as reads arrived.
 *
 * The label is a heading (under the block's own h2) because it names what the refusal
 * under it is about.
 */
export function MoneyRowPending({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="py-4">
      <h3 className="text-[13px] font-medium text-ink-muted">{label}</h3>
      <div className="mt-2">{children}</div>
    </section>
  );
}
