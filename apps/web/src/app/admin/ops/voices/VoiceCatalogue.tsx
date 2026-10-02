"use client";

import { useState } from "react";
import { TriangleAlert } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { RowMenu } from "@/components/console/rowMenu";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { NoticeBox, ProblemNotice, formatCount } from "@/components/ui";
import {
  CURATION_ACTIONS,
  CURATION_MEANING,
  useSetVoiceCuration,
  type CuratedVoice,
  type CuratedVoices,
  type CurationState,
  type VoiceScope,
} from "@/lib/api/opsVoices";
import { lookup } from "@/lib/lookup";

import { voiceColumns } from "./voiceColumns";

const KEEP_SPEAKING = "Disabling or archiving will not affect them — they keep speaking it.";

type Pending = { voice: CuratedVoice; state: CurationState };

/**
 * The table, given a catalogue that ARRIVED. It takes the payload rather than the query
 * envelope so nothing below can make a claim about what this platform offers out of
 * `undefined`. `offered`, `cached` and `note` are the server's; only the withdrawn tally is
 * counted here, from the rows the server sent.
 */
export function VoiceCatalogue({
  catalogue,
  scope,
  onScope,
}: {
  catalogue: CuratedVoices;
  scope: VoiceScope;
  onScope: (scope: VoiceScope) => void;
}) {
  const curate = useSetVoiceCuration();
  const [confirming, setConfirming] = useState<Pending | null>(null);
  const withdrawn = catalogue.voices.filter((row) => row.withdrawn_at !== null).length;
  const undecided = Math.max(catalogue.cached - catalogue.voices.length, 0);

  const move = (voice: CuratedVoice, state: CurationState) =>
    curate.mutate({ voice_id: voice.voice_id, state }, { onSuccess: () => setConfirming(null) });

  const columns: DataColumn<CuratedVoice>[] = [
    ...voiceColumns(KEEP_SPEAKING),
    {
      id: "actions",
      header: "Actions",
      renderHeader: () => null,
      align: "right",
      cell: (voice) => (
        <RowMenu
          label={voice.label}
          items={CURATION_ACTIONS.map((action) => ({
            id: action.state,
            label: action.label,
            disabled:
              voice.state === action.state ||
              (curate.isPending && curate.variables?.voice_id === voice.voice_id),
            hint: voice.state === action.state ? "Current state" : undefined,
            // Enabling offers a voice and takes nothing away, so it needs no second step.
            onSelect: () =>
              action.state === "enabled" ? move(voice, action.state) : setConfirming({ voice, state: action.state }),
          }))}
        />
      ),
    },
  ];

  return (
    <section aria-labelledby="voices-list" className="space-y-4">
      <div>
        <h2 id="voices-list" className="text-[17px] font-semibold text-ink">
          The voices this platform offers
        </h2>
        <p className="mt-1 text-sm tabular-nums text-ink-muted">
          Offered {formatCount(catalogue.offered)} of {formatCount(catalogue.voices.length)}
          {" · "}
          {formatCount(withdrawn)} withdrawn{" · "}
          {formatCount(catalogue.cached)} on the platform
        </p>
      </div>

      {/* Zero offered has two causes and the server's sentence says which. Above the table,
          because it changes how the table should be read. */}
      {catalogue.offered === 0 && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="No voice can be chosen for any agent right now"
        >
          <p className="mt-1">{catalogue.note}</p>
        </NoticeBox>
      )}

      {confirming === null && curate.error != null && <ProblemNotice error={curate.error} />}
      {curate.data && (
        <NoticeBox tone="neutral" title={`${curate.data.voice.label} updated`}>
          <p className="mt-1">{curate.data.next_step}</p>
        </NoticeBox>
      )}

      {/* The vendor's full list is a reference, one control away, never the screen (D-590). */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <SegmentedControl
          label="Which voices to list"
          value={scope}
          onValueChange={(next) => onScope(next as VoiceScope)}
          options={[
            { value: "decided", label: "Added here" },
            {
              value: "all",
              label: "Every voice the platform lists",
              count: formatCount(catalogue.cached),
            },
          ]}
        />
        {scope === "decided" && undecided > 0 && (
          <span className="text-xs text-ink-muted">
            {formatCount(undecided)} more are on the platform and have not been added. Nothing
            needs to be done with them.
          </span>
        )}
      </div>

      {catalogue.voices.length === 0 ? (
        <EmptyState message="No voice has been added yet. You will need its ID and its name from the provider you cloned it on." />
      ) : (
        <DataTable
          rows={catalogue.voices}
          columns={columns}
          getRowId={(voice) => voice.voice_id}
          label="Voice catalogue"
        />
      )}

      {confirming && (
        <ConfirmDialog
          title={`${confirming.state === "archived" ? "Archive" : "Disable"} ${confirming.voice.label}?`}
          confirmLabel={confirming.state === "archived" ? "Archive voice" : "Disable voice"}
          pendingLabel="Saving…"
          pending={curate.isPending}
          error={curate.error}
          onCancel={() => {
            setConfirming(null);
            curate.reset();
          }}
          onConfirm={() => move(confirming.voice, confirming.state)}
        >
          <p>{lookup(CURATION_MEANING, confirming.state)}</p>
          <p>
            {confirming.voice.live_agents === 0
              ? "No live agent speaks it now."
              : `${formatCount(confirming.voice.live_agents)} live ${
                  confirming.voice.live_agents === 1 ? "agent speaks" : "agents speak"
                } it now, across every client. ${KEEP_SPEAKING}`}
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}
