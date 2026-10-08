"use client";

import { useState } from "react";
import { CircleCheck, KeyRound, PowerOff, TriangleAlert } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { Card, NoticeBox, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatCount } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import {
  useDisableStudioVoices,
  useEnableStudioVoices,
  useStudioVoices,
} from "@/lib/api/opsHostedVoices";

/**
 * Studio voices (D-688): our Cartesia key, switched on in the one ThinnestAI workspace for the
 * voice only. Every agent says per agent whether it follows that switch, so Clear and Studio
 * agents share the workspace. The card says whether the switch is on and offers the two
 * actions; every sentence about the state, and why switching on keeps Clear agents off first,
 * is the server's.
 */
export function StudioVoicesCard() {
  const studio = useStudioVoices(true);
  const enable = useEnableStudioVoices();
  const disable = useDisableStudioVoices();
  const [confirming, setConfirming] = useState<"enable" | "disable" | null>(null);
  const inUse = disable.error instanceof ApiProblem && disable.error.code === "studio_voices_in_use";
  const last = enable.data ?? disable.data;

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 className="text-[15px] font-semibold text-ink">Studio voices (our Cartesia key)</h2>
          {studio.error != null ? (
            <ProblemNotice error={studio.error} onRetry={() => void studio.refetch()} />
          ) : !studio.data ? (
            <Skeleton rows={2} label="Reading whether Studio voices are on" />
          ) : (
            <>
              <p className="flex items-center gap-1.5 text-sm font-medium">
                {studio.data.ready ? (
                  <>
                    <CircleCheck aria-hidden className="h-4 w-4 text-brand-strong" />
                    <span className="text-ink">On — Studio voices can be offered</span>
                  </>
                ) : (
                  <>
                    <TriangleAlert aria-hidden className="h-4 w-4 text-warn" />
                    <span className="text-warn">Off — Studio voices cannot be offered</span>
                  </>
                )}
              </p>
              <p className="text-sm text-ink-muted">{studio.data.note}</p>
              <p className="text-xs text-ink-muted">{studio.data.explanation}</p>
              <dl className="mt-1 grid gap-x-4 gap-y-0.5 text-xs text-ink-muted sm:grid-cols-[auto_1fr]">
                <dt className="font-medium">Voice key</dt>
                <dd>
                  {[
                    studio.data.key.enabled ? "Own keys on" : "Own keys off",
                    studio.data.key.scope ? `scope ${studio.data.key.scope}` : null,
                    studio.data.key.voice_provider
                      ? `voice by ${studio.data.key.voice_provider}`
                      : "no voice key",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </dd>
                <dt className="font-medium">Published Studio agents</dt>
                <dd className="tabular-nums">{formatCount(studio.data.live_studio_agents)}</dd>
                <dt className="font-medium">Cartesia key in the ops console</dt>
                <dd>{studio.data.cartesia_key_configured ? "Set" : "Not set"}</dd>
              </dl>
            </>
          )}
        </div>
        {studio.data && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              onClick={() => {
                enable.reset();
                setConfirming("enable");
              }}
            >
              <KeyRound aria-hidden className="h-4 w-4" />
              {studio.data.ready ? "Enable again" : "Enable Studio voices"}
            </button>
            {studio.data.ready && (
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                onClick={() => {
                  disable.reset();
                  setConfirming("disable");
                }}
              >
                <PowerOff aria-hidden className="h-4 w-4" />
                Turn off Studio voices
              </button>
            )}
          </div>
        )}
      </div>
      {confirming === null && last && (
        <p role="status" className="mt-2 text-sm text-ink-muted">
          {last.note}
        </p>
      )}
      {confirming === "enable" && (
        <ConfirmDialog
          title="Enable Studio voices?"
          confirmLabel="Enable Studio voices"
          pendingLabel="Enabling…"
          pending={enable.isPending}
          error={enable.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => enable.mutate({}, { onSuccess: () => setConfirming(null) })}
        >
          <p>{studio.data?.explanation}</p>
          <p className="mt-2">
            In order: every published Clear agent is set to stay on the platform&rsquo;s own
            voices and checked, our Cartesia key is installed unless the workspace already holds
            one, and the key is switched on for the voice only. It installs a credential, so you
            may be asked to confirm it is still you.
          </p>
        </ConfirmDialog>
      )}
      {confirming === "disable" && (
        <ConfirmDialog
          title="Turn off Studio voices?"
          confirmLabel={inUse ? "Turn off and move those agents" : "Turn off Studio voices"}
          pendingLabel="Turning off…"
          pending={disable.isPending}
          error={inUse ? null : disable.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() =>
            disable.mutate({ confirm: inUse }, { onSuccess: () => setConfirming(null) })
          }
        >
          <p>
            Studio voices come off the picker, and agents on a Studio voice speak the
            platform&rsquo;s default voice from their next call.
          </p>
          {inUse && (
            <NoticeBox tone="warn" title="Published agents speak Studio voices" className="mt-2">
              <p className="mt-1">{disable.error?.message}</p>
            </NoticeBox>
          )}
        </ConfirmDialog>
      )}
    </Card>
  );
}
