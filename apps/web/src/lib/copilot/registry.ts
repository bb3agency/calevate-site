"use client";

import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import type { CopilotFact, CopilotField, CopilotSurface } from "./types";

/**
 * Where a screen says what it holds, and where the dock in the layout reads it.
 *
 * The two ends are twenty components apart — `app/admin/layout.tsx` mounts the dock,
 * `admin/tenants/[id]/commercials/page.tsx` declares the fields — so this is a store and
 * not a context: a context provider would have to live in the layout and every screen
 * would have to be inside a consumer, which is the same wiring with a re-render on every
 * keystroke of every form in the console attached to it.
 *
 * `useSyncExternalStore` is React 18+'s prescribed way to read one (and the idiom
 * `components/navDrawer.tsx` already uses here for `matchMedia`).
 *
 * ## The part that is not obvious: what is IN the store
 *
 * Not the surface. A HOLDER that can be asked for the surface.
 *
 * A surface contains the CURRENT VALUE of every control on the screen, so it is a new
 * object on every keystroke. Storing it would notify the dock on every keystroke, which
 * would re-render the panel — including a half-typed question — for a value nobody is
 * looking at until the moment somebody presses Ask. The holder's identity is stable for
 * the life of the screen, so the store notifies exactly twice per screen (mount,
 * unmount), and the values are read at the instant they are needed and no earlier.
 *
 * ## A stack, not a slot
 *
 * Two surfaces can legitimately be mounted at once — a panel inside a screen that also
 * registers — and mount/unmount order is not guaranteed to interleave neatly. A stack
 * makes the innermost (last registered) the live one and makes an out-of-order unmount a
 * removal rather than a clobber of somebody else's registration.
 */

export interface SurfaceHolder {
  /** The surface as of the last commit. Never memoised — see the header. */
  read: () => CopilotSurface;
}

const stack: SurfaceHolder[] = [];
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

/** The live surface holder, or `null` when the screen on show declares nothing. */
function snapshot(): SurfaceHolder | null {
  return stack.length === 0 ? null : stack[stack.length - 1];
}

/**
 * The SERVER snapshot, and it is `null` for a reason rather than by omission: a
 * registration happens in an EFFECT, and effects do not run on the server, so `null` is
 * the truthful answer and the first client render agrees with it.
 *
 * The dock ALWAYS renders (D-501), falling back to a route-only surface while the stack is
 * empty, so `null` here costs one render of the fallback TITLE before a declaring screen's
 * effect commits, on a launcher whose panel is closed — never a launcher appearing and
 * disappearing.
 */
function serverSnapshot(): SurfaceHolder | null {
  return null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Register a holder; returns the un-registration. Exported for tests, not for screens. */
export function registerSurfaceHolder(holder: SurfaceHolder): () => void {
  stack.push(holder);
  notify();
  return () => {
    const at = stack.indexOf(holder);
    if (at !== -1) stack.splice(at, 1);
    notify();
  };
}

/** What the dock reads. `null` means "this screen has not declared itself". */
export function useCopilotSurfaceHolder(): SurfaceHolder | null {
  return useSyncExternalStore(subscribe, snapshot, serverSnapshot);
}

/**
 * DECLARE THIS SCREEN TO THE ASSISTANT. The one call a screen makes.
 *
 * ```tsx
 * useCopilotSurface({
 *   route: `/c/${slug}/agents/new`,
 *   title: "Build an agent",
 *   realm: "client",
 *   fields: [{ id: "new-agent-name", label: "Agent name", type: "text", value: name }],
 *   apply: (items) => { for (const item of items) … },
 * });
 * ```
 *
 * It renders nothing, returns nothing and never re-renders the caller. Passing a fresh
 * object literal on every render is the INTENDED use — there is deliberately no
 * dependency array to keep in step with the fields, which is the thing that silently goes
 * stale and leaves the assistant filling in a form it is reading a minute-old copy of.
 *
 * The write is in an effect rather than during render because a render may be discarded
 * (React can render a tree it then throws away); a committed effect cannot. The cost is
 * that between a keystroke and its commit the holder is one render behind, which is
 * unobservable: it is read from a click handler, and a click cannot land inside that gap.
 */
export function useCopilotSurface(surface: CopilotSurface | null): void {
  const scope = useContext(SurfaceScope);
  const latest = useRef(surface);
  // No dependency array: after EVERY commit, the holder sees exactly what was rendered.
  useEffect(() => {
    latest.current = surface;
  });
  /*
   * `null` DECLARES NOTHING, and since D-501 the launcher no longer disappears with it —
   * the dock falls back to a route-only surface, so what a `null` costs is the FIELD LIST,
   * not the assistant.
   *
   * A screen with more than one step is why it exists: the new-client wizard's step 1 is a
   * form, step 3 is a confirmation with an invite address on it, and the SAME component
   * renders both. Without this the step-1 declaration would still be live on step 3 and the
   * assistant would offer to fill in five controls that are no longer on the page — an
   * assistant confidently wrong about the screen, which is worse than one that says it
   * cannot see the screen, and it is why passing `null` is still the right answer there.
   *
   * Only the null-ness is a dependency, so a keystroke does not re-register (which would
   * push a second holder onto the stack every time), and a step change does.
   */
  const declares = surface !== null;
  useEffect(() => {
    if (!declares) return undefined;
    const holder = { read: () => latest.current as CopilotSurface };
    return scope ? scope.add(holder) : registerSurfaceHolder(holder);
  }, [declares, scope]);
}

/**
 * ONE SCREEN, SEVERAL PANELS, ONE SURFACE.
 *
 * A tab that mounts several panels which each declare themselves (an agent's Settings: call
 * handling, the model, what it is) would otherwise show the assistant only the newest of
 * them, because the stack above answers with its top. Inside a scope, every
 * `useCopilotSurface` below it is a PART, and the scope registers ONE holder that merges
 * the parts at read time: the scope's route and title, every part's fields and facts in
 * mount order (a field id or fact key seen twice keeps its first), each fill routed to the
 * part that declared that field, and `unsaved` true when any part says so.
 *
 * The alternative was to lift every panel's fields into the parent's one declaration (as
 * the teach box once took its screen's extra fields as a prop). That moves each panel's
 * state and queries up into a screen that does not otherwise need them; a scope leaves
 * each panel declaring what it owns.
 *
 * The holder's identity is stable for the scope's life, so a part arriving or leaving (a
 * disclosure opening) changes what the next read returns without re-registering, and the
 * dock, which closes its panel when the holder changes, stays open.
 */
interface ScopeValue {
  add: (part: SurfaceHolder) => () => void;
}

const SurfaceScope = createContext<ScopeValue | null>(null);

type ScopeOwn = Pick<CopilotSurface, "route" | "title" | "realm"> & { facts: CopilotFact[] };

export function CopilotSurfaceScope({
  route,
  title,
  realm,
  facts = NO_FACTS,
  children,
}: {
  route: string;
  title: string;
  realm: CopilotSurface["realm"];
  /** Facts about the whole screen, listed before any part's. */
  facts?: CopilotFact[];
  children: ReactNode;
}) {
  const parts = useRef<SurfaceHolder[]>([]);
  const own = useRef<ScopeOwn>({ route, title, realm, facts });
  useEffect(() => {
    own.current = { route, title, realm, facts };
  });
  const value = useMemo<ScopeValue>(
    () => ({
      add: (part) => {
        parts.current = [...parts.current, part];
        return () => {
          parts.current = parts.current.filter((p) => p !== part);
        };
      },
    }),
    [],
  );
  useEffect(
    () =>
      registerSurfaceHolder({
        read: () => mergeSurfaces(own.current, parts.current.map((part) => part.read())),
      }),
    [],
  );
  return createElement(SurfaceScope.Provider, { value }, children);
}

const NO_FACTS: CopilotFact[] = [];

/** The scope's merge, pure so a test can drive it without a render. */
export function mergeSurfaces(own: ScopeOwn, parts: CopilotSurface[]): CopilotSurface {
  const fields: CopilotField[] = [];
  const owner = new Map<string, CopilotSurface>();
  const facts: CopilotFact[] = [...own.facts];
  const keys = new Set(own.facts.map((fact) => fact.key));
  for (const part of parts) {
    for (const field of part.fields) {
      if (owner.has(field.id)) continue;
      owner.set(field.id, part);
      fields.push(field);
    }
    for (const fact of part.facts ?? []) {
      if (keys.has(fact.key)) continue;
      keys.add(fact.key);
      facts.push(fact);
    }
  }
  const said = parts.flatMap((part) => (part.unsaved === undefined ? [] : [part.unsaved]));
  const tenantId = parts.find((part) => part.tenantId !== undefined)?.tenantId;
  // How filled values are kept belongs to the part that holds fields; the first one that
  // says is the screen's answer (a tab's parts are all saved the same way).
  const keeper = parts.find((part) => part.saves !== undefined && part.fields.length > 0);
  return {
    route: own.route,
    title: own.title,
    realm: own.realm,
    ...(tenantId !== undefined ? { tenantId } : {}),
    ...(keeper ? { saves: keeper.saves, ...(keeper.liveStep ? { liveStep: keeper.liveStep } : {}) } : {}),
    fields,
    facts,
    apply: (items) => {
      for (const part of parts) {
        const mine = items.filter((item) => owner.get(item.field_id) === part);
        if (mine.length > 0) part.apply(mine);
      }
    },
    // A part that did not say is not a part with nothing to lose (see `unsaved` in
    // types.ts): the answer is unknown unless every part gave one, and true once any did.
    unsaved: said.includes(true) ? true : said.length === parts.length ? false : undefined,
  };
}
