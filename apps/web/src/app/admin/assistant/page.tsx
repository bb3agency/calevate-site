"use client";

import { useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";

import {
  AdminAssistantWorkspace,
  focusMain,
  type Destination,
} from "@/components/copilot/workspace/AssistantWorkspace";
import { RestrictionNote } from "@/components/ui";
import { adminSession } from "@/lib/api/admin";
import { resolveAdminDestination } from "@/lib/copilot/navigate";

import { useAdminAccess } from "../access";

/** `/admin/assistant`: the admin assistant's conversation and its activity log (D-694). */
export default function AdminAssistantPage() {
  const session = useMemo(() => adminSession(), []);
  const router = useRouter();
  const access = useAdminAccess("copilot:admin", "use the assistant");
  const onNavigate = useCallback(
    (destination: Destination) => {
      const path = resolveAdminDestination(destination.route);
      if (path === null) return;
      router.push(path);
      focusMain();
    },
    [router],
  );
  if (access.refused) return <RestrictionNote reason={access.reason} />;
  return <AdminAssistantWorkspace session={session} onNavigate={onNavigate} />;
}
