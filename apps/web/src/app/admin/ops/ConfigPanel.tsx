"use client";

import { useState } from "react";
import {
  CheckCircle2,
  CircleHelp,
  Lock,
  RotateCcw,
  Save,
  Settings2,
  TriangleAlert,
} from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import {
  useOpsConfig,
  useRevertConfig,
  useSetConfig,
  type ConfigField,
  type ConfigList,
  type ConfigValue,
} from "@/lib/api/opsConfig";

/**
 * Core config — PLATFORM-CONFIG §8 panel 2: "grouped, each row showing value, source,
 * who, when. A value coming from `env` is shown as read-only with the reason."
 *
 * ## The three states, and why there is no fourth
 *
 * BUILD-LOG §52, which this screen's own history is the cautionary tale for: loading is
 * a skeleton, failure is a refusal, and neither is a number, a state, or an empty state.
 * Applied here that means the panel renders exactly one of:
 *
 * 1. **loading** — a skeleton. Not an empty table, which would read as "this deployment
 *    manages nothing".
 * 2. **unreadable** — a refusal naming what stopped, with NO field list. This matters
 *    more here than on most screens: a config table rendered from a failed read would
 *    show every key at its TypeScript default, which is a screenful of confident,
 *    invented values an operator would then act on.
 * 3. **read** — the server's own fields, values, sources and provenance.
 *
 * ## Read-only is not the same as hidden
 *
 * A key set in the environment is rendered WITH its value, marked read-only, and told
 * which variable to change instead. Hiding it would leave an operator hunting for a
 * setting they can see in `.env`; offering an editable box for it would be the field
 * that silently does nothing. The API refuses the write too, so the two halves agree.
 *
 * ## Why every write takes a typed confirmation
 *
 * The same argument the switches above make, with a different blast radius: `engine`
 * decides which vendor every call is placed through, and `self_serve_inr_per_min` is
 * what every self-serve client is charged. The word typed here is sent to the API as
 * `X-Confirm-Action`, so a session that did not go through this form cannot perform the
 * write — and the header names the KEY, so a confirmation captured for one setting
 * cannot be replayed against another.
 *
 * ## Staleness is stated, never smoothed
 *
 * `stale` and `never_loaded` come from the serving process's own snapshot. A console
 * that showed values without saying whether the process could still reach the store
 * would render an hour-old snapshot identically to a live one — and on THIS screen the
 * difference decides whether the change you just made is in force.
 */

/** The panel's three states, as a type rather than as discipline (§52). */
type ConfigState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; config: ConfigList };

export function configState(query: {
  data: ConfigList | undefined;
  error: unknown;
  isLoading: boolean;
}): ConfigState {
  // Error first: a failed refetch leaves the previous `data` in place, and a stale
  // config table rendered as current is the same lie as an invented one.
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  return { status: "read", config: query.data };
}

/**
 * How the fields are grouped on screen.
 *
 * PREFIX MATCHING on the key, in order, first match wins — not a per-key table. A
 * per-key map would be a second list of every setting, which is exactly the drift the
 * API side went out of its way to avoid; a key that matches nothing lands in "Other" and
 * is still fully editable, so a new `Settings` field appears on this screen the day it
 * is added with no edit here.
 */
const GROUPS: { title: string; hint: string; prefixes: string[] }[] = [
  {
    title: "Voice engine",
    hint: "Which platform places the calls, and how it is reached.",
    prefixes: ["engine", "bolna_", "cartesia_", "webhook_base_url"],
  },
  {
    title: "Money",
    hint: "Rates and prices. Exact decimals — never rounded, never a float.",
    prefixes: ["usd_inr_rate", "self_serve_inr", "gst_"],
  },
  {
    title: "Capacity and dialling",
    hint: "How much of the platform outbound calling may use.",
    prefixes: ["inbound_reserve", "db_pool_size", "self_serve_signup"],
  },
  {
    title: "Notifications",
    hint: "Where hot-lead alerts and operator alarms go.",
    prefixes: ["smtp_", "notifications_", "alerts_", "whatsapp_"],
  },
  {
    title: "Integrations",
    hint: "Which providers this deployment has, as a statement of capability.",
    prefixes: ["google_sheets_", "meta_", "payment_provider", "number_provider", "razorpay_"],
  },
  {
    title: "Observability",
    hint: "Tracing and release identity.",
    prefixes: ["otel_", "release_version", "sentry_"],
  },
  {
    title: "Identity",
    hint: "Clerk applications and object storage.",
    prefixes: ["clerk_", "object_store_"],
  },
];

const OTHER = "Other";

function groupOf(key: string): string {
  for (const group of GROUPS) {
    if (group.prefixes.some((prefix) => key.startsWith(prefix))) return group.title;
  }
  return OTHER;
}

function grouped(fields: ConfigField[]): { title: string; hint: string; fields: ConfigField[] }[] {
  const byTitle = new Map<string, ConfigField[]>();
  for (const field of fields) {
    const title = groupOf(field.key);
    // `Map`, not an object literal: the key comes off the wire, and a group named after
    // an `Object.prototype` member would resolve to the prototype's value
    // (`src/lib/lookup.ts` records the six sites this bit). A Map has no prototype
    // chain to fall through to.
    const bucket = byTitle.get(title);
    if (bucket) bucket.push(field);
    else byTitle.set(title, [field]);
  }
  const ordered = GROUPS.filter((g) => byTitle.has(g.title)).map((g) => ({
    title: g.title,
    hint: g.hint,
    fields: byTitle.get(g.title) ?? [],
  }));
  const rest = byTitle.get(OTHER);
  return rest
    ? [
        ...ordered,
        {
          title: OTHER,
          hint: "Settings this console has no group for yet — editable like any other.",
          fields: rest,
        },
      ]
    : ordered;
}

/** What the API returned, rendered for a human. `null` is stated, never blanked. */
function display(value: ConfigValue): string {
  if (value === null) return "not set";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

const SOURCE_NOTE: Record<string, string> = {
  env: "Set in this deployment's environment, which always wins over the console.",
  db: "Set from this console.",
  default: "The value built into this release.",
};

export function ConfigPanel({ access }: { access: { allowed: boolean; reason: string | null } }) {
  const query = useOpsConfig();
  const state = configState(query);

  return (
    <Card title="Platform configuration">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Every setting this deployment can change without an SSH session. Credentials are
          NOT here — they are write-only and live under Secrets. A change reaches every
          process within a few seconds; a setting marked <em>needs a restart</em> is the
          exception and says so on its own row.
        </p>

        {query.error && <ProblemNotice error={query.error} onRetry={() => query.refetch()} />}

        {state.status === "loading" && <Skeleton rows={4} />}

        {/* THE REFUSAL. Not an empty table and not a table of defaults: a config screen
            rendered from a failed read would show a screenful of invented values that an
            operator would then act on. */}
        {state.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We could not read the platform configuration"
          >
            <p className="mt-1">
              This panel will not show you values it did not receive. The error above says
              what stopped the read — nothing here has changed, and the settings currently
              in force are unaffected by this screen failing to load.
            </p>
          </NoticeBox>
        )}

        {state.status === "read" && (
          <>
            <StoreHealth config={state.config} />
            {/* The database's own account of when the configuration last moved, beside
                the version it moved to. It is the fact an operator needs when a change
                is not appearing: a version bumped seconds ago with a value they cannot
                see means a process is behind, and one bumped days ago means their write
                never landed. Read from the sentinel, not from any row's `updated_at` —
                a revert deletes the row and takes that timestamp with it. */}
            <p className="text-xs text-ink-faint">
              Configuration version{" "}
              <span className="font-mono">{state.config.config_version}</span>
              {state.config.config_changed_at
                ? `, last changed ${formatIST(state.config.config_changed_at)}.`
                : ", never changed on this deployment."}
            </p>
            {grouped(state.config.fields).map((group) => (
              <section key={group.title} className="space-y-2">
                <div>
                  <h3 className="text-sm font-semibold text-ink">{group.title}</h3>
                  <p className="text-xs text-ink-faint">{group.hint}</p>
                </div>
                <ul className="space-y-2">
                  {group.fields.map((field) => (
                    <li key={field.key}>
                      <ConfigRow field={field} access={access} />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </>
        )}
      </div>
    </Card>
  );
}

/**
 * Whether the process that answered can still reach the store.
 *
 * Rendered only when the answer is NOT "yes", because a green box on every load trains
 * people to stop reading it. The two failure states are separate sentences: one means
 * the values are real but possibly stale, the other means this process has never read
 * the store at all and is running on its environment and its defaults — in which case a
 * change made here will not be reflected by the process serving this screen.
 */
function StoreHealth({ config }: { config: ConfigList }) {
  if (config.never_loaded) {
    return (
      <NoticeBox
        tone="stop"
        icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
        title="This process has never read the configuration store"
      >
        <p className="mt-1">
          It is running on environment variables and code defaults. Values below are what
          it is using, but nothing set from this console is in force here, and a change
          you make now may not appear. Check that the database is reachable before
          treating this screen as the platform&apos;s configuration.
        </p>
      </NoticeBox>
    );
  }
  if (config.stale) {
    return (
      <NoticeBox
        tone="warn"
        icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
        title="The last refresh of the configuration failed"
      >
        <p className="mt-1">
          The values below are the last ones read successfully, so they are real rather
          than invented — but a change made recently may not have reached this process. It
          keeps serving them deliberately: a configuration lookup must never be able to
          take the phone system down.
        </p>
      </NoticeBox>
    );
  }
  return null;
}

/**
 * One setting: what it is now, where it came from, and — when it can be changed — a form
 * bound to that key.
 *
 * The form is COLLAPSED until an operator opens it. Thirty-six settings each with an
 * open input is a screen where a stray keystroke edits the platform, and the row's job
 * most of the time is to answer "what is this set to and who set it".
 */
function ConfigRow({
  field,
  access,
}: {
  field: ConfigField;
  access: { allowed: boolean; reason: string | null };
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-card border border-line bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-sm text-ink">{field.key}</p>
          <p className="mt-0.5 break-all font-mono text-sm font-semibold text-ink">
            {display(field.value)}
          </p>
          <p className="mt-1 text-xs text-ink-faint">
            {/* `lookup`-free: SOURCE_NOTE is keyed by a server-controlled union of three
                values, and an unknown one falls back to printing the source itself
                rather than blanking the line. */}
            {SOURCE_NOTE[field.source] ?? `Source: ${field.source}`}
            {field.source === "db" && field.updated_by && (
              <>
                {" "}
                {field.updated_by}, {formatIST(field.updated_at)}
              </>
            )}
          </p>
          {field.source === "db" && field.note && (
            <p className="mt-1 text-xs text-ink-muted">&ldquo;{field.note}&rdquo;</p>
          )}
          {field.applies === "on_restart" && (
            <p className="mt-1 flex items-start gap-1.5 text-xs text-amber-700">
              <TriangleAlert aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
              Needs a restart to take effect — {field.caveat}
            </p>
          )}
          {field.applies === "live" && field.caveat && (
            <p className="mt-1 text-xs text-ink-muted">Note: {field.caveat}</p>
          )}
        </div>

        <div className="shrink-0">
          {field.editable ? (
            <button
              type="button"
              onClick={() => setOpen((was) => !was)}
              disabled={!access.allowed}
              title={access.reason ?? undefined}
              className={SECONDARY_BUTTON_SM}
            >
              <Settings2 aria-hidden className="h-3.5 w-3.5" />
              {open ? "Cancel" : "Change"}
            </button>
          ) : (
            // READ-ONLY WITH THE REASON (§8). Not a hidden row and not a dead input:
            // the operator is told exactly which variable pins this value, so they know
            // where to go instead of concluding the console is broken.
            <p className="flex max-w-[16rem] items-start gap-1.5 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Fixed by <span className="font-mono">{field.env_var}</span> in this
                deployment&apos;s environment. The environment always wins over the
                console, so this cannot be changed here — change the variable and restart.
              </span>
            </p>
          )}
        </div>
      </div>

      {open && field.editable && <ConfigForm field={field} onDone={() => setOpen(false)} />}
    </div>
  );
}

function ConfigForm({ field, onDone }: { field: ConfigField; onDone: () => void }) {
  const save = useSetConfig();
  const revert = useRevertConfig();
  // Seeded from the value in force, so changing one setting is an edit rather than a
  // retype — and so submitting without touching the box is a no-op the operator can see.
  const [draft, setDraft] = useState(field.value === null ? "" : String(field.value));
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  const word = field.key.toUpperCase();
  const ready = reason.trim().length >= 3 && confirm === word;

  return (
    <form
      className="mt-3 space-y-3 border-t border-line pt-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(
          { key: field.key, value: parseDraft(field, draft), reason: reason.trim() },
          {
            onSuccess: () => {
              setReason("");
              setConfirm("");
              onDone();
            },
          },
        );
      }}
    >
      {save.error && <ProblemNotice error={save.error} />}
      {revert.error && <ProblemNotice error={revert.error} />}

      <label className="block">
        <span className={FIELD_LABEL}>New value</span>
        {field.kind === "enum" ? (
          <select value={draft} onChange={(e) => setDraft(e.target.value)} className={FIELD}>
            {field.options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        ) : field.kind === "boolean" ? (
          <select value={draft} onChange={(e) => setDraft(e.target.value)} className={FIELD}>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : (
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            // `text` even for numbers and decimals, deliberately: a `number` input
            // hands back a JS float, and `usd_inr_rate` is money that has to reach the
            // API as an exact string (hard rule 7). The server validates against the
            // same model the app loads at boot, so a bad value is refused with the
            // model's own message rather than silently coerced by the browser.
            inputMode={field.kind === "integer" ? "numeric" : "text"}
            className={`${FIELD} font-mono`}
          />
        )}
        <span className={FIELD_HINT}>
          {field.has_default ? (
            <>
              Built-in default: <span className="font-mono">{display(field.default)}</span>.
            </>
          ) : (
            <>This setting has no built-in default, so it cannot be reverted.</>
          )}{" "}
          Validated against the same model the API loads at startup — a value that would
          break the next deploy is refused here.
        </span>
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>Reason</span>
        <input
          required
          minLength={3}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. 'Q3 price change, approved in #pricing'"
          className={FIELD}
        />
        <span className={FIELD_HINT}>
          Stored on the row and in the audit log. Whoever finds this value in force reads
          it to decide whether the reason still holds.
        </span>
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>
          Type <span className="font-mono">{word}</span> to confirm
        </span>
        <input
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          placeholder={word}
          className={`${FIELD} font-mono`}
        />
        <span className={FIELD_HINT}>
          Sent to the API as this change&apos;s confirmation, bound to this key — a
          confirmation typed for one setting cannot change another.
        </span>
      </label>

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={!ready || save.isPending}
          className={PRIMARY_BUTTON_SM}
        >
          <Save aria-hidden className="h-3.5 w-3.5" />
          {save.isPending ? "Saving…" : "Save"}
        </button>
        {/* Reverting is offered only where there is something to revert TO and something
            to revert FROM. It carries its own confirmation string on the wire, so the
            word typed above does not authorise it — the button asks again. */}
        {field.source === "db" && field.has_default && (
          <button
            type="button"
            disabled={revert.isPending}
            onClick={() => {
              if (confirm !== word) return;
              revert.mutate(field.key, { onSuccess: onDone });
            }}
            title={
              confirm === word
                ? undefined
                : `Type ${word} above first — reverting is confirmed the same way`
            }
            className={SECONDARY_BUTTON_SM}
          >
            <RotateCcw aria-hidden className="h-3.5 w-3.5" />
            {revert.isPending ? "Reverting…" : "Revert to default"}
          </button>
        )}
      </div>

      {save.data && (
        <p className="flex items-center gap-2 text-sm text-ink-muted">
          <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand" />
          Saved. Every process picks it up within a few seconds.
        </p>
      )}
    </form>
  );
}

/**
 * The typed value to send, from what the operator typed.
 *
 * DELIBERATELY MINIMAL. Booleans become booleans and integers become numbers because
 * those are unambiguous; everything else — including `decimal` and `number` — is sent as
 * the STRING the operator typed. Money must not pass through a JS float on its way to a
 * NUMERIC column (hard rule 7), and the server validates every value against the same
 * model the application loads at boot, so a string it cannot parse is refused with the
 * model's own message rather than being helpfully coerced here into something that
 * validates but is not what was typed.
 */
export function parseDraft(field: ConfigField, draft: string): ConfigValue {
  const trimmed = draft.trim();
  if (trimmed === "") return null;
  if (field.kind === "boolean") return trimmed === "true";
  if (field.kind === "integer") {
    const parsed = Number(trimmed);
    // Not a number? Send the string and let the server say so in the field's own words.
    return Number.isInteger(parsed) ? parsed : trimmed;
  }
  return trimmed;
}
