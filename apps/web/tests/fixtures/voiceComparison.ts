import type {
  ComparisonRound,
  ComparisonSetup,
  ComparisonVoices,
} from "@/lib/api/opsVoiceComparison";

/** Ops > Voice comparison (D-946), ready to start a round and with one round open. */
export const COMPARISON_SETUP: ComparisonSetup = {
  sarvam_key_stored: true,
  workspace_made: true,
  sarvam_ready: true,
  voice_provider: "sarvam",
  cartesia_ready: true,
  steps: [],
};

export const COMPARISON_VOICES: ComparisonVoices = {
  cartesia: [
    {
      vendor_id: "car-1",
      label: "Priya Studio",
      language: "te",
      gender: "female",
    },
  ],
  sarvam: [
    { vendor_id: "anushka", label: "Anushka", language: "te-IN", gender: null },
  ],
  sarvam_complete: true,
  sarvam_note: null,
};

export const COMPARISON_ROUND_ID = "0192f0aa-0000-7000-8000-00000000a001";
export const COMPARISON_TRIAL_ID = "0192f0aa-0000-7000-8000-00000000b001";

export const COMPARISON_SENTENCES = {
  language: "te-IN",
  sentences: ["నమస్కారం అండి", "వన్ ట్వంటీ రూపీస్"],
  max_sentences: 20,
  max_chars: 200,
};

export const COMPARISON_ROUNDS = {
  rounds: [
    {
      id: COMPARISON_ROUND_ID,
      title: "Telugu test",
      created_at: "2026-11-01T06:00:00Z",
      finished_at: null,
      pairs: 1,
      rated: 0,
    },
  ],
};

export const COMPARISON_ROUND: ComparisonRound = {
  id: COMPARISON_ROUND_ID,
  title: "Telugu test",
  language: "te-IN",
  created_at: "2026-11-01T06:00:00Z",
  finished_at: null,
  pairs: 1,
  rated: 0,
  cartesia_voices: 1,
  sarvam_voices: 1,
  trials: [
    {
      id: COMPARISON_TRIAL_ID,
      position: 1,
      sentence: "వన్ ట్వంటీ రూపీస్",
      rating_a: null,
      rating_b: null,
      preference: null,
      rated: false,
    },
  ],
};
