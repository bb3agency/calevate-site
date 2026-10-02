import { CLONE_FIRST, type CuratedVoices } from "@/lib/api/opsVoices";

type Fact = { key: string; label: string; value: string };

/**
 * What the screen assistant is told. Counts only: nothing on this screen is fillable by
 * it, because every field is a fact about a voice on another company's platform that the
 * operator has in front of them and the model does not.
 */
export function voiceFacts(
  refused: boolean,
  data: CuratedVoices | undefined,
  failed: boolean,
): Fact[] {
  if (refused) {
    return [
      {
        key: "voices",
        label: "The voice catalogue",
        value: "withheld — this admin account may not read it",
      },
    ];
  }
  if (!data) {
    return [
      {
        key: "voices",
        label: "The voice catalogue",
        value: failed ? "could not be read" : "still loading",
      },
    ];
  }
  return [
    {
      key: "offered",
      label: "Voices any client or admin can currently choose",
      value: String(data.offered),
    },
    {
      key: "added",
      label: "Voices this platform has decided about",
      value: String(data.voices.length),
    },
    {
      key: "cached",
      label: "Voices the voice platform lists for our account",
      value: String(data.cached),
    },
    {
      key: "withdrawn",
      label: "Voices marked withdrawn",
      value: String(data.voices.filter((row) => row.withdrawn_at !== null).length),
    },
    { key: "adding", label: "How a NEW voice is added", value: CLONE_FIRST },
  ];
}
