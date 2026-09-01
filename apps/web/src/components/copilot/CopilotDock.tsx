"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { BotMessageSquare } from "lucide-react";

import { adminSession } from "@/lib/api/admin";
import type { Session } from "@/lib/api/client";
import { useClientSession } from "@/lib/api/session";
import { fallbackSurface } from "@/lib/copilot/fallback";
import { useCopilotSurfaceHolder, type SurfaceHolder } from "@/lib/copilot/registry";

import { CopilotPanel } from "./CopilotPanel";

/**
 * The floating launcher, and the panel it anchors — mounted once per realm shell.
 *
 * ## IT ALWAYS RENDERS, AND THIS PARAGRAPH USED TO ARGUE THE OPPOSITE (D-501)
 *
 * The old rule was that a screen becomes assistable by calling `useCopilotSurface`
 * (`lib/copilot/registry.ts`) and in no other way, so that a screen with no declaration
 * showed no launcher at all. The reason given was sound and is worth keeping in view: a
 * launcher that "opens onto an empty context" — an assistant that can see nothing and fill
 * nothing — teaches a person the feature is broken on the screen where they first tried it,
 * which is worse than no launcher.
 *
 * WHAT ANSWERS IT IS THAT THE CONTEXT IS NOT EMPTY. An undeclared screen still sends the
 * ROUTE the person is on, a title derived from it, an explicit "this screen did not
 * describe itself" fact, and — the part that carries the feature — the assistant keeps all
 * of its read tools. `leads_search`, `business_snapshot`, `campaigns_list`, `agents_list`,
 * `calls_recent` and `search_knowledge` answer from the account's own rows and know nothing
 * about which screen asked, so "how many leads do I have?" is answered exactly as well on a
 * screen that declared nothing as on one that declared forty fields. The failure mode the
 * old comment feared — a launcher that does nothing — is not the failure mode available
 * here; what is available is "slightly less context", which is a degradation and not a
 * disappearance. The empty-context objection would apply again the day the read tools go
 * away, and then this comment should be re-read rather than this behaviour kept.
 *
 * Every screen in both consoles declares itself today (30/30 client, 23/23 admin), so this
 * is INSURANCE for the next screen somebody adds, not a repair of a present hole.
 *
 * ## The fallback is composed HERE and is never registered
 *
 * `registry.ts` is a stack whose top entry wins, and a parent's effect commits AFTER its
 * children's — so a shell that declared a generic surface would sit ON TOP of the real
 * declaration made by the screen inside it and shadow it (which has already cost this
 * console two field lists once). Reading the stack and falling back only when it is EMPTY
 * has no such ordering: a real declaration wins by construction, in any mount order,
 * because the fallback is never in the stack to compete.
 *
 * ## Position, and the one collision it accepts
 *
 * Bottom-right, the conventional corner, at `z-[70]`. `components/interior/toaster.tsx`
 * puts the toast lane in the same corner at `z-[60]` and 360px wide, so a toast fires
 * BEHIND the 44px launcher and its bottom-right corner is covered. That is the accepted
 * trade rather than an oversight: moving the launcher left would put it over the
 * sidebar's account block above `lg`, and lowering it under the toasts would make the
 * control unclickable exactly while a toast is showing — a dead button is a worse defect
 * than a clipped corner of a notification that also says its text on the left.
 *
 * ## Realm
 *
 * Two exported wrappers rather than one component taking a session, because the two
 * realms obtain a session in ways that cannot be selected at runtime: the client realm
 * READS A HOOK that must run inside `ClientRealmProvider`, and the admin realm calls a
 * plain builder. A single component branching on a prop would be a conditional hook.
 */
export function CopilotDock({
  session,
  realm,
}: {
  session: Session;
  realm: "client" | "admin";
}) {
  const declared = useCopilotSurfaceHolder();
  const pathname = usePathname();
  // Memoised on the address, so the holder's identity is as stable as a screen's own
  // registration is — the effect below closes the panel whenever the holder changes, and a
  // fresh object per render would slam it shut on every keystroke of every form.
  const fallback = useMemo<SurfaceHolder>(() => {
    const surface = fallbackSurface(pathname, realm);
    return { read: () => surface };
  }, [pathname, realm]);
  const holder = declared ?? fallback;
  const [isOpen, setIsOpen] = useState(false);
  const launcher = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  // Set while the panel is closing, so focus is returned to the launcher — the modal
  // contract's last step, kept even though the panel deliberately does not trap focus.
  const shouldRestoreFocus = useRef(false);

  // A navigation swaps the surface underneath an open panel. The conversation is about
  // the OLD screen's fields, so it must not survive: closing is the honest response, and
  // it is what keeps `CopilotPanel`'s conversation state from being reused across two
  // different forms (it is unmounted, so there is nothing to reset).
  useEffect(() => {
    setIsOpen(false);
  }, [holder]);

  useEffect(() => {
    if (isOpen || !shouldRestoreFocus.current) return;
    shouldRestoreFocus.current = false;
    launcher.current?.focus();
  }, [isOpen]);

  return (
    <>
      <button
        ref={launcher}
        type="button"
        aria-expanded={isOpen}
        aria-label={isOpen ? "Close the screen assistant" : "Ask about this screen"}
        onClick={() => {
          shouldRestoreFocus.current = isOpen;
          setIsOpen((open) => !open);
        }}
        className="fixed bottom-4 right-4 z-[70] flex h-11 w-11 items-center justify-center rounded-full border border-line bg-brand-strong text-white shadow-lg transition-colors hover:bg-brand-deep focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
      >
        {/* `BotMessageSquare` — a bot inside a speech bubble.
         *
         * It replaced `Sparkles`, and the reason is what the two icons SAY. Sparkles is
         * the industry's badge for "generated by a model": it is on the re-summarise
         * button, the script draft and eight other surfaces in this console, so as a
         * launcher it meant "AI happens here" rather than "there is someone here you can
         * ask" — and it was the tenth copy of a glyph that is supposed to mark a feature,
         * not a doorway. `Wand2` and `Stars` are the same claim in different clothes
         * ("magic"), and `Wand2` is worse now that the assistant can propose real changes
         * to leads and campaigns: a wand promises something happens by itself, which is
         * precisely the opposite of the confirmation design.
         *
         * The two honest candidates were `Bot` and `MessageCircle`/`MessageSquare`. `Bot`
         * is already the console's word for a VOICE AGENT — the roster, the call detail
         * and the tenant page all use it for the thing that answers the phone — so a
         * launcher wearing it would name the client's product, not ours. A bare message
         * bubble is unmistakably "chat" and reads well at 20px, but it is also what every
         * support widget on the internet looks like, and this is not a route to a human.
         *
         * `BotMessageSquare` is the compound of exactly those two ideas and is used
         * nowhere else in this tree (grepped). At 20px it holds up: one filled-weight
         * bubble silhouette carries the shape, and the antenna breaks the outline at the
         * top so it does not read as a plain square against the round launcher. */}
        <BotMessageSquare aria-hidden className="h-5 w-5" />
      </button>
      {isOpen && (
        <CopilotPanel
          session={session}
          holder={holder}
          realm={realm}
          labelledBy={titleId}
          onClose={() => {
            shouldRestoreFocus.current = true;
            setIsOpen(false);
          }}
        />
      )}
    </>
  );
}

/** Mounted by `app/c/[slug]/layout.tsx`, INSIDE `ClientRealmProvider`. */
export function ClientCopilotDock() {
  return <CopilotDock session={useClientSession()} realm="client" />;
}

/** Mounted by `app/admin/layout.tsx`. `adminSession()` takes no org — an operator's
 *  session is not scoped to one tenant, and the screens that are name it in the path. */
export function AdminCopilotDock() {
  return <CopilotDock session={adminSession()} realm="admin" />;
}
