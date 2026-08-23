"use client";

/**
 * The plain-language layer for the operations console, in one place.
 *
 * ## Why this module exists
 *
 * Every screen under `/admin/ops` is used by ONE person — the founder-operator — who is
 * not an engineer. The panels were first written by engineers and leaked the vocabulary
 * of the code straight onto the screen: source filenames (`core/loadshed.py`), HTTP
 * status text (`503 service_load_shed`), internal enum values (`not_registered`), and
 * security-engineering terms with no gloss (`KEK`, "envelope encryption", "attestation").
 * A person cannot act on a word they have to be an engineer to read.
 *
 * So the translation from internal vocabulary to human language lives HERE, not inlined
 * per panel, for the same reason `NOTICE_TONES` and `formatINR` do: five panels each
 * describing the same five load-shed modes, or the same five "when does it take effect"
 * timings, is where the wording drifts — one screen gets the friendlier phrasing and the
 * next keeps the enum. One table, one voice, and `tests/opsLanguage.test.tsx` pins it.
 *
 * ## The rules the copy follows (sources in the research brief)
 *
 * - Sentence case, second person ("you"), present tense, active voice — the shared rule
 *   across the GOV.UK, Mailchimp and Microsoft style guides.
 * - Never surface a code symbol, file path or HTTP status to the operator; NN/g's error
 *   guidance is explicit that error codes are "for technical diagnostic purposes only".
 * - Say what happened AND what to do next; never blame the reader.
 * - Legally load-bearing telecom terms (DLT, PE, TM, DND) are KEPT verbatim and glossed
 *   in place — GOV.UK plain-language guidance allows an unavoidable technical term when it
 *   is explained where it is used. `TermGloss` below is that mechanism.
 *
 * Screen-specific prose (a panel's intro, a one-off warning) stays on its panel; what is
 * centralised here is the vocabulary shared across panels and the field/confirm controls
 * every write form is built from.
 */

import clsx from "clsx";
import { Check, Copy, Eye, EyeOff, Lock } from "lucide-react";
import { useState, type ReactNode } from "react";

import { lookup } from "@/lib/lookup";

import {
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  type NoticeTone,
} from "@/components/ui";

/* ────────────────────────────────────────────────────────────────────────────
 * 1. WHEN A CHANGE TAKES EFFECT  ("applies")
 *
 * The API tells us, per setting, when a change actually does anything. The words it uses
 * are precise and unreadable: `live`, `on_restart`, `needs_republish`, `env_only`,
 * `unclassified`. An operator needs the answer to one question — "have I finished, or is
 * there another step?" — so every label is phrased as that answer.
 * ──────────────────────────────────────────────────────────────────────────── */

export type ConfigApplies =
  | "live"
  | "on_restart"
  | "needs_republish"
  | "env_only"
  | "unclassified";

type TimingCopy = { label: string; help: string; tone: NoticeTone };

const TIMING: Record<ConfigApplies, TimingCopy> = {
  live: {
    label: "Takes effect right away",
    help: "Your change is live across the platform within a few seconds. There's nothing else to do.",
    tone: "ok",
  },
  needs_republish: {
    label: "Takes effect after you republish",
    help: "New work uses your change straight away, but anything already set up keeps the old value until you republish it.",
    tone: "warn",
  },
  on_restart: {
    label: "Takes effect after a restart",
    help: "The platform reads this value once when it starts, so your change applies the next time the service restarts.",
    tone: "warn",
  },
  env_only: {
    label: "Locked to the deployment",
    help: "This value is fixed when the platform is deployed and can't be changed from here. It has to be changed on the server, followed by a restart.",
    tone: "neutral",
  },
  unclassified: {
    label: "Timing not known",
    help: "This build doesn't say when a change to this setting takes effect. Check it after saving, or ask your engineer before relying on it.",
    tone: "neutral",
  },
};

/**
 * The timing copy for an `applies` value the server sent. Uses `lookup` (not `map[key]`)
 * for the same reason `StatusBadge` does — a value naming an `Object.prototype` member
 * must not resolve to a function — and falls back to a visible "not known" rather than a
 * blank, because a timing we can't name is exactly the one worth flagging.
 */
export function timingCopy(applies: string): TimingCopy {
  return (
    lookup(TIMING, applies) ?? {
      label: "Timing not known",
      help: `This build reports a timing ("${applies}") this screen doesn't recognise. Check the change took effect before relying on it.`,
      tone: "neutral",
    }
  );
}

/** A small inline badge stating when a change takes effect. */
export function TimingBadge({ applies }: { applies: string }) {
  const copy = timingCopy(applies);
  const toneClass: Record<NoticeTone, string> = {
    ok: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
    warn: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
    stop: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
    neutral: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  };
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        toneClass[copy.tone],
      )}
    >
      {copy.label}
    </span>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * 2. WHERE A VALUE CAME FROM  (provenance)
 *
 * A setting's current value is either typed here, fixed by the deployment, or the
 * built-in default. The operator needs to know which, because "set at deploy time" means
 * "changing it here does nothing" — the same idea enterprise consoles show as "managed by
 * your organisation".
 * ──────────────────────────────────────────────────────────────────────────── */

export type ConfigSource = "env" | "db" | "default";

type ProvenanceCopy = { label: string; help: string };

const PROVENANCE: Record<ConfigSource, ProvenanceCopy> = {
  db: {
    label: "Set here",
    help: "This value was set from this screen.",
  },
  env: {
    label: "Set at deploy time",
    help: "This value is fixed by the server's deployment settings, which override this screen. Changing it here has no effect until that's removed.",
  },
  default: {
    label: "Using the built-in default",
    help: "No one has changed this, so it's using the value built into this release.",
  },
};

export function provenanceCopy(source: string): ProvenanceCopy {
  return (
    lookup(PROVENANCE, source) ?? {
      label: "Source not known",
      help: `This build reports a source ("${source}") this screen doesn't recognise.`,
    }
  );
}

/** A neutral badge naming where a setting's value came from. */
export function ProvenanceBadge({ source }: { source: string }) {
  const copy = provenanceCopy(source);
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
      {source === "env" && <Lock className="h-3 w-3" aria-hidden />}
      {copy.label}
    </span>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * 3. TESTING A CREDENTIAL  (four honest outcomes)
 *
 * The "test this key" button never reveals the value; it reports one of four states. The
 * copy is deliberately plain and non-blaming, and separates "the vendor said no" from "we
 * couldn't ask" — the two are different problems with different fixes.
 * ──────────────────────────────────────────────────────────────────────────── */

export type SecretTestOutcome = "accepted" | "rejected" | "unreachable" | "no_probe";

type OutcomeCopy = { title: string; help: string; tone: NoticeTone };

const TEST_OUTCOME: Record<SecretTestOutcome, OutcomeCopy> = {
  accepted: {
    title: "This key works",
    help: "The vendor accepted it.",
    tone: "ok",
  },
  rejected: {
    title: "The vendor rejected this key",
    help: "Check you copied the whole key and that it hasn't been revoked or expired on the vendor's dashboard.",
    tone: "stop",
  },
  unreachable: {
    title: "We couldn't reach the vendor to check",
    help: "This doesn't mean the key is wrong — we just couldn't reach the vendor right now. Try again in a moment.",
    tone: "warn",
  },
  no_probe: {
    title: "We can't test this type of key yet",
    help: "There's no automatic check for this vendor. Save it, and it'll show up as working the first time the platform uses it.",
    tone: "neutral",
  },
};

/**
 * `verified` folds in the API's honesty flag: an "accepted" we haven't confirmed against a
 * real refusal from that vendor is shown as indicative, not a green tick, so a probe that
 * has never actually seen the vendor say "no" can't claim it saw it say "yes".
 */
export function testOutcomeCopy(outcome: string, verified = true): OutcomeCopy {
  const base =
    lookup(TEST_OUTCOME, outcome) ??
    ({
      title: "We couldn't read the test result",
      help: "The check returned something this screen doesn't recognise. Try again, or confirm the key the next time it's used.",
      tone: "neutral",
    } satisfies OutcomeCopy);
  if (outcome === "accepted" && !verified) {
    return {
      title: "This key looks right",
      help: "The vendor didn't reject it — but we can't fully confirm this type of key from here. Treat it as a good sign, not a guarantee.",
      tone: "neutral",
    };
  }
  return base;
}

/** The four-outcome result box shown after a credential test. */
export function TestOutcome({
  outcome,
  verified = true,
  lastFour,
}: {
  outcome: string;
  verified?: boolean;
  lastFour?: string | null;
}) {
  const copy = testOutcomeCopy(outcome, verified);
  return (
    <NoticeBox tone={copy.tone} title={copy.title}>
      <p className="mt-1">{copy.help}</p>
      {lastFour ? (
        <p className="mt-1 text-xs opacity-80">
          Checked the key ending <MonoValue>…{lastFour}</MonoValue>.
        </p>
      ) : null}
    </NoticeBox>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * 4. SYSTEM STATE  (load-shed modes, told like a status page)
 *
 * The internal modes are `normal` / `reduced` / `emergency` / `maintenance`. Mapped onto
 * the plain, ordered vocabulary a status page uses (Operational / Degraded / …), which an
 * operator reads instantly, while keeping the truthful description of what each one does —
 * including the honest note that "emergency" sheds exactly what "reduced" does today.
 * ──────────────────────────────────────────────────────────────────────────── */

export type LoadShedMode = "normal" | "reduced" | "emergency" | "maintenance";

type ModeCopy = { label: string; tone: NoticeTone };

const LOAD_SHED_MODE: Record<LoadShedMode, ModeCopy> = {
  normal: { label: "Running normally", tone: "ok" },
  reduced: { label: "Reduced — new changes paused", tone: "warn" },
  emergency: { label: "Emergency — new changes paused", tone: "stop" },
  maintenance: { label: "Maintenance — client screens paused", tone: "stop" },
};

export function loadShedModeCopy(mode: string): ModeCopy {
  return (
    lookup(LOAD_SHED_MODE, mode) ?? {
      label: `Unknown mode (${mode})`,
      tone: "neutral",
    }
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * 5. OUR TELEMARKETER REGISTRATION  (DLT)
 *
 * Enum → plain sentence. The telecom acronyms stay (they are the legal terms an operator
 * will see on the registrar's own letter) and are glossed via `TermGloss`, per the
 * plain-language rule on unavoidable technical terms.
 * ──────────────────────────────────────────────────────────────────────────── */

export type TmStatus =
  | "not_registered"
  | "submitted"
  | "active"
  | "suspended"
  | "revoked";

const TM_STATUS: Record<TmStatus, ProvenanceCopy> = {
  not_registered: {
    label: "Not registered",
    help: "We haven't filed our telemarketer registration yet.",
  },
  submitted: {
    label: "Filed, waiting on the registrar",
    help: "We've applied, but the registrar hasn't granted it yet.",
  },
  active: {
    label: "Active",
    help: "Granted and in force — customers can launch outbound campaigns.",
  },
  suspended: {
    label: "Suspended",
    help: "The registrar has paused it, usually after a complaint. No customer can launch outbound campaigns until it's active again.",
  },
  revoked: {
    label: "Revoked",
    help: "The registration has been withdrawn. No customer can launch outbound campaigns until it's active again.",
  },
};

export function tmStatusCopy(status: string): ProvenanceCopy {
  return (
    lookup(TM_STATUS, status) ?? {
      label: status.replace(/_/g, " "),
      help: "",
    }
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * 6. DO-NOT-CALL SOURCES
 * ──────────────────────────────────────────────────────────────────────────── */

export type DncSource = "regulator" | "platform_block";

const DNC_SOURCE: Record<DncSource, ProvenanceCopy> = {
  regulator: {
    label: "A regulator, telecom operator or registrar told us to",
    help: "Put the escalation or ticket reference in the reason — a year from now, that's what answers 'on whose instruction'.",
  },
  platform_block: {
    label: "Our own decision never to call it",
    help: "No outside instruction. The reason you write is the whole record of why — write it for someone who wasn't here.",
  },
};

export function dncSourceCopy(source: string): ProvenanceCopy {
  return (
    lookup(DNC_SOURCE, source) ?? {
      label: source.replace(/_/g, " "),
      help: "",
    }
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * 7. GLOSSING A LEGAL / TECHNICAL TERM IN PLACE
 *
 * `<TermGloss term="DLT">India's telecom message registry…</TermGloss>` renders the term
 * with a dotted underline and a native tooltip, and — because a tooltip is invisible to a
 * touch user and to some screen readers — also exposes the gloss as the accessible
 * description. This is the "keep the term, explain it where it's used" pattern; it is the
 * only sanctioned way to put DLT / PE / TM / DND on screen.
 * ──────────────────────────────────────────────────────────────────────────── */

export function TermGloss({ term, children }: { term: string; children: string }) {
  return (
    <abbr
      title={children}
      aria-label={`${term}: ${children}`}
      className="cursor-help underline decoration-dotted underline-offset-2"
    >
      {term}
    </abbr>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * 8. A FIXED-WIDTH VALUE  (keys' last-4, IDs, versions, codes)
 *
 * Anything an operator reads character-by-character renders in JetBrains Mono via
 * `font-mono` (globals.css), where 0/O and 1/l/I are distinct. A component rather than a
 * bare `<span className="font-mono">` so the choice is made once and a reader is never
 * asked to tell an O from a 0 in a proportional font on one screen and a mono one on the
 * next.
 * ──────────────────────────────────────────────────────────────────────────── */

export function MonoValue({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <span className={clsx("font-mono", className)}>{children}</span>;
}

/* ────────────────────────────────────────────────────────────────────────────
 * 9. THE KEY / SECRET INPUT
 *
 * The field an operator pastes an API key into. This is the control the whole rebuild was
 * asked for, so its rules are deliberate:
 *
 * - Monospace (`font-mono`), so a pasted key's characters are unambiguous.
 * - `type="password"` by default with a show/hide toggle — a key is shoulder-surfable, and
 *   the operator sometimes needs to eyeball what they pasted. Toggling reveals only what
 *   is in THIS field right now; nothing stored is ever shown here.
 * - `autoComplete="off"`, `spellCheck={false}`, `autoCapitalize="off"` — a browser must
 *   not offer to remember a secret, underline it as a typo, or capitalise it.
 * - `aria-describedby` wires the hint to the field for a screen reader.
 *
 * It is a controlled input: the parent owns the value and clears it after a successful
 * save so the plaintext does not linger (the ops mutation hooks already set `gcTime: 0`
 * for the same reason).
 */
export function KeyField({
  id,
  label,
  value,
  onChange,
  hint,
  placeholder,
  autoFocus,
  disabled,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
  placeholder?: string;
  autoFocus?: boolean;
  disabled?: boolean;
}) {
  const [revealed, setRevealed] = useState(false);
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div>
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      <div className="relative mt-1">
        <input
          id={id}
          // The form opens on the operator's click specifically to paste a key, so focus
          // belongs in this field the moment it appears.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus={autoFocus}
          type={revealed ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          aria-describedby={hintId}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          // `pr-10` leaves room for the reveal toggle; `mt-0` because the wrapper owns the
          // top margin the shared FIELD class would otherwise add.
          className={clsx(FIELD, "mt-0 pr-10 font-mono")}
        />
        <button
          type="button"
          onClick={() => setRevealed((r) => !r)}
          disabled={disabled}
          aria-label={revealed ? "Hide the key" : "Show the key"}
          aria-pressed={revealed}
          className="absolute inset-y-0 right-0 flex items-center px-3 text-ink-faint hover:text-ink-muted disabled:opacity-50"
        >
          {revealed ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
        </button>
      </div>
      {hint ? (
        <span id={hintId} className={FIELD_HINT}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * 10. TYPE-TO-CONFIRM
 *
 * The last gate before a consequential write. The operator types an exact word to arm the
 * action. This is one component, not a copy per form, so the phrasing ("Type STOP to
 * confirm"), the monospace field and the exact-match logic are identical on every lever —
 * the pattern GitHub uses for repository deletion.
 *
 * `word` is the literal to type (usually a short verb like STOP / HALT / REWRAP). The
 * parent decides whether the typed value matches; this component only renders the field
 * and reports what was typed, so the parent's existing `ready` logic stays the source of
 * truth.
 */
export function TypeToConfirm({
  id,
  word,
  value,
  onChange,
  hint,
  disabled,
}: {
  id: string;
  word: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div>
      <label htmlFor={id} className={FIELD_LABEL}>
        Type <MonoValue className="font-semibold">{word}</MonoValue> to confirm
      </label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={word}
        disabled={disabled}
        aria-describedby={hintId}
        autoComplete="off"
        autoCapitalize="characters"
        autoCorrect="off"
        spellCheck={false}
        className={clsx(FIELD, "font-mono")}
      />
      {hint ? (
        <span id={hintId} className={FIELD_HINT}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

/** True when what the operator typed exactly matches the confirm word. */
export function confirmMatches(typed: string, word: string): boolean {
  return typed === word;
}

/* ────────────────────────────────────────────────────────────────────────────
 * 11. DANGER ZONE
 *
 * The wrapper for a lever that changes platform state for every customer at once. A rose
 * border and a plain "This affects every customer" heading, following GitHub's own
 * "Danger zone" convention, so the eye separates the kill switches from the everyday
 * settings and does not fire one by reflex.
 * ──────────────────────────────────────────────────────────────────────────── */

export function DangerZone({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-card border border-rose-200 bg-rose-50/40 dark:border-rose-900 dark:bg-rose-950/20">
      <header className="flex items-center gap-2 border-b border-rose-200 px-4 py-3 dark:border-rose-900">
        <Lock className="h-4 w-4 text-rose-700 dark:text-rose-300" aria-hidden />
        <h2 className="text-[15px] font-semibold text-rose-900 dark:text-rose-200">{title}</h2>
      </header>
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * 12. COPY-TO-CLIPBOARD  (for IDs the operator needs to quote — never for secrets)
 *
 * A small affordance beside an ID or reference the operator may need to paste into a
 * support ticket. Deliberately NOT offered for any secret value: there is no secret value
 * on screen to copy, and this must never become the exception that puts one there.
 * ──────────────────────────────────────────────────────────────────────────── */

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(
          () => setCopied(true),
          () => setCopied(false),
        );
      }}
      aria-label={copied ? `${label} copied` : `Copy ${label}`}
      className="inline-flex items-center gap-1 text-ink-faint hover:text-ink-muted"
    >
      {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
    </button>
  );
}

/* Re-export the danger button class so a panel building a destructive action inside a
 * DangerZone imports its button from the same place as the zone. */
export { DANGER_BUTTON };
