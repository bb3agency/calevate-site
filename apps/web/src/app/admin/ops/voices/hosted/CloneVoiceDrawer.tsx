"use client";

import { useId, useState } from "react";
import { AudioLines } from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { Drawer, DrawerSubmit } from "@/components/console/drawer";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ToggleSwitch,
} from "@/components/ui";
import { LANGUAGE_CHOICES } from "@/lib/agentState";
import { MAX_SAMPLE_BYTES, useCloneVoice } from "@/lib/api/opsHostedVoices";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

/** The formats the clone route accepts. The server checks again; this only filters the picker. */
const SAMPLE_ACCEPT = "audio/wav,audio/x-wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/webm,.wav,.mp3,.m4a,.webm";

/** This product's languages, as the tags the clone route takes. */
const LANGUAGES: readonly { value: string; label: string }[] = [
  { value: "", label: "Not specified" },
  ...LANGUAGE_CHOICES,
];

const NAME_MAX = 40;
const DESCRIPTION_MAX = 200;

/**
 * Clone a voice on ThinnestAI from one recording (D-687). Only an admin clones; the clone
 * lands ADDED and DISABLED, so no client hears it until it is enabled on the list.
 *
 * The two consents are the operator's own legal attestations, recorded on the server with
 * who gave them and when. They are separate checkboxes, both required, and never
 * pre-ticked: one box covering both would be a promise nobody read.
 *
 * The write is step-up confirmed (`X-Confirm-Action: clone_voice`); a stale second factor
 * comes back as `reauthentication_required` and `WriteFailure` offers the prompt.
 */
export function CloneVoiceDrawer({ onClose }: { onClose: () => void }) {
  const clone = useCloneVoice();
  const formId = useId();
  const [sample, setSample] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [language, setLanguage] = useState<string>(LANGUAGE_CHOICES[0]?.value ?? "");
  const [removeNoise, setRemoveNoise] = useState(true);
  const [ownVoice, setOwnVoice] = useState(false);
  const [noImpersonation, setNoImpersonation] = useState(false);
  const dirty = !clone.data && (sample !== null || name !== "" || description !== "");
  useUnsavedGuard(dirty);

  const tooBig = sample !== null && sample.size > MAX_SAMPLE_BYTES;
  const complete = sample !== null && !tooBig && name.trim() !== "" && ownVoice && noImpersonation;

  if (clone.data) {
    return (
      <Drawer open onClose={onClose} title="Voice cloned" width="lg">
        <div className="space-y-4">
          <NoticeBox tone="ok" title={`${clone.data.voice.label} is cloned`}>
            <p className="mt-1">{clone.data.next_step}</p>
            {!clone.data.usable_on_agents && (
              <p className="mt-1">It cannot be put on an agent yet.</p>
            )}
          </NoticeBox>
          <p className="text-sm text-ink-muted">
            It is added but not offered. A clone is a Studio-tier voice, so it can be offered as
            Clear only while Clear is sold on the Studio tier. Listen to its preview, then switch
            on &ldquo;Offered to clients&rdquo;.
          </p>
          <button type="button" className={PRIMARY_BUTTON} onClick={onClose}>
            Back to voices
          </button>
        </div>
      </Drawer>
    );
  }

  return (
    <Drawer
      open
      dirty={dirty}
      onClose={onClose}
      title="Clone a voice"
      description="One clean recording of one speaker becomes a Studio-tier voice of ours. Cloning needs ThinnestAI Pro or above. Clients never clone; they choose from voices you enable."
      width="lg"
      formId={formId}
      footer={
        <DrawerSubmit className={PRIMARY_BUTTON} disabled={clone.isPending || !complete}>
          <AudioLines aria-hidden className="h-4 w-4" />
          {clone.isPending ? "Cloning — this can take a minute…" : "Clone this voice"}
        </DrawerSubmit>
      }
    >
      <form
        id={formId}
        noValidate
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (!complete || sample === null) return;
          clone.mutate({
            sample,
            name: name.trim(),
            description: description.trim(),
            language,
            removeNoise,
            consentOwnVoice: ownVoice,
            consentNoImpersonation: noImpersonation,
          });
        }}
      >
        <label className="block">
          <span className={FIELD_LABEL}>Recording</span>
          <input
            type="file"
            accept={SAMPLE_ACCEPT}
            className={`${FIELD} py-1.5`}
            aria-describedby={`${formId}-sample-hint`}
            aria-invalid={tooBig ? true : undefined}
            onChange={(event) => setSample(event.target.files?.[0] ?? null)}
          />
          <span id={`${formId}-sample-hint`} className={FIELD_HINT}>
            WAV, MP3, M4A or WebM, at most 2 MB. Between 5 and 30 seconds of one person
            speaking naturally; about 15 seconds in a quiet room works best.
          </span>
          {tooBig && (
            <span role="alert" className="mt-1 block text-xs text-warn">
              That file is larger than 2 MB. Trim it or export a compressed MP3.
            </span>
          )}
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className={FIELD_LABEL}>Name</span>
            <input
              className={FIELD}
              value={name}
              maxLength={NAME_MAX}
              onChange={(event) => setName(event.target.value)}
            />
            <span className={FIELD_HINT}>What clients see in the picker. At most 40 characters.</span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Language</span>
            <select className={FIELD} value={language} onChange={(event) => setLanguage(event.target.value)}>
              {LANGUAGES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <span className={FIELD_HINT}>The language spoken in the recording.</span>
          </label>
        </div>

        <label className="block">
          <span className={FIELD_LABEL}>Description (optional)</span>
          <textarea
            className={FIELD}
            rows={2}
            value={description}
            maxLength={DESCRIPTION_MAX}
            onChange={(event) => setDescription(event.target.value)}
          />
          <span className={FIELD_HINT}>For example &ldquo;warm, calm, middle-aged&rdquo;. At most 200 characters.</span>
        </label>

        <ToggleSwitch
          label="Remove background noise"
          hint="Cleans the recording before cloning. Leave on unless the sample is studio-clean."
          checked={removeNoise}
          onChange={setRemoveNoise}
        />

        <fieldset className="space-y-3 rounded-card border border-line p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Your two promises</legend>
          <p className="text-xs text-ink-muted">
            Both are recorded against your name with the time. The clone cannot be made without
            them.
          </p>
          <label className="flex items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-1"
              checked={ownVoice}
              onChange={(event) => setOwnVoice(event.target.checked)}
            />
            <span>
              The voice in this recording is mine, or the person speaking has agreed in
              writing to have their voice cloned for use on calls.
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-1"
              checked={noImpersonation}
              onChange={(event) => setNoImpersonation(event.target.checked)}
            />
            <span>
              This voice will not be used to pretend to be any real person, and will not be
              presented as anyone it is not.
            </span>
          </label>
        </fieldset>

        {clone.error != null && <WriteFailure error={clone.error} actionLabel="Clone this voice" />}
      </form>
    </Drawer>
  );
}
