"use client";

import { useState } from "react";
import { Plus, RefreshCw } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import {
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import {
  useAddVoice,
  useCuratedVoices,
  useRefreshVoiceCatalogue,
  type VoiceScope,
} from "@/lib/api/opsVoices";
import { useHostedVoices } from "@/lib/api/opsHostedVoices";
import { useCopilotSurface } from "@/lib/copilot/registry";

import { AddVoiceDrawer } from "./AddVoiceDrawer";
import { HostedVoicesScreen } from "./hosted/HostedVoicesScreen";
import { VoiceCatalogue } from "./VoiceCatalogue";
import { hostedVoiceFacts, voiceFacts } from "./voiceFacts";

/**
 * The voices this platform has added (D-590): add a cloned voice, and decide which
 * voices clients may pick.
 *
 * TWO SCREENS, AND THE SERVER PICKS (D-687). The hosted list is read first: on an engine
 * that hosts its own voices (ThinnestAI) it answers `available: true` and the hosted screen
 * is shown; anywhere else it answers `available: false` and the Pipecat catalogue below is
 * read and shown, unchanged. The engine is never named in this bundle. The server decides `offered`, the counts and every sentence;
 * this screen computes none of them.
 *
 * `ops:manage` gates the READ as well as the writes, asked of `GET /v1/admin/me`; it is a
 * preview, never the enforcement. No `<h1>`: the shell prints the nav label.
 */
export default function VoicesPage() {
  const access = useAdminAccess("ops:manage", "add and manage the voices this platform offers");
  const [scope, setScope] = useState<VoiceScope>("decided");
  const [adding, setAdding] = useState(false);
  const hosted = useHostedVoices(!access.refused, "added");
  const hostedData = hosted.data?.available ? hosted.data : undefined;
  const pipecat = !access.refused && hosted.data?.available === false;
  const voices = useCuratedVoices(pipecat, scope);
  const add = useAddVoice();
  const refresh = useRefreshVoiceCatalogue();
  const data = voices.data;

  useCopilotSurface({
    route: "/admin/ops/voices",
    title: "Voices",
    realm: "admin",
    fields: [],
    // Nothing here is fillable by the assistant: a guessed voice id would be refused by the
    // platform or, worse, belong to a different voice.
    apply: () => undefined,
    facts: hostedData
      ? hostedVoiceFacts(hostedData)
      : voiceFacts(access.refused, data, voices.error != null || hosted.error != null),
  });

  if (hostedData) return <HostedVoicesScreen added={hostedData} />;

  const openAdd = () => {
    add.reset();
    setAdding(true);
  };

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        description="Only voices added here can be chosen for an agent — by a client for their own, or by an admin for anyone's."
        actions={
          !access.refused && data ? (
            <>
              <div className="flex items-center gap-0.5">
                <button
                  type="button"
                  className={SECONDARY_BUTTON}
                  disabled={refresh.isPending}
                  onClick={() => void refresh.mutateAsync().catch(() => undefined)}
                >
                  <RefreshCw aria-hidden className="h-4 w-4" />
                  {refresh.isPending ? "Reading the voice platform…" : "Refresh from the platform"}
                </button>
                <InfoTip label="Refresh">
                  Re-reads the voice platform&rsquo;s own list. It does not add anything &mdash; it
                  keeps the &ldquo;last seen&rdquo; column honest and marks voices that platform
                  has stopped listing.
                </InfoTip>
              </div>
              <button type="button" className={PRIMARY_BUTTON} onClick={openAdd}>
                <Plus aria-hidden className="h-4 w-4" />
                Add a voice
              </button>
            </>
          ) : undefined
        }
      />

      {access.refused ? (
        // The refusal INSTEAD of the screen: this is a permission working as designed, not
        // an outage.
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          {hosted.error != null && (
            <ProblemNotice error={hosted.error} onRetry={() => void hosted.refetch()} />
          )}
          {voices.error != null && (
            <ProblemNotice error={voices.error} onRetry={() => void voices.refetch()} />
          )}
          {/* A MUTATION's `data` is the operator having asked, so rendering it is correct;
              each is the server's sentence, verbatim. */}
          {refresh.data && (
            <NoticeBox tone="neutral" title="The voice platform's catalogue was re-read">
              <p className="mt-1">{refresh.data.note}</p>
            </NoticeBox>
          )}
          {refresh.error != null && <ProblemNotice error={refresh.error} />}
          {add.data && !adding && (
            <NoticeBox tone="neutral" title="Voice added">
              <p className="mt-1">{add.data.next_step}</p>
            </NoticeBox>
          )}

          {/* §52: no data is in flight, failed, or paused — never "no voices". */}
          {!data ? (
            voices.error || hosted.error ? null : <Skeleton rows={8} label="Loading the voices this platform offers" />
          ) : (
            <VoiceCatalogue catalogue={data} scope={scope} onScope={setScope} />
          )}

          {adding && data && (
            <AddVoiceDrawer
              form={data.form}
              busy={add.isPending}
              error={add.error}
              onAdd={(body) =>
                void add
                  .mutateAsync(body)
                  .then(() => setAdding(false))
                  .catch(() => undefined)
              }
              onClose={() => setAdding(false)}
            />
          )}
        </>
      )}
    </div>
  );
}
