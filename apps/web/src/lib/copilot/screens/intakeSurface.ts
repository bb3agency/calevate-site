"use client";

import { intakeFieldId, type IntakeDraft } from "@/lib/api/intake";

import { applyByPaths } from "../paths";
import type { CopilotField, CopilotFillItem, CopilotSurface } from "../types";

/**
 * The new-client wizard's intake sheet, declared to the screen assistant.
 *
 * THIS IS THE SCREEN THE FEATURE EXISTS FOR — forty controls, every one of them a
 * sentence somebody has to get out of a business owner on the phone — so it is the
 * worked example of the good apply path and it is worth reading before writing another.
 *
 * ## Ids, and the two addressing schemes that already exist
 *
 * `lib/api/intake.ts::intakeFieldId` derives a DOM id from a WIRE path
 * (`services.1.price_inr` -> `intake-services-1-price_inr`), and the form uses it on
 * every control. So the copilot field id IS that DOM id — no third naming scheme — and
 * the outline `lib/copilot/highlight.ts` draws lands on the right control for free.
 *
 * The business-hours rows are the one place the two schemes diverge, and the form says
 * why: its ids are keyed by DAY (`business_hours.monday.opens`) because the grid always
 * shows seven days while the BODY carries only the answered ones, so a wire index would
 * name a different day tomorrow. `pathFor` below is therefore a real mapping and not a
 * string substitution: it turns the day back into this draft's index.
 *
 * ## Why it applies through the draft and not the DOM
 *
 * `IntakeStep` holds one `IntakeDraft` object, so a six-field fill is ONE immutable
 * update and one re-render — see `lib/copilot/paths.ts`, which also explains why a fill
 * naming a row that does not exist is dropped rather than growing the array.
 */

const HOUR_PARTS = ["opens", "closes", "closed"] as const;

/** Every `{ id, path }` this draft currently offers, in the order the form shows them. */
function addressBook(draft: IntakeDraft): { id: string; path: string }[] {
  const rows: { id: string; path: string }[] = [];
  draft.business_hours.forEach((day, index) => {
    for (const part of HOUR_PARTS) {
      rows.push({
        id: intakeFieldId(`business_hours.${day.day}.${part}`),
        path: `business_hours.${index}.${part}`,
      });
    }
  });
  const list = (key: keyof IntakeDraft, members: readonly string[]) => {
    const value = draft[key];
    if (!Array.isArray(value)) return;
    value.forEach((_row, index) => {
      for (const member of members) {
        rows.push({
          id: intakeFieldId(`${key}.${index}.${member}`),
          path: `${key}.${index}.${member}`,
        });
      }
    });
  };
  list("branches", ["label", "address"]);
  list("services", ["name", "price_inr", "notes"]);
  list("faqs", ["question", "answer"]);
  list("staff", ["name", "pronunciation", "role"]);
  list("escalation_contacts", ["name", "phone_e164", "hours"]);
  rows.push({ id: intakeFieldId("booking_rules"), path: "booking_rules" });
  return rows;
}

/** What each path holds, for the two decisions that depend on it. */
function describe(path: string): Pick<CopilotField, "label" | "type" | "personal" | "help"> {
  const member = path.split(".").pop() ?? path;
  const row = path.startsWith("business_hours") ? "" : `${Number(path.split(".")[1]) + 1} `;
  switch (member) {
    case "opens":
      return { label: "Opens", type: "text", help: "24-hour HH:MM. Blank means unanswered." };
    case "closes":
      return { label: "Closes", type: "text", help: "24-hour HH:MM." };
    case "closed":
      return {
        label: "Closed all day",
        type: "bool",
        help: '"true" or "false". Closed is a different fact from unanswered.',
      };
    case "label":
      return { label: `Branch ${row}name`, type: "text" };
    case "address":
      return { label: `Branch ${row}address`, type: "textarea" };
    case "price_inr":
      return { label: `Service ${row}price`, type: "text", help: "Rupees, e.g. 500.00. Blank if it varies." };
    case "notes":
      return { label: `Service ${row}notes`, type: "textarea" };
    case "question":
      return { label: `FAQ ${row}question`, type: "text" };
    case "answer":
      return { label: `FAQ ${row}answer`, type: "textarea" };
    case "pronunciation":
      return { label: `Staff ${row}pronunciation`, type: "text" };
    case "role":
      return { label: `Staff ${row}role`, type: "text" };
    case "phone_e164":
      // A named human's mobile. It leaves as «PHONE_n» and returns as itself.
      return { label: `Escalation ${row}phone`, type: "text", personal: "phone" };
    case "hours":
      return { label: `Escalation ${row}hours`, type: "text" };
    case "booking_rules":
      return { label: "Booking rules", type: "textarea" };
    case "name":
      return path.startsWith("staff")
        ? { label: `Staff ${row}name`, type: "text", personal: "name" }
        : path.startsWith("escalation_contacts")
          ? { label: `Escalation ${row}name`, type: "text", personal: "name" }
          : { label: `Service ${row}name`, type: "text" };
    default:
      return { label: member, type: "text" };
  }
}

function valueAt(draft: IntakeDraft, path: string): string {
  const segments = path.split(".");
  let node: unknown = draft;
  for (const segment of segments) {
    if (Array.isArray(node)) node = node[Number(segment)];
    else if (node !== null && typeof node === "object") node = (node as Record<string, unknown>)[segment];
    else return "";
  }
  if (typeof node === "boolean") return node ? "true" : "false";
  return typeof node === "string" ? node : "";
}

export function intakeCopilotSurface(
  draft: IntakeDraft,
  context: { route: string; vertical: string; primaryLanguage: string },
  onDraftChange: (next: IntakeDraft) => void,
): CopilotSurface {
  const book = addressBook(draft);
  const pathById = new Map(book.map((entry) => [entry.id, entry.path]));

  const fields: CopilotField[] = book.map((entry) => ({
    id: entry.id,
    value: valueAt(draft, entry.path),
    ...describe(entry.path),
  }));

  return {
    route: context.route,
    title: "New client — business intake",
    realm: "admin",
    fields,
    facts: [
      { key: "vertical", label: "Vertical template", value: context.vertical },
      { key: "language_primary", label: "Agent's primary language", value: context.primaryLanguage },
      {
        key: "languages",
        label: "Languages the business works in",
        value: draft.languages.join(", "),
      },
    ],
    apply: (items: CopilotFillItem[]) => {
      onDraftChange(
        applyByPaths(
          draft,
          items,
          (id) => pathById.get(id) ?? null,
          // The draft is strings everywhere except the closed flag, which is a real
          // boolean — writing "true" into it would render a ticked box that submits a
          // string and be refused by the body shaper, not by the form.
          // Tolerant of BOTH, deliberately: the server sends a real boolean for a `bool`
          // field, and a model that answers a text field with "true" should still close a
          // day rather than write the word into it.
          (path, value) =>
            path.endsWith(".closed") ? value === true || value === "true" : value,
        ),
      );
    },
  };
}
