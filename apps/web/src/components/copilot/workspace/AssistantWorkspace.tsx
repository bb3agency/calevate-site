"use client";

import { useCallback, useEffect, useId, useMemo, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/console/pageHeader";
import { FlashValue } from "@/components/console/valueFlash";
import { LiveActivity, useLiveActivity } from "@/components/interior/live-activity";
import { SkeletonSwap } from "@/components/interior/skeleton-swap";
import { Tabs } from "@/components/interior/tabs";
import { MAIN_CONTENT_ID } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { fallbackSurface } from "@/lib/copilot/fallback";
import { useCopilotSurface, useCopilotSurfaceHolder, type SurfaceHolder } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import {
  useCopilotApprovals,
  useCopilotJobs,
  useRoutines,
  type CopilotJobOut,
  type Realm,
} from "@/lib/copilot/workspace";

import { CopilotPanel } from "../CopilotPanel";
import { ActivityLog } from "./ActivityLog";
import { ApprovalsInbox } from "./ApprovalsInbox";
import { Routines } from "./Routines";
import { TasksList } from "./TasksList";

type Destination = { route: string; screen: string; where: string };

/**
 * THE ASSISTANT'S OWN PAGE (D-694): the conversation, laid into the page rather than in a
 * side panel, and everything around it — what is waiting for the person, what is running,
 * the routines, and everything the assistant did with its Undo.
 *
 * The tab is in the address (`?tab=approvals`), so "Review approvals" in a task, a link
 * in an email or the browser's back button all land on the right part of the page.
 */
export function ClientAssistantWorkspace({
  session,
  route,
  onNavigate,
}: {
  session: Session;
  route: string;
  onNavigate: (destination: Destination) => void;
}) {
  const approvals = useCopilotApprovals(session);
  const jobs = useCopilotJobs(session);
  const routines = useRoutines(session);
  const waiting = approvals.data?.actions.length;
  const running = jobs.data?.jobs.filter(isRunning).length;
  const routinesOn = routines.data?.routines.filter((routine) => routine.enabled).length;
  const [tab, setTab] = useTabParam(CLIENT_TABS);
  const holder = useWorkspaceSurface(route, "client", [
    { key: "waiting", label: "Approvals waiting", value: String(waiting ?? "unknown") },
    { key: "running", label: "Background tasks running", value: String(running ?? "unknown") },
    { key: "routines", label: "Routines switched on", value: String(routinesOn ?? "unknown") },
  ]);
  const titleId = useId();

  return (
    <div className="space-y-5 pb-12">
      <PageHeader description="What the assistant is doing for you, what's waiting for you, and everything it did." />
      <RunningTask jobs={jobs.data?.jobs} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Tile label="Waiting for you" value={waiting} onOpen={() => setTab("approvals")} />
        <Tile label="Running now" value={running} onOpen={() => setTab("tasks")} />
        <Tile label="Routines on" value={routinesOn} onOpen={() => setTab("routines")} />
      </div>
      <Tabs
        label="The assistant"
        items={CLIENT_TABS.map((item) => ({
          value: item.value,
          label:
            item.value === "approvals" && waiting !== undefined && waiting > 0
              ? `${item.label} (${waiting})`
              : item.label,
        }))}
        value={tab}
        onValueChange={setTab}
        panelClassName="pt-4"
        renderPanel={(value) => {
          switch (value) {
            case "approvals":
              return <ApprovalsInbox session={session} />;
            case "tasks":
              return <TasksList session={session} onOpenApprovals={() => setTab("approvals")} />;
            case "routines":
              return <Routines session={session} />;
            case "activity":
              return <ActivityLog session={session} realm="client" />;
            default:
              return (
                <CopilotPanel
                  session={session}
                  holder={holder}
                  realm="client"
                  labelledBy={titleId}
                  placement="page"
                  onNavigate={onNavigate}
                />
              );
          }
        }}
      />
    </div>
  );
}

/** The admin realm's page: the conversation and the activity log, with its Undo. */
export function AdminAssistantWorkspace({
  session,
  onNavigate,
}: {
  session: Session;
  onNavigate: (destination: Destination) => void;
}) {
  const [tab, setTab] = useTabParam(ADMIN_TABS);
  const holder = useWorkspaceSurface("/admin/assistant", "admin", []);
  const titleId = useId();
  return (
    <div className="space-y-5 pb-12">
      <PageHeader description="Your conversation with the assistant, and everything it changed." />
      <Tabs
        label="The assistant"
        items={[...ADMIN_TABS]}
        value={tab}
        onValueChange={setTab}
        panelClassName="pt-4"
        renderPanel={(value) =>
          value === "activity" ? (
            <ActivityLog session={session} realm="admin" />
          ) : (
            <CopilotPanel
              session={session}
              holder={holder}
              realm="admin"
              labelledBy={titleId}
              placement="page"
              onNavigate={onNavigate}
            />
          )
        }
      />
    </div>
  );
}

const CLIENT_TABS = [
  { value: "conversation", label: "Conversation" },
  { value: "approvals", label: "Approvals" },
  { value: "tasks", label: "Tasks" },
  { value: "routines", label: "Routines" },
  { value: "activity", label: "Activity" },
] as const;

const ADMIN_TABS = [
  { value: "conversation", label: "Conversation" },
  { value: "activity", label: "Activity" },
] as const;

function isRunning(job: CopilotJobOut): boolean {
  return job.status === "queued" || job.status === "running";
}

/** The current tab, kept in `?tab=`; an unknown value falls back to the first tab. */
function useTabParam(
  tabs: readonly { value: string; label: string }[],
): [string, (next: string) => void] {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const asked = params.get("tab");
  const tab = tabs.some((item) => item.value === asked) ? (asked as string) : tabs[0].value;
  const setTab = useCallback(
    (next: string) => {
      const query = new URLSearchParams(params.toString());
      if (next === tabs[0].value) query.delete("tab");
      else query.set("tab", next);
      const suffix = query.toString();
      router.replace(suffix ? `${pathname}?${suffix}` : pathname, { scroll: false });
    },
    [params, pathname, router, tabs],
  );
  return [tab, setTab];
}

/**
 * This page declares itself to the assistant like every other screen, with the counts it
 * shows as facts, and hands the same holder to the conversation it lays into the page.
 */
function useWorkspaceSurface(
  route: string,
  realm: Realm,
  facts: { key: string; label: string; value: string }[],
): SurfaceHolder {
  useCopilotSurface({ route, title: "Assistant", realm, fields: [], facts, apply: noFill });
  const declared = useCopilotSurfaceHolder();
  const fallback = useMemo<SurfaceHolder>(() => {
    const surface = fallbackSurface(route, realm);
    return { read: () => surface };
  }, [route, realm]);
  return declared ?? fallback;
}

/** One count, a button to the tab that lists it. The skeleton waits for a real number. */
function Tile({
  label,
  value,
  onOpen,
}: {
  label: string;
  value: number | undefined;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="press min-w-0 rounded-card border border-line bg-surface px-4 py-3 text-left hover:bg-ink/[0.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
    >
      <span className="block text-[13px] font-medium text-ink-muted">{label}</span>
      <SkeletonSwap ready={value !== undefined} lines={1} lineHeight={34} barHeight={14}>
        <span className="block text-[26px] font-semibold leading-tight tracking-tight tabular-nums text-ink">
          <FlashValue value={value === undefined ? null : String(value)}>
            {value ?? ""}
          </FlashValue>
        </span>
      </SkeletonSwap>
    </button>
  );
}

/**
 * The newest running task as a live pod: it says when one starts, peeks its latest step,
 * and says how it ended. Polling feeds it; it never asks the server for anything itself.
 */
function RunningTask({ jobs }: { jobs: CopilotJobOut[] | undefined }) {
  const live = useLiveActivity({ linger: 4000 });
  const { start, update, succeed, fail, dismiss } = live;
  const tracked = useRef<string | null>(null);
  const current = jobs?.find(isRunning);
  const latest = current?.progress[current.progress.length - 1]?.text;
  const finished =
    tracked.current === null ? undefined : jobs?.find((job) => job.id === tracked.current);

  useEffect(() => {
    if (current !== undefined) {
      if (tracked.current !== current.id) {
        tracked.current = current.id;
        start({ title: "A task is running", detail: latest ?? current.goal });
      } else if (latest !== undefined) {
        update({ detail: latest });
      }
      return;
    }
    if (tracked.current === null) return;
    tracked.current = null;
    if (finished?.status === "done") succeed({ title: "Task finished" });
    else if (finished?.status === "failed") fail({ title: "Task stopped" });
    else dismiss();
  }, [current, latest, finished, start, update, succeed, fail, dismiss]);

  return <LiveActivity activity={live.activity} onDismiss={dismiss} label="Background task" />;
}

/** Shared by both page modules: after a move, put the caret at the top of the new screen. */
export function focusMain(): void {
  requestAnimationFrame(() => document.getElementById(MAIN_CONTENT_ID)?.focus());
}

export type { Destination };
