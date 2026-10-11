import { CATEGORY_DOT, CATEGORY_LABEL, type CallMoment } from "@/lib/callMoments";

/**
 * The marker under a transcript bubble that holds a key moment: a category dot and the
 * moment's label, plus "Suggested" when the model chose it. Static text, not a control: the
 * bubble itself already seeks, and a second click target inside it would be ambiguous.
 * Renders nothing for an empty list, so a caller can pass `byTurn.get(idx) ?? []`.
 */
export function MomentTag({
  moments,
  className = "",
}: {
  moments: readonly CallMoment[];
  className?: string;
}) {
  if (moments.length === 0) return null;
  return (
    <ul className={`flex flex-wrap gap-x-3 gap-y-1 ${className}`} aria-label="Key moments in this line">
      {moments.map((moment, i) => (
        <li
          key={`${moment.kind}-${i}`}
          className="inline-flex items-center gap-1.5 text-meta text-ink-muted"
        >
          <span
            aria-hidden="true"
            className={`h-1.5 w-1.5 shrink-0 rounded-full ${CATEGORY_DOT[moment.category]}`}
          />
          <span className="sr-only">{CATEGORY_LABEL[moment.category]}: </span>
          <span>{moment.label}</span>
          {moment.source === "model" && <span className="text-ink-faint">· Suggested</span>}
        </li>
      ))}
    </ul>
  );
}
