"use client";

import { useState } from "react";

import {
  WithheldPanel,
  forbiddenReason,
  isForbidden,
} from "@/app/admin/withheld";
import { WriteFailure } from "@/app/admin/writeFailure";
import {
  BadgeCheck,
  CircleHelp,
  Save,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { providerLabel } from "@/lib/api/llmModels";
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
  MonoValue,
  TypeToConfirm,
  confirmMatches,
} from "@/app/admin/ops/opsLanguage";
import {
  useAttestDashboardDataUse,
  useDashboardDataUse,
  type DashboardDataUse,
  type DashboardDataUseList,
} from "@/lib/api/opsDashboardDataUse";

/**
 * LLM data-use attestation for the dashboard assist — D-477.
 *
 * ## Why this panel exists
 *
 * The in-app AI assistant prefers the provider a client's own agents run on, and whether it
 * MAY is a question about that vendor's terms for OUR account — not a model's merit, not a
 * credential being present. Every Google-owned host is egress-blocked from this deployment,
 * so no primary source about any vendor's data-use position can be read from the server. The
 * answer arrives the way the LLM price already does: the operator reads it in the vendor's
 * console and puts their name to it, with the account it is about captured as a first-class
 * field so the claim can be re-checked later rather than only re-made
 * (`apps/api/ops/dashboard_data_use_routes.py`).
 *
 * ## What the attestation ACHIEVES is not what UNBLOCKS the leg
 *
 * Eligibility is the AND of this attestation and whether this platform can build a dashboard
 * chat request for the leg at all (`dashboard_leg_built`). Today only the Azure leg satisfies
 * the second, so a complete attestation on another leg does NOT switch the assistant onto it.
 * The server says so in `blocked_reason`, and this panel renders that reason prominently
 * rather than inviting an operator to a five-minute job that cannot yet take effect. Both the
 * verdict and the ground come from the GET response, never from this screen's assumptions.
 *
 * ## This surface does NOT govern the in-call leg
 *
 * In-call sends RAW caller speech to whatever provider a client's chosen model sits on —
 * strictly worse exposure than this leg's redacted screen text — and nothing here gates it.
 * The copy says so, so nobody mistakes an attestation here for a control over that.
 *
 * ## The three states, and why there is no fourth
 *
 * loading is a skeleton, unreadable is a refusal with NO rows (a leg table rendered from a
 * failed read would show invented eligibility an operator would act on), and read is the
 * server's own rows. forbidden is the fourth of the same family — the server answered "not
 * you" — rendered as a withheld panel, exactly like the model-prices panel it sits beside.
 */

type DataUseState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "forbidden"; said: string | null }
  | { status: "read"; list: DashboardDataUseList };

export function dashboardDataUseState(query: {
  data: DashboardDataUseList | undefined;
  error: unknown;
  isLoading: boolean;
}): DataUseState {
  if (isForbidden(query.error)) {
    return { status: "forbidden", said: forbiddenReason(query.error) };
  }
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  return { status: "read", list: query.data };
}

export function DashboardDataUsePanel({
  access,
}: {
  access: { allowed: boolean; reason: string | null };
}) {
  const query = useDashboardDataUse();
  const state = dashboardDataUseState(query);

  if (state.status === "forbidden") {
    return (
      <WithheldPanel
        title="Dashboard AI data-use"
        reason={
          state.said ??
          "The API refused this read: your admin account may not manage platform configuration."
        }
        subject="This panel would list every LLM provider the in-app AI assistant could run on, whether it may today, and the latest data-use attestation for each."
      />
    );
  }

  return (
    <Card title="Dashboard AI data-use">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          The in-app AI assistant prefers the provider a client&apos;s own agents run on.
          Whether it may is a question about that vendor&apos;s terms for our account, which
          no page reachable from here can answer — so you read it in the vendor&apos;s own
          console and record it here. This governs only the assistant&apos;s redacted screen
          text; it does not govern the in-call leg, which sends raw caller speech and is not
          gated here.
        </p>

        {query.error && (
          <ProblemNotice error={query.error} onRetry={() => query.refetch()} />
        )}
        {state.status === "loading" && <Skeleton rows={4} />}

        {state.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We could not read the data-use attestations"
          >
            <p className="mt-1">
              This panel will not show invented eligibility when it could not read the real
              answer — an assistant routed on a guessed data-use position is the mistake that
              would cause. The error above says what stopped the read.
            </p>
          </NoticeBox>
        )}

        {state.status === "read" && (
          <ul className="space-y-2">
            {state.list.providers.map((provider) => (
              <li key={provider.provider}>
                <DataUseRow
                  leg={provider}
                  statement={state.list.statement}
                  access={access}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

/** True once an operator has recorded an attestation for this leg — every attestation field
 *  arrives `null` together when nobody has looked (`attested_at` is the marker). */
function hasAttestation(leg: DashboardDataUse): boolean {
  return leg.attested_at !== null;
}

function DataUseRow({
  leg,
  statement,
  access,
}: {
  leg: DashboardDataUse;
  statement: string;
  access: { allowed: boolean; reason: string | null };
}) {
  const [open, setOpen] = useState(false);
  const attested = hasAttestation(leg);

  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm text-ink">{providerLabel(leg.provider)}</p>
          <p className="mt-0.5 text-xs text-ink-faint">
            <MonoValue>{leg.provider}</MonoValue>
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1 text-xs font-medium ${
            leg.eligible ? "text-brand" : "text-amber-600"
          }`}
        >
          {leg.eligible ? (
            <BadgeCheck aria-hidden className="h-3.5 w-3.5" />
          ) : (
            <TriangleAlert aria-hidden className="h-3.5 w-3.5" />
          )}
          {leg.eligible ? "Assistant may run here" : "Not eligible"}
        </span>
      </div>

      {/* WHAT STILL BLOCKS THE LEG, in the server's own words. Rendered whenever the leg is
          not eligible — including after a perfectly valid attestation, when the reason the
          assistant still cannot run is that this platform cannot build a dashboard request
          for the provider at all (`dashboard_leg_built`). An operator who attested and saw
          nothing change would reasonably conclude their write did not land; this is why the
          panel states the ground rather than only the verdict, and never paraphrases it. */}
      {leg.blocked_reason != null && (
        <NoticeBox
          tone="warn"
          icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
          title={
            attested
              ? "Attested, but the assistant still cannot run on this leg"
              : "The assistant cannot run on this leg yet"
          }
        >
          <p className="mt-1">{leg.blocked_reason}</p>
        </NoticeBox>
      )}

      {leg.eligible && (
        <NoticeBox
          tone="ok"
          icon={<ShieldCheck aria-hidden className="h-5 w-5" />}
          title="The assistant may run on this leg"
        >
          <p className="mt-1">
            Both are true: this data-use position is attested, and this platform can build a
            dashboard request for the provider.
          </p>
        </NoticeBox>
      )}

      {attested ? (
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <dt className="text-ink-faint">Vendor project / account</dt>
          <dd className="text-ink">
            <MonoValue>{leg.vendor_account_ref}</MonoValue>
          </dd>
          <dt className="text-ink-faint">On the vendor&apos;s paid tier</dt>
          <dd className="text-ink">{leg.paid_tier_confirmed ? "Yes" : "No"}</dd>
          <dt className="text-ink-faint">Content not opted into free-tier terms</dt>
          <dd className="text-ink">
            {leg.no_training_opt_in_confirmed ? "Yes" : "No"}
          </dd>
          <dt className="text-ink-faint">Attested</dt>
          <dd className="text-ink">
            {formatIST(leg.attested_at)}
            {leg.attested_by ? ` · ${leg.attested_by}` : ""}
          </dd>
          {leg.source_note && (
            <>
              <dt className="text-ink-faint">Source</dt>
              <dd className="text-ink">{leg.source_note}</dd>
            </>
          )}
        </dl>
      ) : (
        <p className="mt-2 text-xs text-ink-faint">
          Nobody has looked yet. Recording that a leg is NOT on the paid tier, or HAS opted
          its content in, is worth as much as recording that it is clean — it is a different
          and more useful state than an unanswered one.
        </p>
      )}

      {access.allowed ? (
        <div className="mt-3">
          {open ? (
            <AttestForm
              leg={leg}
              statement={statement}
              onDone={() => setOpen(false)}
            />
          ) : (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => setOpen(true)}
            >
              <ShieldCheck aria-hidden className="h-3.5 w-3.5" />
              {attested ? "Update attestation" : "Record attestation"}
            </button>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-faint">
          {access.reason ??
            "Your admin account cannot change platform configuration."}
        </p>
      )}
    </div>
  );
}

function AttestForm({
  leg,
  statement,
  onDone,
}: {
  leg: DashboardDataUse;
  statement: string;
  onDone: () => void;
}) {
  const [vendorAccountRef, setVendorAccountRef] = useState(leg.vendor_account_ref ?? "");
  // Seeded from the last attestation so an update is an edit, not a retype — the operator
  // may be re-confirming after moving one account onto billing while everything else stands.
  const [paidTier, setPaidTier] = useState(leg.paid_tier_confirmed ?? false);
  const [noTrainingOptIn, setNoTrainingOptIn] = useState(
    leg.no_training_opt_in_confirmed ?? false,
  );
  const [sourceNote, setSourceNote] = useState("");
  const [confirm, setConfirm] = useState("");

  const save = useAttestDashboardDataUse();
  // The word the operator TYPES to arm the save — a clean, short word rather than the raw
  // step-up string the API checks. The real confirmation (`attest_dashboard_data_use:
  // <provider>`) still goes on the wire, set inside `useAttestDashboardDataUse`; conflating
  // the two is how a copy change would quietly become an API change.
  const word = "CONFIRM";
  // The two booleans are NOT required to be true: a negative answer is a valid and useful
  // attestation ("somebody looked and it is not on the paid tier"), so only the account ref,
  // the evidence note and the typed word arm the save.
  const ready =
    vendorAccountRef.trim().length > 0 &&
    sourceNote.trim().length >= 3 &&
    confirmMatches(confirm, word);

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready || save.isPending) return;
        save.mutate(
          {
            provider: leg.provider,
            vendorAccountRef: vendorAccountRef.trim(),
            paidTierConfirmed: paidTier,
            noTrainingOptInConfirmed: noTrainingOptIn,
            sourceNote: sourceNote.trim(),
          },
          { onSuccess: onDone },
        );
      }}
    >
      {save.error && (
        <WriteFailure error={save.error} actionLabel="Record attestation" />
      )}

      {/* THE EXACT SENTENCE THE OPERATOR IS AGREEING TO, rendered verbatim from the server so
          the console never keeps its own copy that drifts from what the API records. */}
      <div className="rounded-lg border border-line bg-app px-3 py-2">
        <p className="text-xs font-medium text-ink">What you are attesting</p>
        <p className="mt-1 text-xs leading-relaxed text-ink-muted">{statement}</p>
      </div>

      <label className="block">
        <span className={FIELD_LABEL}>Vendor project or account</span>
        <input
          value={vendorAccountRef}
          onChange={(e) => setVendorAccountRef(e.target.value)}
          placeholder="e.g. the project id our Google key belongs to"
          className={`${FIELD} font-mono`}
        />
        <span className={FIELD_HINT}>
          The project or account our API key for this provider belongs to. Required — it is
          what lets this claim be re-checked later rather than only re-made. For Google, it is
          the project shown on the AI Studio Projects page.
        </span>
      </label>

      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={paidTier}
          onChange={(e) => setPaidTier(e.target.checked)}
          className="mt-0.5 h-4 w-4"
        />
        <span className="text-sm text-ink">
          This project is on the vendor&apos;s paid tier
          <span className={`${FIELD_HINT} block`}>
            For Google, the &quot;Billing Tier&quot; column on the AI Studio Projects page
            shows the project linked to an open billing account.
          </span>
        </span>
      </label>

      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={noTrainingOptIn}
          onChange={(e) => setNoTrainingOptIn(e.target.checked)}
          className="mt-0.5 h-4 w-4"
        />
        <span className="text-sm text-ink">
          Nothing on this project opts our content into the vendor&apos;s free-tier data terms
          <span className={`${FIELD_HINT} block`}>
            For Google, Gemini API Logs and Datasets sharing is OFF. Leave this unticked if you
            found it ON — a negative answer is worth recording.
          </span>
        </span>
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>Source</span>
        <input
          value={sourceNote}
          onChange={(e) => setSourceNote(e.target.value)}
          placeholder="e.g. AI Studio Projects page read today, project 'calevate-prod'"
          className={FIELD}
        />
        <span className={FIELD_HINT}>
          Where you read this, in your own words. Saved with the attestation, so a later reader
          knows who looked and where.
        </span>
      </label>

      <TypeToConfirm
        id={`confirm-data-use-${leg.provider}`}
        word={word}
        value={confirm}
        onChange={setConfirm}
        hint="A correction is added as a new dated entry — nothing is overwritten — so what was believed when a client's content reached this vendor stays answerable."
      />

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!ready || save.isPending}
          className={PRIMARY_BUTTON_SM}
        >
          <Save aria-hidden className="h-3.5 w-3.5" />
          {save.isPending ? "Saving…" : "Record attestation"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
