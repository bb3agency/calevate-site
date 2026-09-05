"use client";

/**
 * The conversation, as it comes back off the server (D-540).
 *
 * Before this the whole chat was `useState<CopilotTurn[]>([])`, so a refresh, a route
 * change that unmounted the dock, or a closed browser lost it. It is now stored per
 * PERSON — the same thread on a phone and a desktop — and it ends when their last
 * session ends.
 *
 * ## What a second device sees, since it is the question this design has to answer
 *
 * **IT REFRESHES WHEN YOU COME BACK TO THE TAB, AND THAT IS THE WHOLE SYNC MODEL.** The
 * founder's decision, and it is bought with `refetchOnWindowFocus` — the option this
 * console already runs on by default (`app/providers.tsx` sets no other) — plus one
 * refetch after anything this device sends. So a phone and a desktop converge the moment
 * either is looked at, and there is no socket, no poll and no channel behind an open panel.
 *
 * The alternatives were priced and each buys nothing here. **SSE is one-way**, so a panel
 * on it still needs a separate request to send anything and the send is what already
 * refreshes us ("Long polling vs WebSockets", getstream.io, read 5 Sep 2026 — ⚠ EVIDENCE
 * CLASS: REPORTED, the host is egress-blocked from this container and the reading was
 * relayed). **Multi-connection ordering needs application-level sequence numbers**, and
 * timestamp last-write-wins has known defects (Ably, "reliable message ordering", same
 * date and same class) — a focus refetch sidesteps that entirely, because the SERVER's
 * `created_at, id` order is the only order anybody ever renders.
 *
 * Both devices write to the same rows, so nothing is lost either way; what the refetch
 * adds is that neither has to be reloaded to see the other.
 *
 * ## `content` is the redacted form, and that is visible
 *
 * A live turn holds two strings — what the person reads, with the screen's own digits
 * restored, and the wire form with the placeholders still in it — and only the second is
 * ever stored (`apps/api/copilot/transcript.py` argues why). So a turn re-read after a
 * reload shows `«PHONE_1»` where the live one showed the number, and `wire` and `content`
 * are the same string on a loaded turn. That is the cost of not keeping a caller's digits
 * in a durable row, and it is the right way round.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "@/lib/api/client";

import type { CopilotTurn } from "./useCopilotConversation";

/** How many turns one page carries. The server caps `limit` at 100 and the store at 200. */
export const CONVERSATION_PAGE = 50;

const CLIENT_PATH = "/v1/copilot/conversation";
const ADMIN_PATH = "/v1/admin/copilot/conversation";

/**
 * WHICH ENDPOINT THIS REALM READS. Derived from the realm the dock was mounted with, never
 * from the pathname — `copilotAskPath` makes the same choice for the same reason, and the
 * two must agree or a conversation would be written on one realm and read on the other.
 */
export function conversationPath(realm: "client" | "admin"): string {
  return realm === "admin" ? ADMIN_PATH : CLIENT_PATH;
}

interface StoredTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  screen_route: string;
  said_at: string;
}

interface ConversationBody {
  turns: StoredTurn[];
  has_more: boolean;
}

/**
 * The stored conversation as the panel's own turn shape, oldest first.
 *
 * `content` and `wire` are the SAME string here, deliberately, and the reason is the one
 * thing about replaying history that could go wrong: `wire` is what may be sent back to
 * the server as `history`, so it must be the redacted form. Setting `content` to anything
 * richer would need digits we do not have; setting `wire` to anything richer would hand
 * the server exactly what the field redaction withheld.
 */
export async function loadConversation(
  session: Session,
  realm: "client" | "admin",
): Promise<CopilotTurn[]> {
  const body = await apiRequest<ConversationBody>(
    session,
    `${conversationPath(realm)}?limit=${CONVERSATION_PAGE}`,
  );
  return body.turns.map((turn) => ({
    id: turn.id,
    role: turn.role,
    content: turn.content,
    wire: turn.content,
  }));
}

/**
 * The cache key.
 *
 * Per REALM, because the two realms are two conversations in two tables — and per ORG
 * SLUG, because one `QueryClient` outlives a switch between accounts (D-22 "View as
 * client") and the key is the only thing keeping two tenants' cached data apart. The
 * admin conversation is not per-tenant, so the slug there only costs a refetch when the
 * account on screen changes; a shared key would cost the wrong thread on screen, which is
 * not a trade worth making for one request.
 */
export function conversationKey(orgSlug: string, realm: "client" | "admin"): readonly unknown[] {
  return ["copilot", "conversation", orgSlug, realm];
}

/**
 * The stored conversation as a query, so the tab getting focus refreshes it.
 *
 * `staleTime: 0` rather than the client default of ten seconds: the whole point is that
 * coming back to the tab shows what the other device said, and a ten-second window in
 * which focus does nothing is the one case a person would notice ("I sent it on my phone
 * and the laptop still doesn't have it").
 *
 * `refetchOnWindowFocus` and `refetchOnReconnect` are handed the SAME predicate, and it is
 * the one rule this query has: **never refetch while an answer is streaming.** The panel
 * appends its turns to this cache as they complete, so a refetch that landed mid-exchange
 * would replace the list with a server page taken before the question was asked — the
 * person would watch their own message disappear. `streaming()` reads a ref, so the answer
 * is the truth at the instant focus fires rather than whatever a render last captured.
 */
export function useConversation(
  session: Session,
  realm: "client" | "admin" | null,
  streaming: () => boolean,
): UseQueryResult<CopilotTurn[]> {
  return useQuery({
    queryKey: conversationKey(session.orgSlug, realm ?? "client"),
    queryFn: () => loadConversation(session, realm ?? "client"),
    enabled: realm !== null,
    staleTime: 0,
    refetchOnWindowFocus: () => !streaming(),
    refetchOnReconnect: () => !streaming(),
  });
}

/** Forget it, on every device. Returns how many turns were removed. */
export async function clearConversation(
  session: Session,
  realm: "client" | "admin",
): Promise<number> {
  const body = await apiRequest<{ cleared: number }>(session, conversationPath(realm), {
    method: "DELETE",
  });
  return body.cleared;
}
