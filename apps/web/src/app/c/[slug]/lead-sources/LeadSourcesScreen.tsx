"use client";

import { useState } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { PRIMARY_BUTTON, ProblemNotice, RestrictionNote } from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useCreateLeadSource,
  useIngestActivity,
  useLeadSources,
  useMetaRedrive,
  useMetaSetup,
  useRotateLeadSourceSecret,
  useSetLeadSourceActive,
  useTestWebhook,
  type LeadSource,
  type LeadSourceDryRun,
} from "@/lib/api/leadSources";
import {
  useDropHeldLead,
  useHeldLeads,
  useLeadCalling,
  useReleaseHeldLead,
  useSaveLeadCalling,
} from "@/lib/api/leadCalling";
import { useClientSession } from "@/lib/api/session";

import { AddSourceDrawer } from "./AddSourceDrawer";
import { CallingPlan } from "./CallingPlan";
import { DeliveryLog } from "./DeliveryLog";
import { HeldLeads } from "./HeldLeads";
import { MetaDrawer } from "./MetaDrawer";
import { RotateDrawer } from "./RotateDrawer";
import { SourcesList } from "./SourcesList";
import { TestLeadDrawer } from "./TestLeadDrawer";
import { useLeadSourcesCopilot } from "./copilot";
import { sampleText } from "./testSample";

/**
 * Leads & hours: how new leads are called (one plan for the business, D-716), the leads held
 * for release, where leads come from, and proof that they are arriving.
 *
 * PRIMARY JOB: connect a website form or Meta ads, and see that leads land. The sources
 * are rows; adding one, testing one and Meta's setup each open a drawer over the list, so
 * the list stays the screen. Every test, setup and provisioning route is `org:manage`, and
 * the screen says so once at the top rather than on each control.
 *
 * No `<h1>`: the shell prints "Leads & hours".
 */
export function LeadSourcesScreen() {
  const session = useClientSession();
  const sources = useLeadSources(session);
  const agents = useAgents(session);
  const activity = useIngestActivity(session);
  const create = useCreateLeadSource(session);
  const rotate = useRotateLeadSourceSecret(session);
  const setActive = useSetLeadSourceActive(session);
  const test = useTestWebhook(session);
  const metaSetup = useMetaSetup(session);
  const redrive = useMetaRedrive(session);
  const write = useWriteAccess(
    session,
    "org:manage",
    "change how leads are called or set up a lead source",
  );
  const plan = useLeadCalling(session);
  const savePlan = useSaveLeadCalling(session);
  const held = useHeldLeads(session);
  const release = useReleaseHeldLead(session);
  const drop = useDropHeldLead(session);

  const [adding, setAdding] = useState(false);
  const [rotating, setRotating] = useState<LeadSource | null>(null);
  const [testSourceId, setTestSourceId] = useState("");
  const [metaSourceId, setMetaSourceId] = useState("");
  const [payloadText, setPayloadText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [result, setResult] = useState<LeadSourceDryRun | null>(null);

  const items = sources.data?.items ?? [];
  const testSource = items.find((item) => item.id === testSourceId) ?? null;
  const metaSource = items.find((item) => item.id === metaSourceId) ?? null;

  /** Runs the dry run on `text`; a sample that is not a JSON object never leaves the page. */
  const runTest = (sourceId: string, text: string) => {
    setJsonError(null);
    setResult(null);
    let payload: unknown;
    try {
      payload = JSON.parse(text);
    } catch {
      setJsonError("That doesn't look like valid JSON — check for a missing quote, comma or brace.");
      return;
    }
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
      setJsonError("The sample must be a JSON object like the pre-filled example.");
      return;
    }
    test.mutate({ webhookId: sourceId, payload }, { onSuccess: setResult });
  };

  /** Opening a source's test sends its own sample at once: a test is one press. */
  const openTest = (source: LeadSource) => {
    const text = sampleText(source);
    test.reset();
    setTestSourceId(source.id);
    setPayloadText(text);
    runTest(source.id, text);
  };

  const closeTest = () => {
    setTestSourceId("");
    setResult(null);
    setJsonError(null);
    test.reset();
  };

  /** Opening Meta's setup reads it; both results reset so nothing carries across sources. */
  const openMeta = (sourceId: string) => {
    metaSetup.reset();
    redrive.reset();
    setMetaSourceId(sourceId);
    if (sourceId && write.allowed) metaSetup.mutate(sourceId);
  };

  useLeadSourcesCopilot({
    sources,
    activity,
    testSourceId,
    setTestSourceId: (id) => {
      const source = items.find((item) => item.id === id);
      if (source) openTest(source);
    },
    metaSourceId,
    setMetaSourceId: openMeta,
    payloadText,
    jsonError,
    result,
    write,
  });

  return (
    <div className="space-y-5 pb-12">
      <PageHeader
        description="How new leads from your forms and ads are called, and every delivery accounted for."
        actions={
          <button
            type="button"
            onClick={() => setAdding(true)}
            disabled={!write.allowed}
            title={write.reason ?? undefined}
            className={PRIMARY_BUTTON}
          >
            Add source
          </button>
        }
      />
      <RestrictionNote reason={write.reason} />
      {setActive.error != null && <ProblemNotice error={setActive.error} />}

      <CallingPlan
        plan={plan}
        agents={agents.data}
        canWrite={write.allowed}
        refusal={write.reason}
        saving={savePlan.isPending}
        saveError={savePlan.error}
        savedAgents={savePlan.data?.agents_updated ?? null}
        onSave={(next) => savePlan.mutate(next)}
      />

      <HeldLeads
        held={held}
        holding={plan.data?.after_hours === "hold"}
        canWrite={write.allowed}
        busyId={
          release.isPending ? (release.variables ?? null) : drop.isPending ? (drop.variables ?? null) : null
        }
        actionError={release.error ?? drop.error}
        onRelease={(id) => release.mutate(id)}
        onDrop={(id) => drop.mutate(id)}
      />

      <h2 className="pt-2 text-base font-semibold text-ink">Where leads come from</h2>
      <SourcesList
        sources={sources}
        agents={agents.data}
        activity={activity.data}
        canWrite={write.allowed}
        busy={setActive.isPending}
        onToggle={(item) =>
          setActive.mutate({ webhookId: item.id, active: !item.active })
        }
        onTest={openTest}
        onRotate={setRotating}
        onMeta={(item) => openMeta(item.id)}
      />

      <DeliveryLog activity={activity} />

      <AddSourceDrawer
        open={adding}
        onClose={() => setAdding(false)}
        create={create}
        agents={agents}
        canWrite={write.allowed}
      />
      <RotateDrawer source={rotating} onClose={() => setRotating(null)} rotate={rotate} />
      <TestLeadDrawer
        source={testSource}
        onClose={closeTest}
        test={test}
        payloadText={payloadText}
        onPayloadText={(next) => {
          // An edit retracts the verdict: it was about the sample as it was.
          setPayloadText(next);
          setResult(null);
          setJsonError(null);
          test.reset();
        }}
        jsonError={jsonError}
        result={result}
        onRun={() => testSource && runTest(testSource.id, payloadText)}
      />
      <MetaDrawer
        source={metaSource}
        onClose={() => openMeta("")}
        metaSetup={metaSetup}
        redrive={redrive}
        activity={activity}
        canWrite={write.allowed}
        refusal={write.reason}
      />
    </div>
  );
}
