"use client";

import { Webhook } from "lucide-react";

import { Card, PRIMARY_BUTTON_SM, ProblemNotice } from "@/components/ui";
import type { useIngestActivity, useMetaRedrive, useMetaSetup } from "@/lib/api/leadSources";

import { MetaRecovery } from "./MetaRecovery";
import { MetaSetupDetails } from "./MetaSetupDetails";
import { SourcePicker, type SourcesQuery } from "./SourcePicker";

/**
 * Meta Lead Ads (SURFACES §2b). Placed above the delivery log on purpose: the capability
 * statement in the response is the thing someone needs BEFORE they wire an ad account up,
 * not something to infer from a column of rejections.
 *
 * ## Nothing here says a source is connected, because nothing here can know
 *
 * This card hands over a callback URL and a verify token. That is SETUP MATERIAL, not a
 * connection: until someone pastes both into the Meta App Dashboard and Meta completes the
 * handshake, no delivery has happened and this deployment cannot tell the difference
 * between "not wired up yet" and "wired up wrong". The only evidence a source is live is a
 * row in the deliveries table below, so the card points at it rather than implying success.
 */
export function MetaCard({
  sources,
  activity,
  metaSetup,
  redrive,
  sourceId,
  onSourceId,
  canWrite,
}: {
  sources: SourcesQuery;
  activity: ReturnType<typeof useIngestActivity>;
  metaSetup: ReturnType<typeof useMetaSetup>;
  redrive: ReturnType<typeof useMetaRedrive>;
  sourceId: string;
  onSourceId: (id: string) => void;
  canWrite: boolean;
}) {
  return (
    <Card title="Meta Lead Ads">
      <p className="text-sm text-ink-muted">
        Add a Meta Lead Ads source above, then pick it here to see what to paste into
        the Meta App Dashboard.
      </p>

      <form
        className="mt-3 flex flex-wrap items-end gap-2"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          metaSetup.mutate(sourceId.trim());
        }}
      >
        <SourcePicker
          label="Meta lead source"
          value={sourceId}
          onChange={(id) => {
            onSourceId(id);
            // The response carries a credential for ONE source; leaving it on screen
            // beside a different ID is how the wrong token gets pasted into Meta.
            metaSetup.reset();
            // And the recovery result is about ONE source too: "2 of 2 recovered"
            // left standing under a different Page reads as a statement about that
            // Page's leads, which is the wrong answer rather than a stale one.
            redrive.reset();
          }}
          query={sources}
          // Only Meta sources: the other kinds have no Meta endpoint at all, and
          // `POST .../meta/setup` answers 404 for them. A picker that offers a choice
          // whose only outcome is a refusal is a worse ID box than the one it replaced.
          only="meta_lead_ads"
          emptyHint="Add a Meta Lead Ads source above first."
        />
        <button
          type="submit"
          disabled={!canWrite || metaSetup.isPending || !sourceId.trim()}
          className={PRIMARY_BUTTON_SM}
        >
          <Webhook className="h-4 w-4" />
          {metaSetup.isPending ? "Loading…" : "Show setup details"}
        </button>
      </form>

      {metaSetup.error != null && (
        <div className="mt-3">
          <ProblemNotice error={metaSetup.error} />
        </div>
      )}
      {metaSetup.data && <MetaSetupDetails setup={metaSetup.data} />}

      <MetaRecovery
        sourceId={sourceId.trim()}
        activity={activity}
        redrive={redrive}
        canWrite={canWrite}
      />
    </Card>
  );
}
