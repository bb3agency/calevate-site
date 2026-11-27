"use client";

import { UsageMeter } from "@/components/arc/usage-meter";
import { Disclosure, formatCount } from "@/components/ui";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

/**
 * How long a campaign's or Inbound line's saved script is, against the length Pip aims for
 * and the most a call can take, as the server measures it. Counts only, never the text.
 */
export interface ScriptSize {
  /** The script as sent on a call, in characters. */
  chars: number;
  /** The length to stay under, leaving room for later changes. */
  target_chars: number;
  /** The most a call takes; past it the script cannot go live. */
  limit_chars: number;
}

const whole = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;

/**
 * The holder's `script_size`, or null when the server does not send one (or sends a shape
 * this screen cannot read), so the meter hides rather than guess a number.
 */
export function scriptSizeOf(holder: object): ScriptSize | null {
  const size = (holder as { script_size?: unknown }).script_size;
  if (typeof size !== "object" || size === null) return null;
  const { chars, target_chars, limit_chars } = size as Record<string, unknown>;
  if (!whole(chars) || !whole(target_chars) || !whole(limit_chars) || target_chars === 0 || limit_chars === 0) {
    return null;
  }
  return { chars, target_chars, limit_chars };
}

/** "about 6,800": the count to the nearest hundred, since the owner needs the size, not the digit. */
function about(chars: number): string {
  return formatCount(Math.max(100, Math.round(chars / 100) * 100));
}

export function ScriptSizeMeter({ size }: { size: ScriptSize }) {
  const { chars, target_chars: target, limit_chars: limit } = size;
  const tooLong = chars > limit;
  const caption = `Length: about ${about(chars)} of ${formatCount(target)} characters`;
  return (
    <div className="space-y-1" data-testid="script-size">
      <UsageMeter
        variant="inline"
        label="Script length"
        used={chars}
        limit={target}
        usedText={about(chars)}
        caption={caption}
        valueText={tooLong ? `${caption}. Too long to put live.` : caption}
        overTone={tooLong ? "danger" : "warn"}
      />
      <Disclosure variant="inline" title="About length" headingLevel={4}>
        <p className="max-w-prose text-meta text-ink-muted">
          {tooLong
            ? `A call takes up to ${formatCount(limit)} characters, so this script cannot go live. Shorten the longest steps, or ask ${ASSISTANT_NAME} for a shorter script.`
            : `A call takes up to ${formatCount(limit)} characters. Staying under ${formatCount(target)} leaves room for changes later.`}
        </p>
      </Disclosure>
    </div>
  );
}
