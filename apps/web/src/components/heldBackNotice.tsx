import { NoticeBox, formatIST } from "@/components/ui";

/** A part of the script and its length, as the server counts it. Never its text. */
export interface PartLength {
  label: string;
  chars: number;
}

/**
 * The script is longer than the calling system takes (D-752). The sentence is the server's
 * (`engine_limits.too_long_sentence`), the same one a refused "Put it live" gives, and the
 * parts are the script's longest sections, so the owner knows what to shorten.
 */
export function TooLongNotice({ message, longest }: { message: string; longest: PartLength[] }) {
  return (
    <NoticeBox tone="stop" role="alert" title={message}>
      {longest.length > 0 && <LongestParts parts={longest} />}
    </NoticeBox>
  );
}

/**
 * An update the live agent did not take, so callers still hear its previous settings
 * (`PendingOut.held_back`). Shown to the owner on the Script page and to an operator on the
 * agent's page, in the same words.
 */
export function HeldBackNotice({
  held,
}: {
  held: {
    code: string;
    message: string;
    failed_at?: string | null;
    longest?: PartLength[];
  };
}) {
  return (
    <NoticeBox
      tone="warn"
      role="alert"
      title="Callers still hear the previous version"
      info={held.failed_at ? `The update was refused ${formatIST(held.failed_at)}.` : undefined}
    >
      <p className="mt-1 text-meta">{held.message}</p>
      {held.longest && held.longest.length > 0 && <LongestParts parts={held.longest} />}
    </NoticeBox>
  );
}

function LongestParts({ parts }: { parts: PartLength[] }) {
  return (
    <>
      <p className="mt-1 text-meta">The longest parts:</p>
      <ul className="ml-5 list-disc text-meta text-ink-muted">
        {parts.map((part) => (
          <li key={part.label}>
            {part.label}: {part.chars.toLocaleString("en-IN")} characters
          </li>
        ))}
      </ul>
    </>
  );
}
