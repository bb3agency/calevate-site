import type { ReactNode } from "react";
import { CheckCircle2, TriangleAlert } from "lucide-react";

import { forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import { NoticeBox, formatIST, type NoticeTone } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import type { ConfigField, ConfigList, ConfigValue } from "@/lib/api/opsConfig";

/**
 * What one platform setting IS, said for a human: its name, its value, where the value came
 * from, and when a change to it takes effect. React-light on purpose — the screen, the row,
 * the form and the tests all read these, and none of them may answer differently.
 */

/**
 * The read, as a type rather than as discipline (§52): loading is not empty, a failure is
 * not a table of defaults, and a 403 is a settled refusal rather than an outage.
 */
export type ConfigState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "forbidden"; said: string | null }
  | { status: "read"; config: ConfigList };

export function configState(query: {
  data: ConfigList | undefined;
  error: unknown;
  isLoading: boolean;
}): ConfigState {
  // The 403 before the generic failure: `GET /v1/ops/config` carries `platform:config`
  // exactly as the PUT does, and "we could not read it" with a retry beside it is the
  // sentence for an outage — this one is settled.
  if (isForbidden(query.error)) {
    return { status: "forbidden", said: forbiddenReason(query.error) };
  }
  // Error before data: a failed refetch leaves the previous `data` in place, and a stale
  // config table rendered as current is the same lie as an invented one.
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  return { status: "read", config: query.data };
}

/** What the API returned, rendered for a human. `null` is stated, never blanked. */
export function display(value: ConfigValue): string {
  if (value === null) return "not set";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

/**
 * A plain name shown ABOVE the machine key. Curated for the keys an operator meets most;
 * anything newer is humanised, and the key is always printed beside it so the fallback can
 * never hide which setting is which. Read through `lookup` because the key is a wire string.
 */
const SETTING_LABELS: Record<string, string> = {
  engine: "Active voice engine",
  webhook_base_url: "Webhook web address",
  self_serve_inr_per_min: "Self-serve price per minute",
  usd_inr_rate: "US dollar to rupee rate",
  inbound_reserve_ratio: "Share of lines kept free for inbound calls",
  db_pool_size: "Database connection pool size",
  self_serve_signup_enabled: "Self-serve sign-up",
  email_provider: "Email provider",
  payment_provider: "Payment provider",
  number_provider: "Phone-number provider",
  carrier: "Active telephony carrier",
  carrier_cps: "Outbound calls started per second",
  carrier_concurrency: "Simultaneous calls the carrier account allows",
  carrier_transfer_enabled: "Transfer callers to a human",
  vobiz_signature_required: "Require Vobiz request signatures",
  vobiz_callback_ips: "Vobiz callback addresses (override)",
  azure_openai_resource: "Azure OpenAI resource",
  azure_openai_deployment: "Azure OpenAI deployment",
  azure_openai_model: "Model in use",
  first_party_auth_enabled: "Sign-in enabled",
  object_store_bucket: "Storage bucket",
};

export function settingLabel(key: string): string {
  const curated = lookup(SETTING_LABELS, key);
  if (curated) return curated;
  const words = key.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * WHEN a change to this key takes effect — every answer the API has, plus one.
 *
 * `core/platform_config.APPLIES_VALUES` names five. `applies` is a plain `str` on the wire,
 * so a deployment newer than this bundle can send a sixth word; that case says so instead of
 * falling through to silence, because silence reads as "live" and live is the dangerous
 * assumption (`webhook_base_url` is live for new agents and NOT for published ones).
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
      // A LIVE field carrying a caveat is a classification that has drifted; the sentence
      // exists because somebody wrote it about this key, so it is rendered, not dropped.
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
        // Kept verbatim: a runbook and a test both print it.
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
 * WHY this key cannot be changed here. `editable: false` has three independent causes
 * (`platform_config.describe`) that send an operator to three different places, so the
 * environment's answer is printed only when the environment is the reason.
 */
export function readOnlyReason(field: ConfigField): ReactNode {
  if (field.source === "env") {
    return (
      <>
        Fixed by <MonoValue>{field.env_var}</MonoValue> in this deployment&apos;s
        environment. The environment always wins over the console, so this cannot be changed
        here — change that on the server and restart.
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
export function AppliesNotice({ verdict }: { verdict: AppliesVerdict }) {
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
export function provenance(field: ConfigField): string {
  if (field.source === "db") {
    const who = field.updated_by ?? "an operator this console cannot name";
    return field.updated_at ? `set by ${who} at ${formatIST(field.updated_at)}` : `set by ${who}`;
  }
  if (field.source === "default") return "at the value built into this release";
  if (field.source === "env") return `pinned by ${field.env_var} in this deployment's environment`;
  // The server said something; printing it beats inventing a story.
  return `reported by the server with source "${field.source}"`;
}

/** The box the operator types in, from a value the server sent. */
export function draftOf(value: ConfigValue): string {
  return value === null ? "" : String(value);
}

/**
 * This key's concurrency token, or `null` when the API did not send one.
 *
 * `null` is NOT `"0"`: `"0"` is a real token meaning "no row is stored", while an absent
 * field means an API that predates the precondition and refuses every write with 428. The
 * row offers no form at all for the second, rather than a form whose only outcome is that
 * refusal.
 */
export function etagOf(field: ConfigField): string | null {
  return typeof field.etag === "string" && field.etag.length > 0 ? field.etag : null;
}

/**
 * The typed value to send, from what the operator typed.
 *
 * Booleans and integers are converted because those are unambiguous; everything else —
 * including `decimal` and `number` — goes as the STRING typed. Money must not pass through
 * a JS float on its way to a NUMERIC column (hard rule 7), and the server validates against
 * the model the app loads at boot, so an unparseable string is refused in the model's words
 * rather than coerced here into something that validates but is not what was typed.
 */
export function parseDraft(field: ConfigField, draft: string): ConfigValue {
  const trimmed = draft.trim();
  if (trimmed === "") return null;
  if (field.kind === "boolean") return trimmed === "true";
  if (field.kind === "integer") {
    const parsed = Number(trimmed);
    return Number.isInteger(parsed) ? parsed : trimmed;
  }
  return trimmed;
}
