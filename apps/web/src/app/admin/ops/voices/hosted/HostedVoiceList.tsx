"use client";

import { useRef, useState } from "react";
import { Archive, Plus, Sparkles, Trash2, Upload } from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { SavedNote, StatusPill } from "@/components/admin/kit";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { VoicePreviewButton } from "@/components/voicePreviewButton";
import {
  MonoValue,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  ToggleSwitch,
  formatCount,
} from "@/components/ui";
import { adminSession } from "@/lib/api/admin";
import { ApiProblem } from "@/lib/api/client";
import {
  BAND_LABEL,
  HOSTED_STATE_MEANING,
  MAX_SAMPLE_BYTES,
  RUNG_LABEL,
  useAddHostedVoice,
  useDeleteClone,
  useFetchPreview,
  useSetHostedState,
  useUploadPreview,
  type HostedVoice,
} from "@/lib/api/opsHostedVoices";
import { OPS_PREVIEW_PATH } from "@/lib/api/voicePreview";
import { lookup } from "@/lib/lookup";

/** One row per voice, between hairlines: each row carries its own actions. */
export function HostedVoiceList({ voices, empty }: { voices: HostedVoice[]; empty: string }) {
  // What the last delete did, said above the list: the deleted voice's row is gone, so its
  // own acknowledgement cannot sit beside it.
  const [deleted, setDeleted] = useState<string | null>(null);
  return (
    <div className="space-y-3">
      {deleted && <SavedNote>{deleted}</SavedNote>}
      {voices.length === 0 ? (
        <EmptyState message={empty} />
      ) : (
        <ul className="divide-y divide-line border-y border-line" aria-label="Voices">
          {voices.map((voice) => (
            <VoiceCard key={voice.voice_id} voice={voice} onDeleted={setDeleted} />
          ))}
        </ul>
      )}
    </div>
  );
}

function VoiceCard({ voice, onDeleted }: { voice: HostedVoice; onDeleted: (said: string) => void }) {
  const add = useAddHostedVoice();
  const setState = useSetHostedState();
  const [archiving, setArchiving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const withdrawn = voice.withdrawn_at !== null;
  const headingId = `voice-${voice.voice_id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
  const notSoldId = `${headingId}-not-sold`;

  return (
    <li
      aria-labelledby={headingId}
      className="flex min-w-0 flex-col gap-3 py-4 sm:px-2"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 id={headingId} className="break-words font-semibold text-ink">
            {voice.label}
          </h3>
          <MonoValue className="block break-all text-meta text-ink-muted">{voice.voice_id}</MonoValue>
        </div>
        <div className="flex flex-wrap gap-1">
          {voice.rung != null && (
            <StatusPill tone={voice.rung === "clear" ? "ok" : "neutral"}>
              {lookup(RUNG_LABEL, voice.rung) ?? voice.rung}
            </StatusPill>
          )}
          {voice.band != null && (
            <StatusPill>{`${lookup(BAND_LABEL, voice.band) ?? voice.band} tier`}</StatusPill>
          )}
          {voice.is_custom && <StatusPill>Our clone</StatusPill>}
          {voice.source === "byok" && (
            <StatusPill>Cartesia, our key</StatusPill>
          )}
        </div>
      </div>

      <div className="space-y-1 text-body text-ink-muted">
        <p>{voice.language_note}</p>
        {(voice.accent || voice.description) && (
          <p className="break-words text-meta">
            {[voice.accent, voice.description].filter(Boolean).join(" · ")}
          </p>
        )}
        <p className="text-meta tabular-nums">
          {voice.live_agents === 0
            ? "No live agent speaks it."
            : `${formatCount(voice.live_agents)} live ${voice.live_agents === 1 ? "agent speaks" : "agents speak"} it, across every client.`}
        </p>
        {withdrawn && (
          <p className="text-meta text-warn">
            The voice platform no longer lists this voice, so it is not offered whatever its
            state here.
          </p>
        )}
      </div>

      <PreviewControls voice={voice} />

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
        {!voice.added ? (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={add.isPending || !voice.sold}
            aria-describedby={voice.sold ? undefined : notSoldId}
            onClick={() => add.mutate(voice.voice_id)}
          >
            <Plus aria-hidden className="h-4 w-4" />
            {add.isPending ? "Adding…" : `Add ${voice.label}`}
          </button>
        ) : (
          <>
            <ToggleSwitch
              className="min-w-0 flex-1"
              label="Offered to clients"
              hint={lookup(HOSTED_STATE_MEANING, voice.state) ?? voice.state}
              checked={voice.state === "enabled"}
              disabled={setState.isPending}
              onChange={(on) =>
                setState.mutate({ voice_id: voice.voice_id, state: on ? "enabled" : "disabled" })
              }
            />
            {voice.state !== "archived" && (
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                onClick={() => {
                  setState.reset();
                  setArchiving(true);
                }}
                aria-label={`Archive ${voice.label}`}
              >
                <Archive aria-hidden className="h-4 w-4" />
                Archive
              </button>
            )}
          </>
        )}
        {voice.deletable_clone && (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => setDeleting(true)}
            aria-label={`Delete the clone ${voice.label}`}
          >
            <Trash2 aria-hidden className="h-4 w-4" />
            Delete clone
          </button>
        )}
      </div>

      {!voice.sold && (
        <p id={notSoldId} className="text-meta text-ink-muted">
          {voice.not_sold_reason ?? "Only Studio-tier voices can be offered as Clear."}
        </p>
      )}
      {add.error != null && <ProblemNotice error={add.error} />}
      {add.data && <p className="text-meta text-ink-muted">{add.data.next_step}</p>}
      {!archiving && setState.error != null && <ProblemNotice error={setState.error} />}
      {!archiving && setState.data && <p className="text-meta text-ink-muted">{setState.data.next_step}</p>}

      {archiving && (
        <ConfirmDialog
          title={`Archive ${voice.label}?`}
          confirmLabel="Archive voice"
          pendingLabel="Archiving…"
          pending={setState.isPending}
          error={setState.error}
          onCancel={() => setArchiving(false)}
          onConfirm={() =>
            setState.mutate(
              { voice_id: voice.voice_id, state: "archived" },
              { onSuccess: () => setArchiving(false) },
            )
          }
        >
          <p>{HOSTED_STATE_MEANING.archived}</p>
        </ConfirmDialog>
      )}
      {deleting && (
        <DeleteCloneDialog voice={voice} onClose={() => setDeleting(false)} onDeleted={onDeleted} />
      )}
    </li>
  );
}

/**
 * Play the stored clip, or make one. A Studio voice and one of our clones can have the
 * platform's own preview fetched; a stock platform voice has none, so a clip is uploaded.
 */
function PreviewControls({ voice }: { voice: HostedVoice }) {
  const upload = useUploadPreview();
  const fetchPreview = useFetchPreview();
  const file = useRef<HTMLInputElement>(null);
  const [tooBig, setTooBig] = useState(false);
  const canGenerate = voice.source === "byok" || voice.is_custom;
  const fetchRefused =
    fetchPreview.error instanceof ApiProblem && fetchPreview.error.code === "voice_preview_unavailable";
  const inputId = `preview-file-${voice.voice_id.replace(/[^A-Za-z0-9_-]/g, "-")}`;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {voice.preview_available ? (
          <VoicePreviewButton
            session={adminSession()}
            path={OPS_PREVIEW_PATH}
            voiceId={voice.voice_id}
            label={voice.label}
          />
        ) : (
          <span className="text-meta text-warn">No preview yet — clients cannot listen to it.</span>
        )}
        {canGenerate && (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={fetchPreview.isPending}
            onClick={() => fetchPreview.mutate({ voice_id: voice.voice_id })}
          >
            <Sparkles aria-hidden className="h-4 w-4" />
            {fetchPreview.isPending
              ? "Fetching…"
              : voice.preview_available
                ? "Generate again"
                : "Generate preview"}
          </button>
        )}
        {(!canGenerate || fetchRefused) && (
          <>
            <input
              ref={file}
              id={inputId}
              type="file"
              accept="audio/mpeg,audio/wav,.mp3,.wav"
              className="hidden"
              aria-label={`Upload a preview clip for ${voice.label} (MP3 or WAV, at most 2 MB)`}
              onChange={(event) => {
                const chosen = event.target.files?.[0];
                event.target.value = "";
                if (!chosen) return;
                if (chosen.size > MAX_SAMPLE_BYTES) {
                  setTooBig(true);
                  return;
                }
                setTooBig(false);
                upload.mutate({ voiceId: voice.voice_id, sample: chosen });
              }}
            />
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={upload.isPending}
              onClick={() => file.current?.click()}
            >
              <Upload aria-hidden className="h-4 w-4" />
              {upload.isPending
                ? "Uploading…"
                : voice.preview_available
                  ? "Replace preview"
                  : "Upload preview"}
            </button>
          </>
        )}
      </div>
      {voice.source === "byok" && !voice.preview_available && (
        <p className="text-meta text-ink-muted">
          Generating speaks one short line on our Cartesia key, which Cartesia charges per
          character.
        </p>
      )}
      {tooBig && (
        <p role="alert" className="text-meta text-warn">
          That clip is larger than 2 MB. Choose a shorter MP3 or WAV.
        </p>
      )}
      {fetchPreview.error != null && <ProblemNotice error={fetchPreview.error} />}
      {fetchRefused && (
        <p className="text-meta text-ink-muted">Upload a short MP3 or WAV clip of this voice instead.</p>
      )}
      {upload.error != null && <ProblemNotice error={upload.error} />}
    </div>
  );
}

/**
 * Delete one of our clones. The first request is sent WITHOUT `confirm`: if live agents are
 * on it the server refuses with `voice_clone_in_use` and names them, and only then is the
 * operator offered the delete that moves them.
 */
function DeleteCloneDialog({
  voice,
  onClose,
  onDeleted,
}: {
  voice: HostedVoice;
  onClose: () => void;
  onDeleted: (said: string) => void;
}) {
  const remove = useDeleteClone();
  const inUse = remove.error instanceof ApiProblem && remove.error.code === "voice_clone_in_use";
  const [confirmed, setConfirmed] = useState(false);
  return (
    <ConfirmDialog
      title={`Delete the clone ${voice.label}?`}
      confirmLabel={inUse ? "Delete and move those agents" : "Delete clone"}
      pendingLabel="Deleting…"
      pending={remove.isPending}
      error={null}
      onCancel={onClose}
      onConfirm={() => {
        const confirm = inUse || confirmed;
        if (inUse) setConfirmed(true);
        remove.mutate(
          { voiceId: voice.voice_id, confirm },
          {
            onSuccess: (result) => {
              onDeleted(
                `${voice.label} was deleted. ` +
                  (result.moved_agents === 0
                    ? "No agent was on it. "
                    : `${formatCount(result.moved_agents)} ${result.moved_agents === 1 ? "agent was" : "agents were"} moved to the voice platform's default voice. `) +
                  result.next_step,
              );
              onClose();
            },
          },
        );
      }}
    >
      <p>
        This deletes the voice on the voice platform and cannot be undone. Every agent on it is
        moved to the voice platform&rsquo;s default voice.
      </p>
      {inUse ? (
        <NoticeBox tone="warn" title="Live agents are speaking this voice">
          <p className="mt-1">{remove.error?.message}</p>
        </NoticeBox>
      ) : (
        remove.error != null && <WriteFailure error={remove.error} actionLabel="Delete clone" />
      )}
    </ConfirmDialog>
  );
}
