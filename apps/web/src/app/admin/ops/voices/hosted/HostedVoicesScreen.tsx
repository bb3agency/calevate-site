"use client";

import { useState } from "react";
import { AudioLines, RefreshCw } from "lucide-react";

import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { Tabs } from "@/components/interior/tabs";
import {
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  formatCount,
} from "@/components/ui";
import { useHostedVoices, type HostedVoices } from "@/lib/api/opsHostedVoices";
import { useRefreshVoiceCatalogue } from "@/lib/api/opsVoices";

import { CloneVoiceDrawer } from "./CloneVoiceDrawer";
import { HostedVoiceList } from "./HostedVoiceList";
import { StudioWorkspaceCard } from "./StudioWorkspaceCard";

type Tab = "clear" | "studio" | "all";

const TAB_ITEMS = [
  { value: "clear", label: "Clear" },
  { value: "studio", label: "Studio" },
  { value: "all", label: "Every voice on the platform" },
];

/**
 * The Voices page on an engine that HOSTS its voices (D-687, ENGINE=thinnest).
 *
 * Clear is ThinnestAI's studio-band voices plus the clones made here; Studio is Cartesia on
 * our own key, through the shared Studio workspace. A client picks only from voices ADDED
 * and ENABLED here, and can play each one's preview first — so the screen's three jobs are
 * adding, enabling, and making sure every offered voice has a clip to play.
 *
 * `added` is the page's probe query (the parent read it to decide which screen to show), so
 * the Clear and Studio tabs cost no second request. "Every voice" is the full synced list
 * and is read only when opened.
 */
export function HostedVoicesScreen({ added }: { added: HostedVoices }) {
  const [tab, setTab] = useState<Tab>("clear");
  const [cloning, setCloning] = useState(false);
  const everything = useHostedVoices(tab === "all", "all");
  const refresh = useRefreshVoiceCatalogue();

  const byRung = (rung: "clear" | "studio") => added.voices.filter((voice) => voice.rung === rung);
  const studioCount = byRung("studio").length;

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        description="Clients choose only from the voices added and enabled here, and can listen to each one first."
        actions={
          <>
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                className={SECONDARY_BUTTON}
                disabled={refresh.isPending}
                onClick={() => void refresh.mutateAsync().catch(() => undefined)}
              >
                <RefreshCw aria-hidden className="h-4 w-4" />
                {refresh.isPending ? "Reading the voice platform…" : "Refresh"}
              </button>
              <InfoTip label="Refresh">
                Re-reads ThinnestAI&rsquo;s studio-band voices, our clones and the Cartesia voices
                in the Studio workspace. A newly seen voice arrives not added; nothing here changes
                an agent or a call.
              </InfoTip>
            </div>
            <button type="button" className={PRIMARY_BUTTON} onClick={() => setCloning(true)}>
              <AudioLines aria-hidden className="h-4 w-4" />
              Clone a voice
            </button>
          </>
        }
      />

      {refresh.data && (
        <NoticeBox tone="neutral" title="The voice platform was re-read">
          <p className="mt-1">{refresh.data.note}</p>
        </NoticeBox>
      )}
      {refresh.error != null && <ProblemNotice error={refresh.error} />}

      <StudioWorkspaceCard />

      <section aria-labelledby="hosted-voices" className="space-y-3">
        <div>
          <h2 id="hosted-voices" className="text-[17px] font-semibold text-ink">
            The voices clients can be offered
          </h2>
          <p className="mt-1 text-sm tabular-nums text-ink-muted">
            {formatCount(added.offered)} offered{" · "}
            {formatCount(added.voices.length)} added{" · "}
            {formatCount(added.cached)} on the platform
          </p>
          {added.note && <p className="mt-1 text-sm text-ink-muted">{added.note}</p>}
        </div>

        <Tabs
          label="Which voices to list"
          items={TAB_ITEMS}
          value={tab}
          onValueChange={(next) => setTab(next as Tab)}
          panelClassName="p-3 sm:p-4"
          renderPanel={(value) => {
            if (value === "all") {
              if (everything.error != null) {
                return (
                  <ProblemNotice error={everything.error} onRetry={() => void everything.refetch()} />
                );
              }
              if (!everything.data) return <Skeleton rows={6} label="Loading every voice on the platform" />;
              return (
                <HostedVoiceList
                  voices={everything.data.voices}
                  empty="The last sync read no voices. Press Refresh to read the platform again."
                />
              );
            }
            if (value === "studio" && added.studio_workspace_id === null && studioCount === 0) {
              return (
                <p className="text-sm text-ink-muted">
                  Studio voices are read from the Studio workspace, which is not set up yet. Set it
                  up above, then press Refresh.
                </p>
              );
            }
            return (
              <HostedVoiceList
                voices={byRung(value as "clear" | "studio")}
                empty={
                  value === "clear"
                    ? "No Clear voice is added yet. Clone one, or add a studio-band voice from “Every voice on the platform”."
                    : "No Studio voice is added yet. Add one from “Every voice on the platform”."
                }
              />
            );
          }}
        />
      </section>

      {cloning && <CloneVoiceDrawer onClose={() => setCloning(false)} />}
    </div>
  );
}
