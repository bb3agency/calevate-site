import type { LeadSource } from "@/lib/api/leadSources";

/** The sample's number: a well-formed Indian mobile. A dry run normalises it and dials nothing. */
const SAMPLE_PHONE = "9876543210";

/**
 * A sample lead shaped for ONE source, so "Send test lead" is one button rather than a JSON
 * editor.
 *
 * Built from the server's own reading rules, not from a guess:
 * - With no mapping, the payload is read as it arrives and the phone is taken from `phone`
 *   or `phone_number` (`apps/api/ingest/routes.py::test_webhook`).
 * - With a mapping, ONLY mapped fields survive (`ingest/service.py::apply_mapping`), so the
 *   sample uses the source's own field names for phone and name.
 * - A configured consent field is affirmed by `true`, `yes`, `1` or `on`
 *   (the same function); the sample answers `yes`, which is what a ticked box sends.
 *   A source with no consent field gets none, and the dry run says what that means.
 */
export function sampleFor(source: Pick<LeadSource, "mapping">): Record<string, string> {
  const mapping = source.mapping ?? {};
  const sample: Record<string, string> = {
    [mapping.phone || "phone"]: SAMPLE_PHONE,
    [mapping.name || "name"]: "Priya",
  };
  if (mapping.consent_field) sample[mapping.consent_field] = "yes";
  return sample;
}

export function sampleText(source: Pick<LeadSource, "mapping">): string {
  return JSON.stringify(sampleFor(source), null, 2);
}
