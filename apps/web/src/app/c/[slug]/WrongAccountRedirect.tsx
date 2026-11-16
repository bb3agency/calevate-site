"use client";

/**
 * An account address this person does not belong to — a mistyped slug, an old bookmark —
 * takes them to the same page in their own account (founder, 16 Nov 2026), instead of
 * "You do not have access" on every screen. Only when the slug-less `/v1/me` names exactly
 * one account: a person in several gets `org_required` there, and this then leaves the
 * refusal on screen rather than guessing which account they meant.
 */

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { ApiProblem } from "@/lib/api/client";
import { useMe, useUnscopedMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

export function WrongAccountRedirect({ slug }: { slug: string }) {
  const { session } = useClientRealm();
  const me = useMe(session);
  const refused = me.error instanceof ApiProblem && me.error.status === 403 && me.error.code === "forbidden";
  return refused ? <GoToOwnAccount slug={slug} /> : null;
}

function GoToOwnAccount({ slug }: { slug: string }) {
  const own = useUnscopedMe();
  const router = useRouter();
  const pathname = usePathname();
  const target = own.data?.organization?.slug ?? null;
  useEffect(() => {
    if (!target || target === slug) return;
    const prefix = `/c/${slug}`;
    const rest = pathname.startsWith(prefix) ? pathname.slice(prefix.length) : "";
    router.replace(`/c/${target}${rest}${window.location.search}`);
  }, [target, slug, pathname, router]);
  return null;
}
