"use client";

import { useState } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { RestrictionNote } from "@/components/ui";
import { parsePastedNumbers, type DncSource } from "@/lib/api/dnc";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

import { ConsentPosture } from "./ConsentPosture";
import { useDncCopilot } from "./copilot";
import { NumberField } from "./NumberField";
import { SuppressedList } from "./SuppressedList";
import { DNC_COPY as COPY, DNC_KEPT as KEPT } from "./copy";

/**
 * Do not call (SEC-COMP §3, hard rule 5): the suppression list the dispatch gate reads on
 * every call, made visible and writable by the client.
 *
 * Checking a number needs only `leads:read`, so every viewer can ask the question people
 * arrive with. Adding and removing need `leads:dispatch`, the authority that causes a call,
 * because suppressing is that decision in the other direction; it is writable in a view-as
 * session, so support can suppress a number with the client on the phone. "May this session
 * write" goes through `useWriteAccess`, so "we could not find out" is said rather than
 * rendered as a missing form.
 */
export default function DoNotCallPage() {
  const session = useClientSession();
  const write = useWriteAccess(session, "leads:dispatch", "add or remove numbers on this list");
  const [paste, setPaste] = useState("");
  const [source, setSource] = useState<DncSource>("manual");
  const parsed = parsePastedNumbers(paste);
  useDncCopilot({ session, paste, parsed, source, setSource, write });

  return (
    <div className="max-w-4xl space-y-6 pb-12">
      {/* The live-check line is the compliance notice (it binds a running campaign too),
          so it stays on screen in its own words under the one-line job. */}
      <PageHeader
        description={
          <>
            <span className="block font-medium text-ink">{COPY.description}</span>
            <span className="block text-meta">{KEPT.liveCheck}</span>
          </>
        }
      />

      <RestrictionNote reason={write.reason} />

      {/* Checking comes first: "did we stop calling this person?" is the question people
          arrive with, and the one thing everyone with access may do. */}
      <NumberField
        session={session}
        value={paste}
        onChange={setPaste}
        parsed={parsed}
        source={source}
        onSourceChange={setSource}
        canAdd={write.allowed}
      />

      {/* Above the list: the list names people we must not ring; this says whether anyone
          with no record at all may be rung. */}
      <ConsentPosture session={session} />

      <SuppressedList session={session} canSuppress={write.allowed} />
    </div>
  );
}
