"use client";

/**
 * A collapsible view of a JSON value, for the admin console: a tool test's result, an
 * integration delivery's request and response. Adapted from uiarc's `json-viewer` (MIT,
 * see ./LICENSE): nested disclosure rows with the type shown by colour AND by the value's
 * own spelling (quotes on strings, `null` in words), so colour is never the only signal.
 *
 * It renders exactly what it is given. Redaction is the caller's job, before the value
 * reaches the browser (hard rule 6: no phone numbers, transcript text or extraction payload
 * in anything a log or screenshot keeps).
 *
 * Large payloads stay cheap: branches deeper than `expandDepth` start closed, and an array
 * or object longer than `pageSize` shows its first page with a "Show N more" control rather
 * than rendering thousands of rows at once. Each leaf can be copied as a value, and each
 * branch as JSON, through the one clipboard path (`interior/copy-button`).
 */

import { useId, useState } from "react";
import { ChevronRight } from "lucide-react";
import clsx from "clsx";

import { CopyButton } from "@/components/interior/copy-button";

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

export type JsonViewerProps = {
  /** Any JSON-serialisable value. A value JSON cannot hold (a function, undefined) shows as its type. */
  value: unknown;
  /** Names the payload for assistive tech and the copy buttons: "Delivery response". */
  label: string;
  /** Branches deeper than this start closed. 0 shows only the root, closed. */
  expandDepth?: number;
  /** Children shown per branch before "Show more". */
  pageSize?: number;
  /** "Show {n} more" — `{n}` is replaced. */
  moreLabel?: string;
  className?: string;
};

function kind(value: unknown): "object" | "array" | "string" | "number" | "boolean" | "null" | "other" {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  const t = typeof value;
  if (t === "object") return "object";
  if (t === "string" || t === "number" || t === "boolean") return t;
  return "other";
}

const LEAF_TONE: Record<string, string> = {
  string: "text-brand-strong",
  number: "text-ink",
  boolean: "text-warn",
  null: "text-ink-faint italic",
  other: "text-ink-faint italic",
};

function leafText(value: unknown): string {
  const k = kind(value);
  if (k === "string") return JSON.stringify(value);
  if (k === "null") return "null";
  if (k === "other") return `(${typeof value})`;
  return String(value);
}

function size(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === "object") return Object.keys(value).length;
  return 0;
}

function Node({
  name,
  value,
  path,
  depth,
  expandDepth,
  pageSize,
  moreLabel,
  label,
}: {
  name: string | null;
  value: unknown;
  path: string;
  depth: number;
  expandDepth: number;
  pageSize: number;
  moreLabel: string;
  label: string;
}) {
  const k = kind(value);
  const branch = k === "object" || k === "array";
  const [open, setOpen] = useState(depth < expandDepth);
  const [shown, setShown] = useState(pageSize);
  const id = useId();
  const keyText = name === null ? null : (
    <span className="text-ink-muted">
      {name}
      <span aria-hidden>: </span>
    </span>
  );

  if (!branch) {
    return (
      <li className="group/leaf flex min-h-7 items-center gap-1 py-0.5 pl-5 touch:min-h-11">
        <span className="min-w-0 break-all">
          {keyText}
          <span className={LEAF_TONE[k]}>{leafText(value)}</span>
        </span>
        <CopyButton
          value={k === "string" ? (value as string) : leafText(value)}
          label={`Copy ${path || label}`}
          className="opacity-0 group-hover/leaf:opacity-100 focus-visible:opacity-100 touch:opacity-100"
        />
      </li>
    );
  }

  const entries: [string, unknown][] =
    k === "array" ? (value as unknown[]).map((v, i) => [String(i), v]) : Object.entries(value as object);
  const count = size(value);
  const summary = k === "array" ? `[${count}]` : `{${count}}`;
  return (
    <li className="py-0.5">
      <div className="group/branch flex min-h-7 items-center gap-1 touch:min-h-11">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((o) => !o)}
          className="flex min-h-7 min-w-0 items-center gap-1 rounded-sm text-left hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          <ChevronRight
            aria-hidden
            className={clsx(
              "h-4 w-4 shrink-0 text-ink-faint motion-safe:transition-transform motion-safe:duration-(--duration-fast)",
              open && "rotate-90",
            )}
          />
          <span className="min-w-0 break-all">
            {keyText ?? <span className="text-ink-muted">{label}</span>}
            <span className="text-ink-faint">{summary}</span>
          </span>
        </button>
        <CopyButton
          value={safeStringify(value)}
          label={`Copy ${path || label} as JSON`}
          className="opacity-0 group-hover/branch:opacity-100 focus-visible:opacity-100 touch:opacity-100"
        />
      </div>
      {open ? (
        <ul id={id} role="group" className="ml-2 border-l border-line pl-2">
          {entries.slice(0, shown).map(([key, child]) => (
            <Node
              key={key}
              name={key}
              value={child}
              path={path ? `${path}${k === "array" ? `[${key}]` : `.${key}`}` : k === "array" ? `[${key}]` : key}
              depth={depth + 1}
              expandDepth={expandDepth}
              pageSize={pageSize}
              moreLabel={moreLabel}
              label={label}
            />
          ))}
          {entries.length > shown ? (
            <li className="py-0.5 pl-5">
              <button
                type="button"
                onClick={() => setShown((n) => n + pageSize)}
                className="inline-flex min-h-7 items-center rounded-sm text-meta font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
              >
                {moreLabel.replace("{n}", String(Math.min(pageSize, entries.length - shown)))}
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </li>
  );
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return "";
  }
}

export function JsonViewer({
  value,
  label,
  expandDepth = 2,
  pageSize = 50,
  moreLabel = "Show {n} more",
  className,
}: JsonViewerProps) {
  return (
    <div
      role="region"
      aria-label={label}
      className={clsx(
        "max-w-full overflow-x-auto rounded-md border border-line bg-surface-muted p-2 font-mono text-[12.5px] leading-5",
        className,
      )}
    >
      <ul>
        <Node
          name={null}
          value={value as Json}
          path=""
          depth={0}
          expandDepth={expandDepth}
          pageSize={pageSize}
          moreLabel={moreLabel}
          label={label}
        />
      </ul>
    </div>
  );
}
