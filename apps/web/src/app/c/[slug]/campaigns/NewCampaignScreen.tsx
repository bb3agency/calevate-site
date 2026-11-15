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
 *
 * Every draft starts as Service calls held to the account's call lines; where the list came
 * from, the kind of call and the number are answered on the campaign page, and the launch
 * check refuses to start until they are.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { PageHeader } from "@/components/console/pageHeader";
import { Tabs } from "@/components/interior/tabs";
import { FIELD, PRIMARY_BUTTON_SM, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { isAssignable } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { useMyCallLines } from "@/lib/api/callLines";
import { useCreateCampaign } from "@/lib/api/campaigns";
import { apiRequest } from "@/lib/api/client";
import { uploadMaterial } from "@/lib/api/campaignWorkspace";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { TrialLockNotice } from "../TrialLockNotice";
import { MAIN_TASK_HINT, MAIN_TASK_INFO, MAIN_TASK_PLACEHOLDER, SCRIPT_HINT, SCRIPT_INFO } from "./CampaignWorkspace";
import { MaterialsDraft, type PendingMaterial } from "./MaterialsDraft";
import { AgentChoice, NoAgentYet } from "./NewCampaignSteps";
import { PipGenerateBand } from "./PipGenerateBand";
import { SectionHead } from "./SectionHead";
import { clampConcurrency, concurrencyCap, nameFromGoal } from "./campaignForm";

const MAIN_TASK_MIN = 10;
/** What a new draft asks for before the account's lines hold it. */
const DEFAULT_CONCURRENCY = 3;

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
  const callLines = useMyCallLines(session);
  const create = useCreateCampaign(session);
  useActionFeedback(create, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");

  const [mainTask, setMainTask] = useState("");
  const [materials, setMaterials] = useState<PendingMaterial[]>([]);
  const [agentId, setAgentId] = useState("");
  const [saving, setSaving] = useState(false);
  const [followUpError, setFollowUpError] = useState<unknown>(null);
  const [draftId, setDraftId] = useState<string | null>(null);

  const agentOptions = (agents.data ?? []).filter(isAssignable);
  const selectedAgentId = agentId || agentOptions[0]?.id || "";
  const selectedAgent = agentOptions.find((agent) => agent.id === selectedAgentId);
  const ready = mainTask.trim().length >= MAIN_TASK_MIN && selectedAgentId !== "";
  const busy = saving || create.isPending;
  useUnsavedGuard(!saving && (mainTask.trim() !== "" || materials.length > 0));

  const detail = (id: string) => href(`/c/${slug}/campaigns/${id}`);

  /** The draft, then its materials, then (with Pip) the script; a refusal stops with the draft linked. */
  const submit = async (withPip: boolean) => {
    if (!ready || busy) return;
    setFollowUpError(null);
    create.reset();
    setSaving(true);
    let id = draftId;
    try {
      if (!id) {
        const made = await create.mutateAsync({
          agent_id: selectedAgentId,
          name: nameFromMainTask(mainTask),
          main_task: mainTask.trim(),
          classification: "service",
          concurrency: clampConcurrency(DEFAULT_CONCURRENCY, concurrencyCap(callLines.data?.call_lines)),
        });
        id = made.id;
        setDraftId(id);
      }
    } catch {
      // The refusal is `create.error`, rendered beside the buttons.
      setSaving(false);
      return;
    }
    try {
      const base = `/v1/campaigns/${encodeURIComponent(id)}`;
      // Each item leaves the list once it is on the campaign, so pressing again after a
      // refusal sends only what is still missing.
      for (const item of materials) {
        if (item.file) {
          await uploadMaterial(session, id, item.file, item.title);
        } else {
          const body = { kind: item.kind, title: item.title, url: item.url, note: item.note, kb_upload_id: item.kb_upload_id };
          await apiRequest(session, `${base}/materials`, { method: "POST", body });
        }
        setMaterials((held) => held.filter((kept) => kept !== item));
      }
      if (withPip) await apiRequest(session, `${base}/script/proposal`, { method: "POST" });
      void queryClient.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] });
      router.push(detail(id));
    } catch (e) {
      setSaving(false);
      setFollowUpError(e);
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
            empty("No calls yet. They show here once it calls.")
          ) : tab === "questions" ? (
            empty("Questions its calls could not answer show here.")
          ) : tab === "improve" ? (
            empty("Ways to do better show here once it calls.")
          ) : (
            <div className="max-w-4xl space-y-6">
              <section
                aria-labelledby="new-campaign-main-task-head"
                className="rounded-card border border-line border-l-4 border-l-brand bg-surface p-4 shadow-card sm:p-6"
              >
                <SectionHead
                  id="new-campaign-main-task-head"
                  step={1}
                  title="Main task"
                  hint={MAIN_TASK_HINT}
                  info={MAIN_TASK_INFO}
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
                  placeholder={MAIN_TASK_PLACEHOLDER}
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
                  <span className="text-meta text-ink-muted">Saves it as a draft.</span>
                </div>
              </section>

              <MaterialsDraft items={materials} onChange={setMaterials} canWrite={write.allowed} />

              <PipGenerateBand
                onGenerate={() => void submit(true)}
                busy={busy}
                disabled={!write.allowed || !ready}
                reason={!ready ? "Write the main task first." : undefined}
                refusal={write.reason ?? undefined}
              />
              {create.error != null && <ProblemNotice error={create.error} />}
              {followUpError != null && (
                <div className="space-y-2">
                  <ProblemNotice error={followUpError} />
                  {draftId && (
                    <a className="text-meta text-brand-strong underline" href={detail(draftId)}>
                      Open the draft
                    </a>
                  )}
                </div>
              )}

              <section
                aria-labelledby="new-campaign-script"
                className="rounded-card border border-line border-l-4 border-l-brand-strong bg-surface p-4 shadow-card sm:p-6"
              >
                <SectionHead id="new-campaign-script" step={3} title="Script" hint={SCRIPT_HINT} info={SCRIPT_INFO} />
                {!agents.data && !agents.error && <Skeleton rows={2} label="Loading your agents" />}
                {agents.data && agentOptions.length === 0 && <NoAgentYet />}
                {agentOptions.length > 0 && (
                  <AgentChoice
                    onChange={setAgentId}
                    agentOptions={agentOptions}
                    selectedAgentId={selectedAgentId}
                    selectedAgent={selectedAgent}
                  />
                )}
                <p className="mt-4 text-meta text-ink-muted">Press Generate above to write it.</p>
              </section>
            </div>
          )
        }
      />
    </div>
  );
}
