"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";

import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import {
  ClientAssistantWorkspace,
  focusMain,
  type Destination,
} from "@/components/copilot/workspace/AssistantWorkspace";
import { useClientRealm } from "@/lib/api/session";
import { resolveDestination } from "@/lib/copilot/navigate";

import { ASSISTANT_COPY as COPY } from "./copy";

/**
 * The client's assistant page. Inside a view-as session the assistant is closed (asking it
 * would spend the client's own allowance), so an operator sees why rather than a page of
 * refusals.
 */
export function AssistantScreen() {
  const realm = useClientRealm();
  const router = useRouter();
  const slug = realm.session.orgSlug;
  const onNavigate = useCallback(
    (destination: Destination) => {
      const path = resolveDestination(destination.route, slug);
      if (path === null) return;
      router.push(realm.href(path));
      focusMain();
    },
    [realm, router, slug],
  );

  if (realm.session.impersonateOrg) {
    return (
      <div className="max-w-4xl space-y-5 pb-12">
        <PageHeader description={COPY.viewAsDescription} />
        <EmptyState message={COPY.viewAsOff} hint={COPY.viewAsWhy} />
      </div>
    );
  }
  return (
    <ClientAssistantWorkspace
      session={realm.session}
      route={`/c/${slug}/assistant`}
      onNavigate={onNavigate}
    />
  );
}
