"use client";

import { useState } from "react";
import { Plus } from "lucide-react";

import { Drawer } from "@/components/console/drawer";
import { FIELD, FIELD_HINT, FIELD_LABEL, PRIMARY_BUTTON, ProblemNotice } from "@/components/ui";
import {
  ADD_FIELD_HINTS,
  CLONE_FIRST,
  type AddVoiceForm,
  type AddVoiceIn,
  type AddVoiceLanguages,
} from "@/lib/api/opsVoices";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

/**
 * Five facts for one cloned voice, checked on the SERVER against the voice platform's own
 * list. Nothing is refused in the browser: a duplicate check here would be a second, weaker
 * copy of the server's, and the copy that disagreed.
 *
 * The provider is radio buttons rather than a `<select>` because a disabled `<option>`
 * cannot be focused on most platforms, so a refused provider's reason would be unreadable.
 * As radios it is visible, disabled, and carries the server's sentence.
 */
export function AddVoiceDrawer({
  form,
  busy,
  error,
  onAdd,
  onClose,
}: {
  form: AddVoiceForm;
  busy: boolean;
  error: Error | null;
  onAdd: (body: AddVoiceIn) => void;
  onClose: () => void;
}) {
  const selectable = form.providers.filter((option) => option.selectable);
  const [provider, setProvider] = useState(selectable[0]?.provider ?? "");
  const models = form.providers.find((o) => o.provider === provider)?.models ?? [];
  const [model, setModel] = useState<string>(models[0] ?? "");
  const [voiceId, setVoiceId] = useState("");
  const [label, setLabel] = useState("");
  const [languages, setLanguages] = useState<string[]>(form.languages.slice(0, 1));
  const dirty = voiceId !== "" || label !== "";
  useUnsavedGuard(dirty);

  // The model belongs to the provider, so a different provider moves it — in the handler,
  // because it is a consequence of a click, not of a render.
  function pickProvider(next: string) {
    setProvider(next);
    setModel(form.providers.find((o) => o.provider === next)?.models[0] ?? "");
  }

  const complete = provider && model && voiceId.trim() && label.trim() && languages.length > 0;

  return (
    <Drawer open dirty={dirty} onClose={onClose} title="Add a voice" description={CLONE_FIRST} width="lg">
      <form
        noValidate
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          onAdd({
            provider,
            tts_model: model,
            engine_voice_id: voiceId.trim(),
            label: label.trim(),
            // The checkbox state is built from the server's `form.languages`; one assertion
            // at the boundary, against the generated type.
            languages: languages as AddVoiceLanguages,
          });
        }}
      >
        <fieldset>
          <legend className={FIELD_LABEL}>Who you cloned it on</legend>
          <span className={FIELD_HINT}>{ADD_FIELD_HINTS.provider}</span>
          <div className="mt-2 space-y-2">
            {form.providers.map((option) => (
              <div key={option.provider}>
                <label className="flex items-center gap-2 text-body touch:min-h-11">
                  <input
                    type="radio"
                    name="voice-provider"
                    value={option.provider}
                    checked={provider === option.provider}
                    disabled={!option.selectable}
                    onChange={() => pickProvider(option.provider)}
                  />
                  <span className={option.selectable ? "" : "text-ink-faint"}>
                    {option.provider}
                    {option.tier_label && (
                      <span className="ml-1 text-meta text-ink-muted">
                        &mdash; the {option.tier_label} tier
                      </span>
                    )}
                  </span>
                </label>
                {option.unavailable_reason && (
                  <p className="ml-6 mt-0.5 text-meta text-warn">{option.unavailable_reason}</p>
                )}
              </div>
            ))}
          </div>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className={FIELD_LABEL}>Speech model</span>
            <select className={FIELD} value={model} onChange={(event) => setModel(event.target.value)}>
              {models.map((each) => (
                <option key={each} value={each}>
                  {each}
                </option>
              ))}
            </select>
            <span className={FIELD_HINT}>{ADD_FIELD_HINTS.tts_model}</span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Voice ID</span>
            <input
              className={`${FIELD} font-mono`}
              value={voiceId}
              maxLength={128}
              onChange={(event) => setVoiceId(event.target.value)}
            />
            <span className={FIELD_HINT}>{ADD_FIELD_HINTS.engine_voice_id}</span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Name, exactly as the provider shows it</span>
            <input
              className={FIELD}
              value={label}
              maxLength={200}
              onChange={(event) => setLabel(event.target.value)}
            />
            <span className={FIELD_HINT}>{ADD_FIELD_HINTS.label}</span>
          </label>

          <fieldset>
            <legend className={FIELD_LABEL}>Languages</legend>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              {form.languages.map((language) => (
                <label key={language} className="flex items-center gap-1.5 text-body touch:min-h-11">
                  <input
                    type="checkbox"
                    checked={languages.includes(language)}
                    onChange={(event) =>
                      setLanguages((held) =>
                        event.target.checked
                          ? [...held, language]
                          : held.filter((each) => each !== language),
                      )
                    }
                  />
                  {language}
                </label>
              ))}
            </div>
            <span className={FIELD_HINT}>{ADD_FIELD_HINTS.languages}</span>
          </fieldset>
        </div>

        {/* The server's refusal, verbatim: it names the field and what the platform says. */}
        {error != null && <ProblemNotice error={error} />}

        <button type="submit" className={PRIMARY_BUTTON} disabled={busy || !complete}>
          <Plus aria-hidden className="h-4 w-4" />
          {busy ? "Checking it against the voice platform…" : "Add this voice"}
        </button>
      </form>
    </Drawer>
  );
}
