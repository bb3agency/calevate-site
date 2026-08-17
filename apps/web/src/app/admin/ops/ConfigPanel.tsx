"use client";

import { useState, type ReactNode } from "react";

import { lookup } from "@/lib/lookup";
import {
  CheckCircle2,
  CircleHelp,
  Lock,
  RotateCcw,
  Save,
  Settings2,
  TriangleAlert,
  Users,
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
  type NoticeTone,
} from "@/components/ui";
import {
  isLostUpdate,
  useOpsConfig,
  useRevertConfig,
  useSetConfig,
  type ConfigField,
  type ConfigList,
  type ConfigValue,
  type ConfigWrite,
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
 *
 * ## What the hardening pass changed, and what each change is protecting against
 *
 * 1. **The receipt is the SERVER's answer, not the operator's typing.** The form used to
 *    close on success and render "Saved." from a branch that had already unmounted — so
 *    a save produced no confirmation at all, and the only evidence was the list refetch,
 *    which on a `stale` snapshot comes back showing the OLD value. An operator would
 *    read that as "it did not take" and write it again. `ConfigWriteOut` carries the
 *    stored field and the version it landed at; that is what is rendered, next to what
 *    THIS process reports, and a disagreement between the two is said out loud.
 * 2. **`applies` is a four-way answer and every branch renders.** It used to be two
 *    `if`s: `on_restart` got a warning, `live` with a caveat got a muted "Note:", and
 *    anything else got SILENCE — so `webhook_base_url`, whose new value is live but
 *    whose already-published agents keep the old one, read as an ordinary live change,
 *    and a value the server labels with a word this build has never seen would read as
 *    live too. The consequence is now stated in the FORM, above the button, before the
 *    save — a caveat an operator meets afterwards is a caveat they meet too late.
 * 3. **A value that moved underneath the operator stops the write.** Two operators on
 *    one key is the case this console makes possible for the first time, and the poll is
 *    what surfaces it: the form remembers the value its edit was decided against, and a
 *    refetch that disagrees blocks the save until a person chooses. There is no merge
 *    (these are scalars — a merged engine selection is not a thing) and no retry button
 *    (a retry that re-sends the same body is last-write-wins with a confirmation step).
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
    // `email_provider` belongs here rather than under Integrations, even though it is
    // the same "a credential is not a statement of capability" selector `payment_provider`
    // is: an operator looking for why an alert did not arrive looks under the alerts, and
    // the setting that decides whether ANY transport exists is the first one they need.
    prefixes: ["smtp_", "notifications_", "alerts_", "whatsapp_", "email_provider", "resend_"],
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
    // The `clerk_` prefix went with the vendor (D-177) — authentication has no
    // console-managed setting at all now, and a prefix matching nothing would be a group
    // that renders empty on a screen whose job is to say what is installed.
    title: "Storage",
    hint: "Where recordings, transcripts and exports are kept.",
    prefixes: ["object_store_"],
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

/**
 * WHEN a change to this key actually takes effect — every answer the API has, plus one.
 *
 * `core/platform_config.APPLIES_VALUES` names five: `live`, `on_restart`,
 * `needs_republish`, `env_only`, `unclassified`. The console used to read two of them and
 * answer the rest with SILENCE, which reads as "live" — and the field that fell through
 * was `webhook_base_url`, whose new value IS live while every agent already published
 * keeps the old URL until it is re-published. That is the field most likely to be changed
 * mid-incident, and the screen was telling an operator it was done.
 *
 * The sixth branch is the one that has to exist. `applies` is `str` on the wire
 * (`ops/config_routes.ConfigFieldOut`), not a Literal, deliberately — a deployment newer
 * than this bundle can send a sixth word, and D-75's rule applies: the union is what THIS
 * BUILD has words for, not what the RUNNING DEPLOYMENT sends. So an unrecognised value
 * says so instead of being rendered as the safest-sounding one. §52 one level in: the
 * absence of a statement is itself a claim, and here it is the dangerous claim.
 */
export type AppliesId =
  | "live"
  | "needs_republish"
  | "on_restart"
  | "env_only"
  | "unclassified"
  | "unknown";

export interface AppliesVerdict {
  id: AppliesId;
  tone: NoticeTone;
  /** The headline an operator scans for. */
  label: string;
  /** What they have to do about it, in a sentence. */
  sentence: string;
}

/** The server's own caveat, or a stated absence — never a blank. */
function withCaveat(lead: string, caveat: string | null): string {
  return caveat ? `${lead} — ${caveat}.` : `${lead}.`;
}

export function appliesVerdict(field: ConfigField): AppliesVerdict {
  switch (field.applies) {
    case "live":
      // `caveat` is null for LIVE by the API's own rule, so a LIVE field carrying one is
      // a classification that has drifted. Rendered rather than dropped: the sentence
      // exists because somebody wrote it about this key.
      return field.caveat
        ? {
            id: "needs_republish",
            tone: "warn",
            label: "Live within seconds, but NOT retroactive",
            sentence: withCaveat(
              "The new value reaches every process in a few seconds, and it does not " +
                "change what already exists",
              field.caveat,
            ),
          }
        : {
            id: "live",
            tone: "neutral",
            label: "Live within seconds",
            sentence:
              "Every process picks this up within a few seconds, with no restart and " +
              "nothing to re-publish.",
          };
    case "needs_republish":
      return {
        id: "needs_republish",
        tone: "warn",
        label: "Live within seconds, but NOT retroactive",
        sentence: withCaveat(
          "The new value is in force in seconds and it does not change what already " +
            "exists, so part of the platform keeps running on the old one until you go " +
            "and re-publish",
          field.caveat,
        ),
      };
    case "on_restart":
      return {
        id: "on_restart",
        tone: "warn",
        // The existing wording is kept verbatim: a runbook and a test both print it, and
        // renaming a sentence an operator has learned to recognise buys nothing.
        label: "Needs a restart to take effect",
        sentence: withCaveat(
          "Saving this stores the new value but does NOT change the value in force. " +
            "Every process reads this once, when it starts, so the old value keeps " +
            "running until they are restarted",
          field.caveat,
        ),
      };
    case "env_only":
      return {
        id: "env_only",
        tone: "warn",
        label: "The store can never deliver this value",
        sentence: withCaveat(
          `Whatever is stored here would never be read: set ${field.env_var} in the ` +
            "deployment's environment and restart. NOT the same as needing a restart, " +
            "which promises a restart is enough",
          field.caveat,
        ),
      };
    case "unclassified":
      return {
        id: "unclassified",
        tone: "warn",
        label: "This build has not said when a change would take effect",
        sentence: withCaveat(
          "The key is not classified in this release, so the console will not offer to " +
            "change it — a field whose effect nobody has established is the one most " +
            "likely to do nothing quietly",
          field.caveat,
        ),
      };
    default:
      return {
        id: "unknown",
        tone: "warn",
        label: "This build cannot say when this takes effect",
        sentence:
          `The server reports this setting applies "${field.applies}", which is not a ` +
          "word this console knows. Do NOT assume the change is live: check the release " +
          "notes for the deployment serving this screen before relying on it.",
      };
  }
}

/**
 * WHY this key cannot be changed here — one of three answers, never one answer.
 *
 * `describe()` sets `editable: false` for three independent reasons and its own comment
 * says the console renders which: the environment already decides it, the store could
 * never deliver it, or this build has not established when a change would take effect.
 * They send an operator to three different places, and printing the first for all of them
 * is the failure a "fixed by X" line looks least like.
 */
function readOnlyReason(field: ConfigField): ReactNode {
  if (field.source === "env") {
    return (
      <>
        Fixed by <span className="font-mono">{field.env_var}</span> in this
        deployment&apos;s environment. The environment always wins over the console, so
        this cannot be changed here — change the variable and restart.
      </>
    );
  }
  const verdict = appliesVerdict(field);
  return (
    <>
      <span className="font-semibold">{verdict.label}.</span> {verdict.sentence}
    </>
  );
}

/** The consequence, at the weight the consequence deserves. */
function AppliesNotice({ verdict }: { verdict: AppliesVerdict }) {
  if (verdict.id === "live") {
    return (
      <p className="flex items-start gap-1.5 text-xs text-ink-muted">
        <CheckCircle2 aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          <span className="font-medium">{verdict.label}.</span> {verdict.sentence}
        </span>
      </p>
    );
  }
  return (
    <NoticeBox
      tone={verdict.tone}
      icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
      title={verdict.label}
    >
      <p className="mt-1">{verdict.sentence}</p>
    </NoticeBox>
  );
}

/** Who put the value in force, in the words the row can prove. */
function provenance(field: ConfigField): string {
  if (field.source === "db") {
    const who = field.updated_by ?? "an operator this console cannot name";
    return field.updated_at
      ? `set by ${who} at ${formatIST(field.updated_at)}`
      : `set by ${who}`;
  }
  if (field.source === "default") return "at the value built into this release";
  if (field.source === "env") return `pinned by ${field.env_var} in this deployment's environment`;
  // Not "unknown": the server said something, and printing it beats inventing a story.
  return `reported by the server with source "${field.source}"`;
}

/** The box the operator types in, from a value the server sent. */
function draftOf(value: ConfigValue): string {
  return value === null ? "" : String(value);
}

/**
 * This key's concurrency token, or `null` when the API did not send one.
 *
 * `null` is NOT treated as `"0"`, and that distinction is the whole guard. `"0"` is a
 * real token meaning "no row is stored", which a write may legitimately be conditional
 * on; an absent field means this deployment's API predates the precondition, and every
 * write to it would come back 428 (`require_if_match`). One is a state, the other is our
 * ignorance, and §52's rule is that they must not render the same — so the form is not
 * offered at all rather than offered and doomed.
 */
function etagOf(field: ConfigField): string | null {
  return typeof field.etag === "string" && field.etag.length > 0 ? field.etag : null;
}

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
  // The SERVER's answer to the last write, held by the ROW rather than by the form —
  // the form unmounts on success, and a confirmation rendered inside it was the one this
  // panel shipped with: unreachable code, so a save produced no confirmation at all.
  const [receipt, setReceipt] = useState<ConfigWrite | null>(null);
  const verdict = appliesVerdict(field);
  const tag = etagOf(field);

  return (
    <div className="rounded-card border border-line bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          {/* `break-all`, like the value line below: these keys are unbroken snake_case
              identifiers (`self_serve_inr_per_min`, `object_store_bucket`) with no space
              for a browser to wrap at, so at 320px they painted 15px outside the card. */}
          <p className="break-all font-mono text-sm text-ink">{field.key}</p>
          <p className="mt-0.5 break-all font-mono text-sm font-semibold text-ink">
            {display(field.value)}
          </p>
          <p className="mt-1 text-xs text-ink-faint">
            {/* Through `lookup()`, not a bare index. The comment here used to argue
                the index was safe because the union is server-controlled — but the
                union is our CLAIM about the wire, not a runtime guarantee, and a
                response carrying `constructor` would resolve to the `Object` function
                rather than to undefined. The fallback still prints the source itself
                rather than blanking the line. */}
            {lookup(SOURCE_NOTE, field.source) ?? `Source: ${field.source}`}
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
          {/* Flagged on the row itself so the exceptional cases are visible while
              scanning. Two conditions, both load-bearing: `live` is silent HERE and
              stated in the form, because a badge on all thirty-six rows is a badge
              nobody reads; and a NON-editable row is silent too, because
              `readOnlyReason` on the right is already saying this exact sentence as the
              reason there is no control — printing it twice is how an operator learns to
              read neither. */}
          {field.editable && verdict.id !== "live" && (
            <p className="mt-1 flex items-start gap-1.5 text-xs text-amber-700">
              <TriangleAlert aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
              <span>
                <span className="font-semibold">{verdict.label}</span> — {verdict.sentence}
              </span>
            </p>
          )}
        </div>

        {/* `sm:shrink-0`, not a flat `shrink-0`. The row is `flex-wrap`, so below `sm`
            this column drops onto its own line — but `shrink-0` then held it at its
            256px content width inside a 228px card, painting 28px across the card's
            border. Refusing to shrink is right on a wide row where the left column has
            room to give; on a phone there is no second column to take the space from. */}
        <div className="min-w-0 sm:shrink-0">
          {field.editable && tag === null ? (
            // The API answered without a precondition token, and it refuses every write
            // that carries no `If-Match` (428). Offering the form would be a control
            // whose only outcome is a refusal an operator cannot act on.
            <p className="flex max-w-[16rem] items-start gap-1.5 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                This deployment&apos;s API did not send a concurrency token for this key,
                and it refuses any change that does not name the value being replaced. The
                console cannot offer an edit it knows will be refused — this is an API and
                console version mismatch, not a permission.
              </span>
            </p>
          ) : field.editable ? (
            <button
              type="button"
              onClick={() => {
                // Opening the form retires the previous receipt: a confirmation for the
                // last write sitting above the next one is how two changes become one
                // remembered change.
                setReceipt(null);
                setOpen((was) => !was);
              }}
              disabled={!access.allowed}
              title={access.reason ?? undefined}
              className={SECONDARY_BUTTON_SM}
            >
              <Settings2 aria-hidden className="h-3.5 w-3.5" />
              {open ? "Cancel" : "Change"}
            </button>
          ) : (
            // READ-ONLY WITH THE REASON (§8). Not a hidden row and not a dead input —
            // and not ONE reason either. `editable: false` has three causes
            // (`platform_config.describe`), and the console used to print the
            // environment's for all of them, so an `unclassified` key told an operator to
            // go and change a variable that nobody has set and that would not help.
            <div className="flex max-w-[16rem] items-start gap-1.5 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{readOnlyReason(field)}</span>
            </div>
          )}
        </div>
      </div>

      {/* `field.editable` is re-read on EVERY render, not only when the button was
          clicked: a refetch that turns a key env-pinned (someone set the variable and
          restarted the process serving this screen) takes the form away, because the
          write it would send is one the API now refuses. */}
      {open && field.editable && tag !== null && (
        <ConfigForm
          field={field}
          basis={tag}
          onDone={() => setOpen(false)}
          onWritten={(write) => {
            setReceipt(write);
            setOpen(false);
          }}
        />
      )}

      {!open && receipt && (
        <WriteReceipt write={receipt} field={field} onDismiss={() => setReceipt(null)} />
      )}
    </div>
  );
}

/**
 * What the SERVER stored, after it stored it.
 *
 * Every value here comes from `ConfigWriteOut` — never from the draft the operator
 * typed. The two differ exactly when something worth knowing happened: the model
 * coerced the value, the key already had a row so `source` is now `db` rather than
 * `default`, or a peer's write landed between the read and the write.
 *
 * The last paragraph is the one that matters most and did not exist before: the write
 * went to the STORE, and the list beside it is what the process serving this screen has
 * in force. On a `stale` or `never_loaded` snapshot those disagree, and an operator
 * reading only the row would conclude the save failed and do it again.
 */
function WriteReceipt({
  write,
  field,
  onDismiss,
}: {
  write: ConfigWrite;
  field: ConfigField;
  onDismiss: () => void;
}) {
  const verdict = appliesVerdict(write.field);
  const inForceHere = field.value === write.field.value;
  // `recorded === false` is the server saying the submitted value was ALREADY the stored
  // one: no row moved, no audit entry exists, the sentinel did not bump and no process in
  // the fleet re-read anything. Absent means an API without the field, which only ever
  // recorded — so the fallback is the true statement for that deployment, not a guess.
  const recorded = write.recorded !== false;

  return (
    <div className="mt-3 space-y-2 border-t border-line pt-3">
      {/* A live region, because this is the answer to an action and it appears after the
          form that had focus has gone. Polite rather than assertive: the write already
          succeeded, so it must not interrupt. */}
      <p role="status" className="flex items-start gap-2 text-sm text-ink">
        <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
        {recorded ? (
          <span>
            Stored. <span className="font-mono">{write.key}</span> was{" "}
            <span className="font-mono font-semibold">{display(write.previous)}</span> and the
            store now holds{" "}
            <span className="font-mono font-semibold">{display(write.field.value)}</span>, at
            configuration version <span className="font-mono">{write.config_version}</span>.
          </span>
        ) : (
          // NOT "Stored." A double-clicked Save, or two operators reaching the same
          // conclusion, must not produce a receipt for a change that did not happen —
          // the audit log has no entry for this request, and a screen claiming otherwise
          // is the exact defect this slice exists to remove, in its politest costume.
          <span>
            Already the value. <span className="font-mono">{write.key}</span> was already{" "}
            <span className="font-mono font-semibold">{display(write.field.value)}</span>, so
            nothing was written, no audit entry was made, and no process was asked to
            re-read anything.
          </span>
        )}
      </p>
      {recorded && <AppliesNotice verdict={verdict} />}
      {recorded && !inForceHere && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="The process serving this screen has not picked it up yet"
        >
          <p className="mt-1">
            It still reports{" "}
            <span className="font-mono font-semibold">{display(field.value)}</span>. That is
            expected for a few seconds; if it persists, this process cannot reach the
            configuration store — check the banner at the top of this panel before assuming
            the change is in force anywhere.
          </p>
        </NoticeBox>
      )}
      <button type="button" onClick={onDismiss} className={SECONDARY_BUTTON_SM}>
        Dismiss
      </button>
    </div>
  );
}

/**
 * The value moved underneath this edit — the two-operators case, stated and stopped.
 *
 * Three choices and no fourth, because the fourth is the defect: there is no "retry".
 * Re-sending the same body against a value that has since changed is last-write-wins
 * wearing a confirmation step, and these are scalars — an `engine` of `bolna` and one of
 * `cartesia` have no merge, so offering one would be inventing a third state neither
 * operator asked for.
 *
 * Taking either of the two continuing choices RE-BASES the precondition onto the value
 * shown here and clears the typed confirmation, so the next save is still conditional and
 * still deliberate: if the key moves a second time, it refuses a second time.
 */
function ValueMoved({
  field,
  refused,
  serverSaid,
  onTakeTheirs,
  onKeepMine,
  onDiscard,
}: {
  field: ConfigField;
  refused: boolean;
  /** The API's own sentence, when it is the API that refused. */
  serverSaid: string | null;
  onTakeTheirs: () => void;
  onKeepMine: () => void;
  onDiscard: () => void;
}) {
  return (
    <NoticeBox
      tone="stop"
      icon={<Users aria-hidden className="h-5 w-5" />}
      title={
        refused
          ? "The server refused this change — the value had already moved"
          : "This value changed while you had this form open"
      }
    >
      <p className="mt-1">
        {refused
          ? "Nothing was written. Somebody else changed this key between the value you " +
            "were shown and the moment you pressed save."
          : "Somebody else changed this key since you opened this form. Nothing you typed " +
            "has been sent."}
      </p>
      {/* The API's own words, inside this box rather than in a second red one above it.
          Two accounts of one refusal is how an operator ends up answering the wrong one. */}
      {refused && serverSaid && <p className="mt-1 text-xs">The API said: {serverSaid}</p>}
      <p className="mt-2">
        It is now{" "}
        <span className="font-mono font-semibold">{display(field.value)}</span>,{" "}
        {provenance(field)}.
        {field.note && <> Their reason: &ldquo;{field.note}&rdquo;</>}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={onTakeTheirs} className={SECONDARY_BUTTON_SM}>
          Start from their value
        </button>
        <button type="button" onClick={onKeepMine} className={SECONDARY_BUTTON_SM}>
          Keep mine and replace theirs
        </button>
        <button type="button" onClick={onDiscard} className={SECONDARY_BUTTON_SM}>
          Discard my change
        </button>
      </div>
      <p className="mt-2 text-xs">
        Either of the first two puts you back in the form with the confirmation cleared, so
        the next save is a fresh decision made against the value above.
      </p>
    </NoticeBox>
  );
}

function ConfigForm({
  field,
  basis,
  onDone,
  onWritten,
}: {
  field: ConfigField;
  /** The token this form opened against — non-null by construction (see `ConfigRow`). */
  basis: string;
  onDone: () => void;
  onWritten: (write: ConfigWrite) => void;
}) {
  const save = useSetConfig();
  const revert = useRevertConfig();
  // Seeded from the value in force, so changing one setting is an edit rather than a
  // retype — and so submitting without touching the box is a no-op the operator can see.
  const [draft, setDraft] = useState(draftOf(field.value));
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  /**
   * The ENTITY-TAG this edit was decided against — captured when the form opened, moved
   * only by an explicit choice in `ValueMoved`.
   *
   * It is sent as `If-Match` and it is what makes "somebody else changed this" detectable
   * without a request: the panel's poll re-reads the list, and a token that no longer
   * matches IS the conflict. Deliberately not derived from `field` on every render —
   * that would make the conflict vanish the moment it appeared.
   *
   * THE TOKEN AND NOT THE VALUE, which was the first draft. A peer who sets 88 → 91 → 88
   * leaves the value identical and the revision two higher, and the server refuses that
   * write (412) because the operator decided against a row that no longer exists. A
   * console comparing values would have offered a Save that could only fail.
   */
  const [basisTag, setBasisTag] = useState(basis);
  /**
   * The server refused a conditional write. Held separately from the value comparison
   * because the two can disagree: a peer could set the key and set it back, leaving the
   * refusal true and the values equal. Cleared only by an operator's choice.
   */
  const [refused, setRefused] = useState(false);

  const word = field.key.toUpperCase();
  // `etagOf(field) ?? ""` rather than a non-null assertion: a field that LOSES its token
  // between two reads has, as far as this form can tell, moved — which is the safe
  // reading and the one that stops the write.
  const conflicted = (etagOf(field) ?? "") !== basisTag || refused;
  const ready = reason.trim().length >= 3 && confirm === word && !conflicted;
  const verdict = appliesVerdict(field);

  /** Continue from a stated current value: re-base the precondition, re-arm the typing. */
  const rebase = (nextDraft: string) => {
    setDraft(nextDraft);
    setBasisTag(etagOf(field) ?? "");
    setRefused(false);
    setConfirm("");
  };

  return (
    <form
      className="mt-3 space-y-3 border-t border-line pt-3"
      onSubmit={(e) => {
        e.preventDefault();
        // Belt and braces with the button's `disabled`: Enter in a text input submits a
        // form, and a conflict that only disabled the button would still be overridable
        // from the keyboard.
        if (!ready || save.isPending) return;
        save.mutate(
          {
            key: field.key,
            value: parseDraft(field, draft),
            reason: reason.trim(),
            ifMatch: basisTag,
          },
          {
            onSuccess: (write) => {
              setReason("");
              setConfirm("");
              onWritten(write);
            },
            onError: (error) => {
              // ONLY the flag. Clearing the confirmation here too was the obvious second
              // line and it was wrong twice over: `rebase` already does it on the two
              // paths that can continue, and a second mechanism made the first
              // untestable — a sabotage removing `rebase`'s clear left the suite green,
              // because this line was quietly covering for it. One way per problem, and
              // the way is `rebase`.
              if (isLostUpdate(error)) setRefused(true);
            },
          },
        );
      }}
    >
      {/* The conflict comes FIRST — above the inputs, because it decides whether anything
          below them may be sent. */}
      {conflicted && (
        <ValueMoved
          field={field}
          refused={refused}
          serverSaid={save.error?.message ?? revert.error?.message ?? null}
          onTakeTheirs={() => rebase(draftOf(field.value))}
          onKeepMine={() => rebase(draft)}
          onDiscard={onDone}
        />
      )}

      {/* Suppressed while the conflict box is up: it is carrying the same refusal, with
          the choices attached. Every other failure still gets the full problem+json
          rendering, including its remediation. */}
      {!refused && save.error && <ProblemNotice error={save.error} />}
      {!refused && revert.error && <ProblemNotice error={revert.error} />}

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

      {/* WHAT SAVING WILL AND WILL NOT DO, immediately above the button that does it.
          The row states this too, but a form is a screenful tall and the row's line is
          off the top of it by the time the confirmation is typed — and "needs a restart"
          learned afterwards is the same as not learned. */}
      <AppliesNotice verdict={verdict} />

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
            // Was a `title` plus a silent `return` inside the handler: the button looked
            // live, a click did nothing, and the explanation was in a tooltip a keyboard
            // or screen-reader user never reaches. A control that refuses is disabled and
            // says why in text — see the hint below.
            disabled={confirm !== word || conflicted || revert.isPending}
            onClick={() =>
              revert.mutate(
                { key: field.key, ifMatch: basisTag },
                {
                  onSuccess: (write) => {
                    setConfirm("");
                    onWritten(write);
                  },
                  onError: (error) => {
                    if (isLostUpdate(error)) setRefused(true);
                  },
                },
              )
            }
            className={SECONDARY_BUTTON_SM}
          >
            <RotateCcw aria-hidden className="h-3.5 w-3.5" />
            {revert.isPending ? "Reverting…" : "Revert to default"}
          </button>
        )}
      </div>

      {/* Why a control is dead, where the control is. */}
      {conflicted ? (
        <p className="text-xs text-ink-muted">
          Saving and reverting are both held until you choose above — nothing will be sent
          against a value that has already changed.
        </p>
      ) : (
        confirm !== word &&
        field.source === "db" &&
        field.has_default && (
          <p className="text-xs text-ink-muted">
            Type <span className="font-mono">{word}</span> above to enable both buttons —
            reverting is confirmed the same way, and sends its own confirmation string.
          </p>
        )
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
