/**
 * The vocabulary the screen assistant and the screens it can fill in agree on.
 *
 * Everything here is a description of a screen a human is looking at, not of an API
 * resource — which is why nothing in this file is generated from the OpenAPI schema and
 * why every value is a STRING. A control on a form holds text until somebody submits it;
 * `""` is the honest spelling of "empty", and a number that has been through
 * `JSON.parse` on the way to a rupee field would be hard rule 7's defect one screen
 * earlier. The screen converts on the way in and on the way out; this layer never does.
 *
 * ## The one rule that shapes the whole module
 *
 * A screen DECLARES what it holds (`useCopilotSurface`), and the assistant reads that
 * declaration. Nothing here scrapes the DOM to find out what is on screen. Scraping is
 * the design that appears to work on the screen you tested and silently reads a
 * neighbouring dialog's inputs on the next one, and it cannot tell a rupee ceiling from
 * a phone number, which is exactly the distinction `personal` below has to carry.
 */

/** What kind of control a field is — the wire's own six, spelled the way it spells them. */
export type CopilotFieldType = "text" | "number" | "select" | "bool" | "date" | "textarea";

/**
 * What a field holds that a person would recognise as being ABOUT a person.
 *
 * A boolean would have been enough for the wire (`redacted: true`), and it is not enough
 * here: the placeholder handed to the model has to be readable enough for it to reason
 * with ("«PHONE_1» is the escalation number") and it must not be guessed from the value.
 * Sniffing was the alternative and it fails in both directions — a `+91…` in a WhatsApp
 * TEMPLATE ID is not a phone number, and a customer's name is not detectable at all.
 * So the screen says which kind it is, because the screen is the only thing that knows.
 */
export type PersonalKind = "phone" | "email" | "name" | "text";

export interface CopilotOption {
  value: string;
  label: string;
}

export interface CopilotField {
  /**
   * The field's stable, semantic id — and, wherever the screen has one, the DOM `id` of
   * the control itself.
   *
   * The same idea as `lib/api/intake.ts::intakeFieldId`, which derives `#intake-services-1
   * -price_inr` from the wire path `services.1.price_inr`, and the same reason: a control
   * and the thing said about it must not be given two different names. It is what the
   * model names in a `fill`, what `apply` dispatches on, and what the highlight looks up.
   */
  id: string;
  label: string;
  type: CopilotFieldType;
  /** The value as it is RIGHT NOW. `""` is empty; there is no `null`. */
  value: string;
  /** Every accepted value, for a `select` or a set of choice cards. */
  options?: CopilotOption[] | null;
  /** Default true. A read-only field is still worth SENDING — the model reasons about it. */
  writable?: boolean;
  /** The sentence already under the control, if it explains something a model would need. */
  help?: string | null;
  /** Set when the value is personal data. See `redaction.ts` — this is D-127 G-2's seam. */
  personal?: PersonalKind;
}

/** Something loaded on the screen that is not editable but is worth knowing. */
export interface CopilotFact {
  key: string;
  label: string;
  value: string;
  personal?: PersonalKind;
}

/**
 * One field the assistant wants filled in. The wire's `fill` item, unchanged.
 *
 * `value` IS NOT ALWAYS A STRING, and declaring it as one crashed the panel. The server
 * types each filled value to the field's own declared `type`: a `bool` field gets `true`,
 * a `number` field gets `12` — deliberately, because sending `"12"` for a number would
 * make the browser parse a value the server had already validated. Since
 * `CopilotFieldType` has always included `"bool"` and `"number"`, any screen declaring
 * one would have reached `restore(item.value)`, whose body is `text.split(...)`, and
 * thrown a TypeError on the first fill.
 *
 * Found by the server lane before either half shipped; the fix is here rather than a
 * server that stringifies, because the type a control holds is a property of the control.
 */
export interface CopilotFillItem {
  field_id: string;
  value: string | number | boolean | null;
}

/**
 * One screen's declaration of itself.
 *
 * `apply` is deliberately the ONLY way a value reaches the screen, and it is the screen's
 * own function: the screens that hold a typed draft object apply to their setter, which
 * is a real state update React re-renders from, rather than being driven through their
 * own DOM. `dom.ts` exists for the minority that have neither a draft nor per-field
 * setters, and says at its top why it is the last resort.
 */
export interface CopilotSurface {
  /** The route as a human would name it — `/c/{slug}/agents/new`, slug substituted. */
  route: string;
  /** What the screen is called on screen. Sent so the model can say "this screen". */
  title: string;
  realm: "client" | "admin";
  fields: CopilotField[];
  facts?: CopilotFact[];
  /**
   * Put these values into the screen. Called once per batch, never per field: a screen
   * with one draft object must be able to apply six fields in ONE state update, because
   * six sequential updates against a stale closure lose five of them.
   *
   * Unknown `field_id`s are the screen's to ignore. The panel already filters to declared
   * ids, so anything reaching here that is not declared is a bug on our side, not the
   * model's, and a screen crashing on it would take the console with it.
   */
  apply: (items: CopilotFillItem[]) => void;
}

/**
 * The wire value as the string a text-shaped control holds.
 *
 * `CopilotFillItem.value` is typed to the FIELD, so a screen that declared `text` gets a
 * string and one that declared `bool` gets a boolean — but the union permits every shape
 * at the call site, and a screen holding `useState<string>` cannot take the others. This
 * is the one coercion, in one place, so eleven screens do not each grow a cast.
 *
 * `null` becomes `""` because on a text control that is what "clear it" looks like; there
 * is no other representation of empty in a `useState<string>`. A boolean or a number
 * reaching here means a screen declared a type it does not hold — `String()` is wrong but
 * recoverable, where a crash mid-fill loses the whole batch including the fields that
 * were right.
 */
export function asText(value: CopilotFillItem["value"]): string {
  return value === null ? "" : String(value);
}

/**
 * The `apply` a READ-ONLY screen declares — a dashboard, a log, a statement.
 *
 * Most screens in the client console hold no writable control at all: they render counts,
 * statuses and a filter or two. They still declare themselves, because a launcher that is
 * absent on nineteen screens out of thirty teaches a person the assistant does not exist,
 * and because the copilot's read tools can answer "why is this campaign held" perfectly
 * well from a screen whose only contribution is "you are on the campaign-review screen and
 * the verdict says pending".
 *
 * A named export rather than `apply: () => {}` written out at each of those call sites:
 * one spelling means a reader can tell "this screen has nothing to fill" from "this screen
 * forgot to wire its setters", which two dozen anonymous empty arrows cannot.
 *
 * It takes NO parameter, which is what TypeScript wants of a function used where one
 * taking `CopilotFillItem[]` is expected — a narrower parameter list is assignable, and
 * naming an argument this body cannot use is an unused binding the linter is right about.
 * Nothing reaches it in any case: the panel filters fills to DECLARED ids, and a screen
 * that declares no writable field has none to be filled.
 */
export function noFill(): void {
  /* Nothing to fill — see above. */
}

/**
 * A described, server-signed intent — the `proposal` SSE frame, unchanged.
 *
 * **NOTHING HAS HAPPENED WHEN ONE OF THESE ARRIVES.** It is the copilot's write surface,
 * and the whole design is that the write tools cannot mutate anything: they read, they
 * describe, and they return this (`apps/api/copilot/write_tools.py`). The change happens
 * only if the person presses Confirm, which posts `token` back — UNCHANGED, and with
 * nothing beside it — to `POST /v1/copilot/confirm`.
 *
 * ## Every string here is the SERVER'S, and the browser composes none of them
 *
 * `title`, `summary`, `current` and `proposed` are written server-side from what the tool
 * READ, not from what the model said it would do. A console that re-derived the sentence
 * from `tool` and `object_id` would be a second, drifting account of the change, and it
 * would be the one the person actually approved. So the card renders these verbatim; the
 * only strings it adds are its own chrome ("Confirm", "Dismiss", "Suggestion").
 *
 * `current` is nullable because a tool may have no single value to name; every tool
 * shipped so far has one, and the pair is what makes the decision informed — "set this to
 * Hot" is a label, "it is Contacted now, this makes it Hot" is a description.
 *
 * `object_id` is an id and never a name or a number (hard rule 6): this crosses the same
 * wire the answer does. It is not rendered.
 *
 * `expires_at` is an ISO instant five minutes after minting. The card disables its own
 * Confirm at that point rather than letting somebody click into a refusal.
 */
export interface CopilotProposal {
  token: string;
  tool: string;
  title: string;
  summary: string;
  object_type: string;
  object_id: string;
  current: string | null;
  proposed: string;
  expires_at: string;
}
