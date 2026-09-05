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
 * It sees everything up to the moment it loaded, plus whatever it says itself. There is
 * no realtime channel and none is built: this is one person's conversation with an
 * assistant, not shared state, and a person is not usually typing into two devices at
 * once. Both devices write to the same rows, so nothing is lost — the second device's
 * next load shows the first device's turns in their real order. Buying convergence would
 * mean a socket or a poll behind every open panel for a case whose cost is a reload.
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
    role: turn.role,
    content: turn.content,
    wire: turn.content,
  }));
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
