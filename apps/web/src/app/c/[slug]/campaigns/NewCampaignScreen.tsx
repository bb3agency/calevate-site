"use client";

/**
 * `/c/{slug}/campaigns/new`: A NEW CAMPAIGN ON ONE PAGE (D-992, founder 15 Nov 2026: "keep all in
 * the same page"; the four-step wizard and its why / goal / name fields were removed).
 *
 * The page has the campaign's own tabs from the start; only Set up has anything in it until
 * the campaign calls. Set up is the same four sections the campaign page continues with:
 *   1. Main task — what the campaign should achieve.
 *   2. Materials — files and links (uploaded into the knowledge at once) and notes.
 *   3. Script — who speaks it (the agent, the voice), and "Create and write the script with Pip":
 *      the draft is made, the materials attached, Pip asked; the campaign page shows Pip writing
 *      it, with Stop, then the review. Section 4 (agent and start) is on the campaign page.
 * Saving the main task alone also makes the draft (with any materials) and continues there.
 * The name is made from the main task; it can be renamed on the campaign page.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { problemToast } from "@/components/arc/feedback";
import { PageHeader } from "@/components/console/pageHeader";
import { Tabs } from "@/components/interior/tabs";
import { FIELD, PRIMARY_BUTTON, PRIMARY_BUTTON_SM, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { LANGUAGE_NAMES, isAssignable } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { useCreateCampaign } from "@/lib/api/campaigns";
import { apiRequest } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import { lookup } from "@/lib/lookup";
import { useClientRealm } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { TrialLockNotice } from "../TrialLockNotice";
import { MaterialsDraft, type PendingMaterial } from "./MaterialsDraft";
import { nameFromGoal } from "./campaignForm";

const MAIN_TASK_MIN = 10;

function Step({ n, title, hint }: { n: number; title: string; hint: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-heading text-ink">
        <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-ink text-meta font-semibold text-surface">
          {n}
        </span>
        {title}
      </h2>
      <p className="mt-1 text-meta text-ink-muted">{hint}</p>
    </div>
  );
}

/** The list name, from the main task's first line: "Help farmers install the app, 15 Nov". */
export function nameFromMainTask(task: string): string {
  const first = task.trim().split(/\n/)[0]?.replace(/\s+/g, " ") ?? "";
  const short = first.length > 60 ? `${first.slice(0, 60).replace(/\s+\S*$/, "")}…` : first;
  return nameFromGoal(short).slice(0, 120);
}

export function NewCampaignScreen({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const queryClient = useQueryClient();
  const agents = useAgents(session);
  const create = useCreateCampaign(session);
  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");

  const [mainTask, setMainTask] = useState("");
  const [materials, setMaterials] = useState<PendingMaterial[]>([]);
  const [agentId, setAgentId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [draftId, setDraftId] = useState<string | null>(null);

  const agentOptions = (agents.data ?? []).filter(isAssignable);
  const selectedAgentId = agentId || agentOptions[0]?.id || "";
  const ready = mainTask.trim().length >= MAIN_TASK_MIN && selectedAgentId !== "";
  const busy = saving || create.isPending;
  useUnsavedGuard(!saving && (mainTask.trim() !== "" || materials.length > 0));

  const detail = (id: string) => href(`/c/${slug}/campaigns/${id}`);

  /** The draft, then its materials, then (with Pip) the script; a refusal stops with the draft linked. */
  const submit = async (withPip: boolean) => {
    if (!ready || busy) return;
    setError(null);
    setSaving(true);
    let id = draftId;
    try {
      if (!id) {
        const made = await create.mutateAsync({
          agent_id: selectedAgentId,
          name: nameFromMainTask(mainTask),
          main_task: mainTask.trim(),
          classification: "service",
          concurrency: 3,
        });
        id = made.id;
        setDraftId(id);
      }
      const base = `/v1/campaigns/${encodeURIComponent(id)}`;
      for (const item of materials) {
        const body = { kind: item.kind, title: item.title, url: item.url, note: item.note, kb_upload_id: item.kb_upload_id };
        await apiRequest(session, `${base}/materials`, { method: "POST", body });
      }
      setMaterials([]);
      if (withPip) await apiRequest(session, `${base}/script/proposal`, { method: "POST" });
      void queryClient.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] });
      router.push(detail(id));
    } catch (e) {
      setSaving(false);
      setError(e);
    }
  };

  const empty = (what: string) => (
    <p className="rounded-card border border-dashed border-line p-6 text-body text-ink-muted">{what}</p>
  );

  return (
    <div className="max-w-6xl space-y-5 pb-12">
      <PageHeader back={{ href: href(`/c/${slug}/campaigns`), label: "All campaigns" }} title="New campaign" />
      <TrialLockNotice lock="campaigns" />
      <RestrictionNote reason={write.reason} />
      {agents.error && <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />}

      <Tabs
        label="New campaign"
        defaultValue="setup"
        items={[
          { value: "setup", label: "Set up" },
          { value: "calls", label: "Calls & recordings" },
          { value: "questions", label: "Questions to answer" },
          { value: "improve", label: "Improve" },
        ]}
        panelClassName="pt-5"
        renderPanel={(tab) =>
          tab === "calls" ? (
            empty("No calls yet. Each call and its recording shows here once the campaign starts calling.")
          ) : tab === "questions" ? (
            empty("Nothing yet. Questions the agent could not answer on this campaign's calls show here for you to answer.")
          ) : tab === "improve" ? (
            empty("Once the campaign calls: the best hours to call, how two opening lines compare, and a re-call of the people not reached.")
          ) : (
            <div className="max-w-4xl space-y-6">
              <section className="rounded-card border border-line border-l-4 border-l-brand bg-surface p-4 shadow-card sm:p-6">
                <Step
                  n={1}
                  title="Main task"
                  hint="What should this campaign achieve? Write it in your own words, as much as you like."
                />
                <label htmlFor="new-campaign-main-task" className="sr-only">
                  Main task
                </label>
                <textarea
                  id="new-campaign-main-task"
                  className={`${FIELD} min-h-40 w-full resize-y`}
                  value={mainTask}
                  maxLength={4000}
                  disabled={!write.allowed}
                  placeholder="For example: call farmers who registered on Rytu Khata but never opened the app, and help them add it to their home screen, step by step for Android or iPhone."
                  onChange={(e) => setMainTask(e.target.value)}
                />
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    className={PRIMARY_BUTTON_SM}
                    disabled={!write.allowed || !ready || busy}
                    title={!ready ? "Write the main task first" : (write.reason ?? undefined)}
                    onClick={() => void submit(false)}
                  >
                    {busy ? "Saving…" : "Save"}
                  </button>
                  <span className="text-meta text-ink-muted">Saves this as a draft campaign. You can edit it any time.</span>
                </div>
              </section>

              <MaterialsDraft items={materials} onChange={setMaterials} canWrite={write.allowed} />

              <section className="rounded-card border border-brand/30 bg-brand-soft p-4 sm:p-6 dark:bg-brand-strong/15">
                <Step
                  n={3}
                  title="Script"
                  hint="Pip writes the script from your main task and materials, for the agent you choose to speak it. You review it and change anything; then add who to call and start."
                />
                <p className="mb-2 text-meta font-medium text-ink">Who speaks it</p>
                {!agents.data && !agents.error && <Skeleton rows={2} label="Loading your agents" />}
                {agents.data && agentOptions.length === 0 && (
                  <p className="text-body text-ink-muted">No agent is set up yet. Create one under Agents first.</p>
                )}
                {agentOptions.length > 0 && (
                  <div role="radiogroup" aria-label="Who speaks it" className="grid gap-3 sm:grid-cols-2">
                    {agentOptions.map((agent) => {
                      const on = agent.id === selectedAgentId;
                      return (
                        <button
                          key={agent.id}
                          type="button"
                          role="radio"
                          aria-checked={on}
                          disabled={!write.allowed}
                          onClick={() => setAgentId(agent.id)}
                          className={`rounded-card border bg-surface p-4 text-left transition-colors ${
                            on ? "border-brand ring-1 ring-brand" : "border-line hover:bg-surface-muted"
                          }`}
                        >
                          <span className="block text-body font-semibold text-ink">{agent.name}</span>
                          <span className="block text-meta text-ink-muted">
                            {lookup(LANGUAGE_NAMES, agent.language_primary) ?? agent.language_primary}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
                {error != null && (
                  <p role="alert" className="mt-3 text-meta text-danger">
                    {problemToast(error, "That did not finish").description ?? "That did not finish"}
                    {draftId && (
                      <>
                        {" "}
                        <a className="underline" href={detail(draftId)}>
                          Open the draft
                        </a>
                      </>
                    )}
                  </p>
                )}
                <button
                  type="button"
                  className={`${PRIMARY_BUTTON} mt-4`}
                  disabled={!write.allowed || !ready || busy}
                  title={!ready ? "Write the main task first" : (write.reason ?? undefined)}
                  onClick={() => void submit(true)}
                >
                  {busy ? "Creating…" : "Create and write the script with Pip"}
                </button>
                {!ready && (
                  <p className="mt-2 text-meta text-ink-muted">Write the main task (a sentence or more) to continue.</p>
                )}
              </section>
            </div>
          )
        }
      />
    </div>
  );
}
