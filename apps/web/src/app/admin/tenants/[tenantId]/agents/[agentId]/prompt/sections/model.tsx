"use client";

import Link from "next/link";

import type { useAdminAccess } from "@/app/admin/access";
import { TenantEngineModels } from "@/components/engineCatalogueList";
import type { Agent } from "@/lib/api/agents";
import { useTenantEngineCatalogue } from "@/lib/api/engineCatalogue";

import { ModelBandControl } from "./modelBand";

/**
 * WHICH LANGUAGE MODEL THIS AGENT RUNS ON, apart from its voice (founder, 11 Oct 2026).
 *
 * On a voice platform that runs its own models (ThinnestAI) this is the platform's real list,
 * each with its maker's mark, whether it costs extra and its reply speed. Only models the
 * platform says can answer a call on this account's plan and that are included in the
 * per-minute price are listed (D-750); on a Studio voice, only the ones it allows beside our
 * voice key. A model nobody has checked yet carries the control that records it. The client
 * never sees this list, and chooses no model at all on this platform.
 *
 * On an engine that runs our own models the account's tier decides, so this points there.
 */
export function ModelPanel({
  tenantId,
  slug,
  agent,
  write,
}: {
  tenantId: string;
  slug: string;
  agent: Agent | undefined;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const catalogue = useTenantEngineCatalogue(slug);
  const ownModels = catalogue.data !== undefined && !catalogue.data.available;
  return (
    <div className="space-y-4">
      <p className="max-w-prose text-body text-ink-muted">
        The model that writes what this agent says. A change applies from its next call.
      </p>
      {ownModels ? (
        <p className="text-body text-ink-muted">
          This voice platform runs Calevate&apos;s own models, chosen by the account&apos;s
          tier.{" "}
          <Link
            href={`/admin/tenants/${tenantId}/llm-model`}
            className="font-medium underline underline-offset-2 hover:text-ink"
          >
            Open the account&apos;s AI model
          </Link>
        </p>
      ) : (
        <TenantEngineModels
          slug={slug}
          agent={agent}
          disabledReason={write.allowed ? null : write.reason}
          bandControl={(entry) => <ModelBandControl model={entry} />}
        />
      )}
    </div>
  );
}
