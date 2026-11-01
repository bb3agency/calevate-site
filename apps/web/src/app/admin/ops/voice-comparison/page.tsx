"use client";

import {
  identityAnswerPending,
  useAdminAccess,
  useAdminMe,
} from "@/app/admin/access";
import { PageHeader } from "@/components/console/pageHeader";
import { RestrictionNote } from "@/components/ui";
import { useCopilotSurface } from "@/lib/copilot/registry";

import { VoiceComparisonScreen } from "./VoiceComparisonScreen";

/**
 * The blind voice comparison (D-946): Cartesia and Sarvam voices on the same Telugu lines,
 * rated without knowing which provider spoke, to decide Studio's voice provider. No client
 * is affected by anything here.
 *
 * `ops:manage` gates every read, asked of `GET /v1/admin/me` first so a session without it
 * sends nothing it can only be refused. No `<h1>`: the shell prints the nav label.
 */
export default function VoiceComparisonPage() {
  const access = useAdminAccess("ops:manage", "run the blind voice comparison");
  const identityLoading = identityAnswerPending(useAdminMe());
  const ready = !identityLoading && !access.refused;

  useCopilotSurface({
    route: "/admin/ops/voice-comparison",
    title: "Voice comparison",
    realm: "admin",
    fields: [],
    // Nothing here is the assistant's to fill: a rating is the listener's own judgement.
    apply: () => undefined,
    facts: [
      {
        key: "blind",
        label: "Providers",
        value: "hidden until the round is finished",
      },
    ],
  });

  return (
    <div className="max-w-4xl space-y-8 pb-12">
      <PageHeader description="Hear Cartesia and Sarvam on the same lines, blind. No client is affected." />
      {access.refused ? (
        <RestrictionNote reason={access.reason} />
      ) : (
        <VoiceComparisonScreen enabled={ready} />
      )}
    </div>
  );
}
