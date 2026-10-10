/**
 * A TINY SKELETON OF THE LIST THIS SCREEN WILL BECOME, for its empty state (REDESIGN-2).
 *
 * Shapes only, never words (founder, 10 Oct 2026: "skeleton placeholders, not actual text
 * lines"): rounded grey bars for the lines a row will hold, a small dot where a person or a
 * status sits, an empty pill where a status chip goes. One pill carries the brand tint, the
 * only accent. Text inside an illustration reads as fake data; a skeleton reads as "this is
 * where your rows will be", which is all an empty state should say with a picture.
 *
 * Tokens only, `aria-hidden` (the empty state's sentence says it in words), no motion.
 *
 * Use a named `kind`, or pass `rows` for a screen without one. A row's strings are never
 * drawn: their LENGTHS set how wide its bars are, so a sketch keeps the rhythm of the
 * screen it stands in for.
 */

export type SketchRow = {
  /** Sets the width of the row's main bar (never drawn as text). */
  title: string;
  /** Sets the width of a second, shorter bar; absent, the row has one line. */
  meta?: string;
  /** Present: the row ends in a status pill (empty). Its length sets the pill's width. */
  pill?: string;
  /** brand = the one accented pill; anything else is neutral. */
  tone?: "brand" | "warn" | "plain";
};

export type SketchKind =
  | "calls"
  | "leads"
  | "campaigns"
  | "callbacks"
  | "knowledge"
  | "numbers"
  | "deliveries"
  | "actions"
  | "attention"
  | "chat";

/** Lengths only: these strings set bar widths and are never shown. */
const ROWS: Record<Exclude<SketchKind, "chat">, SketchRow[]> = {
  calls: [
    { title: "xxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxxxxxx", pill: "xxxxxx", tone: "brand" },
    { title: "xxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxx", pill: "xxxxxxxxx" },
    { title: "xxxxxxxxxxxxxxx", meta: "xxxxxxxxxxx", pill: "xxxxxx" },
  ],
  leads: [
    { title: "xxxxxxxxxx", meta: "xxxxxxxxxx", pill: "xxx", tone: "brand" },
    { title: "xxxxxxx", meta: "xxxxxxxxxxxxxxx", pill: "xxx" },
    { title: "xxxx", meta: "xxxxxxxxxxxxxxx", pill: "xxx" },
  ],
  campaigns: [
    { title: "xxxxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxx", pill: "xxxxxxx", tone: "brand" },
    { title: "xxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxx", pill: "xxxxxxxxx" },
  ],
  callbacks: [
    { title: "xxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxxxx", pill: "xxxxx", tone: "brand" },
    { title: "xxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxxxxxx", pill: "xxxxxxx" },
  ],
  knowledge: [
    { title: "xxxxxxxxxxxxxx", meta: "xxxxxxxx", pill: "xxxxx", tone: "brand" },
    { title: "xxxxxxxxxxxxx", meta: "xxxxxx", pill: "xxxxx" },
  ],
  numbers: [{ title: "xxxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxxxxxxxxx", pill: "xxxxxxxxx", tone: "brand" }],
  deliveries: [
    { title: "xxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxxxxxxxx", pill: "xxxxxxxxx", tone: "brand" },
    { title: "xxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxxxxxxxx", pill: "xxxxxxxxx" },
  ],
  actions: [
    { title: "xxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxxx", pill: "xx", tone: "brand" },
    { title: "xxxxxxxxxxxxxxxxxxx", meta: "xxxxxxxx", pill: "xx" },
  ],
  attention: [
    { title: "xxxxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxx", pill: "xxx", tone: "brand" },
    { title: "xxxxxxxxxxxxxxxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxxx", pill: "xxxxx" },
  ],
};

const W = 240;
const ROW_H = 30;
const CHAR = 4.6;
/** Rows fade as they go down, so the drawing reads as "a list" rather than "three items". */
const FADE = [1, 0.7, 0.45];

export function EmptySketch({ kind, rows }: { kind?: SketchKind; rows?: SketchRow[] }) {
  if (kind === "chat") return <ChatSketch />;
  const list = rows ?? (kind ? ROWS[kind] : []);
  const h = list.length * ROW_H + 2;
  return (
    <svg aria-hidden focusable="false" viewBox={`0 0 ${W} ${h}`} className="h-auto w-60 max-w-full">
      <line x1="0" x2={W} y1="0.5" y2="0.5" className="stroke-line" />
      {list.map((row, i) => {
        const y = i * ROW_H;
        const pillW = row.pill ? Math.min(54, Math.max(22, row.pill.length * 5 + 12)) : 0;
        const room = W - 22 - pillW - 14;
        const titleW = Math.min(room, Math.max(40, row.title.length * CHAR));
        const metaW = row.meta ? Math.min(room, Math.max(30, row.meta.length * CHAR * 0.8)) : 0;
        const twoLines = Boolean(row.meta);
        return (
          <g key={i} opacity={FADE[i] ?? 0.35}>
            <circle cx="7" cy={y + 15} r="5" className="fill-ink/[0.08]" />
            <rect x="20" y={twoLines ? y + 8 : y + 12} width={titleW} height="5" rx="2.5" className="fill-ink/[0.14]" />
            {twoLines ? <rect x="20" y={y + 18} width={metaW} height="4" rx="2" className="fill-ink/[0.07]" /> : null}
            {row.pill ? (
              <rect
                x={W - pillW - 2}
                y={y + 9}
                width={pillW}
                height="12"
                rx="6"
                className={row.tone === "brand" && i === 0 ? "fill-brand-soft" : "fill-ink/[0.06]"}
              />
            ) : null}
            <line x1="0" x2={W} y1={y + ROW_H + 0.5} y2={y + ROW_H + 0.5} className="stroke-line" />
          </g>
        );
      })}
    </svg>
  );
}

/** The assistant's history: a question bubble and an answer bubble, as shapes. */
function ChatSketch() {
  return (
    <svg aria-hidden focusable="false" viewBox="0 0 240 76" className="h-auto w-60 max-w-full">
      <rect x="118" y="2" width="120" height="22" rx="11" className="fill-ink/[0.05]" />
      <rect x="130" y="11" width="80" height="4" rx="2" className="fill-ink/[0.14]" />
      <rect x="2" y="32" width="170" height="40" rx="8" className="fill-surface stroke-line" />
      <rect x="12" y="43" width="130" height="4" rx="2" className="fill-ink/[0.14]" />
      <rect x="12" y="53" width="96" height="4" rx="2" className="fill-ink/[0.10]" />
      <rect x="112" y="53" width="28" height="4" rx="2" className="fill-brand/60" />
    </svg>
  );
}
