"use client";

import Link from "next/link";

import { Disclosure, SECONDARY_BUTTON_SM, formatCountOf } from "@/components/ui";
import type { KbUpload } from "@/lib/api/kb";
import { useClientRealm } from "@/lib/api/session";

/**
 * WHAT A FILE TELLS THE AGENT TO DO ON A CALL ("ask whether now is a good time"). These are
 * kept out of what the agents look up, because an instruction that is only found when a
 * caller's question happens to match it is not followed; they belong in a call script.
 *
 * An agent has no script of its own (D-997): an Inbound line or a campaign does, and Pip
 * reads a picked file's call instructions when it writes that script
 * (`first_run/documents.document_words`). So this lists them and points to where a file is
 * picked, rather than sending them anywhere.
 */
export function CallInstructions({
  upload,
  expanded = false,
}: {
  upload: KbUpload;
  /** Opened from the file's row, which already said how many: the list, then the way on. */
  expanded?: boolean;
}) {
  const items = upload.call_instructions ?? [];
  if (items.length === 0) return null;
  const count = formatCountOf(items.length, "call instruction");
  const list = (
    <ul className="divide-y divide-line" aria-label={`Call instructions in ${upload.name}`}>
      {items.map((item, index) => (
        <li key={`${index}-${item.section ?? ""}`} className="py-2">
          {item.section ? <p className="text-meta font-medium text-ink-muted">{item.section}</p> : null}
          <p className="whitespace-pre-line text-body text-ink [overflow-wrap:anywhere]">{item.text}</p>
        </li>
      ))}
    </ul>
  );
  if (expanded) {
    return (
      <div className="mt-3 space-y-3">
        <div className="border-y border-line">{list}</div>
        <WhereTheyAreUsed />
      </div>
    );
  }
  return (
    <div className="space-y-3 rounded-lg border border-line p-4">
      <p className="text-body text-ink">
        {count} in {upload.name}. Not used as facts.
      </p>
      <Disclosure variant="inline" headingLevel={4} title="See them">
        {list}
      </Disclosure>
      <WhereTheyAreUsed />
    </div>
  );
}

/** Pick the file on a line or a campaign, and Pip follows them when it writes that script. */
export const USED_WHERE = "Pick this file on an Inbound line or campaign to use them.";

function WhereTheyAreUsed() {
  const { session, href } = useClientRealm();
  const slug = session.orgSlug;
  return (
    <div className="space-y-2">
      <p className="text-meta text-ink-muted">{USED_WHERE}</p>
      <div className="flex flex-wrap gap-2">
        <Link href={href(`/c/${slug}/inbound`)} className={SECONDARY_BUTTON_SM}>
          Open Inbound
        </Link>
        <Link href={href(`/c/${slug}/campaigns`)} className={SECONDARY_BUTTON_SM}>
          Open Campaigns
        </Link>
      </div>
    </div>
  );
}
