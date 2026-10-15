"use client";

/**
 * The conversation, as it comes back off the server (D-540).
 *
 * Before this the whole chat was `useState<CopilotTurn[]>([])`, so a refresh, a route
 * change that unmounted the dock, or a closed browser lost it. It is now stored per
 * PERSON — the same thread on a phone and a desktop — and it ends when their last
 * session ends.
 *
 * ## What a second device sees (D-782, replacing D-542's refresh-on-focus)
 *
 * **IT IS TOLD, WITHIN A SECOND.** The server stores a question the moment it is asked and
 * its answer when it is finished, and after each write sends a `conversation` note on the
 * person's own live channel (`apps/api/copilot/live_sync.py`). `lib/live/topics.ts` maps
 * that note to this query's family, so every open window of that person refetches through
 * this ordinary, authorised route — and nobody else's does. The note carries no text and
 * no id (hard rule 6); `answering` in the response says Pip is still answering.
 *
 * Reconnect is the catch-up: a stream that opens again says `ready`, which refetches every
 * live family, this one included. The newest page IS the delta — a conversation is at most
 * `transcript.MAX_STORED_TURNS` turns and the panel shows the newest page — so there is no
 * separate "since" endpoint to keep in step with this one.
 *
 * The server's `created_at, id` order is the only order anybody renders, so two devices
 * asking at once both keep their turns, interleaved as stored.
 *
 * ## `content` is the redacted form, and that is visible
 *
 * A live turn holds two strings — what the person reads, with the screen's own digits
 * restored, and the wire form with the placeholders still in it — and only the second is
 * ever stored (`apps/api/copilot/transcript.py` argues why). So a turn read on ANOTHER
 * device, or after a reload, shows `«PHONE_1»` where the asking device showed the number.
 * The asking device keeps showing its own restored text for as long as the panel lives
 * (`useCopilotConversation`), so a turn does not change under the reader when its stored
 * copy arrives.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

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
  /** Absent from a server older than D-782, which never says. */
  answering?: boolean;
  uploads_available?: boolean;
  consent?: PipConsent;
}

/** One read of the stored conversation. */
export interface StoredConversation {
  /** Oldest first. */
  turns: CopilotTurn[];
  /** Pip is still answering a question this person asked, here or on another device. */
  answering: boolean;
  /**
   * Files can be attached to a question. False until a server says true, so the panel
   * never starts an upload the server would refuse while the body is still arriving.
   */
  uploadsAvailable: boolean;
  /**
   * Whether Pip is on for this account (D-788), or `null` when the server did not say. The
   * panel shows the owner's step or the locked sentence while it is `required` or
   * `outdated`; the server refuses an ask either way.
   */
  consent: PipConsent | null;
}

/** The server's `CopilotConsentOut`: what the owner reads, and whether this person may tick. */
export type PipConsent = components["schemas"]["CopilotConsentOut"];

/** Pip is locked for this account until the owner turns it on. */
export function pipLocked(consent: PipConsent | null | undefined): boolean {
  return consent?.status === "required" || consent?.status === "outdated";
}

export const EMPTY_CONVERSATION: StoredConversation = {
  turns: [],
  answering: false,
  uploadsAvailable: false,
  consent: null,
};

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
): Promise<StoredConversation> {
  const body = await apiRequest<ConversationBody>(
    session,
    `${conversationPath(realm)}?limit=${CONVERSATION_PAGE}`,
  );
  return {
    turns: body.turns.map((turn) => ({
      id: turn.id,
      role: turn.role,
      content: turn.content,
      wire: turn.content,
    })),
    answering: body.answering === true,
    uploadsAvailable: body.uploads_available === true,
    consent: body.consent ?? null,
  };
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
 *
 * The family is `copilot`, which `lib/live/topics.ts` puts under the `conversation` topic
 * alone: nothing else a live note announces refetches it.
 */
export function conversationKey(orgSlug: string, realm: "client" | "admin"): readonly unknown[] {
  return ["copilot", "conversation", orgSlug, realm];
}

/**
 * The stored conversation as a query: the live note, a reconnect and the tab getting focus
 * all refresh it.
 *
 * `staleTime: 0` rather than the client default of ten seconds, so coming back to a tab
 * whose stream was closed while hidden shows what the other device said at once.
 *
 * Focus and reconnect skip the refetch while an answer is streaming on THIS device: it is
 * a read nobody needs (the stream is the fresher copy) at the moment the panel is busiest.
 * A live note still refetches mid-stream, and that is safe — the merge in
 * `useCopilotConversation` matches turns by id.
 */
export function useConversation(
  session: Session,
  realm: "client" | "admin" | null,
  streaming: () => boolean,
): UseQueryResult<StoredConversation> {
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

/**
 * A new turn id, minted HERE so the device that asks can recognise its own question and
 * answer when the stored page brings them back (D-782) — matched by id, never by counting
 * or by text. The server stores the turn under exactly this id (`CopilotAskIn.turn_ids`)
 * and a repeat stores nothing twice.
 *
 * UUIDv7 (RFC 9562 §5.7: 48-bit Unix milliseconds, version 7, variant 10, random tail),
 * the shape every id in this system has, so the stored order's `id` tiebreak stays in time
 * order.
 */
export function newTurnId(now: number = Date.now()): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let ms = now;
  for (let i = 5; i >= 0; i -= 1) {
    bytes[i] = ms % 256;
    ms = Math.floor(ms / 256);
  }
  bytes[6] = (bytes[6]! & 0x0f) | 0x70;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const CONSENT_PATH = "/v1/copilot/consent";

/**
 * The account owner turning Pip on (D-788). It echoes the version and hash the panel showed,
 * so a panel opened before the words changed cannot accept words the owner never read. The
 * stored conversation takes the answer at once, so the panel unlocks without a second read;
 * every other member's panel reads it when it opens or its tab regains focus.
 */
export function useTurnPipOn(session: Session) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: (consent: Pick<PipConsent, "version" | "text_sha256">) =>
      apiRequest<PipConsent>(session, CONSENT_PATH, {
        method: "POST",
        body: { version: consent.version, text_sha256: consent.text_sha256 },
      }),
    onSuccess: (fresh) =>
      queries.setQueryData<StoredConversation>(
        conversationKey(session.orgSlug, "client"),
        (current) => ({ ...(current ?? EMPTY_CONVERSATION), consent: fresh }),
      ),
  });
}
