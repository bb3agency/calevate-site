"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { usePathname, useRouter } from "next/navigation";
import { AnimatePresence } from "motion/react";
import { createPortal } from "react-dom";

import { PipMark } from "@/components/illustration/pip";
import { MAIN_CONTENT_ID } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { fallbackSurface } from "@/lib/copilot/fallback";
import { useAssistantRequests } from "@/lib/copilot/launcher";
import { resolveDestination } from "@/lib/copilot/navigate";
import { useCopilotSurfaceHolder, type SurfaceHolder } from "@/lib/copilot/registry";

import { ViewAsPanel } from "./ViewAsPanel";

/*
 * THE PANEL IS ITS OWN CHUNK. The dock is in both consoles' layouts, so a static import put
 * the whole conversation (the stream, attachments, office-file reading, proposals, jobs)
 * into the first load of every screen, for a panel that is closed until somebody asks.
 * It is fetched when the browser is idle after the screen has loaded, and on the
 * launcher's hover or focus if that comes first, so opening it does not wait on the
 * network (vercel-react-best-practices: bundle-dynamic-imports, bundle-preload).
 */
const loadPanel = () => import("./CopilotPanel");
const CopilotPanel = dynamic(() => loadPanel().then((m) => m.CopilotPanel), { ssr: false });

function preloadPanel(): void {
  void loadPanel();
}

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
 * Bottom-right, the conventional corner, on the `z-assistant` layer. The toast lane
 * (`components/interior/toaster.tsx`, `z-toast`) shares the corner and sits above it:
 * a toast is short-lived and says its text on the left, so it may cover the launcher's
 * corner for a few seconds. Moving the launcher left would put it over the sidebar's
 * account block above `lg`.
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
  // The portal target exists only in the browser; mounting it after hydration keeps the
  // server and first client render identical.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    if (typeof window.requestIdleCallback !== "function") {
      const timer = window.setTimeout(preloadPanel, 2000);
      return () => window.clearTimeout(timer);
    }
    const idle = window.requestIdleCallback(preloadPanel, { timeout: 4000 });
    return () => window.cancelIdleCallback(idle);
  }, []);
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

  // ON THE ASSISTANT'S OWN PAGE, and on the first-agent screen (D-854), the conversation is
  // laid into the page, so a second copy of it in a side panel would be two transcripts of
  // one thread on one screen.
  const onWorkspace = /^\/((c\/[^/]+|admin)\/assistant|c\/[^/]+\/agents\/first)\/?$/.test(pathname ?? "");

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
        // One name in both states; `aria-expanded` says whether the panel is open.
        aria-label={`Ask ${ASSISTANT_NAME}`}
        onPointerEnter={preloadPanel}
        onFocus={preloadPanel}
        onClick={() => {
          shouldRestoreFocus.current = isOpen;
          setIsOpen((open) => !open);
        }}
        // THE CLIENT'S LAUNCHER IS A QUIET HEADER BUTTON (REDESIGN-2): bordered, ink,
        // Pip's face and "Ask Pip" (D-772). It sits beside the bell as one of the header's
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
                  : "fixed bottom-[calc(1rem+env(safe-area-inset-bottom,0px))] right-4 z-assistant flex h-11 w-11 items-center justify-center rounded-full border border-line shadow-raised"
              } text-white press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 ${
                realm === "admin"
                  ? "bg-slate-900 hover:bg-slate-700 dark:bg-slate-200 dark:text-slate-900 dark:hover:bg-slate-400"
                  : "bg-brand-strong hover:bg-brand-deep"
              }`
        }
      >
        {realm === "client" && placement === "header" ? (
          <>
            <PipMark size={20} />
            <span className="hidden sm:inline">Ask {ASSISTANT_NAME}</span>
          </>
        ) : (
          <PipMark size={24} />
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
          sits in. `AnimatePresence` lets it leave the way it came in. Portalled into
          `document.body`: the launcher lives in the sticky top bar, whose stacking context
          would otherwise hold the panel under the page's own sticky bars. */}
      {mounted &&
        createPortal(
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
          </AnimatePresence>,
          document.body,
        )}
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
