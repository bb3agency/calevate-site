"use client";

/**
 * The panels one agent's screen is made of.
 *
 * They live beside the route rather than inside it because a Next route module may export
 * only `default` and route-segment fields (D-196, tests/routeModuleExports) — and because
 * three of them are the parts of this section most likely to be reused: the publishing
 * state, the two opening notices, and the capture list.
 *
 * EVERY number and label here is the server's or is absent: the call cap, its bounds, the
 * worst-case cost, the version numbers and the voice all come from
 * `GET /v1/agents/{id}/pending`. Loading is a `Skeleton`, failure is a `ProblemNotice`,
 * and neither is ever a zero.
 */

import { useMemo, useState, type ReactNode } from "react";
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Clock,
  Hourglass,
  IndianRupee,
  ListChecks,
  Plus,
  Save,
  Send,
  ShieldCheck,
  Timer,
  Trash2,
  Volume2,
} from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NOTICE_TONES,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  TermGloss,
  formatCallCap,
  formatINR,
  formatIST,
} from "@/components/ui";
import { useToast } from "@/components/interior/toaster";
import { ARCHIVED_STATUS } from "@/lib/agentState";
import { useWriteAccess } from "@/lib/api/hooks";
import { useKbSources, useSubmitKnowledge } from "@/lib/api/kb";
import {
  useSetDisclosure,
  useSetExtractionSchema,
  type Agent,
  type AgentExtractionField,
} from "@/lib/api/agents";
import {
  usePendingChanges,
  type PendingChange,
  type PendingState,
} from "@/lib/api/publishing";
import { useClientSession } from "@/lib/api/session";
import { hasKey, lookup } from "@/lib/lookup";

/**
 * The label over a block, with the medallion the design puts on a section marker.
 *
 * Local to this section for now — it is the `StatTile` medallion idiom applied to a
 * heading, and it belongs in `components/ui.tsx` the moment a screen outside `/agents`
 * wants one.
 */
export function SectionHeading({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
        {icon}
      </span>
      {children}
    </h3>
  );
}

/** One labelled fact. `dt`/`dd` because that is exactly what these are. */
export function Fact({
  label,
  hint,
  icon,
  children,
}: {
  label: string;
  hint?: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        {icon && (
          <span aria-hidden className="shrink-0 text-brand">
            {icon}
          </span>
        )}
        {label}
      </dt>
      <dd className="mt-1 text-sm font-semibold text-ink">{children}</dd>
      {hint && <dd className="mt-0.5 text-xs text-ink-muted">{hint}</dd>}
    </div>
  );
}

/**
 * The two opening notices, as switches — and the one sentence the switches do not reach.
 *
 * ## What the client is actually deciding (D-163)
 *
 * SEC-COMP §2 states two invariants that used to share one database column: "this is an
 * AI" (TRAI/UCC) and "this call is recorded" (DPDP notice-and-consent). They are separate
 * obligations under separate regimes, and they are separate switches — because the client
 * is the Principal Entity and the exposure is theirs to carry. `org:manage` is the
 * owner's permission and no admin or impersonating session holds it against a tenant
 * (D-22), so this is one of the few controls on the client app that is genuinely and only
 * theirs. Every flip is written to the audit log.
 *
 * ## Why the copy is written the way it is
 *
 * Three sentences a screen like this gets wrong, all of them avoided here:
 *
 * - **"Off" does not mean the agent lies.** `truthful_answer_rule` comes from the server
 *   (`compliance/disclosure.TRUTHFUL_ANSWER_PROMISE`) and is rendered verbatim, above the
 *   switches rather than under them. Paraphrasing it here is how a client ends up
 *   believing they bought a bot that can pass for human.
 * - **"Off" does not stop the recording.** Nothing in the product can, so the recording
 *   switch says what it moves — the notice — and not what it does not.
 * - **"Off" does not discharge the obligation.** It moves where the notice is given.
 *   Naming that plainly is the difference between a setting and a trap.
 *
 * `opening_line` is the SERVER's composition of what callers now hear, quoted back. This
 * screen never joins the two sentences itself: that would be a second implementation of a
 * compliance rule, and the second one is where the drift starts.
 *
 * ## The wording of the two sentences is not client-editable, and the screen says so
 *
 * `agents.ai_disclosure_line` / `recording_notice_line` are NOT NULL and non-blank by
 * CHECK constraint (hard rule 5), the dial gate refuses an agent with no AI sentence, and
 * every write to them is admin-realm. So there is no textbox here and there must not be
 * one — but a quoted sentence with no control beside it reads as an oversight, so the
 * reason is stated rather than left to be inferred.
 */
export function OpeningNotices({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const setDisclosure = useSetDisclosure(session, agent.id);

  return (
    <section>
      <SectionHeading icon={<ShieldCheck className="h-3.5 w-3.5" />}>
        What it says at the start of every call
      </SectionHeading>

      {/* FIRST, and deliberately not last: the guarantee has to be read before the
          switches, or a client reads two "off" positions and infers the opposite. */}
      <p
        className={`mt-2 flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES.neutral}`}
      >
        <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{agent.truthful_answer_rule}</span>
      </p>

      {setDisclosure.error && <ProblemNotice error={setDisclosure.error} />}

      <div className="mt-4 space-y-3">
        <NoticeToggle
          label="Say it is an AI assistant"
          hint="Spoken first, before anything else, in your language."
          quote={agent.ai_disclosure_line}
          checked={agent.ai_disclosure_enabled}
          pending={setDisclosure.isPending}
          offNote="Callers are not told at the start of the call. If one asks, the agent still says it is an AI."
          onChange={(next) => setDisclosure.mutate({ ai_disclosure_enabled: next })}
        />
        <NoticeToggle
          label="Say the call is being recorded"
          hint="Spoken with the line above, at the start of the call."
          quote={agent.recording_notice_line}
          checked={agent.recording_notice_enabled}
          pending={setDisclosure.isPending}
          offNote={
            <>
              Calls are still recorded — this only stops the agent announcing it. Telling
              callers their call is recorded is still your responsibility under the{" "}
              <TermGloss term="DPDP">
                India&apos;s Digital Personal Data Protection Act
              </TermGloss>{" "}
              Act; with this off, it has to be covered by your own privacy notice or
              consent. If a caller asks, the agent still says yes.
            </>
          }
          onChange={(next) => setDisclosure.mutate({ recording_notice_enabled: next })}
        />
      </div>

      {/* The server's composition, quoted — this is the actual first utterance. */}
      <div className="mt-4">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
          What callers hear first
        </p>
        {agent.opening_line.trim() ? (
          <blockquote className="mt-2 border-l-2 border-brand pl-3 text-sm italic text-ink">
            “{agent.opening_line}”
          </blockquote>
        ) : (
          <p className="mt-2 text-sm text-ink-muted">
            Nothing. The agent opens straight into its script. It still answers honestly if
            a caller asks whether it is an AI or whether the call is recorded.
          </p>
        )}
        <p className="mt-2 text-xs text-ink-muted">
          Changes take effect on the next call. The two sentences themselves are written by
          your account manager and cannot be edited here or switched off entirely — every
          agent must have both on file. Tell them if anything in the wording is wrong.
        </p>
      </div>
    </section>
  );
}

/**
 * One notice, as a switch with its sentence under it.
 *
 * A native `<input type="checkbox" role="switch">` rather than a styled `<div>`: it is
 * keyboard-operable, it announces its own state, and it is the one control on this screen
 * a screen-reader user must be able to find and change (`tests/a11y.test.tsx` walks this
 * page). The visual switch is drawn from the input's own `peer` state, so what is painted
 * and what is checked cannot disagree.
 *
 * `pending` disables BOTH switches while either is in flight. The two write one row, and a
 * second click before the first response is a lost update the API has no way to catch —
 * `null` means "leave alone", so the second request would carry the pre-flight value of
 * neither field and simply race.
 */
function NoticeToggle({
  label,
  hint,
  quote,
  checked,
  pending,
  offNote,
  onChange,
}: {
  label: string;
  hint: string;
  quote: string;
  checked: boolean;
  pending: boolean;
  offNote: ReactNode;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="rounded-card border border-line bg-app p-4">
      <label className="flex cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          role="switch"
          className="peer sr-only"
          checked={checked}
          disabled={pending}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span
          aria-hidden
          className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full border border-line bg-surface transition-colors peer-checked:border-brand peer-checked:bg-brand peer-disabled:opacity-50 peer-focus-visible:ring-2 peer-focus-visible:ring-brand peer-focus-visible:ring-offset-2 after:absolute after:left-0.5 after:top-0.5 after:h-3.5 after:w-3.5 after:rounded-full after:bg-ink-faint after:transition-transform peer-checked:after:translate-x-4 peer-checked:after:bg-white"
        />
        <span className="min-w-0">
          <span className="block text-sm font-medium text-ink">{label}</span>
          <span className="block text-xs text-ink-muted">{hint}</span>
        </span>
      </label>
      <blockquote className="mt-3 border-l-2 border-line pl-3 text-sm italic text-ink-muted">
        “{quote}”
      </blockquote>
      {!checked && (
        <p
          className={`mt-3 flex items-start gap-2 rounded-lg border p-3 text-xs ${NOTICE_TONES.warn}`}
        >
          <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{offNote}</span>
        </p>
      )}
    </div>
  );
}

/**
 * The unsaved-changes banner (§2b) and the cost-runaway guard, from the client's side of
 * the fence.
 *
 * `headline` and `why` are rendered as sent. The server composes them from version NUMBERS
 * (a prompt body carries the client's prices and staff names — hard rule 6), and restating
 * them here would be a second source for one sentence.
 *
 * Takes the whole `agent` rather than an id: `PendingOut` carries `published` and
 * `agent_status` too, and reading THOSE here would give one screen two sources for one
 * fact — the badge above says "Being set up" from the roster read while this paragraph
 * could say the opposite from a response that landed a second later. The agent row is the
 * screen's single source; the pending read supplies only what it does not have.
 */
export function PublishingPanel({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const pending = usePendingChanges(session, agent.id);

  if (pending.isLoading) return <Skeleton rows={2} />;
  if (pending.error) {
    return <ProblemNotice error={pending.error} onRetry={() => void pending.refetch()} />;
  }
  if (!pending.data) return null;

  const state = pending.data;

  return (
    <div className="space-y-3">
      {state.has_pending ? (
        <div role="status" className={`rounded-card border p-4 text-sm ${NOTICE_TONES.warn}`}>
          <p className="flex items-center gap-2 font-semibold">
            <Hourglass aria-hidden className="h-4 w-4 shrink-0" />
            Changes waiting to go live
          </p>
          <ul className="mt-3 space-y-3">
            {state.pending.map((change) => (
              <PendingRow key={change.field} change={change} />
            ))}
          </ul>
          <p className="mt-3 text-xs">
            {/* NOT "the version above": the line above is the WAITING one. Which pointer is
                which is rendered as data in `PendingRow`; this sentence only says who
                moves it. */}
            Callers keep hearing the live version until your account manager applies the
            change — nothing goes live silently. Ask them to apply it, or to discard it if
            it was not meant to happen.
          </p>
        </div>
      ) : (
        /* The reassuring case is worth a line: an owner who has been told an edit was made
           needs to be able to see that it HAS landed, not just infer it from the absence
           of a warning. It says something different for an agent no caller can reach yet —
           "what callers hear right now" is not a true sentence about an agent that is not
           on the calling system. */
        <p className="text-sm text-ink-muted">
          {agent.published
            ? "Nothing is waiting to go live — what is described on this page is what callers hear right now."
            : "Nothing is waiting to go live. This agent is not on the calling system yet, so no caller hears it at all."}
        </p>
      )}

      {/* The cost-runaway guard, as the question it actually answers: what is the worst one
          call can do to my bill — plus the voice, which is a cost question too. */}
      <dl className="grid gap-5 rounded-card border border-line bg-app p-4 sm:grid-cols-2">
        <VoiceFacts state={state.voice} published={agent.published} />
        <Fact
          label="Longest one call may run"
          icon={<Timer className="h-3.5 w-3.5" />}
          hint={
            state.call_cap_is_platform_default
              ? "The standard limit we put on every agent."
              : "Set specifically for this agent."
          }
        >
          {formatCallCap(state.effective_call_cap_s)}
        </Fact>
        <Fact
          label="Most one call can cost you"
          icon={<IndianRupee className="h-3.5 w-3.5" />}
          hint={
            state.worst_case_call_cost_inr === null
              ? "Your plan does not quote a per-minute rate, so we cannot put a number on it. Your account manager can."
              : "A call that runs the full limit, at your plan's per-minute rate. Almost every call ends long before this."
          }
        >
          {/* Null is "we cannot say", NOT zero — quoting ₹0.00 for a ten-minute call is the
              one answer that is actively wrong (`publishing.py::_overage_rate`). The figure
              is an exact NUMERIC and stays a STRING all the way here: `formatINR` formats
              the digits and never parses them, because `Number("10159.00")` is how
              ₹10,159.00 becomes ₹10,158.999999999998 (hard rule 7). */}
          {state.worst_case_call_cost_inr === null
            ? "We cannot say yet"
            : formatINR(state.worst_case_call_cost_inr)}
        </Fact>
      </dl>
    </div>
  );
}

/**
 * The voice the caller hears — and, only when they differ, the one waiting for us.
 *
 * **Why a client sees this at all.** D-36's premium/value ladder is a PRICE ladder — the
 * two rungs bill at different per-minute rates (§2b's honest degraded-tier billing) and
 * `usage_events.meta.tts_tier` already records which rung each call ran on. A client
 * billed by rung gets to read the rung. Changing it is still ours (D-21), which is why
 * there is no control here, only a fact and who moves it.
 *
 * **One box when there is one answer, two when there are two.** A configured voice the
 * calling system is already holding is a single fact. A voice chosen and not yet published
 * is TWO facts, and collapsing them would say the caller hears something they do not — the
 * same inversion `PendingRow` exists to prevent for the script. The server decides which
 * case this is (`voice.republish_required`); this component does not compare the two ids
 * itself, because an unpublished agent has two different values and no problem at all.
 */
function VoiceFacts({
  state,
  published,
}: {
  state: PendingState["voice"] | undefined;
  published: boolean;
}) {
  // The field is absent on an older API build; a missing fact is honest, an invented one
  // is not. Nothing else on this card depends on it.
  if (!state) return null;
  const heard = state.live
    ? clientVoiceName(state.live)
    : published
      ? "We cannot say from here"
      : "Nothing yet";
  return (
    <>
      <Fact
        label="Voice callers hear"
        icon={<Volume2 className="h-3.5 w-3.5" />}
        hint={
          state.live
            ? "The voice the calling system is speaking in right now."
            : published
              ? "The calling system has a voice for this agent; we have no record of which one. Your account manager can confirm it."
              : "Nothing is on the calling system yet, so no caller hears a voice at all."
        }
      >
        {heard}
      </Fact>
      {state.republish_required && state.configured && (
        <Fact
          label="New voice waiting"
          icon={<Hourglass className="h-3.5 w-3.5" />}
          hint="Chosen for this agent and not switched on yet. Your account manager publishes the agent to make callers hear it."
        >
          {clientVoiceName(state.configured)}
        </Fact>
      )}
    </>
  );
}

/** A voice in words a client recognises. Unknown to the catalogue is still named by its
 *  id — an owner can quote an id to their account manager, and "unknown" reads as a fault
 *  rather than as a voice we simply no longer list. */
function clientVoiceName(voice: NonNullable<PendingState["voice"]["configured"]>): string {
  return voice.catalog?.label ?? voice.voice_id;
}

/**
 * One staged change, with BOTH pointers named.
 *
 * The two-speed model has exactly one way to be catastrophically misread — showing the
 * staged script as the one callers hear — and `agents/publishing.py` opens by recording
 * that the backend shipped that inversion once already. So the pointers are rendered as
 * labelled DATA (`live_version`, `staged_version`) rather than left to the prose: a
 * sentence can be read the wrong way round, a two-item list under "Callers hear now" and
 * "Waiting to be applied" cannot. It also covers what the server's headline leaves out —
 * `live_version` is null for an agent whose script has never been applied.
 */
function PendingRow({ change }: { change: PendingChange }) {
  return (
    <li className="border-l-2 border-amber-400 pl-3">
      <p className="font-medium">{change.headline}</p>
      <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-wide opacity-70">
            Callers hear now
          </dt>
          <dd className="text-sm font-semibold tabular-nums">
            {change.live_version === null ? "Nothing live yet" : `v${change.live_version}`}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-wide opacity-70">
            Waiting to be applied
          </dt>
          <dd className="text-sm font-semibold tabular-nums">v{change.staged_version}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs">{change.why}</p>
      <p className="mt-1 text-xs opacity-80">Waiting since {formatIST(change.staged_at)}</p>
    </li>
  );
}

/**
 * The five field types the server's `ExtractionField.type` union admits, in the owner's
 * words. Ordered, because these become `<option>`s and insertion order is what a reader
 * scans. "One of a set list" is `enum` — the only type that also needs its allowed values.
 */
const FIELD_TYPE_COPY: Record<AgentExtractionField["type"], string> = {
  text: "Text",
  number: "Number",
  bool: "Yes / no",
  enum: "One of a set list",
  date: "Date",
};

type FieldType = AgentExtractionField["type"];

/**
 * A `key` the server accepts: a lowercase letter, then up to 39 more of `[a-z0-9_]`
 * (`crm/columns.py` and the schema validator). We derive one from the label for a NEW
 * variable and validate it before the button lights, but reserved-key and duplicate-key
 * refusals are the SERVER's to make — it owns the fixed-column list — and arrive as a 422
 * the ProblemNotice renders field by field.
 */
const KEY_RE = /^[a-z][a-z0-9_]{0,39}$/;

function slugifyKey(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^[^a-z]+/, "") // a key must START with a letter — drop leading digits/underscores
    .replace(/_+/g, "_")
    .slice(0, 40)
    .replace(/_+$/, "");
}

/** Comma- OR newline-separated, trimmed, blanks dropped — the two ways a person types a list. */
function parseEnumValues(text: string): string[] {
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
interface DraftRow {
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
function newUid(): string {
  draftCounter += 1;
  return `draft-${draftCounter}`;
}

function toDraft(field: AgentExtractionField): DraftRow {
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

/** The key a row will actually be saved under: derived from the label for an untouched new row. */
function effectiveKey(row: DraftRow): string {
  if (!row.isNew) return row.key;
  return row.keyTouched ? row.key : slugifyKey(row.label);
}

/** Draft rows → the wire list a PUT carries. `enum_values` is null for every non-enum type. */
function toWireFields(rows: DraftRow[]): AgentExtractionField[] {
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
function canonical(fields: AgentExtractionField[]): string {
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
function clientValidationError(rows: DraftRow[]): string | null {
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

/**
 * What the agent writes down — and, for the owner, the form that changes it (D-21 is
 * superseded here; the capture columns are the client's to edit self-serve).
 *
 * `leadsHref` is passed rather than derived so this component knows nothing about routing
 * or about the view-as marker; the screen that has the slug builds the link. An ARCHIVED
 * agent keeps its columns as a record of what it did — editing them would rewrite that
 * record — so it gets the read-only list, mirroring `AgentIdentity` and `AgentModel`.
 */
export function ExtractionList({ agent, leadsHref }: { agent: Agent; leadsHref: ReactNode }) {
  if (agent.status === ARCHIVED_STATUS) {
    return <ArchivedExtractionList agent={agent} leadsHref={leadsHref} />;
  }
  return <ExtractionEditor agent={agent} leadsHref={leadsHref} />;
}

/** The editable form: add, rename, retype, reorder, delete, then save the whole list. */
function ExtractionEditor({ agent, leadsHref }: { agent: Agent; leadsHref: ReactNode }) {
  const session = useClientSession();
  const save = useSetExtractionSchema(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change what this agent captures");
  const { toast } = useToast();

  const [rows, setRows] = useState<DraftRow[]>(() => agent.extraction_fields.map(toDraft));

  const savedCanonical = useMemo(() => canonical(agent.extraction_fields), [agent.extraction_fields]);
  const wireFields = toWireFields(rows);
  const dirty = canonical(wireFields) !== savedCanonical;
  const clientError = clientValidationError(rows);

  function patchRow(uid: string, patch: Partial<DraftRow>) {
    setRows((current) => current.map((row) => (row.uid === uid ? { ...row, ...patch } : row)));
  }

  function move(index: number, delta: number) {
    setRows((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function addRow() {
    setRows((current) => [
      ...current,
      {
        uid: newUid(),
        key: "",
        label: "",
        type: "text",
        required: false,
        reason: "",
        enumText: "",
        isNew: true,
        keyTouched: false,
      },
    ]);
  }

  return (
    <section>
      <SectionHeading icon={<ListChecks className="h-3.5 w-3.5" />}>
        What it writes down
      </SectionHeading>

      <p className="mt-2 text-sm text-ink-muted">
        These are the columns in your {leadsHref} table. The agent fills them in from the
        conversation — it never reads a form aloud, so a caller who answers early is not
        asked twice.
      </p>

      <RestrictionNote reason={write.reason} />
      {save.error && (
        <div className="mt-3">
          <ProblemNotice error={save.error} />
        </div>
      )}

      <form
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!write.allowed || !dirty || clientError || save.isPending) return;
          save.mutate(
            { fields: toWireFields(rows) },
            {
              onSuccess: (result) => {
                // Repaint from the server's stored answer, not the draft — the validator
                // may have trimmed or reordered, and the screen must show what is on file.
                setRows(result.fields.map(toDraft));
                toast({ tone: "success", title: "Variables saved" });
              },
            },
          );
        }}
      >
        {rows.length === 0 ? (
          <p className="rounded-lg border border-line bg-app px-3 py-3 text-sm text-ink-muted">
            No variables yet. Calls still turn into leads with the caller name, number and a
            summary — add a variable to capture a business-specific detail on top of that.
          </p>
        ) : (
          <ul className="space-y-3">
            {rows.map((row, index) => (
              <FieldEditorRow
                key={row.uid}
                row={row}
                index={index}
                total={rows.length}
                disabled={!write.allowed || save.isPending}
                onChange={(patch) => patchRow(row.uid, patch)}
                onDelete={() => setRows((current) => current.filter((r) => r.uid !== row.uid))}
                onMoveUp={() => move(index, -1)}
                onMoveDown={() => move(index, 1)}
              />
            ))}
          </ul>
        )}

        <button
          type="button"
          onClick={addRow}
          disabled={!write.allowed || save.isPending}
          title={write.reason ?? undefined}
          className={SECONDARY_BUTTON}
        >
          <Plus aria-hidden className="h-4 w-4" />
          Add variable
        </button>

        <p className="text-xs text-ink-muted">
          {/* What `required` does, without promising an interrogation the product does not
              do: it marks the field REQUIRED in the extraction instruction, and a call that
              ends without it still becomes a lead with that column left empty
              (packages/shared/.../extraction.py). */}
          A variable marked <span className="font-medium text-ink">Required</span> is what
          the agent is told to capture on every call; a call that ends without one still
          becomes a lead, with that column left empty. The optional{" "}
          <span className="font-medium text-ink">reason</span> is fed to the AI so it fills
          the column more accurately — leave it blank to use just the name.
        </p>

        <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
          <button
            type="submit"
            disabled={!write.allowed || !dirty || Boolean(clientError) || save.isPending}
            title={write.reason ?? undefined}
            className={PRIMARY_BUTTON}
          >
            <Save aria-hidden className="h-4 w-4" />
            {save.isPending ? "Saving…" : "Save variables"}
          </button>
          {clientError ? (
            <span className="text-xs text-amber-700 dark:text-amber-400">{clientError}</span>
          ) : dirty ? (
            <span className="text-xs text-ink-muted">You have unsaved changes.</span>
          ) : (
            <span className="text-xs text-ink-muted">Nothing has been changed yet.</span>
          )}
        </div>

        <p className="text-xs text-ink-muted">
          Changes are saved here and take effect on the next call — there is no test run and
          no waiting. Renaming or removing a variable stops it showing as a column on leads
          captured before the change — their saved values are kept, just no longer shown
          under that name. That is why an existing variable&apos;s id cannot be changed here.
        </p>
      </form>
    </section>
  );
}

/**
 * One editable variable, as a stacked card so it works on a phone with no sideways scroll.
 *
 * Every control is wrapped in its own `<label>` (implicit association) rather than carrying
 * an `id` — two editors of two agents on one screen would collide on any id scheme, and the
 * wrapping label is what keeps the axe sweep (`tests/a11y.test.tsx`) green without one.
 */
function FieldEditorRow({
  row,
  index,
  total,
  disabled,
  onChange,
  onDelete,
  onMoveUp,
  onMoveDown,
}: {
  row: DraftRow;
  index: number;
  total: number;
  disabled: boolean;
  onChange: (patch: Partial<DraftRow>) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}) {
  const named = row.label.trim() || "this variable";
  return (
    <li className="rounded-card border border-line bg-app p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
          Variable {index + 1}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onMoveUp}
            disabled={disabled || index === 0}
            aria-label={`Move ${named} up`}
            className={SECONDARY_BUTTON_SM}
          >
            <ChevronUp aria-hidden className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={disabled || index === total - 1}
            aria-label={`Move ${named} down`}
            className={SECONDARY_BUTTON_SM}
          >
            <ChevronDown aria-hidden className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={disabled}
            aria-label={`Delete ${named}`}
            className={SECONDARY_BUTTON_SM}
          >
            <Trash2 aria-hidden className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className={FIELD_LABEL}>Name</span>
          <input
            required
            maxLength={80}
            value={row.label}
            disabled={disabled}
            onChange={(event) => onChange({ label: event.target.value })}
            placeholder="e.g. Reason for visit"
            className={FIELD}
          />
        </label>
        <label className="block">
          <span className={FIELD_LABEL}>Type</span>
          <select
            value={row.type}
            disabled={disabled}
            onChange={(event) => onChange({ type: event.target.value as FieldType })}
            className={FIELD}
          >
            {/* An unrecognised stored type (a value this build's union does not name) is
                offered as itself, so opening the editor never silently retypes a column. */}
            {!hasKey(FIELD_TYPE_COPY, row.type) && <option value={row.type}>{row.type}</option>}
            {Object.entries(FIELD_TYPE_COPY).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {row.type === "enum" && (
        <label className="mt-3 block">
          <span className={FIELD_LABEL}>Options</span>
          <textarea
            rows={3}
            value={row.enumText}
            disabled={disabled}
            onChange={(event) => onChange({ enumText: event.target.value })}
            placeholder={"One per line, or separated by commas\ne.g. New, Follow-up, Emergency"}
            className={`${FIELD} py-2`}
          />
          <span className={FIELD_HINT}>The agent must pick one of these for the column.</span>
        </label>
      )}

      <label className="mt-3 block">
        <span className={FIELD_LABEL}>Reason — why this is needed (optional)</span>
        <input
          maxLength={200}
          value={row.reason}
          disabled={disabled}
          onChange={(event) => onChange({ reason: event.target.value })}
          placeholder="e.g. so we can route urgent cases to a doctor first"
          className={FIELD}
        />
        <span className={FIELD_HINT}>
          The AI uses this to fill the field more accurately. Leave blank to use just the
          name.
        </span>
      </label>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            role="switch"
            className="peer sr-only"
            checked={row.required}
            disabled={disabled}
            onChange={(event) => onChange({ required: event.target.checked })}
          />
          <span
            aria-hidden
            className="relative h-5 w-9 shrink-0 rounded-full border border-line bg-surface transition-colors peer-checked:border-brand peer-checked:bg-brand peer-disabled:opacity-50 peer-focus-visible:ring-2 peer-focus-visible:ring-brand peer-focus-visible:ring-offset-2 after:absolute after:left-0.5 after:top-0.5 after:h-3.5 after:w-3.5 after:rounded-full after:bg-ink-faint after:transition-transform peer-checked:after:translate-x-4 peer-checked:after:bg-white"
          />
          <span className="text-sm font-medium text-ink">Required</span>
        </label>

        {row.isNew ? (
          <label className="block min-w-0">
            <span className={FIELD_LABEL}>Column id</span>
            <input
              value={effectiveKey(row)}
              disabled={disabled}
              onChange={(event) => onChange({ key: event.target.value, keyTouched: true })}
              className={`${FIELD} font-mono`}
            />
          </label>
        ) : (
          <span className="text-xs text-ink-muted">
            Column id: <span className="font-mono text-ink">{row.key}</span>
          </span>
        )}
      </div>
    </li>
  );
}

/** An archived agent's columns, as the record they are — no editor, and a sentence saying why. */
function ArchivedExtractionList({
  agent,
  leadsHref,
}: {
  agent: Agent;
  leadsHref: ReactNode;
}) {
  return (
    <section>
      <SectionHeading icon={<ListChecks className="h-3.5 w-3.5" />}>
        What it writes down
      </SectionHeading>
      {agent.extraction_fields.length > 0 ? (
        <ul className="mt-2 divide-y divide-line">
          {agent.extraction_fields.map((field) => (
            <li key={field.key} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 py-2.5">
              <span className="text-sm font-medium text-ink">{field.label}</span>
              <span className="rounded bg-app px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
                {lookup(FIELD_TYPE_COPY, field.type) ?? field.type}
              </span>
              {field.required && (
                <span className="rounded bg-brand-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-strong">
                  Required
                </span>
              )}
              {field.reason && (
                <span className="w-full text-xs text-ink-muted">{field.reason}</span>
              )}
              {field.enum_values?.length ? (
                <span className="w-full text-xs text-ink-muted">
                  One of: {field.enum_values.join(" · ")}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-ink-muted">This agent captured no extra columns.</p>
      )}
      <p className="mt-2 text-xs text-ink-muted">
        This agent is archived, so its columns in your {leadsHref} table are kept exactly as
        they were — part of the record of what it did. Bring it back first to change them.
      </p>
    </section>
  );
}

/** What a knowledge submission's state means, in the client's words. Mirrors the wording
 *  on `/c/<slug>/knowledge`, which is the screen that owns the full list. */
const KB_STATUS_COPY: Record<string, string> = {
  pending_approval: "In review",
  approved: "Approved, not live yet",
  rejected: "Not accepted",
  archived: "Replaced by a newer version",
};

/**
 * TRAINING — the one thing on this screen a client can genuinely change themselves.
 *
 * `POST /v1/kb/sources` is client-realm and `kb:write` is held by the OWNER role, so this
 * is a real control rather than a button that would 403. Everything else about an agent's
 * behaviour routes through us (D-21) and this screen says so where it matters; teaching it
 * a fact does not, because a knowledge source is reviewed before it goes live and cannot
 * change what the agent is instructed to DO.
 *
 * Scoped to THIS agent both ways: the list is filtered to `agent_id`, and the submission
 * is filed against it with no picker at all — the picker exists on `/knowledge`, where the
 * screen is about the whole account. A client who arrived here arrived at one agent.
 */
export function TrainingPanel({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const sources = useKbSources(session);
  const submit = useSubmitKnowledge(session);
  const write = useWriteAccess(session, "kb:write", "teach this agent");
  const [name, setName] = useState("");
  const [body, setBody] = useState("");

  return (
    <Card title="What it knows">
      <p className="text-sm text-ink-muted">
        Facts this agent can answer from — opening hours, prices, what you do and do not
        offer. Everything you add is reviewed by your account manager before callers hear
        it, because the agent speaks under your registration.
      </p>

      {sources.error && (
        <div className="mt-4">
          <ProblemNotice error={sources.error} onRetry={() => void sources.refetch()} />
        </div>
      )}

      <div className="mt-4">
        {sources.isLoading ? (
          <Skeleton rows={3} />
        ) : sources.data ? (
          <AgentKnowledgeList sources={sources.data} agentId={agent.id} />
        ) : null}
      </div>

      {submit.error && (
        <div className="mt-4">
          <ProblemNotice error={submit.error} />
        </div>
      )}

      {/* A retired agent answers nobody, so a form for teaching it one more thing is a
          control with no outcome. The list above stays, because what it knew is part of
          the record of what it did. */}
      {agent.status === ARCHIVED_STATUS ? (
        <p className="mt-5 border-t border-line pt-5 text-sm text-ink-muted">
          This agent is archived, so there is nothing to teach it. Bring it back first.
        </p>
      ) : (
      <form
        className="mt-5 space-y-3 border-t border-line pt-5"
        onSubmit={(event) => {
          event.preventDefault();
          submit.mutate(
            { agentId: agent.id, name, body },
            {
              onSuccess: () => {
                setName("");
                setBody("");
              },
            },
          );
        }}
      >
        <label className="block">
          <span className={FIELD_LABEL}>What this is about</span>
          <input
            required
            minLength={2}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Clinic hours"
            className={FIELD}
          />
        </label>
        <label className="block">
          <span className={FIELD_LABEL}>What the agent should say</span>
          <textarea
            required
            minLength={10}
            rows={6}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder={
              "Write it the way you would tell a new receptionist.\n\n" +
              "Leave a blank line between topics."
            }
            className={`${FIELD} py-2`}
          />
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={!write.allowed || submit.isPending || body.length < 10}
            /* The reason travels WITH the control: a dead button whose explanation is
               off-screen is the 403 this pattern exists to avoid shipping. */
            title={write.reason ?? undefined}
            className={PRIMARY_BUTTON}
          >
            <Send aria-hidden className="h-3.5 w-3.5" />
            {submit.isPending ? "Submitting…" : "Submit for review"}
          </button>
          {write.reason && <span className="text-xs text-ink-muted">{write.reason}</span>}
        </div>
      </form>
      )}
    </Card>
  );
}

/** This agent's knowledge, from the account-wide list. */
function AgentKnowledgeList({
  sources,
  agentId,
}: {
  sources: ReturnType<typeof useKbSources>["data"] & object;
  agentId: string;
}) {
  const mine = sources.filter((source) => source.agent_id === agentId);
  if (mine.length === 0) {
    return (
      <p className="rounded-lg border border-line bg-app px-3 py-3 text-sm text-ink-muted">
        Nothing taught yet. The agent still handles calls from its script — this is for the
        questions callers ask that the script does not answer.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-line">
      {mine.map((source) => (
        <li key={source.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2.5">
          <BookOpen aria-hidden className="h-3.5 w-3.5 shrink-0 self-center text-ink-faint" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
            {source.name}
          </span>
          <span className="flex items-center gap-1 text-xs text-ink-muted">
            <Clock aria-hidden className="h-3 w-3" />
            {/* A status this build has never seen keeps its own word rather than
                disappearing — read through `lookup` because it is a wire string. */}
            {lookup(KB_STATUS_COPY, source.status) ?? source.status.replace(/_/g, " ")}
          </span>
        </li>
      ))}
    </ul>
  );
}
