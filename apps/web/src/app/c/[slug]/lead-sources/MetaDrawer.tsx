"use client";

import { Drawer } from "@/components/console/drawer";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import type { LeadSource, useIngestActivity, useMetaRedrive, useMetaSetup } from "@/lib/api/leadSources";

import { MetaRecovery } from "./MetaRecovery";
import { MetaSetupDetails } from "./MetaSetupDetails";
import { rowName } from "./SourcesList";

/**
 * ONE META SOURCE: what to paste into the Meta App Dashboard, and the leads we recorded
 * but could not read. The setup read is fired when the drawer opens (`LeadSourcesScreen`),
 * and both results are reset whenever a different source is opened, so a recovery count
 * is never left standing under another Page.
 */
export function MetaDrawer({
  source,
  onClose,
  metaSetup,
  redrive,
  activity,
  canWrite,
  refusal,
}: {
  source: LeadSource | null;
  onClose: () => void;
  metaSetup: ReturnType<typeof useMetaSetup>;
  redrive: ReturnType<typeof useMetaRedrive>;
  activity: ReturnType<typeof useIngestActivity>;
  canWrite: boolean;
  /** Why this viewer cannot read the setup (it is an `org:manage` route), if they cannot. */
  refusal: string | null;
}) {
  return (
    <Drawer
      open={source !== null}
      onClose={onClose}
      title="Meta setup"
      description={source ? rowName(source) : undefined}
      width="lg"
      initialFocus="container"
    >
      <RestrictionNote reason={canWrite ? null : refusal} />
      {metaSetup.isPending && <Skeleton rows={4} />}
      {metaSetup.error != null && <ProblemNotice error={metaSetup.error} />}
      {metaSetup.data && <MetaSetupDetails setup={metaSetup.data} />}
      {source && (
        <MetaRecovery sourceId={source.id} activity={activity} redrive={redrive} canWrite={canWrite} />
      )}
    </Drawer>
  );
}
