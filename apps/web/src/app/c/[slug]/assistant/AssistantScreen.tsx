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
      <div className="space-y-5 pb-12">
        <PageHeader description="What the assistant is doing for this client, and everything it did." />
        <EmptyState
          message="The assistant is not available while you view this account."
          hint="Asking it would spend the client's own allowance. The client can use it on their own dashboard."
        />
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
