"use client";

import { useCallback } from "react";

import { useHostedVoices, type HostedVoice } from "@/lib/api/opsHostedVoices";
import type { ConfigField, ConfigValue } from "@/lib/api/opsConfig";

import { displayValue } from "./configControl";

/** A voice set as the default and since disabled keeps its name, with why it is not given. */
export function voiceName(voice: HostedVoice): string {
  return voice.offered ? voice.label : `${voice.label} (not enabled for clients)`;
}

/**
 * `displayValue` for one setting, with a picked entity shown by its name rather than its id:
 * the default agent's voice (`client_voices`) as the label the Voices page gives it. Only that
 * setting reads the voice list, and it shares the picker's cached read.
 */
export function useDisplayValue(field: ConfigField): (value: ConfigValue) => string {
  const voices = useHostedVoices(field.control.source === "client_voices", "added");
  const listed = voices.data?.voices;
  return useCallback(
    (value: ConfigValue) =>
      displayValue(field, value, (id) => {
        const voice = listed?.find((each) => each.voice_id === id);
        return voice ? voiceName(voice) : null;
      }),
    [field, listed],
  );
}
