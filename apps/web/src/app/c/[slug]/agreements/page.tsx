"use client";

import { useState } from "react";
import {
  CircleCheck,
  ExternalLink,
  FileText,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import {
  Card,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  NOTICE_TONES,
  PRIMARY_BUTTON_SM,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import {
  needsAction,
  useAcceptAgreement,
  useAgreementsReadiness,
  type DocumentState,
  type LegalDocumentState,
  type LegalReadiness,
  type ReadinessBlocker,
} from "@/lib/api/agreements";
import { useClientSession } from "@/lib/api/session";

/**
 * Agreements & readiness — the screen an owner opens because their calls will not go out.
 *
 * Eight published documents have existed at `/legal/<slug>` since the legal sweep and
 * nothing in this product had ever asked a client to accept one. Four of them BIND:
 * `legal.service.agreements_blocker` refuses the dial gate, both campaign gates and the
 * agent publish path until the owner has accepted them at their current version. This is
 * the only place that refusal can be cleared, so the page is written for the person who
 * arrived at it from a disabled button.
 *
 * ═══ THE SERVER DECIDES; THIS RENDERS ═══════════════════════════════════════════════
 *
 * Every verdict, every state word and every sentence on this screen arrives decided —
 * `may_operate`, `verdict`, each document's `state` and `headline`, each blocker's
 * `title`/`actor`/`next_step`, the acceptance wording, and whether THIS caller may
 * accept. Nothing here compares a version string or counts a list, and that is the
 * doctrine `lib/api/agreements.ts` states at length: whether an organisation may operate
 * is a compliance verdict four server-side gates already compute, and a browser that
 * re-derived it would eventually disagree with the gate that actually refuses the call.
 *
 * It is also why `can_accept` comes off the READ rather than out of `useWriteAccess`.
 * The permission preview would give the same answer today, and it would give it from a
 * SECOND rule: this endpoint's own answer already knows about the owner-only permission
 * AND the D-22 read-only session, and one of them is the reason on the day they differ.
 *
 * ═══ WHY ONE TICK AND FOUR ROWS ═════════════════════════════════════════════════════
 *
 * The acceptance statement is one sentence naming all four documents (the server owns the
 * text — `legal/statements.py`), and the ledger records one row per document, because an
 * acceptance is of a SPECIFIC text at a SPECIFIC version and a single row could not say
 * which. So the screen ticks once and posts once per outstanding document, in order,
 * stopping at the first refusal — a partially-accepted set is a truthful record of what
 * the owner got through, and the ones that landed do not need clicking again.
 *
 * The buttons are absent, not disabled, for a reader who cannot accept: `RestrictionNote`
 * says why instead. A disabled control with no explanation is the shape D-22 exists to
 * stop.
 *
 * BUILD-LOG §52 throughout: loading is a skeleton, a failure is a refusal, and neither is
 * a verdict. `may_operate` is never defaulted — a dead read renders the refusal, never
 * "nothing is holding up your calls".
 */

/** The five server-decided states, as the badge each one wears. */
const STATE_BADGE: Record<DocumentState, { label: string; tone: NoticeTone }> = {
  accepted: { label: "Accepted", tone: "ok" },
  never_accepted: { label: "Not accepted", tone: "stop" },
  reacceptance_required: { label: "Needs accepting again", tone: "stop" },
  changed: { label: "Updated", tone: "warn" },
  not_required: { label: "Reading only", tone: "neutral" },
};

/**
 * A small tone pill.
 *
 * `StatusBadge` next door is not it: that one is keyed on the LEAD and CALL status
 * vocabularies and prints the raw value, and neither vocabulary contains a document
 * state or an actor. It is the shared `NOTICE_TONES` palette either way, so the colour
 * of "not accepted" here is the colour of a refusal everywhere else.
 */
function TonePill({ tone, label }: { tone: NoticeTone; label: string }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-xs font-medium ${NOTICE_TONES[tone]}`}
    >
      {label}
    </span>
  );
}

/** Whose move a blocker is, in the two words the row is labelled with. */
const ACTOR_LABEL = {
  client: "Your move",
  calevate: "Ours to do",
} as const;

export default function AgreementsPage() {
  const session = useClientSession();
  const readiness = useAgreementsReadiness(session);

  if (readiness.isLoading) return <Skeleton rows={8} />;

  // A refusal we received, or an answer that never arrived — one branch, because to the
  // reader they are the same sentence and it is not "you are ready". `isLoading` is false
  // while a query is pending but not FETCHING (an offline browser parks at
  // `fetchStatus: "paused"`), which is how a client on a train gets a blank page.
  if (readiness.error || !readiness.data) {
    return (
      <ProblemNotice
        error={
          readiness.error ??
          new Error("Your agreements did not load, so we cannot say where this account stands.")
        }
        onRetry={() => void readiness.refetch()}
      />
    );
  }

  return <Readiness readiness={readiness.data} />;
}

/**
 * The whole screen, over an answer that has already arrived.
 *
 * Split from the page so every component below takes a decided value rather than a query
 * envelope: there is exactly one place in this file that can render a state from an
 * absent read, and it is the one above.
 */
function Readiness({ readiness }: { readiness: LegalReadiness }) {
  const blocking = readiness.documents.filter((doc) => doc.blocking);
  const readable = readiness.documents.filter((doc) => !doc.blocking);

  return (
    <div className="space-y-5 pb-12">
      <Verdict readiness={readiness} />

      {readiness.provisional_notice && (
        <NoticeBox tone="warn" icon={<FileText className="h-5 w-5" />} title="These are drafts">
          <p className="mt-1">{readiness.provisional_notice}</p>
        </NoticeBox>
      )}

      <Card title="The agreements that bind this business">
        <p className="text-sm text-ink-muted">
          These four decide whether this account may make outgoing calls. Read each one,
          then confirm below. Calls coming IN are unaffected by anything on this page.
        </p>
        <ul className="mt-4 space-y-3">
          {blocking.map((doc) => (
            <DocumentRow key={doc.slug} doc={doc} />
          ))}
        </ul>
        <AcceptPanel readiness={readiness} />
      </Card>

      <Card title="Also published, with nothing to accept">
        <p className="text-sm text-ink-muted">
          Notices we owe you rather than promises you make us — a sub-processor list you
          had to sign would make every vendor change a decision for you to take.
        </p>
        <ul className="mt-4 space-y-3">
          {readable.map((doc) => (
            <DocumentRow key={doc.slug} doc={doc} />
          ))}
        </ul>
      </Card>

      <Blockers rows={readiness.blockers} />
    </div>
  );
}

/**
 * May this account operate, in the server's own sentence.
 *
 * The icon and the tone are keyed on the same boolean as the words, so the badge cannot
 * drift from the sentence beside it — the device `/verification`'s verdict uses, and for
 * its reason.
 */
function Verdict({ readiness }: { readiness: LegalReadiness }) {
  const Icon = readiness.may_operate ? ShieldCheck : ShieldAlert;
  return (
    <NoticeBox
      tone={readiness.may_operate ? "ok" : "stop"}
      icon={<Icon className="h-5 w-5" />}
      title={
        readiness.may_operate
          ? "This account is ready to make calls."
          : "Outgoing calls are blocked."
      }
    >
      <p className="mt-1">{readiness.verdict}</p>
      {!readiness.may_operate && (
        <p className="mt-2 font-semibold">
          Calls coming IN are unaffected — your agent keeps answering the phone.
        </p>
      )}
    </NoticeBox>
  );
}

/** One document: what it is, where it stands, and where to read it. */
function DocumentRow({ doc }: { doc: LegalDocumentState }) {
  const badge = STATE_BADGE[doc.state];
  return (
    <li className="rounded-card border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">{doc.title}</h3>
        <TonePill tone={badge.tone} label={badge.label} />
      </div>
      <p className="mt-1 text-sm text-ink-muted">{doc.headline}</p>
      <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-faint">
        <div className="flex gap-1">
          <dt>Published version</dt>
          <dd className="font-mono text-ink-muted">{doc.version}</dd>
        </div>
        {doc.accepted_version && (
          <div className="flex gap-1">
            <dt>You accepted</dt>
            <dd className="font-mono text-ink-muted">{doc.accepted_version}</dd>
          </div>
        )}
        {doc.accepted_at && (
          <div className="flex gap-1">
            <dt>On</dt>
            <dd className="text-ink-muted">
              {formatIST(doc.accepted_at)}
              {doc.accepted_by_name ? ` by ${doc.accepted_by_name}` : ""}
            </dd>
          </div>
        )}
        {/* An effective date the documents do not have is stated as absent rather than
            hidden: `{{EFFECTIVE_DATE}}` is an unfilled placeholder in the bundle, and a
            reader who sees no row cannot tell that from a screen that forgot to print it. */}
        <div className="flex gap-1">
          <dt>Effective from</dt>
          <dd className="text-ink-muted">{doc.effective_date ?? "not yet dated"}</dd>
        </div>
      </dl>
      <a
        href={doc.href}
        target="_blank"
        rel="noreferrer"
        className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-ink underline"
      >
        Read {doc.title}
        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      </a>
    </li>
  );
}

/**
 * The tick and the button — or the sentence saying why there is neither.
 *
 * The statement text and its version are the server's and are posted back exactly as they
 * arrived: the stored `statement_version` is evidence only while the text it names can be
 * produced, and a sentence living in this component could not be. A console showing a
 * stale build is REFUSED (`legal_statement_not_current`), never recorded.
 */
function AcceptPanel({ readiness }: { readiness: LegalReadiness }) {
  const session = useClientSession();
  const accept = useAcceptAgreement(session);
  const [ticked, setTicked] = useState(false);

  const outstanding = readiness.documents.filter((doc) => doc.blocking && needsAction(doc));

  if (outstanding.length === 0) {
    return (
      <p className="mt-4 flex items-center gap-2 rounded-card border border-line px-3 py-2 text-sm text-ink-muted">
        <CircleCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
        Every agreement here has been accepted at its current version. We will ask again
        when one of them changes in a way that needs it.
      </p>
    );
  }

  if (!readiness.can_accept) {
    return (
      <div className="mt-4">
        <RestrictionNote reason={readiness.can_accept_reason} />
      </div>
    );
  }

  /**
   * One POST per document, in order, stopping at the first refusal.
   *
   * `mutateAsync` in a loop rather than four parallel calls: the response to each one is
   * the WHOLE screen, so concurrent writes would race to seed the cache and the last to
   * land would win with the oldest view. Sequential, the final response is the true final
   * state. A refusal (a version that moved under an open tab) leaves the earlier rows
   * recorded, which is what actually happened.
   */
  const submit = async () => {
    try {
      for (const doc of outstanding) {
        await accept.mutateAsync({
          slug: doc.slug,
          version: doc.version,
          statementVersion: readiness.acceptance_statement_version,
        });
      }
    } catch {
      // Swallowed HERE and nowhere else, and it is not a swallowed error: the refusal is
      // already on `accept.error` and is rendered below, verbatim, with its remediation.
      // What this catch stops is the loop's own rejection escaping into an unhandled
      // promise — `mutateAsync` rejects as well as recording, unlike `mutate` — which in
      // a browser is a console error nobody sees and in the suite is an unhandled
      // rejection that can fail an unrelated test.
      return;
    }
    setTicked(false);
  };

  return (
    <div className="mt-5 border-t border-line pt-4">
      <label className="flex items-start gap-3 text-sm text-ink">
        <input
          type="checkbox"
          checked={ticked}
          onChange={(event) => setTicked(event.target.checked)}
          className="mt-1 h-4 w-4 shrink-0"
        />
        <span>{readiness.acceptance_statement}</span>
      </label>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={!ticked || accept.isPending}
          onClick={() => void submit()}
          className={PRIMARY_BUTTON_SM}
        >
          <CircleCheck className="h-4 w-4" aria-hidden="true" />
          {accept.isPending
            ? "Recording…"
            : `Accept ${outstanding.length} agreement${outstanding.length === 1 ? "" : "s"}`}
        </button>
        <span className="text-xs text-ink-faint">
          We record which documents you accepted, at which version, and when.
        </span>
      </div>
      {accept.error ? <div className="mt-3"><ProblemNotice error={accept.error} /></div> : null}
    </div>
  );
}

/**
 * Everything else standing in the way, with whose move each one is.
 *
 * Rendered even when it is empty — as a stated "nothing else" rather than by disappearing.
 * A section that vanishes reads as a section that failed to load on the one screen whose
 * subject is what is missing.
 */
function Blockers({ rows }: { rows: ReadinessBlocker[] }) {
  return (
    <Card title="Everything else standing in the way">
      {rows.length === 0 ? (
        <p className="text-sm text-ink-muted">
          Nothing else at the account level is blocking outgoing calls. A campaign can
          still have conditions of its own — those are named on the campaign.
        </p>
      ) : (
        <ul className="space-y-3">
          {rows.map((row) => (
            <li key={row.rule} className="rounded-card border border-line p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-ink">{row.title}</h3>
                <TonePill
                  tone={row.actor === "client" ? "warn" : "neutral"}
                  label={ACTOR_LABEL[row.actor]}
                />
              </div>
              <p className="mt-1 text-sm text-ink-muted">{row.reason}</p>
              <p className="mt-2 text-sm text-ink">{row.next_step}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
