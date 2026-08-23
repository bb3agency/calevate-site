"use client";

import {
  identityAnswerPending,
  useAdminAccess,
  useAdminMe,
} from "@/app/admin/access";
import { ConfigPanel } from "@/app/admin/ops/ConfigPanel";
import { ModelPricingPanel } from "@/app/admin/ops/ModelPricingPanel";
import { KeyManagementPanel, SecretsPanel } from "@/app/admin/ops/SecretsPanel";
import { WithheldPanel } from "@/app/admin/withheld";
import { Card, Skeleton } from "@/components/ui";

/**
 * THE OPS CONFIG PANEL — platform settings and vendor credentials, on their own screen.
 *
 * "Only super admin has access to ops config panel and it should be added to the sidebar
 * in the super admin login" (the founder, correcting D-457). These three panels used to
 * sit at the bottom of `/admin/ops`, under the incident switches, with no name of their
 * own anywhere in the navigation — so the surface the founder installs every vendor key
 * on was findable only by scrolling the screen you open when calls have stopped.
 *
 * ## Why a route of its own rather than an anchor on `/admin/ops`
 *
 * A sidebar entry needs a destination, and two entries pointing at one path would break
 * `lib/nav.currentNavItem` (longest prefix wins; a tie is decided by list order, so the
 * header title and the `aria-current` highlight would disagree with each other about
 * which of the two you are on). The split is also what the permissions were already
 * saying: `/admin/ops` is `ops:manage` — the incident levers, held by whoever is on call
 * — while everything here is `platform:config` or `platform:secrets`, which is change
 * management. One screen carrying three permissions meant its nav entry could only
 * declare one of them, and it declared the wrong one for two thirds of what it led to.
 *
 * ## The gating is the same doctrine, moved intact
 *
 * Each panel gates on ITS OWN permission, not on the screen's: a session that may change
 * a calling window does not thereby get to replace the Bolna key. The panels are not
 * MOUNTED for a session the server has refused, because on both these surfaces the READ
 * carries the same permission as the write — mounting would fire a request whose only
 * outcome is a 403, and then render "we could not read this", which is the sentence for
 * an outage (`admin/withheld.tsx` argues it in full). And the mount waits for the
 * identity read to have ANSWERED (`identityAnswerPending`, never `isLoading` — the retry
 * loop that helper documents), so nothing appears, populates and is then replaced.
 *
 * Reaching this URL as a normal admin is therefore three withheld cards and no requests,
 * which is the honest screen: the sidebar does not offer the route to them
 * (`admin/layout.tsx` argues why THIS entry is the console's one hidden one), and the API
 * is the enforcement either way.
 */
export default function OpsConfigPage() {
  // A DIFFERENT permission from the incident screen next door. The config panel reads no
  // platform-row state, so it is gated on the permission alone.
  const mayConfigure = useAdminAccess("platform:config", "change platform configuration");
  // The narrowest permission in the product. `platform:secrets` is held by fewer people
  // than anything else (PLATFORM-CONFIG §10's first mitigation), so the credential and
  // key-management panels gate on it alone.
  const maySecrets = useAdminAccess("platform:secrets", "install or rotate credentials");
  // The same `["admin","me"]` query the two verdicts above read, asked a third way: has it
  // ANSWERED yet. See `identityAnswerPending` for why this is not `isLoading`.
  const identityLoading = identityAnswerPending(useAdminMe());

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <p className="mt-0.5 text-sm text-ink-muted">
          What this deployment runs on: the settings that can be changed without an SSH
          session, and the vendor credentials the platform authenticates with. Every write
          here is audit-logged with its reason, and no route on this screen can display a
          credential — only replace one.
        </p>
      </div>

      {identityLoading ? (
        <PanelPending title="Platform configuration" />
      ) : mayConfigure.refused ? (
        <WithheldPanel
          title="Platform configuration"
          reason={mayConfigure.reason ?? "Your admin account cannot change platform configuration."}
          subject="This panel would list every setting this deployment can change without an SSH session, and the value in force for each."
        />
      ) : (
        <ConfigPanel access={mayConfigure} />
      )}

      {/* Model prices, on the SAME permission as the config panel — a price is
          configuration, not a credential (visible, revertible by a superseding
          attestation, no secret), so `platform:config` gates it and the same
          identity-answered/refused/mount doctrine applies. It is where the founder types
          the vendor price that makes an OpenAI or Google model billable, so it sits beside
          the settings rather than beside the credentials. */}
      {identityLoading ? (
        <PanelPending title="Model prices" />
      ) : mayConfigure.refused ? (
        <WithheldPanel
          title="Model prices"
          reason={mayConfigure.reason ?? "Your admin account cannot change platform configuration."}
          subject="This panel would list every model, its provider and the per-million-token price billing uses."
        />
      ) : (
        <ModelPricingPanel access={mayConfigure} />
      )}

      {/* THE SHARPEST EDGE IN EITHER CONSOLE, so the withheld cards here say LESS than the
          config one and deliberately not more: a normal admin is told what the panel is
          for and nothing whatever about what is installed. Not a count, not a key name,
          not "no credentials found" — an inventory of which vendor credentials a
          deployment holds is a targeting oracle (`apps/api/ops/secret_routes.py`), and a
          placeholder that reads as one is something an operator would act on. */}
      {identityLoading ? (
        <>
          <PanelPending title="Vendor credentials" />
          <PanelPending title="Key management" />
        </>
      ) : maySecrets.refused ? (
        <>
          <WithheldPanel
            title="Vendor credentials"
            reason={maySecrets.reason ?? "Your admin account cannot install or rotate credentials."}
            subject="This panel would list the key names this deployment holds and the last four characters of each."
          />
          <WithheldPanel
            title="Key management"
            reason={maySecrets.reason ?? "Your admin account cannot install or rotate credentials."}
            subject="This panel would show which key-encryption key is active and how many stored versions are still wrapped under an older one."
          />
        </>
      ) : (
        <>
          <SecretsPanel access={maySecrets} />
          <KeyManagementPanel access={maySecrets} />
        </>
      )}
    </div>
  );
}

/**
 * A panel whose PERMISSION is still unknown — the shape held while `/v1/admin/me` is in
 * flight, so the card does not appear, populate and then vanish.
 *
 * A skeleton rather than an empty space or a spinner, because the honest statement is
 * "something belongs here and we are finding out whether you may see it". It claims
 * nothing about the subject: no count, no field, no "none installed". Duplicated from
 * `admin/ops/page.tsx` rather than exported from it because Next's route-file typing
 * rejects any export from a `page.tsx` that is not one of its own conventions
 * (`OmitWithTag` in `.next/types`) — the same constraint that put `currentNavItem` in
 * `lib/nav.ts`.
 */
function PanelPending({ title }: { title: string }) {
  return (
    <Card title={title}>
      <Skeleton rows={3} label={`Checking whether you may see ${title.toLowerCase()}…`} />
    </Card>
  );
}
