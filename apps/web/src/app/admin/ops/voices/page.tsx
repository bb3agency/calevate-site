"use client";

import { identityAnswerPending, useAdminAccess, useAdminMe } from "@/app/admin/access";
import { PageHeader } from "@/components/console/pageHeader";
import { NoticeBox, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { useHostedVoices, type HostedVoices } from "@/lib/api/opsHostedVoices";
import { useCopilotSurface } from "@/lib/copilot/registry";

import { HostedVoicesScreen } from "./hosted/HostedVoicesScreen";

type Fact = { key: string; label: string; value: string };

/**
 * The voices this platform offers (D-590, D-687): the voice platform hosts them, and this
 * page decides which ones clients may pick.
 *
 * An engine that hosts no voices of its own answers `available: false` with the server's
 * sentence, which is printed as it is. The server decides `offered`, the counts and every
 * sentence; this screen computes none of them.
 *
 * `ops:manage` gates the READ as well as the writes, asked of `GET /v1/admin/me`; it is a
 * preview, never the enforcement. The read waits for that answer (`identityAnswerPending`),
 * so a session without the permission sends no request it can only be refused. No `<h1>`:
 * the shell prints the nav label.
 */
export default function VoicesPage() {
  const access = useAdminAccess("ops:manage", "add and manage the voices this platform offers");
  const identityLoading = identityAnswerPending(useAdminMe());
  const hosted = useHostedVoices(!identityLoading && !access.refused, "added");
  const data = hosted.data;

  useCopilotSurface({
    route: "/admin/ops/voices",
    title: "Voices",
    realm: "admin",
    fields: [],
    // Nothing here is fillable by the assistant: a guessed voice id would be refused by the
    // platform or, worse, belong to a different voice.
    apply: () => undefined,
    facts: voiceFacts(access.refused, data, hosted.error != null),
  });

  if (data?.available) return <HostedVoicesScreen added={data} />;

  return (
    <div className="max-w-5xl space-y-10 pb-12">
      <PageHeader description="Clients choose only from the voices offered here." />
      {access.refused ? (
        // The refusal INSTEAD of the screen: a permission working as designed, not an outage.
        <RestrictionNote reason={access.reason} />
      ) : hosted.error != null ? (
        <ProblemNotice error={hosted.error} onRetry={() => void hosted.refetch()} />
      ) : !data ? (
        <Skeleton rows={8} label="Loading the voices this platform offers" />
      ) : (
        <NoticeBox tone="neutral" title="No voices to manage here">
          <p className="mt-1">{data.note}</p>
        </NoticeBox>
      )}
    </div>
  );
}

/**
 * What the screen assistant is told. Counts only: nothing on this screen is fillable by it,
 * because every field is a fact about a voice on another company's platform that the
 * operator has in front of them and the model does not.
 */
function voiceFacts(refused: boolean, data: HostedVoices | undefined, failed: boolean): Fact[] {
  if (refused) {
    return [
      {
        key: "voices",
        label: "The voice catalogue",
        value: "withheld — this admin account may not read it",
      },
    ];
  }
  if (!data?.available) {
    return [
      {
        key: "voices",
        label: "The voice catalogue",
        value: failed ? "could not be read" : data ? data.note : "still loading",
      },
    ];
  }
  return [
    { key: "offered", label: "Voices clients can currently choose", value: String(data.offered) },
    { key: "added", label: "Voices added here", value: String(data.voices.length) },
    { key: "cached", label: "Voices the voice platform lists", value: String(data.cached) },
    {
      key: "studio",
      label: "Studio voices (our Cartesia key)",
      value: data.studio_ready ? "on" : "off",
    },
    {
      key: "no_preview",
      label: "Added voices with no preview clients can play",
      value: String(data.voices.filter((v) => !v.preview_available).length),
    },
    {
      key: "clone_blocked",
      label: "Cloned voices of real people that cannot be offered yet",
      value:
        data.voices
          .filter((v) => v.clone_blocker)
          .map((v) => `${v.label}: ${v.clone_blocker}`)
          .join("; ") || "none",
    },
  ];
}
