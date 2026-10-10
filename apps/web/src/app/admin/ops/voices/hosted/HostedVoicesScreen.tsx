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
import { BAND_LABEL, useHostedVoices, type HostedVoices } from "@/lib/api/opsHostedVoices";
import { lookup } from "@/lib/lookup";
import { useRefreshVoiceCatalogue } from "@/lib/api/opsVoices";

import { CloneVoiceDrawer } from "./CloneVoiceDrawer";
import { HostedVoiceList } from "./HostedVoiceList";
import { StudioVoicesCard } from "./StudioVoicesCard";

type Tab = "clear" | "studio" | "all";

const TAB_ITEMS = [
  { value: "clear", label: "Clear" },
  { value: "studio", label: "Studio" },
  { value: "all", label: "Every voice on the platform" },
];

/**
 * The Voices page on an engine that HOSTS its voices (D-687, ENGINE=thinnest).
 *
 * Clear is ThinnestAI's voices in the band the server names (`clear_band`: its Premium band, or
 * its Studio band with our clones); Studio is Cartesia on our own key, switched on in each
 * Studio client's own workspace (D-717). ThinnestAI's bands are always labelled as theirs
 * ("ThinnestAI Studio band"), so they never read as our Studio tier. A client picks only from
 * voices ADDED and ENABLED here, and can play each one's preview first — so the screen's three jobs are
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
  const soldBand = (added.clear_band && lookup(BAND_LABEL, added.clear_band)) ?? "ThinnestAI Premium band";

  return (
    <div className="max-w-4xl space-y-10 pb-12">
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
                Re-reads every voice ThinnestAI lists (its Standard, Premium and Studio bands), our
                clones and, once a client workspace runs Studio, the Cartesia voices of our key. Only
                voices of the band sold as Clear can be offered as Clear. ThinnestAI lists its Studio
                band only on its Pro plan and above, so a voice its console merely lets you preview is
                not read.
                A newly seen voice arrives not added; nothing here changes an agent or a call.
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

      {added.plan_note != null && (
        <NoticeBox tone="warn" title={`No ${soldBand} voices on the voice platform`}>
          <p className="mt-1">{added.plan_note}</p>
          <p className="mt-1">
            Clear is sold on {soldBand} voices only, so no Clear voice can be added until they
            are listed.
            {added.clear_band === "studio" &&
              " ThinnestAI's Studio band is not our Studio tier below: that is our Cartesia key and adds no voice to this band."}
          </p>
        </NoticeBox>
      )}

      <StudioVoicesCard />

      <section aria-labelledby="hosted-voices" className="space-y-3">
        <div>
          <h2 id="hosted-voices" className="text-heading text-ink">
            The voices clients can be offered
          </h2>
          <p className="mt-1 text-body tabular-nums text-ink-muted">
            {formatCount(added.offered)} offered{" · "}
            {formatCount(added.voices.length)} added{" · "}
            {formatCount(added.cached)} on the platform
          </p>
          {added.note && <p className="mt-1 text-body text-ink-muted">{added.note}</p>}
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
                <div className="space-y-3">
                  <BandSummary bands={everything.data.bands} soldBand={soldBand} />
                  <HostedVoiceList
                    voices={everything.data.voices}
                    empty="The last sync read no voices. Press Refresh to read the platform again."
                  />
                </div>
              );
            }
            if (value === "studio" && !added.studio_ready && studioCount === 0) {
              return (
                <p className="text-body text-ink-muted">
                  Studio voices are read through a client workspace that runs Studio, and none does
                  yet. Run Studio ready above naming the first Studio client, then press Refresh.
                </p>
              );
            }
            return (
              <HostedVoiceList
                voices={byRung(value as "clear" | "studio")}
                empty={
                  value === "clear"
                    ? `No Clear voice is added yet. Add a ${soldBand} voice from “Every voice on the platform”.`
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

const BAND_ORDER = ["standard", "premium", "studio"] as const;

/** How many voices the platform lists in each band, and which band can be sold. */
function BandSummary({ bands, soldBand }: { bands: HostedVoices["bands"]; soldBand: string }) {
  return (
    <p className="text-body tabular-nums text-ink-muted">
      {"Bands on the platform: "}
      {BAND_ORDER.map((band) => `${formatCount(bands[band] ?? 0)} ${lookup(BAND_LABEL, band) ?? band}`).join(" · ")}
      {`. Only ${soldBand} voices can be added as Clear.`}
    </p>
  );
}
