"use client";

import { use, useMemo, useState } from "react";

import { Card, EmptyState, ProblemNotice, StatTile, formatIST } from "@/components/ui";
import {
  parseContactCsv,
  useAddContacts,
  useCampaignNumbers,
  useCampaignProgress,
  useCampaigns,
  useCreateCampaign,
  useDltTemplates,
  useLaunchCampaign,
  useLaunchCheck,
  usePauseCampaign,
  type Classification,
} from "@/lib/api/campaigns";
import { devSession } from "@/lib/api/client";
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

const BLOCKER_COPY: Record<string, string> = {
  status: "This campaign has already been launched.",
  agent_not_live: "Your agent has to be published before it can make calls.",
  disclosure_missing: "The agent needs its AI disclosure line — required on every call.",
  dlt_template_missing: "Attach the DLT voice template this campaign speaks under.",
  dlt_template_not_approved: "The DLT template is still with the registrar.",
  dlt_template_mismatch: "The template's category doesn't match this campaign's.",
  number_missing: "Choose the number these calls will come from.",
  number_series_mismatch: "Promotional calls need a 140 number; service calls need 160.",
  no_contacts: "Upload the contact list.",
};

const CLASSIFICATIONS: { value: Classification; label: string; hint: string }[] = [
  { value: "promotional", label: "Promotional", hint: "Offers and marketing — dials from a 140 number" },
  { value: "service", label: "Service", hint: "Updates to existing customers — 160 or standard" },
  { value: "transactional", label: "Transactional", hint: "Order and appointment updates — 160 or standard" },
];

export default function CampaignsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = devSession(slug);
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
  // Off by default, and "off" means null — not 09:00-21:00 echoed back. The platform
  // window is enforced by the per-dial compliance gate whether or not a campaign
  // carries one of its own, so sending it as a campaign setting would misrepresent
  // a legal bound as something this form chose.
  const [restrictHours, setRestrictHours] = useState(false);
  const [windowStart, setWindowStart] = useState("10:00");
  const [windowEnd, setWindowEnd] = useState("18:00");

  const create = useCreateCampaign(session);
  const addContacts = useAddContacts(session, campaignId);
  const check = useLaunchCheck(session, campaignId);
  const launch = useLaunchCampaign(session, campaignId);
  const progress = useCampaignProgress(session, campaignId);
  const setStatus = usePauseCampaign(session, campaignId);

  const parsed = useMemo(() => parseContactCsv(csv), [csv]);
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

      {campaigns.error && (
        <ProblemNotice error={campaigns.error} onRetry={() => campaigns.refetch()} />
      )}
      {progress.error && <ProblemNotice error={progress.error} onRetry={() => progress.refetch()} />}
      {addContacts.error && <ProblemNotice error={addContacts.error} />}
      {launch.error && <ProblemNotice error={launch.error} />}
      {setStatus.error && <ProblemNotice error={setStatus.error} />}

      {!campaignId && (campaigns.data?.length ?? 0) > 0 && (
        <Card title="Your campaigns">
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {(campaigns.data ?? []).map((campaign) => (
              <li key={campaign.id} className="flex flex-wrap items-center gap-2 py-2.5">
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
                <span className="ml-auto text-xs text-slate-500">
                  {campaign.connected}/{campaign.contacts} reached ·{" "}
                  {campaign.launched_at ? formatIST(campaign.launched_at) : "not launched"}
                </span>
              </li>
            ))}
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

            {/* Kept next to the button that causes it: a window the server refuses
                (too wide, or start after end) comes back as a problem+json with copy
                that explains the law, and ProblemNotice already renders it. Repeating
                that rule as client-side validation would let the two drift. */}
            {create.error && <ProblemNotice error={create.error} />}

            <button
              type="submit"
              disabled={create.isPending || !selectedAgentId || name.length < 2}
              className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              {create.isPending ? "Creating…" : "Create campaign"}
            </button>
            {/* A permanently dead button needs a reason next to it. */}
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
                    disabled={addContacts.isPending || parsed.length === 0}
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
                    disabled={launch.isPending}
                    onClick={() => launch.mutate()}
                    className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                  >
                    {launch.isPending ? "Launching…" : "Launch campaign"}
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  <ul className="space-y-2">
                    {(check.data?.blockers ?? []).map((blocker) => (
                      <li key={blocker.rule} className="flex gap-2 text-sm">
                        <span aria-hidden className="text-amber-500">
                          ●
                        </span>
                        <span className="text-slate-700 dark:text-slate-300">
                          {BLOCKER_COPY[blocker.rule] ?? blocker.reason}
                        </span>
                      </li>
                    ))}
                  </ul>
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
                    disabled={setStatus.isPending}
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
