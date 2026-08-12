"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  RestrictionNote,
  StatTile,
  formatIST,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  consentCollectedAt,
  parseContactCsv,
  useAddContacts,
  useCampaignNumbers,
  useCampaignProgress,
  useCampaigns,
  useCreateCampaign,
  useDeclareConsentProvenance,
  useDltTemplates,
  useLaunchCampaign,
  useLaunchCheck,
  usePauseCampaign,
  type CampaignSummary,
  type Classification,
  type ConsentSource,
} from "@/lib/api/campaigns";
import { FIRST_CAMPAIGN_BLOCKERS } from "@/lib/api/firstCampaign";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useAgents } from "@/lib/api/kb";

/**
 * Outbound campaigns (FLOWS §5, SURFACES §2b).
 *
 * The screen is built around one rule: **the launch button is disabled with its
 * reasons on screen, not after a click.** The API's `/launch-check` returns named
 * blockers precisely so this page can list them as a to-do; a generic "launch failed"
 * toast would send the client to support instead of to the fix. Every blocker below
 * is a real TRAI/DLT requirement, so the copy explains rather than apologises.
 *
 * The client never sees a bypass, because there isn't one: `POST /launch` re-runs the
 * identical gate server-side (hard rule 5).
 */

/**
 * A blocker in the client's words, plus WHOSE desk it lands on.
 *
 * `owner` exists because the DLT blockers are the first ones on this screen that the
 * client cannot act on at all. "Your DLT Principal Entity registration is not active"
 * reads like a to-do, so a client who is told only that will go looking for a setting
 * they do not have, then call support to be told we were already handling it. Naming
 * the desk turns a dead end into a wait with someone to ask.
 */
type BlockerNote = { text: string; owner?: "calevate" | "client" };

const BLOCKER_COPY: Record<string, BlockerNote> = {
  status: { text: "This campaign has already been launched." },
  agent_not_live: { text: "Your agent has to be published before it can make calls." },
  disclosure_missing: {
    text: "The agent needs its AI disclosure line — required on every call.",
  },
  dlt_template_missing: { text: "Attach the DLT voice template this campaign speaks under." },
  dlt_template_not_approved: { text: "The DLT template is still with the registrar." },
  dlt_template_mismatch: { text: "The template's category doesn't match this campaign's." },
  number_missing: { text: "Choose the number these calls will come from." },
  number_series_mismatch: {
    text: "Promotional calls need a 140 number; service calls need 160.",
  },
  no_contacts: { text: "Upload the contact list." },

  // The DLT entity registrations (SEC-COMP §3). Three separate registrations, none
  // implying another, and all three are OUR paperwork — an operator records them in
  // the admin console. The copy says the same thing the badge does, because a badge
  // alone is easy to miss and this is the difference between waiting and hunting.
  pe_registration_missing: {
    text:
      "Your business isn't registered with DLT yet — that's the government register every " +
      "business must be on before an automated call can go out in its name. We do this " +
      "registration for you; ask your account manager where it's up to. Calls coming IN are " +
      "unaffected and keep working.",
    owner: "calevate",
  },
  pe_registration_not_active: {
    text:
      "Your business's DLT registration isn't active — it's either still with the registrar " +
      "or it has lapsed. Only an active registration may place campaign calls. We chase this " +
      "with the registrar; your account manager can tell you where it stands. Calls coming IN " +
      "are unaffected.",
    owner: "calevate",
  },
  tm_link_not_active: {
    text:
      "Your DLT registration hasn't authorised Calevate to call on your behalf yet. It's a " +
      "one-time link between your business and us on the register, and we set it up — your " +
      "account manager will confirm when it's live.",
    owner: "calevate",
  },

  // Provenance — the one blocker on this list only the client can clear, because only
  // the client knows the answer. Both point at the form rendered directly below them.
  consent_provenance_missing: {
    text:
      "Tell us where this list came from and when these people agreed to be called. " +
      "Only you can answer that, and a list we can't trace to a consent can't be dialled. " +
      "Record it below and this clears straight away.",
    owner: "client",
  },
  consent_source_refused: {
    text:
      "This list is recorded as bought or rented. Calevate doesn't dial purchased lists — " +
      "nobody on them agreed to hear from you, so there's no consent behind the call. This " +
      "campaign can't launch. If that answer was a mistake, correct it below; otherwise build " +
      "the list from your own customers and enquiries.",
    owner: "client",
  },
};

/**
 * The same two rules again, sized for a LIST ROW rather than a launch panel.
 *
 * Two separate entries, never one "needs attention" — the values mean different things
 * and end differently, and the list is where a client decides what to open next:
 *
 *  - `consent_provenance_missing` is a question with an answer. The row is one click
 *    from the form that clears it, and nothing about the campaign is wrong yet.
 *  - `consent_source_refused` is a decision. The list is bought or rented, Calevate
 *    will not dial it, and no amount of opening the campaign changes that — the only
 *    thing behind the click is correcting a mis-answer, so that is what the link says.
 *    Sending a client to "fix" it would be a lie; letting them think the first message
 *    applies would waste a trip.
 *
 * Keyed by the API's own rule names so the list, `/launch-check` and the panel below
 * are all describing one fact. The names themselves stay out of the DOM.
 */
const LIST_PROVENANCE_COPY: Record<
  NonNullable<CampaignSummary["consent_provenance_blocker"]>,
  { badge: string; badgeClass: string; text: string; action: string }
> = {
  consent_provenance_missing: {
    badge: "Needs one answer",
    badgeClass:
      "border-amber-300 text-amber-700 dark:border-amber-700/60 dark:text-amber-400",
    text:
      "This campaign can't go out until you say where the list came from and when those " +
      "people agreed to be called. Your contacts stay as they are.",
    action: "Answer it",
  },
  consent_source_refused: {
    badge: "Can't be launched",
    badgeClass: "border-rose-300 text-rose-700 dark:border-rose-800 dark:text-rose-400",
    text:
      "This list is recorded as bought or rented, and Calevate doesn't dial purchased " +
      "lists — nobody on them agreed to hear from you. The campaign stays here but can't " +
      "be launched.",
    action: "If that was a mistake, correct it",
  },
};

const OWNER_BADGE: Record<NonNullable<BlockerNote["owner"]>, string> = {
  calevate: "We handle this",
  client: "You can fix this",
};

/**
 * The one blocker that is not this client's list at all.
 *
 * `tm_registration_missing` means CALEVATE's own telemarketer registration is not live.
 * It is platform-wide: every tenant's campaign is refused at the same instant, for a
 * reason no business can act on, cannot escalate to their account manager as their
 * case, and will not clear by doing anything on this screen. It is our outage.
 *
 * It is DELIBERATELY absent from `BLOCKER_COPY` above, and that absence is the
 * mechanism: the list below renders one `<li>` per entry in that map, so a future edit
 * cannot accidentally turn this into a bullet in a to-do list beside "upload your
 * contacts". The page pulls it out of the blocker list before rendering and gives it
 * its own notice — a different shape, no owner badge, no position in the count.
 *
 * "We handle this" would be the wrong badge too: the PE blockers that carry it are a
 * queue an account manager can report progress on. This one is not paperwork with a
 * desk attached — it is the product being unable to make outbound calls at all.
 */
const PLATFORM_BLOCKER = "tm_registration_missing";

/**
 * The two blockers that have a whole screen behind them.
 *
 * They are deliberately NOT in `BLOCKER_COPY`. `compliance.service.kyc_blocker` returns
 * a reason that already names the state the record is in — "nothing on file" and
 * "submitted / in review / rejected / expired" send the client to different places, and
 * the API interpolates the status precisely so the difference survives. Writing copy
 * keyed on the rule name alone would flatten the two back into one sentence and lose
 * the part that decides what to do next, so the server's reason is what renders.
 *
 * What was missing is not words, it is a destination: the reason explains the refusal
 * and then leaves the client on a campaign screen with nothing to press. This adds the
 * link, and nothing else.
 */
const KYC_BLOCKERS = ["kyc_missing", "kyc_not_verified"];

/**
 * The first-campaign hold — same treatment, same reasoning, one screen behind it.
 *
 * `FIRST_CAMPAIGN_BLOCKERS` is the API's own pair of rule names, imported rather than
 * retyped. Like the KYC pair above, they are deliberately absent from `BLOCKER_COPY`:
 * `first_campaign_hold_blocker` returns a reason that already distinguishes "nobody has
 * looked yet" from "a reviewer looked and said no", and the second interpolates the
 * reviewer's own words. Rule-keyed copy would flatten the two into one sentence and
 * throw away the half that decides whether the client waits or acts.
 *
 * What is added is the destination and ONE fact the server's reason cannot carry in a
 * bullet: this hold is on the account, so it is not a step every campaign will repeat.
 * A client who believes otherwise stops building campaigns, which is the outcome the
 * whole mitigation is trying not to cause.
 */
const FIRST_CAMPAIGN_REVIEW_LABEL = "Why your first campaign is being reviewed";

function PlatformOutageNotice({ reason }: { reason: string }) {
  return (
    <div
      role="status"
      className="rounded-lg border border-slate-300 bg-slate-100 p-3 text-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <p className="font-medium text-slate-900 dark:text-slate-100">
        Outbound calling is paused across Calevate — nothing for you to do here.
      </p>
      <p className="mt-1 text-slate-700 dark:text-slate-300">
        Our own telemarketer registration with the DLT registrar is not live at the
        moment, so no campaign on Calevate can launch — not just yours. This is on us
        and there is no setting on your side that changes it. We are on it, and this
        campaign will be launchable again the moment it is restored. Calls coming IN are
        unaffected and keep being answered.
      </p>
      {/* The server's own sentence, kept but demoted: it is the precise reason support
          and the audit trail will quote, and it should not be the headline a business
          owner reads first. */}
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{reason}</p>
    </div>
  );
}

/**
 * The five answers, in the client's language.
 *
 * `purchased_list` sits in this list at the same size, in the same order it appears in
 * the API's enum, with the same plain description as the other four and NO warning
 * attached. That is deliberate, and it is the whole reason the option exists: the
 * policy is that a purchased list is refused IN WRITING, and a refusal can only be
 * written against an answer somebody actually gave. Labelling it "not allowed" here,
 * greying it out, or hiding it behind a disclosure would not stop anyone dialling a
 * bought list — it would only teach them to pick the nearest acceptable-sounding
 * neighbour ("existing customers"), which loses the refusal AND corrupts the record we
 * would need if a complaint ever landed. So the form asks a neutral question, and the
 * consequence arrives from the server, by name, rendered as its own blocker above.
 */
const CONSENT_SOURCES: { value: ConsentSource; label: string; hint: string }[] = [
  {
    value: "existing_customer",
    label: "Our existing customers",
    hint: "People who have bought from us or hold an account with us.",
  },
  {
    value: "inbound_enquiry",
    label: "People who contacted us",
    hint: "Enquiries by phone, message or walk-in that we're following up.",
  },
  {
    value: "web_form_optin",
    label: "Signed up on our website",
    hint: "Filled in a form online and agreed to be contacted.",
  },
  {
    value: "offline_form_optin",
    label: "Signed up on paper",
    hint: "A form, register or slip filled in at our shop, office or an event.",
  },
  {
    value: "purchased_list",
    label: "Bought or rented list",
    hint: "Contacts supplied by a data vendor, broker or another business.",
  },
];

/**
 * Today, in the browser's own timezone, as a `<input type="date">` value.
 *
 * `toISOString().slice(0,10)` alone is a day early for half of every IST evening. Used
 * only as the picker's `max` — a soft affordance, not validation. The server is the
 * authority on "not in the future" and its refusal renders through ProblemNotice; this
 * just stops the calendar offering next month as if it were a sensible answer.
 */
function todayInputValue(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

const CLASSIFICATIONS: { value: Classification; label: string; hint: string }[] = [
  { value: "promotional", label: "Promotional", hint: "Offers and marketing — dials from a 140 number" },
  { value: "service", label: "Service", hint: "Updates to existing customers — 160 or standard" },
  { value: "transactional", label: "Transactional", hint: "Order and appointment updates — 160 or standard" },
];

export default function CampaignsPage() {
  const session = useClientSession();
  // In-realm links must carry the D-22 view-as marker; `href()` is the one place that
  // rule lives.
  const { href } = useClientRealm();
  const agents = useAgents(session);

  const numbers = useCampaignNumbers(session);
  const templates = useDltTemplates(session);
  const campaigns = useCampaigns(session);

  const [campaignId, setCampaignId] = useState<string | null>(null);
  const [agentId, setAgentId] = useState("");
  const [name, setName] = useState("");
  const [classification, setClassification] = useState<Classification>("service");
  const [concurrency, setConcurrency] = useState(3);
  const [numberId, setNumberId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [csv, setCsv] = useState("");
  // Asked at creation, not deferred to the launch check: the client is holding the
  // list in their hand at this moment, which is the only moment they can answer
  // cheaply. Empty string, never a default source — there is no sensible default for
  // "where did these five thousand numbers come from", and a pre-selected one would
  // put an assertion nobody made into an audited record.
  const [consentSource, setConsentSource] = useState<ConsentSource | "">("");
  const [consentDate, setConsentDate] = useState("");
  // Off by default, and "off" means null — not 09:00-21:00 echoed back. The platform
  // window is enforced by the per-dial compliance gate whether or not a campaign
  // carries one of its own, so sending it as a campaign setting would misrepresent
  // a legal bound as something this form chose.
  const [restrictHours, setRestrictHours] = useState(false);
  const [windowStart, setWindowStart] = useState("10:00");
  const [windowEnd, setWindowEnd] = useState("18:00");

  /**
   * D-22 read-only, applied to the controls rather than discovered on click. All four
   * mutating steps on this screen — create, add contacts, launch, pause/resume — are
   * `leads:dispatch` (campaigns/routes.py), which is a MUTATING permission: `staff`
   * does not hold it, and an impersonating operator is refused it however senior they
   * are. The note is rendered once at the top rather than four times, because the
   * reason is the same one every time and the four controls are never all on screen
   * together. The server still refuses; every ProblemNotice below stays.
   */
  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");

  const create = useCreateCampaign(session);
  const addContacts = useAddContacts(session, campaignId);
  const check = useLaunchCheck(session, campaignId);
  const launch = useLaunchCampaign(session, campaignId);
  const progress = useCampaignProgress(session, campaignId);
  const setStatus = usePauseCampaign(session, campaignId);

  const parsed = useMemo(() => parseContactCsv(csv), [csv]);
  // Both or neither, decided here so the two halves cannot be sent apart: the API
  // takes provenance as one nested object and refuses a half-filled one.
  const consentIso = consentCollectedAt(consentDate);
  const provenanceAnswered = Boolean(consentSource) && consentIso !== null;
  // Which of the two provenance blockers is on this campaign, if either — the answer
  // form is the same either way, but the question it asks is not ("record" vs
  // "correct"), and neither should appear when the launch check is clean.
  // Our outage is split off from the client's list BEFORE anything is rendered, so it
  // can never be counted, bulleted or badged alongside things this business can
  // actually do. See PLATFORM_BLOCKER.
  const allBlockers = check.data?.blockers ?? [];
  const platformOutage = allBlockers.find((b) => b.rule === PLATFORM_BLOCKER);
  const clientBlockers = allBlockers.filter((b) => b.rule !== PLATFORM_BLOCKER);
  const provenanceBlocker = clientBlockers.find(
    (b) => b.rule === "consent_provenance_missing" || b.rule === "consent_source_refused",
  )?.rule;
  const blockedOnKyc = clientBlockers.some((b) => KYC_BLOCKERS.includes(b.rule));
  const blockedOnFirstCampaign = clientBlockers.some((b) =>
    FIRST_CAMPAIGN_BLOCKERS.includes(b.rule),
  );
  // Which agent dials decides the script, the voice and the disclosure line. A
  // silent `agents[0]` picks one for a client who has more than one — including
  // an inbound-only receptionist that cannot dial at all — so the choice is on
  // screen whenever there IS a choice, defaulted to the first.
  const agentOptions = agents.data ?? [];
  const selectedAgentId = agentId || agentOptions[0]?.id || "";
  // Null, not "draft", until the server says: defaulting to draft renders the
  // contact-upload and launch cards over a campaign that is already running.
  const status = progress.data?.status ?? null;
  const counts = progress.data?.contacts ?? {};

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Campaigns</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Call a list of people. Calls go out between 9am and 9pm, numbers on the
          do-not-call list are never dialled, and anyone who doesn&apos;t answer is
          tried again later.
        </p>
      </div>

      <RestrictionNote reason={write.reason} />

      {campaigns.error && (
        <ProblemNotice error={campaigns.error} onRetry={() => campaigns.refetch()} />
      )}
      {progress.error && <ProblemNotice error={progress.error} onRetry={() => progress.refetch()} />}
      {addContacts.error && <ProblemNotice error={addContacts.error} />}
      {launch.error && <ProblemNotice error={launch.error} />}
      {setStatus.error && <ProblemNotice error={setStatus.error} />}

      {!campaignId && (campaigns.data?.length ?? 0) > 0 && (
        <Card title="Your campaigns">
          {/* SYMPTOM this fixed: a draft built before the provenance rule existed is
              now blocked, and nothing on the landing view said so — the client saw a
              normal-looking draft, opened it, and met a refusal with no hint it was
              answerable. This used to be one general notice above the list, because the
              summary carried no consent field and the list genuinely could not tell
              WHICH drafts were affected. It can now: `consent_provenance_blocker` names
              the exact rule per row, so the warning moved onto the rows it is about and
              the rows it is not about say nothing. */}
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {(campaigns.data ?? []).map((campaign) => {
              const blocker = campaign.consent_provenance_blocker ?? null;
              const note = blocker ? LIST_PROVENANCE_COPY[blocker] : null;
              return (
                <li key={campaign.id} className="py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setCampaignId(campaign.id)}
                      className="text-sm font-medium text-slate-800 underline-offset-2 hover:underline dark:text-slate-200"
                    >
                      {campaign.name}
                    </button>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {campaign.status}
                    </span>
                    <span className="text-xs text-slate-500">{campaign.classification}</span>
                    {/* The badge is the rule in the client's words. The enum name itself
                        is never rendered — it is the launch gate's vocabulary, not a
                        sentence anyone reading this list can act on. */}
                    {note && (
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${note.badgeClass}`}
                      >
                        {note.badge}
                      </span>
                    )}
                    <span className="ml-auto text-xs text-slate-500">
                      {campaign.connected}/{campaign.contacts} reached ·{" "}
                      {campaign.launched_at ? formatIST(campaign.launched_at) : "not launched"}
                    </span>
                  </div>
                  {note && (
                    <p className="mt-1 max-w-2xl text-xs text-slate-600 dark:text-slate-400">
                      {note.text}{" "}
                      <button
                        type="button"
                        onClick={() => setCampaignId(campaign.id)}
                        className="font-medium underline underline-offset-2"
                      >
                        {note.action}
                      </button>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      {!campaignId ? (
        <Card title="New campaign">
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (!selectedAgentId) return;
              create.mutate(
                {
                  agent_id: selectedAgentId,
                  name,
                  classification,
                  concurrency,
                  number_id: numberId || null,
                  dlt_template_id: templateId || null,
                  calling_hours: restrictHours
                    ? { start: windowStart, end: windowEnd }
                    : null,
                  consent_provenance:
                    consentSource && consentIso
                      ? { source: consentSource, collected_at: consentIso }
                      : null,
                },
                { onSuccess: (data) => setCampaignId(data.id) },
              );
            }}
          >
            <label className="block">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-300">Name</span>
              <input
                required
                minLength={2}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Diwali service reminder"
                className="mt-1 w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </label>

            {/* Only when there is something to choose: one agent needs no question. */}
            {agentOptions.length > 1 && (
              <label className="block max-w-sm">
                <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  Which agent makes these calls
                </span>
                <select
                  value={selectedAgentId}
                  onChange={(e) => setAgentId(e.target.value)}
                  className="mt-1 w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                >
                  {agentOptions.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-xs text-slate-500">
                  Its script and voice are what your customers will hear.
                </span>
              </label>
            )}

            <fieldset>
              <legend className="text-xs font-medium text-slate-600 dark:text-slate-300">
                What kind of calls are these?
              </legend>
              {/* Not a cosmetic choice: the category decides which number series may
                  dial (DATA-MODEL §6), so it is asked in plain language up front
                  rather than discovered as a launch blocker. */}
              <div className="mt-1 grid gap-2 sm:grid-cols-3">
                {CLASSIFICATIONS.map((option) => (
                  <label
                    key={option.value}
                    className={
                      classification === option.value
                        ? "cursor-pointer rounded-lg border-2 border-slate-900 p-3 dark:border-slate-100"
                        : "cursor-pointer rounded-lg border border-slate-200 p-3 hover:border-slate-400 dark:border-slate-700"
                    }
                  >
                    <input
                      type="radio"
                      name="classification"
                      className="sr-only"
                      checked={classification === option.value}
                      onChange={() => setClassification(option.value)}
                    />
                    <span className="block text-sm font-medium text-slate-800 dark:text-slate-200">
                      {option.label}
                    </span>
                    <span className="mt-0.5 block text-xs text-slate-500">{option.hint}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  Calling from
                </span>
                <select
                  value={numberId}
                  onChange={(e) => setNumberId(e.target.value)}
                  className="mt-1 w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                >
                  <option value="">Choose a number…</option>
                  {(numbers.data ?? []).map((number) => (
                    <option key={number.id} value={number.id}>
                      {number.e164} ({number.series} series)
                    </option>
                  ))}
                </select>
                {numbers.data?.length === 0 && (
                  <span className="mt-1 block text-xs text-slate-500">
                    No numbers yet — your account manager sets these up.
                  </span>
                )}
              </label>

              <label className="block">
                <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  DLT template
                </span>
                <select
                  value={templateId}
                  onChange={(e) => setTemplateId(e.target.value)}
                  className="mt-1 w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                >
                  <option value="">Choose a template…</option>
                  {(templates.data ?? []).map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.classification} —{" "}
                      {template.status === "approved" ? "approved" : template.status}
                    </option>
                  ))}
                </select>
                {templates.data?.length === 0 && (
                  <span className="mt-1 block text-xs text-slate-500">
                    None registered yet. Calls can&apos;t go out without one.
                  </span>
                )}
              </label>
            </div>

            <label className="block max-w-xs">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                Calls at the same time
              </span>
              <input
                type="number"
                min={1}
                max={10}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
              <span className="mt-1 block text-xs text-slate-500">
                Lower means the list takes longer. Lines are always kept free for people
                calling you.
              </span>
            </label>

            {/* The calling window NARROWS a bound that already exists; it does not set
                one. 9am-9pm is TRAI law applied to every dial (hard rule 5), so the
                caption says "never … before 9am or after 9pm" first and offers the
                narrowing second. Copy that read "choose your calling hours" would
                imply the client is picking the outer limit, and the first client who
                typed 08:00 would learn otherwise from a server rejection instead of
                from the form. */}
            <fieldset>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={restrictHours}
                  onChange={(e) => setRestrictHours(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 dark:border-slate-600"
                />
                <span className="text-sm text-slate-700 dark:text-slate-300">
                  Only call during specific hours
                </span>
              </label>
              <p className="mt-1 text-xs text-slate-500">
                Calls never go out before 9am or after 9pm — this narrows that further.
              </p>

              {restrictHours && (
                <div className="mt-2 grid max-w-xs gap-3 sm:grid-cols-2">
                  <label className="block">
                    <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                      From
                    </span>
                    <input
                      type="time"
                      required
                      value={windowStart}
                      onChange={(e) => setWindowStart(e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                      Until
                    </span>
                    <input
                      type="time"
                      required
                      value={windowEnd}
                      onChange={(e) => setWindowEnd(e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                    />
                  </label>
                </div>
              )}
            </fieldset>

            {/* Consent provenance (SEC-COMP §3) — a compliance artefact, not a form
                field: the client is stating on the record where this list came from,
                and the statement is what a complaint would later be answered with.
                Required to submit, because a campaign created without it is a campaign
                that cannot launch, and finding that out at the launch check — after the
                list is uploaded — is a worse place to learn it. */}
            <ConsentProvenanceFields
              idPrefix="new"
              source={consentSource}
              collectedAt={consentDate}
              onSource={setConsentSource}
              onCollectedAt={setConsentDate}
            />

            {/* Kept next to the button that causes it: a window the server refuses
                (too wide, or start after end) comes back as a problem+json with copy
                that explains the law, and ProblemNotice already renders it. Repeating
                that rule as client-side validation would let the two drift. */}
            {create.error && <ProblemNotice error={create.error} />}

            <button
              type="submit"
              disabled={
                !write.allowed ||
                create.isPending ||
                !selectedAgentId ||
                name.length < 2 ||
                !provenanceAnswered
              }
              className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              {create.isPending ? "Creating…" : "Create campaign"}
            </button>
            {/* A dead button needs a reason next to it — including this one, which is
                dead until the provenance question is answered. */}
            {!provenanceAnswered && (
              <p className="text-xs text-slate-500">
                Answer both questions about your list above — a campaign without them
                can&apos;t be launched.
              </p>
            )}
            {!agents.isLoading && agentOptions.length === 0 && (
              <p className="text-xs text-slate-500">
                No agent is set up yet — your account manager builds one before
                campaigns can run.
              </p>
            )}
          </form>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <StatTile label="Status" value={status?.replace(/_/g, " ")} />
            <StatTile label="Contacts" value={progress.data?.total ?? parsed.length} />
            <StatTile label="Connected" value={counts.connected ?? 0} hint="calls answered" />
            <StatTile
              label="Not called"
              value={counts.dnc_blocked ?? 0}
              hint="on the do-not-call list"
            />
          </div>

          {status === "draft" && (
            <Card title="Contact list">
              <div className="space-y-3">
                <textarea
                  rows={6}
                  value={csv}
                  onChange={(e) => setCsv(e.target.value)}
                  placeholder={"phone,name\n9876543210,Priya\n9876501234,Ravi"}
                  className="w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-slate-500">
                    {parsed.length > 0
                      ? `${parsed.length} rows ready. Numbers we can't read are counted and skipped — never guessed.`
                      : "Paste your CSV, or one number per line."}
                  </p>
                  <button
                    type="button"
                    disabled={!write.allowed || addContacts.isPending || parsed.length === 0}
                    onClick={() =>
                      addContacts.mutate(parsed, { onSuccess: () => setCsv("") })
                    }
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium disabled:opacity-50 dark:border-slate-600"
                  >
                    {addContacts.isPending ? "Adding…" : "Add contacts"}
                  </button>
                </div>
                {addContacts.data && (
                  <p className="rounded-md bg-slate-50 p-2 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    Added {addContacts.data.added}.{" "}
                    {addContacts.data.duplicate > 0 &&
                      `${addContacts.data.duplicate} ${
                        addContacts.data.duplicate === 1 ? "was" : "were"
                      } already on the list. `}
                    {addContacts.data.malformed > 0 &&
                      `${addContacts.data.malformed} ${
                        addContacts.data.malformed === 1 ? "number" : "numbers"
                      } couldn't be read and ${
                        addContacts.data.malformed === 1 ? "was" : "were"
                      } skipped.`}
                  </p>
                )}
              </div>
            </Card>
          )}

          {status === "draft" && (
            <Card title="Before you launch">
              {check.isLoading ? (
                <p className="text-sm text-slate-500">Checking…</p>
              ) : check.error ? (
                /* Without this the card renders an empty blocker list under a
                   dead button: "you cannot launch, and we will not say why". */
                <ProblemNotice error={check.error} onRetry={() => check.refetch()} />
              ) : check.data?.ready ? (
                <div className="space-y-3">
                  <p className="text-sm text-emerald-700 dark:text-emerald-400">
                    Everything checks out.
                  </p>
                  <button
                    type="button"
                    disabled={!write.allowed || launch.isPending}
                    onClick={() => launch.mutate()}
                    className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                  >
                    {launch.isPending ? "Launching…" : "Launch campaign"}
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  {/* Above the list, in its own shape, and never inside it. */}
                  {platformOutage && <PlatformOutageNotice reason={platformOutage.reason} />}

                  {/* A campaign blocked ONLY by our outage has an empty to-do list, and
                      an empty list under "Before you launch" reads as "we will not say
                      why". Say the true thing: your side is done. */}
                  {clientBlockers.length === 0 ? (
                    <p className="text-sm text-slate-600 dark:text-slate-400">
                      Everything on your side is ready. There is nothing else to do here.
                    </p>
                  ) : (
                  <ul className="space-y-2">
                    {clientBlockers.map((blocker) => {
                      // The server's own `reason` is the fallback, never dropped: a
                      // blocker this build has no copy for is still a blocker, and an
                      // unnamed one would read as "you cannot launch, and we will not
                      // say why" — the exact failure this card exists to prevent.
                      const note = BLOCKER_COPY[blocker.rule];
                      return (
                        <li key={blocker.rule} className="flex gap-2 text-sm">
                          <span aria-hidden className="text-amber-500">
                            ●
                          </span>
                          <span className="text-slate-700 dark:text-slate-300">
                            {note?.text ?? blocker.reason}
                            {note?.owner && (
                              <span className="ml-2 whitespace-nowrap rounded-full border border-slate-300 px-1.5 py-0.5 text-[11px] font-medium text-slate-500 dark:border-slate-700 dark:text-slate-400">
                                {OWNER_BADGE[note.owner]}
                              </span>
                            )}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                  )}

                  {/* The reason above says WHY; this says where to go. Carries the
                      view-as marker like every other in-realm link, so an operator
                      following it from a "view as client" session does not drop back
                      to a client token two pages in (lib/api/session.tsx). */}
                  {blockedOnKyc && (
                    <p className="text-sm">
                      <Link
                        href={href(`/c/${session.orgSlug}/verification`)}
                        className="font-medium text-sky-700 underline dark:text-sky-400"
                      >
                        See what we need to verify your business
                      </Link>{" "}
                      <span className="text-slate-600 dark:text-slate-400">
                        — incoming calls are unaffected while this is outstanding.
                      </span>
                    </p>
                  )}

                  {/* Same shape as the KYC link above, and for the same reason: the
                      bullet says WHY, this says where to go. The trailing sentence is
                      the one thing the server's per-campaign reason structurally cannot
                      say — the hold is on the ACCOUNT, so it is not a gate this client
                      will meet again on their next campaign. */}
                  {blockedOnFirstCampaign && (
                    <p className="text-sm">
                      <Link
                        href={href(`/c/${session.orgSlug}/campaign-review`)}
                        className="font-medium text-sky-700 underline dark:text-sky-400"
                      >
                        {FIRST_CAMPAIGN_REVIEW_LABEL}
                      </Link>{" "}
                      <span className="text-slate-600 dark:text-slate-400">
                        — it is a one-off check on your account, not on each campaign, and
                        incoming calls are unaffected.
                      </span>
                    </p>
                  )}

                  {/* The one blocker with a control attached, rendered under the
                      sentence that asks for it. `consent_source_refused` gets the form
                      too — a client who mis-answered must be able to correct the record
                      without rebuilding the campaign, and a client who answered truly
                      simply leaves it and the refusal stands. */}
                  {campaignId && provenanceBlocker && (
                    <ConsentProvenanceAnswer
                      campaignId={campaignId}
                      correcting={provenanceBlocker === "consent_source_refused"}
                    />
                  )}

                  {/* Disabled WITH the reasons above it — SURFACES §2b. A blocked
                      feature that is merely missing teaches the client nothing. */}
                  <button
                    type="button"
                    disabled
                    className="cursor-not-allowed rounded-md bg-slate-200 px-4 py-1.5 text-sm font-medium text-slate-500 dark:bg-slate-800"
                  >
                    Launch campaign
                  </button>
                </div>
              )}
            </Card>
          )}

          {launch.data && (
            <Card title="Launched">
              <p className="text-sm text-slate-700 dark:text-slate-300">
                Calling {launch.data.dialable}{" "}
                {launch.data.dialable === 1 ? "person" : "people"}.
                {launch.data.dnc_scrubbed > 0 &&
                  ` ${launch.data.dnc_scrubbed} were on the do-not-call list and won't be called.`}
              </p>
            </Card>
          )}

          {status !== null && ["running", "paused", "completed"].includes(status) && (
            <Card
              title="Progress"
              action={
                status !== "completed" ? (
                  <button
                    type="button"
                    disabled={!write.allowed || setStatus.isPending}
                    onClick={() => setStatus.mutate(status === "running" ? "pause" : "resume")}
                    className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium disabled:opacity-50 dark:border-slate-600"
                  >
                    {status === "running" ? "Pause" : "Resume"}
                  </button>
                ) : null
              }
            >
              {progress.data?.total ? (
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {Object.entries(counts).map(([key, value]) => (
                    <div key={key}>
                      <dt className="text-xs uppercase tracking-wide text-slate-500">
                        {key.replace(/_/g, " ")}
                      </dt>
                      <dd className="text-lg font-semibold tabular-nums text-slate-900 dark:text-slate-50">
                        {value}
                      </dd>
                    </div>
                  ))}
                  <div className="col-span-2 sm:col-span-4 text-xs text-slate-500">
                    Launched {formatIST(progress.data.launched_at)} · up to{" "}
                    {progress.data.concurrency} calls at a time
                  </div>
                </dl>
              ) : (
                <EmptyState title="No contacts yet" />
              )}
            </Card>
          )}

          <button
            type="button"
            onClick={() => {
              setCampaignId(null);
              setName("");
              setCsv("");
            }}
            className="text-xs text-slate-500 underline"
          >
            Start another campaign
          </button>
        </>
      )}
    </div>
  );
}

/**
 * The provenance question itself — one set of fields, two places that ask it.
 *
 * Shared rather than written twice because the two callers must ask IDENTICALLY: a
 * client answering on the create form and a client answering a blocker on a
 * five-thousand-row draft are making the same statement, and it is a statement that
 * gets audited. Two copies would drift, and the drift would show up as two different
 * records of the same declaration.
 */
function ConsentProvenanceFields({
  idPrefix,
  source,
  collectedAt,
  onSource,
  onCollectedAt,
}: {
  idPrefix: string;
  source: ConsentSource | "";
  collectedAt: string;
  onSource: (value: ConsentSource) => void;
  onCollectedAt: (value: string) => void;
}) {
  return (
    <div className="space-y-3">
      <fieldset>
        <legend className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Where did this list come from?
        </legend>
        <p className="mt-1 text-xs text-slate-500">
          You&apos;re putting this on the record: it&apos;s how we can show, later, that the
          people on this list agreed to hear from you. Pick the one that&apos;s true.
        </p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {CONSENT_SOURCES.map((option) => (
            <label
              key={option.value}
              className={
                source === option.value
                  ? "cursor-pointer rounded-lg border-2 border-slate-900 p-3 dark:border-slate-100"
                  : "cursor-pointer rounded-lg border border-slate-200 p-3 hover:border-slate-400 dark:border-slate-700"
              }
            >
              <input
                type="radio"
                name={`${idPrefix}-consent-source`}
                className="sr-only"
                checked={source === option.value}
                onChange={() => onSource(option.value)}
              />
              <span className="block text-sm font-medium text-slate-800 dark:text-slate-200">
                {option.label}
              </span>
              <span className="mt-0.5 block text-xs text-slate-500">{option.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <label className="block max-w-xs">
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
          When did they agree?
        </span>
        <input
          type="date"
          value={collectedAt}
          max={todayInputValue()}
          onChange={(e) => onCollectedAt(e.target.value)}
          className="mt-1 w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
        />
        <span className="mt-1 block text-xs text-slate-500">
          The date on the form, bill or enquiry. If the list was built up over time, use the
          day the most recent person was added.
        </span>
      </label>
    </div>
  );
}

/**
 * The answer path for a draft that is already blocked.
 *
 * SYMPTOM this fixes: a client opens a draft they built last month, the launch check
 * says "tell us where this list came from", and there is nowhere on the screen to tell
 * us — the only field that ever accepted the answer was on the create form, which is
 * behind them. Their options were to abandon the campaign or re-upload five thousand
 * rows into a new one. So the form is rendered where the blocker is read, not on a
 * different screen.
 *
 * Draft-only, matching the endpoint: this whole card only renders inside the
 * `status === "draft"` branch, and the server refuses anything else by name.
 */
function ConsentProvenanceAnswer({
  campaignId,
  correcting,
}: {
  campaignId: string;
  /** True when a refused answer is already on file — the ask is "correct it", not "answer it". */
  correcting: boolean;
}) {
  const session = useClientSession();
  const write = useWriteAccess(session, "leads:dispatch", "record where a list came from");
  const declare = useDeclareConsentProvenance(session, campaignId);
  const [source, setSource] = useState<ConsentSource | "">("");
  const [collectedAt, setCollectedAt] = useState("");

  const iso = consentCollectedAt(collectedAt);

  return (
    <form
      className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800"
      onSubmit={(e) => {
        e.preventDefault();
        if (!source || !iso) return;
        declare.mutate({ source, collected_at: iso });
      }}
    >
      <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
        {correcting ? "Correct where this list came from" : "Record where this list came from"}
      </p>
      <p className="text-xs text-slate-500">
        Your contacts stay as they are — this answers the question against this campaign.
      </p>

      <ConsentProvenanceFields
        idPrefix={`answer-${campaignId}`}
        source={source}
        collectedAt={collectedAt}
        onSource={setSource}
        onCollectedAt={setCollectedAt}
      />

      {/* Same gate as every other mutating control here, said before the click rather
          than discovered as a 403: `leads:dispatch` is a MUTATING permission, so an
          impersonating operator and a `staff` user are both refused it server-side. */}
      <RestrictionNote reason={write.reason} />
      {declare.error && <ProblemNotice error={declare.error} />}

      <button
        type="submit"
        disabled={!write.allowed || declare.isPending || !source || !iso}
        className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
      >
        {declare.isPending ? "Recording…" : "Record this"}
      </button>
      {/* No success banner: the launch check is refetched on success and the blocker
          above either disappears or is replaced by the refusal. That IS the answer,
          and it is more honest than "Saved!" over a campaign still unable to launch. */}
    </form>
  );
}

/**
 * BACKEND GAP — CLOSED. Kept as the record of what the fix was.
 *
 * `CampaignSummaryOut` (GET /v1/campaigns) used to carry `status` but nothing about
 * consent, so this screen could not say WHICH drafts were missing provenance without
 * running the full launch gate once per draft; the list showed one general notice and
 * the specific answer arrived only after opening a campaign.
 *
 * It now carries `consent_provenance_blocker` — and it landed as the NAMED RULE rather
 * than the `needs_consent_provenance` boolean this note originally asked for, which is
 * the better shape: a boolean would have merged "answer this" with "this can never
 * launch", and the list would have sent a client with a purchased list to a form that
 * cannot help them. `LIST_PROVENANCE_COPY` above keeps the two apart for exactly that
 * reason.
 *
 * Nothing left open here. The remaining per-campaign detail (which of the DLT, agent
 * and contact blockers apply) still needs `/launch-check`, and correctly so — that is
 * the whole gate, not a list column.
 */
