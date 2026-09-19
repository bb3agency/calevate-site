"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Info, ShieldAlert } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
  formatISTInput,
  formatWholeCount,
  istInputToInstant,
} from "@/components/ui";
import { MonoValue, TypeToConfirm, confirmMatches } from "@/app/admin/ops/opsLanguage";
import { useAdminAccess } from "@/app/admin/access";
import { useTenant } from "@/lib/api/admin";
import {
  MAX_BLOCKED_NUMBERS,
  needsPreferenceScrub,
  scrubBlockReason,
  scrubBlocker,
  splitBlockedNumbers,
  useRecordPreferenceScrub,
  useTenantCampaigns,
  useTenantLaunchCheck,
  type PreferenceScrubOut,
  type ScrubDraft,
} from "@/lib/api/preferenceScrub";
import type { CampaignSummary } from "@/lib/api/campaigns";

/**
 * THE NATIONAL DND SCRUB — the screen that unblocks promotional dialling.
 *
 * ## The blocker, confirmed in the code before this was built
 *
 * `national_dnd_blocker` refuses every campaign classified `promotional` with
 * `national_dnd_scrub_missing` until a run exists and `national_dnd_scrub_expired` once
 * the one on file has aged out, at LAUNCH and again on every dispatch tick. The only
 * writer of `preference_scrub_runs` is `record_scrub_run`, whose only caller is
 * `POST /v1/admin/tenants/{id}/campaigns/{cid}/preference-scrub` — and nothing in either
 * console called it. So no promotional campaign could be launched by anybody, and the
 * operator holding the provider's report had nowhere to put it. That is the whole reason
 * this screen exists.
 *
 * ## Why it is a screen and not a card on the tenant page
 *
 * The house rule this console already follows (`TenantNav`): a panel that needs its own
 * unsaved state, its own audited write or its own history is a route. This has all
 * three — a five-field form holding a pasted list of up to 5,000 numbers, an audited
 * append-only compliance record, and a per-campaign gate state that has to be read live.
 *
 * ## THE EXPIRY IS THE THING MOST EASILY GOT WRONG, SO IT IS SAID THREE WAYS
 *
 * A scrub is valid until 23:59:59 IST on the day the provider ran it, and the campaign
 * keeps dialling past midnight: a campaign that launched on a valid scrub is dialling an
 * unscrubbed list by morning. So the verdict (`is_current`), the instant (`expires_at`,
 * printed in IST) and the consequence are all on screen — and `is_current` is the
 * SERVER's, never `expires_at > now` computed here. A run recorded after its own day has
 * ended is a legitimate historical record that does not satisfy the gate, and only the
 * server is entitled to say which of those happened.
 *
 * ## The confirmation is the provider's reference, typed twice
 *
 * The route requires `X-Confirm-Action: record_preference_scrub:<campaign_id>` on every
 * call and the client sends it automatically — which means the header on its own is
 * ceremony the browser performs, not a human confirming anything. The human confirmation
 * is therefore the one this repo already chose for an irreversible record keyed on a
 * transcribed string (`credits/page.tsx`): the operator types the provider's reference
 * AGAIN. It buys the two things a fixed word cannot — a reference is different every
 * time so it cannot become muscle memory, and re-keying is the only check that catches a
 * transcription error before a write that `preference_scrub_runs` being INSERT-only makes
 * permanent.
 *
 * This is deliberately the OPPOSITE call from the billing motion and the carrier
 * decision, which carry no ceremony because they are reversible. Ceremony belongs on the
 * act that cannot be taken back.
 */
export default function PreferenceScrubPage({
  params,
}: {
  // Next 15: `params` is a Promise in every page, unwrapped with React's `use()` in a
  // client component — nextjs.org/docs/app/api-reference/file-conventions/dynamic-routes.
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const slug = tenant?.slug ?? "";
  const campaigns = useTenantCampaigns(slug);
  const [campaignId, setCampaignId] = useState<string | null>(null);

  if (tenantQuery.isLoading) return <Skeleton rows={6} />;
  if (tenantQuery.error)
    return <ProblemNotice error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />;
  if (!tenant) return <EmptyState title="Client not found" />;

  const scrubbable = (campaigns.data ?? []).filter(needsPreferenceScrub);
  const selected = scrubbable.find((campaign) => campaign.id === campaignId) ?? null;

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {tenant.name}
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">National DND scrub</h1>
        <p className="text-sm text-ink-muted">
          The national customer preference register. An access provider&apos;s DLT platform
          scrubs a campaign&apos;s list against it and hands back a reference, a report and
          a verdict good until midnight IST that day. Recording that run here is what lets
          a promotional campaign launch — and nothing else does.
        </p>
      </div>

      <NoticeBox tone="neutral" icon={<Info className="h-5 w-5" />} title="What this is not">
        <p className="mt-1 text-xs opacity-90">
          It is not the platform-wide do-not-call list (that is{" "}
          <Link href="/admin/ops/dnc" className="font-medium underline">
            ops · DNC
          </Link>
          ) and it is not the client&apos;s own suppression list. This is a per-campaign
          scrub run by a provider against the national register, recorded against the
          campaign it was run for. Only promotional campaigns are scoped by the register;
          transactional and service traffic is not, and no scrub is offered for them.
        </p>
      </NoticeBox>

      {campaigns.error && (
        <ProblemNotice error={campaigns.error} onRetry={() => campaigns.refetch()} />
      )}

      {campaigns.isLoading ? (
        <Skeleton rows={4} />
      ) : !campaigns.data ? (
        /* Withheld, not empty. "This client has no promotional campaign" is also a REAL
           state, and an operator who reads it over a failed read walks away believing
           there is nothing to unblock. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot list this client's campaigns"
        >
          <p className="mt-1 text-xs opacity-90">
            We could not read them, which is not the same as there being none. Retry the
            read above; the picker comes back with it.
          </p>
        </NoticeBox>
      ) : scrubbable.length === 0 ? (
        <EmptyState
          title="No campaign here needs a scrub"
          hint={
            campaigns.data.length === 0
              ? "This client has not built a campaign yet. A promotional one will appear here the moment they do."
              : "Every campaign on this account is transactional or service traffic, which the preference register does not scope — or has already finished dialling. Nothing is being held up."
          }
        />
      ) : (
        <>
          <CampaignPicker
            campaigns={scrubbable}
            campaignId={campaignId}
            onChange={setCampaignId}
          />
          {selected && (
            <ScrubForCampaign tenantId={tenantId} slug={slug} campaign={selected} />
          )}
        </>
      )}
    </div>
  );
}

function CampaignPicker({
  campaigns,
  campaignId,
  onChange,
}: {
  campaigns: CampaignSummary[];
  campaignId: string | null;
  onChange: (id: string) => void;
}) {
  return (
    <Card title="Which campaign">
      <div>
        <label htmlFor="scrub-campaign" className={FIELD_LABEL}>
          Promotional campaign
        </label>
        <div className="mt-1">
          <select
            id="scrub-campaign"
            value={campaignId ?? ""}
            onChange={(e) => onChange(e.target.value)}
            aria-describedby="scrub-campaign-hint"
            className={FIELD}
          >
            <option value="">— choose a campaign —</option>
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name} · {campaign.status} · {formatWholeCount(String(campaign.contacts))}{" "}
                contacts
              </option>
            ))}
          </select>
        </div>
        <span id="scrub-campaign-hint" className={FIELD_HINT}>
          A scrub is recorded against ONE campaign&apos;s list. Recording it against
          another campaign would be evidence about a list the provider never saw.
        </span>
      </div>
    </Card>
  );
}

/** The gate's live state for this campaign, then the form that changes it. */
function ScrubForCampaign({
  tenantId,
  slug,
  campaign,
}: {
  tenantId: string;
  slug: string;
  campaign: CampaignSummary;
}) {
  const check = useTenantLaunchCheck(slug, campaign.id);
  const record = useRecordPreferenceScrub(tenantId, slug, campaign.id);
  const write = useAdminAccess("admin:tenants", "record a national DND scrub");
  const blocker = scrubBlocker(check.data);

  return (
    <div className="space-y-3">
      {check.error && <ProblemNotice error={check.error} onRetry={() => check.refetch()} />}
      {check.isLoading ? (
        <Skeleton rows={2} />
      ) : !check.data ? (
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot read this campaign's launch gate"
        >
          <p className="mt-1 text-xs opacity-90">
            Recording a scrub still works, and is still the right thing to do if you are
            holding a provider&apos;s report — this panel simply cannot tell you whether
            the gate is currently open. Retry the read above.
          </p>
        </NoticeBox>
      ) : blocker ? (
        <NoticeBox
          tone="stop"
          icon={<ShieldAlert className="h-5 w-5" />}
          title={
            blocker.rule === "national_dnd_scrub_expired"
              ? "The scrub on file has expired — this campaign is held"
              : "No scrub on file — this campaign is held"
          }
        >
          {/* The SERVER's own sentence, which already names the remedy. Not re-worded
              here: the launch preview, the dispatch tick and this screen must say the
              same thing to the client and to the operator. */}
          <p className="mt-1 text-xs opacity-90">{blocker.reason}</p>
        </NoticeBox>
      ) : (
        <NoticeBox
          tone="ok"
          icon={<CheckCircle2 className="h-5 w-5" />}
          title="The preference-register gate is open for this campaign"
        >
          <p className="mt-1 text-xs opacity-90">
            A current scrub is on file. It stops being current at midnight IST, and the
            campaign keeps dialling past midnight — so a run recorded today does not
            cover tomorrow&apos;s dialling.{" "}
            {check.data.ready
              ? "Nothing else is holding this campaign either."
              : "Other launch blockers remain; they are on the client's own campaign screen."}
          </p>
        </NoticeBox>
      )}

      <ScrubForm campaign={campaign} record={record} write={write} />
      {record.error != null && <ProblemNotice error={record.error} />}
      {record.data && <Recorded result={record.data} />}
    </div>
  );
}

/** What the recording did — counts, and whether the gate is now satisfied. */
function Recorded({ result }: { result: PreferenceScrubOut }) {
  return (
    <NoticeBox
      tone={result.is_current ? "ok" : "warn"}
      icon={
        result.is_current ? (
          <CheckCircle2 className="h-5 w-5" />
        ) : (
          <AlertTriangle className="h-5 w-5" />
        )
      }
      title={
        result.is_current
          ? "Recorded — this campaign may launch"
          : "Recorded, but it does NOT open the gate"
      }
    >
      <p className="mt-1 text-xs opacity-90">
        {/* A REPLAY IS NOT A FAILURE AND IS NOT A SECOND RUN. `recorded: false` means this
            provider and reference were already on file: the numbers are re-applied either
            way, and nothing new was written. Rendering it as either extreme is the defect
            — one sends the operator to record it again by another route, the other has
            them believe they filed a second piece of evidence. */}
        {result.recorded
          ? "This run is now on file."
          : "That provider and reference were already on file, so nothing new was written — the suppression was re-applied to be sure."}{" "}
        {result.is_current ? (
          <>
            Valid until <span className="font-medium">{formatIST(result.expires_at)}</span> —
            midnight IST. The campaign keeps dialling past that moment, so a run recorded
            today does not cover tomorrow&apos;s dialling, and the dispatch tick will hold
            it again in the morning.
          </>
        ) : (
          <>
            It was run on <span className="font-medium">{formatIST(result.scrubbed_at)}</span>{" "}
            and expired at <span className="font-medium">{formatIST(result.expires_at)}</span>
            . It is kept as the historical record it is, and the campaign stays held: ask
            the provider for a scrub run TODAY and record that one.
          </>
        )}
      </p>
      <dl className="mt-2 grid gap-2 sm:grid-cols-4">
        {/* `submitted` is the SERVER's count of contacts pending when the run was
            recorded — never a figure typed off the provider's report, which is the one
            number that could disagree with the list about to dial. */}
        <Count label="On the list" value={result.submitted} />
        <Count label="Suppressed" value={result.suppressed} />
        <Count label="Not on this list" value={result.unmatched} />
        <Count label="Unreadable" value={result.malformed} />
      </dl>
      {result.malformed > 0 && (
        <p className="mt-2 text-xs opacity-90">
          {formatWholeCount(String(result.malformed))} of the numbers you pasted could not be read
          as phone numbers, so they suppressed nothing. Check the report for a header row
          or a truncated column, and record the remainder under a second reference.
        </p>
      )}
      {result.unmatched > 0 && (
        <p className="mt-2 text-xs opacity-90">
          {formatWholeCount(String(result.unmatched))} were readable but are not pending on this
          campaign — they may have been dialled already, or belong to a different list.
          That is ordinary; it is shown so the totals add up.
        </p>
      )}
    </NoticeBox>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-xs">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="mt-0.5 font-semibold tabular-nums text-ink">
        {formatWholeCount(String(value))}
      </dd>
    </div>
  );
}

const EMPTY_DRAFT: ScrubDraft = {
  provider: "",
  scrubRef: "",
  scrubbedAtInput: "",
  blockedNumbers: "",
};

function ScrubForm({
  campaign,
  record,
  write,
}: {
  campaign: CampaignSummary;
  record: ReturnType<typeof useRecordPreferenceScrub>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [draft, setDraft] = useState<ScrubDraft>(() => ({
    ...EMPTY_DRAFT,
    // Prefilled to NOW in IST, because the overwhelmingly common case is an operator
    // recording a run they have just had done — and a wrong default here is visible and
    // editable, unlike an empty field that gets filled in a hurry with a UTC time.
    scrubbedAtInput: formatISTInput(new Date().toISOString()),
  }));
  const [confirmation, setConfirmation] = useState("");

  const set = <K extends keyof ScrubDraft>(key: K, value: ScrubDraft[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    record.reset();
  };

  const instant = istInputToInstant(draft.scrubbedAtInput);
  const blocked = scrubBlockReason(draft, instant);
  const pasted = splitBlockedNumbers(draft.blockedNumbers);
  // The confirmation is the reference itself — see the module header for why it is not a
  // fixed word. `confirmMatches` is the console's one comparison, so this control and the
  // ops switches cannot drift on whitespace or case.
  const confirmed = confirmMatches(confirmation, draft.scrubRef.trim());

  return (
    <Card title={`Record a scrub of “${campaign.name}”`}>
      <p className="-mt-2 text-xs text-ink-muted">
        Record what the provider already did. This does not run a scrub and does not
        contact anybody — it files their verdict, suppresses the numbers they blocked, and
        opens this campaign&apos;s launch gate until midnight IST. The record cannot be
        edited or removed afterwards.
      </p>

      <form
        className="mt-4 space-y-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (blocked || !confirmed || instant === null) return;
          record.mutate({ draft, instant });
        }}
      >
        <RestrictionNote reason={write.reason} />

        <div>
          <label htmlFor="scrub-provider" className={FIELD_LABEL}>
            Access provider
          </label>
          <div className="mt-1">
            <input
              id="scrub-provider"
              type="text"
              maxLength={80}
              value={draft.provider}
              disabled={!write.allowed}
              onChange={(e) => set("provider", e.target.value)}
              aria-describedby="scrub-provider-hint"
              className={FIELD}
            />
          </div>
          <span id="scrub-provider-hint" className={FIELD_HINT}>
            Whose DLT platform ran it — the name you would quote back to them.
          </span>
        </div>

        <div>
          <label htmlFor="scrub-ref" className={FIELD_LABEL}>
            Their reference for this run
          </label>
          <div className="mt-1">
            <input
              id="scrub-ref"
              type="text"
              maxLength={120}
              value={draft.scrubRef}
              disabled={!write.allowed}
              onChange={(e) => {
                set("scrubRef", e.target.value);
                // The confirmation names THIS reference, so changing the reference
                // invalidates it. Leaving it matched would let a corrected reference be
                // filed under a confirmation typed for the wrong one.
                setConfirmation("");
              }}
              aria-describedby="scrub-ref-hint"
              className={FIELD}
            />
          </div>
          <span id="scrub-ref-hint" className={FIELD_HINT}>
            The handle that makes this record checkable against their portal a year from
            now. Recording the same provider and reference twice files nothing new.
          </span>
        </div>

        <div>
          <label htmlFor="scrub-at" className={FIELD_LABEL}>
            When the provider ran it (IST)
          </label>
          <div className="mt-1">
            <input
              id="scrub-at"
              type="datetime-local"
              value={draft.scrubbedAtInput}
              disabled={!write.allowed}
              onChange={(e) => set("scrubbedAtInput", e.target.value)}
              aria-describedby="scrub-at-hint"
              className={FIELD}
            />
          </div>
          <span id="scrub-at-hint" className={FIELD_HINT}>
            As their report states it, in Indian time — this field is IST, not your
            machine&apos;s clock. The validity window ends at midnight IST on THIS date,
            so recording yesterday&apos;s run does not open the gate today.
          </span>
        </div>

        <div>
          <label htmlFor="scrub-blocked" className={FIELD_LABEL}>
            Numbers the register SUPPRESSED
          </label>
          <div className="mt-1">
            <textarea
              id="scrub-blocked"
              rows={5}
              value={draft.blockedNumbers}
              disabled={!write.allowed}
              onChange={(e) => set("blockedNumbers", e.target.value)}
              aria-describedby="scrub-blocked-hint"
              className={FIELD}
            />
          </div>
          <span id="scrub-blocked-hint" className={FIELD_HINT}>
            {/* THE MOST EXPENSIVE PASTE ON THIS SCREEN. A DLT portal hands back two files
                — the blocked and the survivors — and pasting the survivors here would
                suppress everybody the scrub cleared. The label and this hint both say
                which one, because by the time the counts come back it is done. */}
            Paste the BLOCKED list — the numbers to take out of this campaign, not the
            ones that survived. One per line or comma-separated;{" "}
            {formatWholeCount(String(pasted.length))} read so far, up to{" "}
            {formatWholeCount(String(MAX_BLOCKED_NUMBERS))}. A clean scrub that blocked nobody is
            a legitimate run: leave this empty.
          </span>
        </div>

        <TypeToConfirm
          id="scrub-confirm"
          word={draft.scrubRef.trim()}
          value={confirmation}
          onChange={setConfirmation}
          disabled={!write.allowed || draft.scrubRef.trim() === ""}
          hint={
            <>
              Type the provider&apos;s reference again. It is the one field a typo makes
              unrecoverable — <MonoValue>preference_scrub_runs</MonoValue> is append-only,
              so a run filed under the wrong reference stays filed.
            </>
          }
        />

        {blocked && (
          <NoticeBox tone="warn" icon={<AlertTriangle className="h-5 w-5" />}>
            <p className="text-xs">{blocked}</p>
          </NoticeBox>
        )}

        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={!write.allowed || blocked !== null || !confirmed || record.isPending}
        >
          {record.isPending ? "Recording…" : "Record this scrub"}
        </button>
      </form>
    </Card>
  );
}
