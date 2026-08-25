/**
 * The extraction editor's ARITHMETIC — key derivation, dirty comparison, validation.
 *
 * A plain `.ts` module beside the component that renders it, for the reason UX-DOCTRINE §6
 * gives about size: the editor was 320 lines of JSX with five pure functions and a
 * regex threaded through it, and the pure half is the half worth reading on its own and
 * the half a test can drive directly without a render.
 *
 * Nothing here touches React, the network or the DOM.
 */

import type { AgentExtractionField } from "@/lib/api/agents";

/**
 * The five field types the server's `ExtractionField.type` union admits, in the owner's
 * words. Ordered, because these become `<option>`s and insertion order is what a reader
 * scans. "One of a set list" is `enum` — the only type that also needs its allowed values.
 */
export const FIELD_TYPE_COPY: Record<AgentExtractionField["type"], string> = {
  text: "Text",
  number: "Number",
  bool: "Yes / no",
  enum: "One of a set list",
  date: "Date",
};

export type FieldType = AgentExtractionField["type"];

/**
 * A `key` the server accepts: a lowercase letter, then up to 39 more of `[a-z0-9_]`
 * (`crm/columns.py` and the schema validator). We derive one from the label for a NEW
 * variable and validate it before the button lights, but reserved-key and duplicate-key
 * refusals are the SERVER's to make — it owns the fixed-column list — and arrive as a 422
 * the ProblemNotice renders field by field.
 */
const KEY_RE = /^[a-z][a-z0-9_]{0,39}$/;

export function slugifyKey(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^[^a-z]+/, "") // a key must START with a letter — drop leading digits/underscores
    .replace(/_+/g, "_")
    .slice(0, 40)
    .replace(/_+$/, "");
}

/** Comma- OR newline-separated, trimmed, blanks dropped — the two ways a person types a list. */
export function parseEnumValues(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((value) => value.trim())
    .filter(Boolean);
}

/**
 * One row of the editor. `uid` is a stable local identity for React's key and for reorder
 * — the `key` field can be blank or change under the user, so it cannot double as one.
 *
 * `isNew` decides whether the key is editable: an EXISTING variable's key is its storage
 * id and history is filed under it, so changing it would orphan older leads' values (kept,
 * but no longer shown in that column) — the editor shows it read-only and says so. A NEW
 * variable has no history yet, so its key is the owner's to set, defaulting to a slug of
 * the label until they touch it.
 */
export interface DraftRow {
  uid: string;
  key: string;
  label: string;
  type: FieldType;
  required: boolean;
  reason: string;
  enumText: string;
  isNew: boolean;
  keyTouched: boolean;
}

let draftCounter = 0;
export function newUid(): string {
  draftCounter += 1;
  return `draft-${draftCounter}`;
}

export function toDraft(field: AgentExtractionField): DraftRow {
  return {
    uid: newUid(),
    key: field.key,
    label: field.label,
    type: field.type,
    required: field.required,
    // `reason` defaults to "" on the wire but an older build may omit it entirely.
    reason: field.reason ?? "",
    enumText: (field.enum_values ?? []).join("\n"),
    isNew: false,
    keyTouched: true,
  };
}

/** A brand-new, empty row — the one `Add variable` appends. */
export function blankRow(): DraftRow {
  return {
    uid: newUid(),
    key: "",
    label: "",
    type: "text",
    required: false,
    reason: "",
    enumText: "",
    isNew: true,
    keyTouched: false,
  };
}

/** The key a row will actually be saved under: derived from the label for an untouched new row. */
export function effectiveKey(row: DraftRow): string {
  if (!row.isNew) return row.key;
  return row.keyTouched ? row.key : slugifyKey(row.label);
}

/** Draft rows → the wire list a PUT carries. `enum_values` is null for every non-enum type. */
export function toWireFields(rows: DraftRow[]): AgentExtractionField[] {
  return rows.map((row) => ({
    key: effectiveKey(row),
    label: row.label.trim(),
    type: row.type,
    required: row.required,
    reason: row.reason.trim(),
    enum_values: row.type === "enum" ? parseEnumValues(row.enumText) : null,
  }));
}

/** A canonical string for "is this different from what is stored", from either side. */
export function canonical(fields: AgentExtractionField[]): string {
  return JSON.stringify(
    fields.map((field) => ({
      key: field.key,
      label: field.label,
      type: field.type,
      required: field.required,
      reason: field.reason ?? "",
      enum_values: field.type === "enum" ? (field.enum_values ?? []) : null,
    })),
  );
}

/**
 * The first thing wrong the owner can fix without a round trip. Reserved and duplicate
 * keys are left to the server (it owns the fixed-column list), but an empty label or an
 * enum with no options is a save that could only 422, so the button stays dead and says
 * why. Returns the client-side reason, or null when the list is send-able.
 */
export function clientValidationError(rows: DraftRow[]): string | null {
  if (rows.some((row) => row.label.trim() === "")) {
    return "Give every variable a name before saving.";
  }
  if (rows.some((row) => row.isNew && !KEY_RE.test(effectiveKey(row)))) {
    return "One variable's id is not a valid name — use a letter, then letters, numbers or underscores.";
  }
  if (rows.some((row) => row.type === "enum" && parseEnumValues(row.enumText).length === 0)) {
    return "A “one of a set list” variable needs at least one option.";
  }
  return null;
}
