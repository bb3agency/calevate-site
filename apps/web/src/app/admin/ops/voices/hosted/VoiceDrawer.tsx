"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { Archive, Check, Copy, Download, RotateCcw, Trash2 } from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { SavedNote, StatusPill, sentenceCase } from "@/components/admin/kit";
import { DatePicker } from "@/components/arc/calendar";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer } from "@/components/console/drawer";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { FileDrop } from "@/components/fileDrop";
import { VoicePreviewButton } from "@/components/voicePreviewButton";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  ToggleSwitch,
  formatIST,
  istDateStamp,
} from "@/components/ui";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import { adminSession } from "@/lib/api/admin";
import { ApiProblem } from "@/lib/api/client";
import {
  CONSENT_SCOPE,
  HOSTED_STATE,
  MAX_SAMPLE_BYTES,
  downloadConsentDocument,
  useAddHostedVoice,
  useDeleteClone,
  useFetchPreview,
  useHostedVoiceAgents,
  useRecordConsent,
  useSetDisplayName,
  useSetHostedState,
  useSetPersonClone,
  useUploadPreview,
  type HostedVoice,
} from "@/lib/api/opsHostedVoices";
import { OPS_PREVIEW_PATH } from "@/lib/api/voicePreview";
import { lookup } from "@/lib/lookup";

import { archiveBlocked, switchBlocked, tierText, usedBy } from "./HostedVoiceList";
import { accentOf } from "./voiceFilters";

const DISPLAY_MAX = 60;

/** A published agent's use of the voice as the drawer's pill says it; any other agent shows its
 *  status ("Draft", "Archived"). */
const AGENT_USE: Record<string, string> = {
  live: "Live",
  ready: "Ready, not taking calls",
};

/** `2026-10-11` as "11 Oct 2026": a calendar date, so no time zone is involved. */
function formatDay(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}
const DEFAULT_STATEMENT =
  "I agree that a cloned copy of my voice may be used by Calevate as a voice option for the AI phone agents of Calevate's clients. I understand callers will hear it as an AI voice under a name Calevate chooses, and that I can withdraw this consent in writing.";

/**
 * One voice in full (D-687, D-721): listen and fix its preview, offer it, the name clients see,
 * its ids and facts, the agents speaking it, and — for a cloned voice of a real person — that
 * person's consent. The list row keeps only what an operator scans.
 */
export function VoiceDrawer({
  voice,
  onClose,
  onDeleted,
}: {
  voice: HostedVoice;
  onClose: () => void;
  onDeleted: (said: string) => void;
}) {
  const { tier, detail } = tierText(voice);
  return (
    <Drawer
      open
      onClose={onClose}
      title={voice.label}
      description={detail ? `${tier} · ${detail}` : tier}
      width="lg"
      initialFocus="container"
    >
      <div className="space-y-8">
        {voice.withdrawn_at !== null && (
          <NoticeBox tone="stop">
            The voice platform no longer lists this voice, so it is not offered whatever its state.
          </NoticeBox>
        )}
        <ListenSection voice={voice} />
        <OfferSection voice={voice} />
        <NameSection voice={voice} />
        <FactsSection voice={voice} />
        <AgentsSection voice={voice} />
        {voice.added && <CloneSection voice={voice} />}
        {voice.deletable_clone && <DeleteCloneSection voice={voice} onDeleted={onDeleted} onClose={onClose} />}
      </div>
    </Drawer>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 text-body font-semibold text-ink">{children}</h3>;
}

/** Play the stored clip, or make one: the platform's own for a Studio voice or our clone, else upload. */
function ListenSection({ voice }: { voice: HostedVoice }) {
  const upload = useUploadPreview();
  const fetchPreview = useFetchPreview();
  // Both refusals are printed under the control; the new clip is the success.
  useActionFeedback(upload, { errorDisplay: "inline" });
  const fetchFeedback = useActionFeedback(fetchPreview, { errorDisplay: "inline" });
  const canGenerate = voice.source === "byok" || voice.is_custom;
  const fetchRefused =
    fetchPreview.error instanceof ApiProblem && fetchPreview.error.code === "voice_preview_unavailable";
  const [file, setFile] = useState<File | null>(null);

  return (
    <section>
      <SectionTitle>Preview</SectionTitle>
      <div className="flex flex-wrap items-center gap-3">
        {voice.preview_available ? (
          <VoicePreviewButton
            session={adminSession()}
            path={OPS_PREVIEW_PATH}
            voiceId={voice.voice_id}
            label={voice.label}
          />
        ) : (
          <p className="text-body text-ink-muted">No preview yet, so clients cannot listen to it.</p>
        )}
        {canGenerate && (
          <ActionButton
            variant="secondary-sm"
            status={fetchFeedback.status}
            pendingLabel="Fetching…"
            successLabel="Generated"
            onClick={() => fetchFeedback.run({ voice_id: voice.voice_id })}
          >
            {voice.preview_available ? "Generate again" : "Generate preview"}
          </ActionButton>
        )}
      </div>
      {voice.source === "byok" && !voice.preview_available && (
        <p className={FIELD_HINT}>Generating speaks one short line on our Cartesia key, charged per character.</p>
      )}
      {fetchPreview.error != null && (
        <div className="mt-2">
          <ProblemNotice error={fetchPreview.error} />
        </div>
      )}
      {/* Upload is offered for every voice, beside Generate where it exists: an operator may
          prefer a clip they recorded or chose over the platform's generated line. */}
      <FileDrop
        className="mt-3"
        label={voice.preview_available ? "Replace the preview" : "Upload a preview"}
        hint={
          canGenerate && !fetchRefused
            ? "Or upload your own MP3 or WAV clip of this voice, up to 2 MB."
            : "An MP3 or WAV clip of this voice, up to 2 MB."
        }
        accept="audio/mpeg,audio/wav,.mp3,.wav"
        maxBytes={MAX_SAMPLE_BYTES}
        files={file ? [file] : []}
        onRemove={() => setFile(null)}
        sending={upload.isPending && file ? { file, percent: null } : null}
        onFiles={([chosen]) => {
          if (!chosen) return;
          setFile(chosen);
          upload.mutate({ voiceId: voice.voice_id, sample: chosen }, { onSettled: () => setFile(null) });
        }}
      />
      {upload.error != null && (
        <div className="mt-2">
          <ProblemNotice error={upload.error} />
        </div>
      )}
      {upload.isSuccess && <SavedNote className="mt-2">Preview saved.</SavedNote>}
    </section>
  );
}

function OfferSection({ voice }: { voice: HostedVoice }) {
  const add = useAddHostedVoice();
  const setState = useSetHostedState();
  const addFeedback = useActionFeedback(add, { errorDisplay: "inline" });
  const setStateFeedback = useActionFeedback(setState, { errorDisplay: "inline" });
  const [archiving, setArchiving] = useState(false);
  // An archive that went through closes its dialog; the switch and the next step say the rest.
  useEffect(() => {
    if (setStateFeedback.status === "success") setArchiving(false);
  }, [setStateFeedback.status]);
  const pressedState = setState.variables?.state;
  const blocked = switchBlocked(voice);
  // Said before the click, like `blocked`: the agents are listed under "Agents on this voice".
  const archiveRefusal = archiveBlocked(voice);
  const archiveHintId = useId();
  const state = lookup(HOSTED_STATE, voice.state);
  // Enabled but not on the picker: the API says why in its own fields.
  const enabledNotOffered = voice.state === "enabled" && !voice.offered;

  return (
    <section>
      <SectionTitle>Offer</SectionTitle>
      {!voice.added ? (
        <div className="space-y-2">
          <p className="text-body text-ink-muted">
            {voice.sold
              ? "Not added yet. Added voices arrive switched off."
              : (voice.not_sold_reason ?? "In a band we do not sell.")}
          </p>
          {voice.sold && (
            <ActionButton
              variant="primary-sm"
              status={addFeedback.status}
              disabled={voice.withdrawn_at !== null}
              pendingLabel="Adding…"
              successLabel="Added"
              onClick={() => addFeedback.run(voice.voice_id)}
            >
              {`Add ${voice.label}`}
            </ActionButton>
          )}
          {add.error != null && <ProblemNotice error={add.error} />}
        </div>
      ) : (
        <div className="space-y-3">
          <ToggleSwitch
            label={state?.label ?? voice.state}
            hint={
              enabledNotOffered
                ? `Switched on, but not offered: ${voice.clone_blocker ?? blocked ?? "it is not on the platform any more"}.`
                : blocked && voice.state !== "enabled"
                  ? `${state?.meaning ?? ""} ${blocked}.`
                  : state?.meaning
            }
            checked={voice.state === "enabled"}
            disabled={setStateFeedback.status === "pending" || (blocked !== null && voice.state !== "enabled")}
            onChange={(on) => setStateFeedback.run({ voice_id: voice.voice_id, state: on ? "enabled" : "disabled" })}
          />
          <div className="flex flex-wrap items-center gap-2">
            {voice.state !== "archived" ? (
              <>
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={archiveRefusal !== null}
                  aria-describedby={archiveRefusal ? archiveHintId : undefined}
                  onClick={() => {
                    setState.reset();
                    setArchiving(true);
                  }}
                >
                  <Archive aria-hidden className="h-4 w-4" />
                  Archive
                </button>
                {archiveRefusal && (
                  <p id={archiveHintId} className="text-meta text-ink-muted">
                    {archiveRefusal}
                  </p>
                )}
              </>
            ) : (
              <ActionButton
                variant="secondary-sm"
                status={pressedState === "disabled" ? setStateFeedback.status : "idle"}
                pendingLabel="Restoring…"
                successLabel="Restored"
                onClick={() => setStateFeedback.run({ voice_id: voice.voice_id, state: "disabled" })}
              >
                <RotateCcw aria-hidden className="h-4 w-4" />
                Restore, not offered
              </ActionButton>
            )}
          </div>
          {!archiving && setState.error != null && <ProblemNotice error={setState.error} />}
          {!archiving && setState.data && <p className="text-meta text-ink-muted">{setState.data.next_step}</p>}
        </div>
      )}
      {archiving && (
        <ConfirmDialog
          title={`Archive ${voice.label}?`}
          confirmLabel="Archive voice"
          pendingLabel="Archiving…"
          status={setStateFeedback.status}
          error={setState.error}
          onCancel={() => setArchiving(false)}
          onConfirm={() => setStateFeedback.run({ voice_id: voice.voice_id, state: "archived" })}
        >
          <p>{HOSTED_STATE.archived!.meaning}</p>
        </ConfirmDialog>
      )}
    </section>
  );
}

/** The name clients see; the provider's own name stays visible to the operator. */
function NameSection({ voice }: { voice: HostedVoice }) {
  const save = useSetDisplayName();
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Name saved" });
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (saveFeedback.status === "success") setEditing(false);
  }, [saveFeedback.status]);
  const [draft, setDraft] = useState(voice.display_label ?? "");
  const fieldId = useId();

  return (
    <section>
      <SectionTitle>Name clients see</SectionTitle>
      {!editing ? (
        <SettingRows>
          <SettingRow
            label="Clients see"
            value={voice.label}
            action={
              <button
                type="button"
                className={TEXT_ACTION}
                onClick={() => {
                  save.reset();
                  setDraft(voice.display_label ?? "");
                  setEditing(true);
                }}
              >
                Change
              </button>
            }
          />
          {voice.display_label && <SettingRow label="Provider's name" value={voice.vendor_label} />}
        </SettingRows>
      ) : (
        <form
          noValidate
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            saveFeedback.run({ voice_id: voice.voice_id, display_label: draft.trim() || null });
          }}
        >
          <label htmlFor={fieldId} className={FIELD_LABEL}>
            Name clients see
          </label>
          <input
            id={fieldId}
            className={FIELD}
            value={draft}
            maxLength={DISPLAY_MAX}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={voice.vendor_label}
          />
          <p className={FIELD_HINT}>
            Empty uses the provider&rsquo;s name, {voice.vendor_label}.
            {voice.person_clone && " A cloned voice needs its own name, never the speaker's."}
          </p>
          {save.error != null && <ProblemNotice error={save.error} />}
          <div className="flex gap-2">
            <ActionButton type="submit" variant="primary-sm" status={saveFeedback.status} pendingLabel="Saving…">
              Save name
            </ActionButton>
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function CopyId({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <MonoValue className="break-all text-meta">{value}</MonoValue>
      <button
        type="button"
        className={TEXT_ACTION}
        aria-label={copied ? "Voice id copied" : "Copy the voice id"}
        onClick={() =>
          void navigator.clipboard?.writeText(value).then(
            () => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            },
            () => undefined,
          )
        }
      >
        {copied ? <Check aria-hidden className="h-4 w-4" /> : <Copy aria-hidden className="h-4 w-4" />}
      </button>
    </span>
  );
}

function FactsSection({ voice }: { voice: HostedVoice }) {
  const accent = accentOf(voice);
  const languages = voice.source === "engine"
    ? "Every language the agent speaks"
    : voice.languages.map((tag) => lookup(LANGUAGE_NAMES, tag) ?? tag).join(", ") || "Not stated";
  return (
    <section>
      <SectionTitle>Details</SectionTitle>
      <SettingRows>
        <SettingRow label="Voice id" value={<CopyId value={voice.vendor_id} />} />
        <SettingRow label="Speaks" value={languages} />
        {accent && <SettingRow label={voice.source === "engine" ? "Accent" : "Language"} value={accent} />}
        {voice.gender && <SettingRow label="Gender" value={sentenceCase(voice.gender)} />}
        {voice.description && <SettingRow label="Description" value={voice.description} />}
        <SettingRow label="Last read from the platform" value={formatIST(voice.synced_at)} />
        {voice.curated_at && <SettingRow label="Last changed here" value={formatIST(voice.curated_at)} />}
      </SettingRows>
    </section>
  );
}

function AgentsSection({ voice }: { voice: HostedVoice }) {
  const agents = useHostedVoiceAgents(voice.voice_id);
  return (
    <section>
      <SectionTitle>Agents on this voice</SectionTitle>
      {agents.error != null ? (
        <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />
      ) : !agents.data ? (
        <Skeleton rows={2} label="Reading the agents on this voice" />
      ) : agents.data.agents.length === 0 ? (
        <p className="text-body text-ink-muted">No agent uses this voice.</p>
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {agents.data.agents.map((agent) => (
            <li key={agent.agent_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className="min-w-0">
                <Link href={`/admin/tenants/${agent.tenant_id}/agents`} className={TEXT_ACTION}>
                  {agent.agent_name}
                </Link>
                <span className="text-meta text-ink-muted">{` · ${agent.tenant_name}`}</span>
              </span>
              <StatusPill tone={agent.use === "live" ? "ok" : "neutral"}>
                {lookup(AGENT_USE, agent.use) ?? sentenceCase(agent.status)}
              </StatusPill>
            </li>
          ))}
        </ul>
      )}
      <p className={FIELD_HINT}>{usedBy(voice.used_by)} across every client.</p>
    </section>
  );
}

/**
 * A cloned voice of a real person (D-721). It cannot be offered until the speaker's consent is
 * recorded and it has a name of our own; clients never learn whose voice it is.
 */
function CloneSection({ voice }: { voice: HostedVoice }) {
  const mark = useSetPersonClone();
  const markFeedback = useActionFeedback(mark, { errorDisplay: "inline" });
  const [unmarking, setUnmarking] = useState(false);
  useEffect(() => {
    if (markFeedback.status === "success") setUnmarking(false);
  }, [markFeedback.status]);
  const [recording, setRecording] = useState(false);
  const consent = voice.clone_consent;

  return (
    <section>
      <SectionTitle>Cloned voice of a real person</SectionTitle>
      <ToggleSwitch
        label="A cloned voice of a real person"
        hint="Clients see it under the name above. Note the speaker's consent once, and it is kept on file."
        checked={voice.person_clone || recording}
        disabled={markFeedback.status === "pending"}
        onChange={(on) => {
          // With no consent on file the server refuses the bare mark on an offered voice, so
          // switching on opens the consent form; recording it sets the mark too.
          if (on && consent) markFeedback.run({ voice_id: voice.voice_id, person_clone: true });
          else if (on) setRecording(true);
          else if (recording && !voice.person_clone) setRecording(false);
          else {
            mark.reset();
            setUnmarking(true);
          }
        }}
      />
      {!unmarking && mark.error != null && (
        <div className="mt-2">
          <WriteFailure error={mark.error} actionLabel="Mark as a cloned voice" />
        </div>
      )}
      {(voice.person_clone || recording) && (
        <div className="mt-4 space-y-3">
          {consent && !recording ? (
            <>
              <SettingRows>
                <SettingRow label="Speaker" value={consent.speaker_name} />
                <SettingRow label="Consented on" value={formatDay(consent.consented_on)} />
                <SettingRow label="Statement" value={consent.statement} />
                <SettingRow label="Covers" value={consent.scope} />
                <SettingRow
                  label="Recorded by"
                  value={`${consent.recorded_by_name ?? "An operator"}, ${formatIST(consent.recorded_at)}`}
                />
                <SettingRow
                  label="Signed document"
                  value={consent.has_document ? "Stored, sealed" : "None uploaded"}
                  action={
                    consent.has_document ? (
                      <button
                        type="button"
                        className={TEXT_ACTION}
                        onClick={() => void downloadConsentDocument(voice.voice_id, voice.label).catch(() => undefined)}
                      >
                        <Download aria-hidden className="h-4 w-4" />
                        Download
                      </button>
                    ) : undefined
                  }
                />
              </SettingRows>
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setRecording(true)}>
                Replace the consent record
              </button>
            </>
          ) : (
            <ConsentForm
              voice={voice}
              onDone={() => setRecording(false)}
              onCancel={consent || !voice.person_clone ? () => setRecording(false) : undefined}
            />
          )}
        </div>
      )}
      {unmarking && (
        <ConfirmDialog
          title={`${voice.label} is not a cloned voice?`}
          confirmLabel="Remove the mark"
          pendingLabel="Removing…"
          status={markFeedback.status}
          error={mark.error}
          onCancel={() => setUnmarking(false)}
          onConfirm={() => markFeedback.run({ voice_id: voice.voice_id, person_clone: false })}
        >
          <p>
            Only do this if the voice is not a copy of a real person&rsquo;s voice.
            {consent && " The consent record and its signed document are kept."}
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}

function ConsentForm({
  voice,
  onDone,
  onCancel,
}: {
  voice: HostedVoice;
  onDone: () => void;
  onCancel?: () => void;
}) {
  const record = useRecordConsent();
  const recordFeedback = useActionFeedback(record, {
    errorDisplay: "inline",
    successToast: "Consent recorded",
  });
  const ids = { speaker: useId(), statement: useId() };
  const today = istDateStamp();
  // Closed from an effect so the toast is raised before the form unmounts.
  useEffect(() => {
    if (recordFeedback.status === "success") onDone();
  }, [recordFeedback.status, onDone]);
  const [speaker, setSpeaker] = useState("");
  const [consentedOn, setConsentedOn] = useState(today);
  const [statement, setStatement] = useState(DEFAULT_STATEMENT);
  const [document, setDocument] = useState<File | null>(null);
  const complete = speaker.trim() !== "" && statement.trim() !== "" && consentedOn !== "" && consentedOn <= today;

  return (
    <form
      noValidate
      className="space-y-3"
      aria-label="Record the speaker's consent"
      onSubmit={(event) => {
        event.preventDefault();
        if (!complete) return;
        recordFeedback.run({
          voiceId: voice.voice_id,
          speakerName: speaker.trim(),
          statement: statement.trim(),
          consentedOn,
          document,
        });
      }}
    >
      <p className="text-body text-ink-muted">
        Record the speaker&rsquo;s consent. It covers: {CONSENT_SCOPE}
      </p>
      <div>
        <label htmlFor={ids.speaker} className={FIELD_LABEL}>
          Speaker&rsquo;s full name
        </label>
        <input id={ids.speaker} className={FIELD} value={speaker} maxLength={120} onChange={(e) => setSpeaker(e.target.value)} />
        <p className={FIELD_HINT}>Kept with the record. Clients never see it.</p>
      </div>
      <DatePicker
        label="Date they consented"
        value={consentedOn || null}
        max={today}
        onChange={(day) => setConsentedOn(day ?? "")}
      />
      <div>
        <label htmlFor={ids.statement} className={FIELD_LABEL}>
          What they agreed to
        </label>
        <textarea
          id={ids.statement}
          className={`${FIELD} min-h-28`}
          value={statement}
          maxLength={2000}
          onChange={(e) => setStatement(e.target.value)}
        />
      </div>
      <FileDrop
        label="Signed consent (optional)"
        hint={
          voice.clone_consent?.has_document
            ? "A PDF, JPEG or PNG, up to 2 MB. Leave empty to keep the stored one."
            : "A PDF, JPEG or PNG, up to 2 MB. Stored sealed."
        }
        accept="application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png"
        maxBytes={MAX_SAMPLE_BYTES}
        files={document ? [document] : []}
        onRemove={() => setDocument(null)}
        onFiles={([chosen]) => setDocument(chosen ?? null)}
      />
      {record.error != null && <WriteFailure error={record.error} actionLabel="Record consent" />}
      <div className="flex flex-wrap gap-2">
        <ActionButton
          type="submit"
          variant="primary-sm"
          status={recordFeedback.status}
          disabled={!complete}
          pendingLabel="Recording…"
        >
          Record consent
        </ActionButton>
        {onCancel && (
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

function DeleteCloneSection({
  voice,
  onDeleted,
  onClose,
}: {
  voice: HostedVoice;
  onDeleted: (said: string) => void;
  onClose: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  return (
    <section>
      <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setDeleting(true)} aria-label={`Delete the clone ${voice.label}`}>
        <Trash2 aria-hidden className="h-4 w-4" />
        Delete clone
      </button>
      {deleting && (
        <DeleteCloneDialog
          voice={voice}
          onClose={() => setDeleting(false)}
          onDeleted={(said) => {
            onDeleted(said);
            onClose();
          }}
        />
      )}
    </section>
  );
}

/**
 * Delete one of our clones. The first request goes WITHOUT `confirm`: with any agent on it
 * the server refuses with `voice_clone_in_use` and names them, and only then is the operator
 * offered the delete that moves them.
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
  // Inline: the in-use refusal is the expected first answer (it names the agents and turns
  // the button into the second decision), and every other refusal is printed in the dialog.
  const removeFeedback = useActionFeedback(remove, { errorDisplay: "inline" });
  const inUse = remove.error instanceof ApiProblem && remove.error.code === "voice_clone_in_use";
  const [confirmed, setConfirmed] = useState(false);
  return (
    <ConfirmDialog
      title={`Delete the clone ${voice.label}?`}
      confirmLabel={inUse ? "Delete and move those agents" : "Delete clone"}
      pendingLabel="Deleting…"
      // The in-use answer is a question, not a failure: the button keeps its new label.
      status={inUse ? "idle" : removeFeedback.status}
      error={null}
      onCancel={onClose}
      onConfirm={() => {
        const confirm = inUse || confirmed;
        if (inUse) setConfirmed(true);
        remove.mutate(
          { voiceId: voice.voice_id, confirm },
          {
            onSuccess: (result) => {
              // `next_step` already says the clone was deleted and how many agents moved;
              // composing those here too printed each of them twice.
              onDeleted(`${voice.label}: ${result.next_step}`);
              onClose();
            },
          },
        );
      }}
    >
      <p>
        This deletes the voice on the voice platform and cannot be undone. Every agent on it, in
        every client account, is moved to the voice platform&rsquo;s default voice.
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
