"use client";

import { useSearchParams } from "next/navigation";

import { RestrictionNote, Skeleton } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

import { MakeCallScreen } from "./MakeCallScreen";

/**
 * `/c/{slug}/make-a-call`: one AI call to one person, now or at a time (founder, 5 Nov 2026).
 * The one form every Call button opens; `?lead=`, `?call=`, `?agent=` and `?when=later`
 * pre-fill it (`lib/api/oneCall.makeCallHref`). Placing a call is `leads:dispatch`.
 */
export default function MakeCallPage() {
  const { session } = useClientRealm();
  const me = useMe(session);
  const params = useSearchParams();
  const refused = me.data !== undefined && !me.data.permissions.includes("leads:dispatch");
  if (refused) {
    return (
      <RestrictionNote reason="Only an account owner can place calls. Ask them to make this call." />
    );
  }
  if (me.data === undefined && me.error == null) {
    return <Skeleton rows={4} label="Loading the call form" />;
  }
  return (
    <MakeCallScreen
      // A new pre-fill is a new form: a lead's Call after a number's must not keep its fields.
      key={params.toString()}
      leadId={params.get("lead") ?? undefined}
      callId={params.get("call") ?? undefined}
      agentId={params.get("agent") ?? undefined}
      later={params.get("when") === "later"}
    />
  );
}
