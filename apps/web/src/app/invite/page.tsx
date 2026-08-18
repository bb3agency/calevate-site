"use client";

/**
 * `/invite?token=…` — the Clerk-era invite page, kept as a REDIRECT and nothing else.
 *
 * ## Why this file still exists at all
 *
 * D-177 collapsed two invite pages into one. This was the Clerk-era half: it asked an
 * invitee to create a vendor account first, then POSTed the token from a signed-in
 * session, and its whole middle section existed to explain a refusal
 * (`invitation_wrong_recipient`) that cannot arise any more. Its successor is
 * `/auth/accept-invitation` (D-174), which takes the password in the same call and reads
 * the address off the invitation.
 *
 * What it cannot be is DELETED, and that is the only reason there is a file here. This
 * URL was minted into emails and chat messages by every owner who has ever used the team
 * screen, and those messages are not editable. A 404 would tell somebody holding a live,
 * single-use credential that their invitation is broken; they get one. So the URL keeps
 * working and forwards the token — the same token, the same parameter name — to the page
 * that redeems it.
 *
 * ## Why a client redirect rather than `next.config` or a 410
 *
 * `redirects()` in `next.config.ts` is the tidier mechanism and is wrong here for one
 * reason: it runs at the EDGE, and the token would be forwarded by a `Location` header
 * this app never sees. That is fine for privacy (the token is in the URL either way) and
 * bad for the property `useLinkToken` exists to hold — the token is taken OUT of the URL
 * on arrival, so it is not left in browser history or in a screenshot. Landing on the
 * successor page as an ordinary navigation is what lets that happen.
 *
 * A 410 was the other option the brief allowed and is rejected for the same reason a 404
 * is: it strands a working credential. `replace` rather than `assign`, so the dead URL
 * does not sit in the back button waiting to bounce again.
 */

import { useEffect } from "react";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { Skeleton } from "@/components/ui";
import { INVITE_TOKEN_PARAM, inviteLink } from "@/lib/api/members";

export default function LegacyInvitePage() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const token = (
      new URL(window.location.href).searchParams.get(INVITE_TOKEN_PARAM) ?? ""
    ).trim();
    // A visit with no token is somebody who typed the path. Send them to the same place;
    // the successor page has the one sentence worth showing for a link with nothing in it.
    window.location.replace(inviteLink(token));
  }, []);

  return (
    <Providers>
      <AuthPageFrame realmLabel="Client console">
        <Skeleton rows={3} label="Opening your invitation…" />
      </AuthPageFrame>
    </Providers>
  );
}
