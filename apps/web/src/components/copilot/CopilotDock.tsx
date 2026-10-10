"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { BotMessageSquare, MessageCircleQuestion } from "lucide-react";
import { AnimatePresence } from "motion/react";

import { MAIN_CONTENT_ID } from "@/components/ui";
import { adminSession } from "@/lib/api/admin";
import type { Session } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";
import { fallbackSurface } from "@/lib/copilot/fallback";
import { useAssistantRequests } from "@/lib/copilot/launcher";
import { resolveAdminDestination, resolveDestination } from "@/lib/copilot/navigate";
import { useCopilotSurfaceHolder, type SurfaceHolder } from "@/lib/copilot/registry";

import { CopilotPanel } from "./CopilotPanel";
import { ViewAsPanel } from "./ViewAsPanel";

/**
 * The floating launcher, and the panel it anchors — mounted once per realm shell.
 *
 * ## IT ALWAYS RENDERS, EVEN ON A SCREEN THAT DECLARED NOTHING (D-501)
 *
 * The alternative — a launcher only on screens that call `useCopilotSurface`
 * (`lib/copilot/registry.ts`) — guards against a real failure worth keeping in view: a
 * launcher that opens onto an empty context teaches a person the feature is broken on the
 * screen where they first tried it, which is worse than no launcher.
 *
 * IT DOES NOT APPLY, BECAUSE THE CONTEXT IS NOT EMPTY. An undeclared screen still sends the
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
  navigation,
  placement = "floating",
}: {
  session: Session;
  realm: "client" | "admin";
  /**
   * WHERE THE LAUNCHER LIVES. `floating` is the bottom-right button. `header` renders it as
   * an ordinary control in the shell's top bar, and the panel then opens under the bar: a
   * floating button sits over whatever is in that corner of the page, and on the client
   * dashboard that was the last figure of the right-hand column.
   */
  placement?: "floating" | "header";
  /**
   * WHAT THE ASSISTANT NEEDS IN ORDER TO OPEN A SCREEN (D-524). Absent on the admin realm,
   * which has no screen inventory — and absent means the panel is given no `onNavigate`, so
   * a `navigate` frame there would be held and never acted on rather than half-handled.
   *
   * `slug` is what the route TEMPLATE on the wire is missing, and `href` is the client
   * realm's own link builder: inside a D-22 view-as session it carries the `view-as` marker
   * across the move, which a bare `router.push` would drop — turning an operator's next
   * screen into a client-session load. Both are passed IN rather than read here because
   * `useClientRealm()` throws outside its provider, and this component is mounted in both
   * shells.
   */
  navigation?: {
    slug: string;
    href: (path: string) => string;
    /** The admin realm checks a destination against its own sidebar (D-694). */
    resolve?: (route: string) => string | null;
  };
}) {
  const declared = useCopilotSurfaceHolder();
  const pathname = usePathname();
  const router = useRouter();
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

  // A button on the screen asked for the panel ("Let the assistant do this"). Opening is
  // the screen's request; SENDING stays the person's (`lib/copilot/launcher.ts`).
  const [request, setRequest] = useState<{ prompt: string; nonce: number } | null>(null);
  const nonce = useRef(0);
  useAssistantRequests((asked) => {
    nonce.current += 1;
    setRequest(asked.prompt ? { prompt: asked.prompt, nonce: nonce.current } : null);
    shouldRestoreFocus.current = false;
    setIsOpen(true);
  });

  // ON THE ASSISTANT'S OWN PAGE the conversation is laid into the page, so a second copy of
  // it in a side panel would be two transcripts of one thread on one screen.
  const onWorkspace = /^\/(c\/[^/]+|admin)\/assistant\/?$/.test(pathname ?? "");

  useEffect(() => {
    if (isOpen || !shouldRestoreFocus.current) return;
    shouldRestoreFocus.current = false;
    launcher.current?.focus();
  }, [isOpen]);

  /** Close, and hand the keyboard back to the launcher — the modal contract's last step.
   *  One function because BOTH panels close the same way, and a second copy is how the
   *  focus return comes to exist on one of them and not the other. */
  const closePanel = useCallback(() => {
    shouldRestoreFocus.current = true;
    setIsOpen(false);
  }, []);

  /*
   * WHAT A SCREEN CHANGE THE PERSON DID NOT CLICK FOR HAS TO SAY, AND WHERE (D-524).
   *
   * A route change that moves focus without announcing it strands a screen-reader user; one
   * that announces nothing and moves nothing leaves them on a launcher in a corner while the
   * page underneath has been replaced. This console does neither today — nothing announces a
   * navigation on any path — so the assistant's own moves say where they went and put the
   * caret at the top of the new screen.
   *
   * THE LIVE REGION IS HERE AND NOT IN THE PANEL because the panel does not survive the
   * move: the dock closes it when the surface underneath changes, so a message rendered
   * there would be removed in the same commit that was meant to announce it. The dock is
   * mounted by the layout and outlives every route change in the realm.
   *
   * FOCUS GOES TO `#main-content`, which is the skip link's own target and is already
   * `tabIndex={-1}` in both shells for exactly this reason — so a `Tab` after arriving
   * continues INTO the new screen rather than resuming in the sidebar the person did not
   * ask to be in. It is deliberately not the first heading (not focusable) and not the
   * document body (which announces nothing).
   */
  const [announcement, setAnnouncement] = useState("");
  const navigateTo = useCallback(
    (destination: { route: string; screen: string; where: string }) => {
      if (navigation === undefined) return;
      const path =
        navigation.resolve !== undefined
          ? navigation.resolve(destination.route)
          : resolveDestination(destination.route, navigation.slug);
      // A DESTINATION THIS CONSOLE DOES NOT HAVE MOVES NOBODY, and says nothing: the answer
      // beside it has already named the screen in words, so the honest response is to leave
      // the person where they are rather than to explain a defect they did not cause.
      if (path === null) return;
      setAnnouncement(`Opened ${destination.where}.`);
      router.push(navigation.href(path));
      // AFTER the push, so the element being focused belongs to the screen being arrived at.
      // `requestAnimationFrame` rather than a timeout: the App Router commits the new tree
      // before the next paint, and a guessed delay would be a race either way.
      requestAnimationFrame(() => {
        document.getElementById(MAIN_CONTENT_ID)?.focus();
      });
    },
    [navigation, router],
  );

  return (
    <>
      {!onWorkspace && (
      <button
        ref={launcher}
        type="button"
        aria-expanded={isOpen}
        aria-label={isOpen ? "Close the screen assistant" : "Ask about this screen"}
        onClick={() => {
          shouldRestoreFocus.current = isOpen;
          setIsOpen((open) => !open);
        }}
        // THE CLIENT'S LAUNCHER IS A QUIET HEADER BUTTON (REDESIGN-2): bordered, ink, a
        // question bubble and the word "Ask". It sits beside the bell as one of the header's
        // tools; a filled green robot tile was the loudest thing on every screen and
        // competed with each screen's own primary action. The admin realm keeps its slate
        // tile, the same signal its shell carries (`components/realmChrome.tsx`), so the
        // two consoles never look alike on the one control that floats over both.
        className={
          realm === "client" && placement === "header"
            ? "press inline-flex h-9 items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 text-body font-medium text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 aria-expanded:bg-ink/[0.06] touch:h-11 touch:min-w-11 touch:justify-center"
            : `${
                placement === "header"
                  ? "flex h-9 w-9 items-center justify-center rounded-md touch:h-11 touch:w-11"
                  : "fixed bottom-[calc(1rem+env(safe-area-inset-bottom,0px))] right-4 z-[70] flex h-11 w-11 items-center justify-center rounded-full border border-line shadow-raised"
              } text-white press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                realm === "admin"
                  ? "bg-slate-900 hover:bg-slate-700 dark:bg-slate-200 dark:text-slate-900 dark:hover:bg-slate-400"
                  : "bg-brand-strong hover:bg-brand-deep"
              }`
        }
      >
        {realm === "client" && placement === "header" ? (
          <>
            {/* A question bubble rather than a robot: it says "ask here", which is the job,
                and `Bot` is already this console's word for a voice agent. */}
            <MessageCircleQuestion aria-hidden className="h-4 w-4 text-ink-muted" />
            <span className="hidden sm:inline">Ask</span>
          </>
        ) : (
          <BotMessageSquare aria-hidden className="h-5 w-5" />
        )}
      </button>
      )}
      {/* WHERE THEY WERE JUST TAKEN. Always mounted and empty until there is something to
          say: a live region added to the DOM at the same moment as its text is not reliably
          announced, which is the classic way to ship an announcement nobody hears. */}
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
      {/* IN A D-22 VIEW-AS SESSION THE CLIENT ASSISTANT CANNOT ANSWER, and the honest
          response is to say so rather than to issue a request the server refuses.
          `copilot:use` is a MUTATING permission (asking spends the account's allowance)
          and is not impersonation-permitted, so all four client copilot routes answer an
          impersonating principal with 403 — `ViewAsPanel` carries the full argument.

          Read off the SESSION rather than off `viewAsRequested`, and the difference
          matters: `session.impersonateOrg` is exactly what makes `apiRequest` send
          `X-Impersonate-Org`, so this branch is true precisely when the request would be
          refused, and cannot drift from it. The admin realm never sets it. */}
      {/* THE SIDE PANEL (D-694): every screen, both realms, whichever corner the launcher
          sits in. `AnimatePresence` lets it leave the way it came in. */}
      <AnimatePresence>
        {isOpen &&
          !onWorkspace &&
          (session.impersonateOrg ? (
            <ViewAsPanel
              key="view-as"
              labelledBy={titleId}
              onClose={closePanel}
              placement="side"
            />
          ) : (
            <CopilotPanel
              key="panel"
              session={session}
              holder={holder}
              realm={realm}
              labelledBy={titleId}
              onNavigate={navigation === undefined ? undefined : navigateTo}
              onClose={closePanel}
              placement="side"
              request={request}
            />
          ))}
      </AnimatePresence>
    </>
  );
}

/** Mounted by `app/c/[slug]/layout.tsx`, INSIDE `ClientRealmProvider`. */
export function ClientCopilotDock({ placement }: { placement?: "floating" | "header" } = {}) {
  // `useClientRealm()` rather than `useClientSession()`: the assistant can now open a screen
  // (D-524), and both halves of that come from this context — the account's slug, which the
  // route template on the wire is missing, and `href`, which carries a view-as session's
  // marker across the move.
  const realm = useClientRealm();
  return (
    <CopilotDock
      session={realm.session}
      realm="client"
      navigation={{ slug: realm.session.orgSlug, href: realm.href }}
      placement={placement}
    />
  );
}

/** Mounted by `app/admin/layout.tsx`. `adminSession()` takes no org — an operator's
 *  session is not scoped to one tenant, and the screens that are name it in the path. */
export function AdminCopilotDock() {
  // HELD, because `adminSession()` BUILDS A NEW OBJECT on every call
  // (`lib/authn/realmSessions.ts::adminRealmSession` returns an object literal). Called
  // inline it changed identity on every render of this component, and `session` is a
  // dependency of `ask`, `reset` and the confirm mutation inside the panel — so all three
  // were rebuilt on every render, and anything that ever memoises on them would have been
  // silently defeated. The credential itself is read lazily through `session.token()`, so
  // holding the wrapper holds nothing stale.
  const session = useMemo(() => adminSession(), []);
  // THE ADMIN ASSISTANT CAN OPEN ITS OWN SCREENS (D-694): a destination is accepted only if
  // it is one of the admin sidebar's own entries.
  return (
    <CopilotDock
      session={session}
      realm="admin"
      navigation={{ slug: "", href: (path) => path, resolve: resolveAdminDestination }}
    />
  );
}
