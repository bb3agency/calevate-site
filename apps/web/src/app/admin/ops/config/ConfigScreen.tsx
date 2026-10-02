"use client";

import type { ReactNode } from "react";

import { identityAnswerPending, useAdminAccess, useAdminMe } from "@/app/admin/access";
import { KeyManagementPanel, SecretsPanel } from "@/app/admin/ops/SecretsPanel";
import { WithheldPanel } from "@/app/admin/withheld";
import { InfoTip } from "@/components/console/infoTip";
import { SettingsLayout, useActiveSection } from "@/components/console/settingsLayout";
import { Card, Skeleton } from "@/components/ui";
import { useOpsConfig } from "@/lib/api/opsConfig";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import type { ConfigField } from "@/lib/api/opsConfig";

import { ConfigSectionBody, WithheldSection } from "./ConfigSection";
import { ConfigStatus } from "./ConfigStatus";
import { CONFIG_SECTIONS, visibleSections, type ConfigSectionId } from "./configSections";

type Access = ReturnType<typeof useAdminAccess>;

/**
 * PLATFORM CONFIGURATION — every setting this deployment can change without logging into
 * the server, and the vendor keys it signs in with, one subject per section (D-661).
 *
 * Job: find one setting, see its value and who set it, and change it safely.
 *
 * Each section gates on ITS OWN permission: `platform:config` for the settings and prices,
 * `platform:secrets` for credentials, so a session that may change a calling window does
 * not thereby get to replace the voice engine's key. Nothing is mounted — and so nothing
 * is requested — for a session the server has refused, because on these surfaces the READ
 * carries the write's permission and a mounted panel's only outcome would be a 403 painted
 * as an outage (`admin/withheld.tsx`). The mount also waits for the identity read to have
 * ANSWERED (`identityAnswerPending`), so nothing appears, populates and is then replaced.
 */
export function ConfigScreen() {
  const mayConfigure = useAdminAccess("platform:config", "change platform configuration");
  const maySecrets = useAdminAccess("platform:secrets", "install or rotate credentials");
  const identityLoading = identityAnswerPending(useAdminMe());

  if (identityLoading || mayConfigure.refused) {
    return (
      <ConfigFrame
        fields={undefined}
        identityLoading={identityLoading}
        mayConfigure={mayConfigure}
        maySecrets={maySecrets}
      />
    );
  }
  return <ReadableConfigScreen mayConfigure={mayConfigure} maySecrets={maySecrets} />;
}

/** Mounted only for a session that may read the configuration, so the read fires only then. */
function ReadableConfigScreen({ mayConfigure, maySecrets }: { mayConfigure: Access; maySecrets: Access }) {
  const query = useOpsConfig();
  const read = query.error ? undefined : query.data;
  return (
    <ConfigFrame
      fields={read?.fields}
      identityLoading={false}
      mayConfigure={mayConfigure}
      maySecrets={maySecrets}
      status={read ? <ConfigStatus config={read} /> : null}
    />
  );
}

function ConfigFrame({
  fields,
  identityLoading,
  mayConfigure,
  maySecrets,
  status = null,
}: {
  fields: ConfigField[] | undefined;
  identityLoading: boolean;
  mayConfigure: Access;
  maySecrets: Access;
  status?: ReactNode;
}) {
  const sections = visibleSections(fields);
  const active = useActiveSection(sections) as ConfigSectionId;
  const spec = CONFIG_SECTIONS.find((section) => section.id === active);

  /*
   * DECLARED TO THE SCREEN ASSISTANT WITH NO INVENTORY. Which vendor credentials a
   * deployment holds is a targeting oracle (`apps/api/ops/secret_routes.py`), so no key
   * name, count or "none installed" leaves this screen, not even for a `platform:secrets`
   * holder. What it declares is which section is open and whether this operator may see
   * it, because "why can I not see the credentials" is answered by a permission.
   */
  useCopilotSurface({
    route: "/admin/ops/config",
    title: "Platform configuration",
    realm: "admin",
    fields: [],
    facts: [
      { key: "identity", label: "Has the permission check answered", value: identityLoading ? "not yet" : "yes" },
      { key: "section", label: "Section open", value: spec?.label ?? active },
      {
        key: "platform_config",
        label: "Sections on platform:config — every section except credentials",
        value: identityLoading ? "unknown" : mayConfigure.refused ? "withheld" : "shown",
      },
      {
        key: "platform_secrets",
        label: "Section on platform:secrets — credentials and key management",
        value: identityLoading ? "unknown" : maySecrets.refused ? "withheld" : "shown",
      },
      {
        key: "no_inventory",
        label: "What this screen tells the assistant about stored credentials",
        value: "nothing — not a key name, not a count",
      },
    ],
    apply: noFill,
  });

  return (
    <div className="space-y-5 pb-12">
      <div className="space-y-3">
        <p className="flex items-center gap-1 text-sm text-ink-muted">
          Changes are recorded in the audit log with your reason. Stored keys are never shown.
          <InfoTip label="Platform configuration">
            <p>
              These are the settings you can change without logging into the server, and the
              vendor keys the platform signs in with. A change reaches the whole platform within
              a few seconds; a setting that needs a restart is the exception, and each row says
              which it is. A stored key can only be replaced, never shown back.
            </p>
          </InfoTip>
        </p>
        {status}
      </div>

      <SettingsLayout
        label="Configuration sections"
        sections={sections.map(({ id, label }) => ({ id, label }))}
        renderSection={(id) => (
          <SectionContent
            id={id as ConfigSectionId}
            identityLoading={identityLoading}
            mayConfigure={mayConfigure}
            maySecrets={maySecrets}
          />
        )}
      />
    </div>
  );
}

function SectionContent({
  id,
  identityLoading,
  mayConfigure,
  maySecrets,
}: {
  id: ConfigSectionId;
  identityLoading: boolean;
  mayConfigure: Access;
  maySecrets: Access;
}) {
  const spec = CONFIG_SECTIONS.find((section) => section.id === id);
  const hint = spec ? <p className="-mt-2 mb-4 text-sm text-ink-muted">{spec.hint}</p> : null;

  if (identityLoading) {
    return (
      <>
        {hint}
        <Card>
          <Skeleton rows={3} label={`Checking whether you may see ${spec?.label.toLowerCase() ?? "this section"}…`} />
        </Card>
      </>
    );
  }

  if (id === "credentials") {
    // THE SHARPEST EDGE IN EITHER CONSOLE: the withheld cards say what each panel is for
    // and nothing whatever about what is installed.
    return (
      <div className="space-y-5">
        {hint}
        {maySecrets.refused ? (
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

  return (
    <div className="space-y-5">
      {hint}
      {mayConfigure.refused ? (
        <WithheldSection id={id} reason={mayConfigure.reason} />
      ) : (
        <ConfigSectionBody id={id} access={mayConfigure} />
      )}
    </div>
  );
}
