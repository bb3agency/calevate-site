"use client";

import { useState } from "react";
import {
  CheckCircle2,
  CircleAlert,
  CircleHelp,
  FileSearch,
  Gauge,
  Landmark,
  Lock,
  PackageOpen,
  PhoneCall,
  PhoneOff,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { useAdminAccess, type AdminAccess } from "@/app/admin/access";
import { WriteFailure } from "@/app/admin/writeFailure";
import {
  Card,
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  ScrollRegion,
  Skeleton,
  formatCount,
  formatIST,
  formatISTInput,
  istInputToInstant,
} from "@/components/ui";
import {
  usePlatformState,
  useReplayOutbox,
  useSetPlatformState,
  useSetTmRegistration,
  useVerifyAuditChain,
  type DeadLetterQueue,
  type EngineDrift,
  type KbDrift,
  type LoadShedMode,
  type PlatformState,
  type TmRegistration,
  type TmStatus,
} from "@/lib/api/admin";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { hasKey, lookup } from "@/lib/lookup";
import { TermGloss, loadShedModeCopy, tmStatusCopy } from "@/app/admin/ops/opsLanguage";

/**
 * The operations surface — the big red switch, the load-shed mode, the one legal fact
 * with the same shape as a switch (whether Calevate is a live registered telemarketer,
 * SEC-COMP §3 company half), and the two platform recovery levers: the outbox dead-letter
 * replay and the audit-chain verification.
 *
 * ## Why the last three are here at all
 *
 * `POST /v1/ops/platform`'s `load_shed_mode`, `POST /v1/ops/outbox/replay` and
 * `GET /v1/ops/audit/verify` existed with no path in the console, so
 * `runbooks/calls-stopped.md` §2 and `webhook-delivery-failures.md` told an operator to
 * hand-assemble a curl — one of them with a step-up header in it — against production,
 * mid-incident, from the document people follow when they are least careful. Every one of
 * them is now a control here, and the runbook names the screen and keeps the curl only as
 * the fallback for a console that cannot load.
 *
 * ## The gating is not uniform, and the difference is the point
 *
 * The three switches that live on the `platform_state` ROW are gated on `opsAccess` —
 * permission AND a successful read of that row. The replay and the verification are gated
 * on the permission alone, because neither reads or moves that row: refusing to let an
 * operator verify the audit chain because an unrelated row was unreadable would remove
 * the control precisely when the platform is behaving strangely.
 *
 * ONE PERMISSION, NOT THREE. This screen used to carry the platform-configuration,
 * credential and key-management panels as well, on `platform:config` and
 * `platform:secrets` — so a screen the sidebar could describe with only one permission
 * string actually needed three, and the two it could not name were the two the founder
 * installs every vendor key with. They are `/admin/ops/config` now, with a sidebar entry
 * of their own (the founder's correction to D-457). What is left here is the INCIDENT
 * surface, and every route it calls is `ops:manage`.
 *
 * ## The properties every control on this screen holds
 *
 * This is the only screen in either realm whose controls act on EVERY tenant at once, so
 * four properties are deliberate and none of them are styling:
 *
 * 1. **THERE IS NO DEFAULT STATE.** `halted` used to be `state.data?.outbound_halted ??
 *    false`, which is the single most dangerous line this console could contain: a read
 *    that failed — expired session, API down, an operator whose role does not hold
 *    `ops:manage` — rendered "Outbound calling: running" with a green pip beside it. An
 *    operator diagnosing "our calls have stopped" (runbooks/calls-stopped.md §1) would
 *    have crossed the switch off the list and gone hunting elsewhere, and an operator
 *    mid-incident would have believed a halt they had just ordered had not taken. The
 *    state is now `boolean | null`, null renders as an explicit "we do not know", and
 *    every control is dead while it is null.
 * 2. **The controls are gated on the permission the ROUTE requires, before the click.**
 *    `GET /v1/ops/platform` and every write on this router are `ops:manage`, which only
 *    `superadmin` holds (core/rbac.py) — an `operator` who types this URL is refused by
 *    the API on everything here. The gate is `useAdminAccess` (`@/app/admin/access`),
 *    reading the admin realm's own identity at `GET /v1/admin/me`, so the controls
 *    disable themselves with the reason rather than offering a button whose only outcome
 *    is a 403 that reads like a fault.
 *
 *    This screen used to derive that from its OWN 403 instead, because there was no
 *    admin-realm identity endpoint to ask — `/v1/me` reaches the admin realm only when
 *    `X-Impersonate-Org` is present (core/auth.py), and this screen's whole subject is
 *    the row that belongs to no tenant, so it had no slug to impersonate into. That was
 *    sound (the read and the writes carry the identical permission) and it is still not
 *    the mechanism, for two reasons: it could answer only once a request had FAILED, and
 *    it was one of three different answers to one question — the same question the nav
 *    has to ask about screens nobody has opened.
 *
 *    The state precondition below is unchanged and is NOT about permissions: a control
 *    that can move a state we could not read is how a halt gets applied twice.
 * 3. **Every control that CHANGES something says what it will do before it is clicked**,
 *    and takes a typed confirmation — echoed to the API as a step-up header, on every one
 *    of them (`platformConfirmation`, `spendCapConfirmation`,
 *    `OUTBOX_REPLAY_CONFIRMATION`). It is not the second factor: admin-realm MFA is
 *    enforced by the API on every admin session (`core/auth.py::verify_token`, the
 *    `fva` claim), so this whole screen is already behind it. The confirmation is the
 *    other half — MFA says WHO holds the session, for the next twelve hours; the typed
 *    word says WHICH act they meant, on this click. A fully verified operator is exactly
 *    who mis-clicks the big red switch, so neither replaces the other (ops/routes.py
 *    records the rejected alternative of dropping it).
 *
 *    ONE asymmetry remains and it is argued at its panel: the audit-chain verification
 *    takes neither a typed word nor a header, because it writes nothing and a
 *    confirmation on a read only teaches operators to type past them. The outbox replay
 *    used to be the second: it collected the typed word and sent NO header, honestly,
 *    because the route accepted none — and the route was the half that was wrong. It is
 *    the most outward-facing write on this screen (it redelivers other people's clients'
 *    data into other people's systems) and it was the only one a single unconfirmed POST
 *    could reach. Both halves closed together; `WriteFailure` renders what a refused
 *    confirmation now means.
 * 4. **`tm_registration.is_live` is DISPLAYED, never computed.** The launch gate refuses
 *    every tenant's campaign with `tm_registration_missing` from the same property, so a
 *    console that decided for itself whether `submitted` counts would be capable of
 *    showing a green platform while every client's launch was being refused. The same
 *    rule governs the two new readouts: the replay renders the server's count and the
 *    verification renders the server's verdict, including a FAILURE, which stays on
 *    screen in the stop palette rather than passing as a notification.
 *
 * 5. **A control whose blast radius can be MEASURED shows the measurement before the
 *    confirmation.** The dead-letter replay used to be the exception and said so in its
 *    own words: there was no count to publish, so an operator confirmed a redelivery of
 *    unknown size, mix and age while every other confirmation here named something
 *    visible. `outbox_dead_letters` closed that, and the three properties it must hold are
 *    property 1 again in another dialect — a depth we could not read is not a zero, an
 *    empty queue is not an unreadable one, and neither is a reason to hide the control.
 *
 * WHAT ELSE THE DESIGN PASS FIXED: `halt_reason` was on the wire (`PlatformStateOut`) and
 * on no screen. The API added the column precisely because "why is outbound stopped" was
 * answerable only by whoever knew which log stream to grep — and this is the screen the
 * person who found it stopped is looking at. It is rendered beside the halt now.
 *
 * NOT HERE, and argued rather than forgotten: `POST /v1/ops/tenants/{id}/spend-cap/
 * recompute`. It is the fourth curl the runbook printed and it is the one control on that
 * list that names a TENANT — so it lives on that tenant's own screen
 * (`/admin/tenants/[tenantId]`), beside the ceilings that decide it. A picker here would
 * be a uuid typed into a form with no client's name, ceilings or counters next to it,
 * which is the curl's failure mode in a nicer font.
 *
 * NO `<h1>`: the admin shell (layout.tsx) derives the page title from the same nav list
 * it renders, so a heading here would print "Operations" twice — and would let the nav
 * entry be renamed while this screen went on arguing with it.
 */

/**
 * The screen's field and control styling, written once.
 *
 * COPIED VERBATIM from `/c/[slug]/campaigns` — same strings, same order — because its
 * author flagged them as belonging in `ui.tsx` once a second screen needed them, and
 * copying identically is what makes that promotion a lift rather than a reconciliation.
 * `DANGER_BUTTON` is the one addition and it exists only here: it is the button that
 * stops every tenant's dialling, and `PRIMARY_BUTTON` (brand green) is the wrong colour
 * for it in a way that matters — an operator's eye should not find it in the same class
 * as "Create campaign".
 */

/** Two sentences per mode: what it is doing now, and what choosing it would do. */
interface LoadShedNote {
  /** Printed for the mode the platform IS in. Present tense, a statement of fact. */
  now: string;
  /** Printed above the button for the mode being CHOSEN, before the click. */
  blast: string;
}

/**
 * What each load-shed mode actually sheds, in one place — and the copy was rewritten
 * against `core/loadshed.py` rather than carried over, because the old wording was wrong
 * in the direction that matters when someone is choosing a mode mid-incident.
 *
 * `is_shed()` is four lines: never shed the always-allowed prefixes; shed EVERYTHING in
 * `maintenance`; otherwise shed non-GET in `reduced`, `emergency` and `maintenance`. So
 * `emergency` does NOT stop reads (the old copy said "Reads only"), `reduced` does not
 * shed only "expensive" writes (it sheds all of them), and — the fact an operator most
 * needs before picking one — **`reduced` and `emergency` shed exactly the same set
 * today.** Saying that out loud is the point: an operator who picks `emergency` believing
 * it does more has spent the escalation and bought nothing.
 *
 * `lookup()` rather than `LOAD_SHED[mode]` at the READ site: `load_shed_mode` is a bare
 * `string` on the wire, so a mode named after an `Object.prototype` member would resolve
 * to the `Object` FUNCTION and render as `function Object() { [native code] }` under a
 * heading an operator is reading mid-incident. Missing fails VISIBLE — the mode is still
 * printed, because a mode this build has no copy for is exactly the one worth reading.
 *
 * `Record<LoadShedMode, …>` over the GENERATED union (not `Record<string, …>`) so that a
 * fifth mode added server-side fails `tsc` here instead of arriving as a mode the console
 * can display but never offer.
 */
const LOAD_SHED: Record<LoadShedMode, LoadShedNote> = {
  normal: {
    now: "Everything is working normally.",
    blast:
      "Takes the platform out of its protective slowdown: clients can make changes again, and new self-serve sign-ups reopen.",
  },
  reduced: {
    now: "Clients can’t make changes right now — launching campaigns, saving agents and adding leads are paused. They can still view everything.",
    blast:
      "Clients stop being able to make changes — launching a campaign, saving an agent, adding a lead. They can still view everything, and a campaign that is already running keeps dialling (a running campaign doesn’t depend on the website). New self-serve sign-ups are turned away.",
  },
  emergency: {
    now: "Clients can’t make changes right now — launching campaigns, saving agents and adding leads are paused. They can still view everything.",
    blast:
      "Pauses exactly what “Reduced” pauses. Today this is a louder label for the same thing, not a stricter one — choose it to signal how serious the situation is, not because it stops more.",
  },
  maintenance: {
    now: "Planned downtime: clients can’t view or change anything. Only calls, sign-in and this operations console keep working.",
    blast:
      "Client screens go dark — a client opening their dashboard sees a “temporarily unavailable” message. Live calls are unaffected, so no lead is lost. This operations console keeps working, so you can always bring the platform back.",
  },
};

/** Offered in this order on purpose: least to most shed. */
const LOAD_SHED_MODES = Object.keys(LOAD_SHED) as LoadShedMode[];

/**
 * What a control on this screen needs to know: whether to enable, and what to say.
 *
 * `AdminAccess` is assignable to it — same two fields, plus a `refused` no control reads
 * — so the panels that depend on the platform ROW take `opsAccess`'s verdict and the two
 * that depend on nothing but the permission take the hook's directly. One shape, two
 * preconditions, and the difference is visible at the call site.
 */
interface OpsAccess {
  allowed: boolean;
  /** Rendered BESIDE the dead control. Null while we do not yet know. */
  reason: string | null;
}

/**
 * May this session move a platform switch? — two conditions, and they are not the same
 * kind of thing.
 *
 * **The permission** comes from the admin realm's identity read (`useAdminAccess`), which
 * is the console's one answer to "may I" everywhere. It names `ops:manage`, and it can say
 * so before any request on this screen has failed.
 *
 * **The state** is this screen's own precondition and has nothing to do with authority:
 * never `allowed: true` without a platform response in hand, because a control that can
 * move a state we cannot read is how a halt gets lifted twice, or lifted by someone who
 * thought they were applying it. "You may not do this" and "we could not find out what
 * the switch is set to" are different sentences and only one of them is about the
 * operator, so the two conditions keep their own words.
 */
// Not exported: a Next.js page module may only export the default and the framework's
// own named exports, so this is asserted through the DOM (tests/ops.test.tsx) rather
// than called directly.
function opsAccess(
  access: AdminAccess,
  query: {
    data: PlatformState | undefined;
    error: unknown;
    isLoading: boolean;
  },
): OpsAccess {
  // Permission first: it is the only half that is about the OPERATOR, and while the
  // identity read is in flight it already answers `allowed: false` with no sentence, so
  // nothing here flashes an explanation it is about to withdraw.
  if (!access.allowed) return { allowed: false, reason: access.reason };
  if (query.error) {
    return {
      allowed: false,
      reason:
        "These controls are disabled because the current state could not be read. Moving a " +
        "switch we cannot see the position of is how a halt gets applied twice, or lifted " +
        "by someone who meant to apply it.",
    };
  }
  if (query.isLoading || !query.data) return { allowed: false, reason: null };
  return { allowed: true, reason: null };
}

export default function OpsPage() {
  const state = usePlatformState();
  const mayManage = useAdminAccess("ops:manage", "change platform-wide switches");
  // The SAME permission — every route on `/v1/ops` is `ops:manage` — asked with a second
  // sentence, because the refusal is read beside the control and "you cannot change
  // platform-wide switches" is the wrong description of a button that replays a dead
  // letter queue. `useAdminMe` shares one query key, so this is a second verdict on one
  // request, not a second request.
  const mayRecover = useAdminAccess("ops:manage", "run the platform recovery tools");
  // TWO VERDICTS, NOT FOUR. `platform:config` and `platform:secrets` were read here as
  // well until their panels moved to `/admin/ops/config`; this screen now asks about one
  // permission, which is what its own nav entry has always declared.
  const access = opsAccess(mayManage, state);

  const platform = state.data;
  /*
   * The SAME three readers the panels below are given, computed once and handed to both.
   * Reaching into `state.data.kb_drift` here instead would be a second opinion about
   * whether the platform row is readable — and it was one: a payload missing `kb_drift`
   * (which `kbDriftState` treats as UNREADABLE, not as an all-clear) crashed the whole
   * screen from this declaration while the panel three lines below rendered it correctly.
   */
  const deadLetters = deadLetterState(state);
  const engineDrift = engineDriftState(state);
  const kbDrift = kbDriftState(state);
  /*
   * THE OPERATIONS SURFACE, DECLARED TO THE SCREEN ASSISTANT.
   *
   * NOT CROSS-TENANT AT ALL — this is the one admin screen whose whole subject is the
   * PLATFORM, so there is no per-client detail to weigh. Everything here is a switch
   * position, a queue depth or a count of agents, and every one of those applies to every
   * client at the same moment.
   *
   * NO FIELDS, and that is the decision worth recording. Each of the three switches below
   * is a typed confirmation plus a written reason, deliberately: the halt stops every
   * client's outbound dialling, and the TM registration is a legal fact about this company.
   * A model that could put a value in those forms would be one keystroke from moving them,
   * and the person's typed confirmation is the whole control. So the assistant reads this
   * screen and explains it; the levers stay in human hands.
   *
   * `halt_reason` IS DELIBERATELY WITHHELD even though it is on screen. It is operator free
   * text, and free text about an incident is where a phone number ends up — which would
   * hit `assert_redacted` and refuse the whole question, on the screen an operator opens
   * when calls have stopped. Whether a reason was recorded is the fact worth having; the
   * words are on the screen they are already looking at.
   */
  useCopilotSurface({
    route: "/admin/ops",
    title: "Operations",
    realm: "admin",
    fields: [],
    facts: platform
      ? [
          {
            key: "outbound_halted",
            label: "Big red switch — outbound dialling halted platform-wide",
            value: platform.outbound_halted ? "yes, halted" : "no, running",
          },
          {
            key: "halt_reason_recorded",
            label: "Is a halt reason on file (the text itself is not sent)",
            value: platform.halt_reason ? "yes" : "no",
          },
          { key: "load_shed_mode", label: "Load-shed mode", value: platform.load_shed_mode },
          {
            key: "tm_registration",
            label: "Calevate's telemarketer registration",
            value: `${platform.tm_registration.status}${platform.tm_registration.is_live ? " (live)" : " (not live)"}`,
          },
          {
            key: "outbox_dead_letters",
            label: "Outbox dead-letter queue",
            value:
              deadLetters.status === "read"
                ? `${deadLetters.queue.depth} dead-lettered, ${deadLetters.queue.deferred} deferred`
                : "could not be read",
          },
          {
            key: "engine_drift",
            label: "Live agents by engine-config drift",
            value:
              engineDrift.status === "read"
                ? `${engineDrift.drift.in_sync} in sync, ${engineDrift.drift.out_of_sync} out of sync, ${engineDrift.drift.undetermined} undetermined, ${engineDrift.drift.never_checked} never checked, of ${engineDrift.drift.live_agents} live`
                : "could not be read",
          },
          {
            key: "kb_drift",
            label: "Live agents by knowledge-base drift",
            value:
              kbDrift.status !== "read"
                ? "could not be read"
                : kbDrift.drift.engine_supports_knowledge_base
                  ? `${kbDrift.drift.in_sync} in sync, ${kbDrift.drift.out_of_sync} out of sync, ${kbDrift.drift.undetermined} undetermined, ${kbDrift.drift.never_checked} never checked, of ${kbDrift.drift.live_agents} live`
                  : "the engine exposes no knowledge-base API, so nothing is checked",
          },
          {
            key: "may_manage",
            label: "May this operator move these switches",
            value: mayManage.allowed ? "yes" : "no",
          },
        ]
      : [
          {
            key: "platform",
            label: "The platform state row",
            // The `boolean | null` the whole screen is built around: "we could not read it"
            // is never rendered as "outbound is running", here least of all.
            value: state.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <p className="mt-0.5 text-sm text-ink-muted">
          Platform-wide switches. Every change is recorded in the activity log with your
          reason, and every one of them applies to every client at the same moment.
        </p>
      </div>

      {state.error && <ProblemNotice error={state.error} onRetry={() => state.refetch()} />}

      {state.isLoading ? (
        <Card>
          <Skeleton rows={4} />
        </Card>
      ) : state.data ? (
        <>
          <OutboundHaltPanel state={state.data} access={access} />
          <LoadShedPanel state={state.data} access={access} />
          <TmRegistrationPanel registration={state.data.tm_registration} access={access} />
        </>
      ) : (
        <UnknownStatePanel reason={access.reason} />
      )}

      {/* Gated on `mayManage` and NOT on `access`, deliberately: neither of these acts on
          the platform row, so neither has a state we failed to read. Hiding the audit-chain
          verification because an unrelated row was unreadable would remove the one control
          an operator most wants when the platform is behaving strangely — and both still
          disable themselves, with the reason, for a session that lacks `ops:manage`. */}
      <OutboxReplayPanel access={mayRecover} queue={deadLetters} />
      {/* READ-ONLY, and the only panel on this screen with no lever — deliberately. The
          sweep behind it re-publishes nothing (D-121/D-123: overwriting an operator's
          emergency console edit is a decision with a blast radius), so the console must
          not offer a "fix it" button that would make that decision from a summary. What
          an operator does with a drift starts on the AGENT's own screen, where the
          per-agent sentence lives. Not gated on `access` for the reason the two panels
          above are not: it reads no platform-row state. */}
      <EngineDriftPanel drift={engineDrift} />
      {/* The same read, on the other object. `EngineDriftPanel` above answers "is the
          agent CONFIGURED as we published"; this answers "is it ANSWERING from text a
          human approved" — an agent can be perfectly in sync on the first and be reading
          out a knowledge base somebody pasted into the vendor's console. Also read-only,
          and here the absence of a lever is stronger: the repair a KB drift invites is a
          DELETE at the vendor of a document our tables cannot describe. */}
      <KnowledgeDriftPanel drift={kbDrift} />
      <AuditChainPanel access={mayRecover} />

      {/* THE CONFIG AND CREDENTIAL PANELS USED TO SIT HERE AND NOW HAVE THEIR OWN SCREEN
          (`/admin/ops/config`), because the founder's correction to D-457 asked for the
          ops config panel to be findable from the sidebar and a nav entry needs a
          destination of its own. The split is also what the permissions were already
          saying: everything above is `ops:manage` — the incident levers, held by whoever
          is on call — and everything that moved is `platform:config` or
          `platform:secrets`, which is change management. One screen carrying three
          permissions meant its nav entry could declare only one of them.

          Deliberately NOT left behind as a link: this screen is what an operator opens
          when calls have stopped, and a pointer to the credential console is not
          something that belongs on it. The sidebar is where surfaces are discovered. */}

      <Card title="What is never shed">
        <ul className="space-y-1.5 text-sm text-ink-muted">
          <li className="flex gap-2">
            <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            Health endpoints
          </li>
          <li className="flex gap-2">
            <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            Engine webhooks — a dropped callback is a call whose lead never appears
          </li>
          <li className="flex gap-2">
            <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            This ops surface — an operator must not be able to lock themselves out
          </li>
        </ul>
      </Card>
    </div>
  );
}

/**
 * THE STATE WE COULD NOT READ, said as itself.
 *
 * This panel is the whole point of the `boolean | null` above. The screen it replaces
 * rendered the halt form over a `?? false`, so the most dangerous render this console can
 * produce — "outbound is running" when we have no idea — was also its default one. There
 * is no control here on purpose: an operator who needs the switch during an outage needs
 * the runbook's curl, not a button that posts a transition computed from nothing.
 */
function UnknownStatePanel({ reason }: { reason: string | null }) {
  return (
    <NoticeBox
      tone="warn"
      icon={<CircleHelp aria-hidden className="h-5 w-5" />}
      title="We do not know whether outbound calling is halted"
    >
      <p className="mt-1">
        The platform state could not be read, so this screen will not tell you it is
        running and it will not tell you it is stopped. Treat the switch as unknown until
        this loads — the error above says what stopped it.
      </p>
      {/* The load-shed mode lives on the same row and failed with it. Its control is
          absent for the same reason the halt's is: a mode selected against a current mode
          nobody read is a change whose direction is a guess. */}
      <p className="mt-2">
        The load-shed mode is on that same row, so it is unknown too, and neither switch
        is offered here while that is true.
      </p>
      {reason && <p className="mt-2">{reason}</p>}
      <p className="mt-2 text-xs">
        If calls have stopped and you need the switch now, the “calls stopped” runbook
        walks through sending it by hand.
      </p>
    </NoticeBox>
  );
}


/**
 * The big red switch, with its current position and its reason.
 *
 * The confirmation is the screen's existing pattern kept intact: a typed word plus a
 * reason, mirroring the `X-Confirm-Action` header the API demands (BACKEND-PATTERNS §7).
 * The reason is trimmed before it is measured, because the server strips it and refuses
 * anything under three characters — a form that enables its button on `"   "` teaches the
 * operator the API is flaky.
 */
function OutboundHaltPanel({ state, access }: { state: PlatformState; access: OpsAccess }) {
  const setState = useSetPlatformState();
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  const halted = state.outbound_halted;
  const confirmWord = halted ? "RESUME" : "HALT";
  const ready = reason.trim().length >= 3 && confirm === confirmWord;

  return (
    <Card>
      <div className="space-y-4">
        <NoticeBox
          tone={halted ? "stop" : "ok"}
          icon={
            halted ? (
              <PhoneOff aria-hidden className="h-5 w-5" />
            ) : (
              <PhoneCall aria-hidden className="h-5 w-5" />
            )
          }
          title={
            halted
              ? "Outbound calling is HALTED for every client"
              : "Outbound calling is running"
          }
        >
          {halted ? (
            <>
              <p className="mt-1">
                No outbound call is being placed for any client. Inbound calls are
                unaffected — clients&apos; receptionists keep answering.
              </p>
              {/* The one question whoever finds the platform halted asks first. It is on
                  the wire and was on no screen until this pass. */}
              <p className="mt-2">
                <span className="font-semibold">Reason on the record:</span>{" "}
                {state.halt_reason ?? "none was recorded with this halt."}
              </p>
            </>
          ) : (
            <p className="mt-1">
              Campaigns dial normally, subject to each one&apos;s own compliance gate.
            </p>
          )}
        </NoticeBox>

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            setState.mutate(
              { outboundHalted: !halted, reason: reason.trim() },
              {
                onSuccess: () => {
                  setReason("");
                  setConfirm("");
                },
              },
            );
          }}
        >
          {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON. Blast radius first, then what is
              NOT affected, then the fact that it is recorded — in that order, because
              an operator who reads only the first line has read the part that matters. */}
          <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
            <TriangleAlert
              aria-hidden
              className={`mt-0.5 h-4 w-4 shrink-0 ${halted ? "text-ink-faint" : "text-rose-600"}`}
            />
            <div className="min-w-0">
              <p className="font-semibold text-ink">
                {halted
                  ? "Resuming lets every client's outbound dialling start again"
                  : "Halting stops every client's outbound dialling immediately"}
              </p>
              <p className="mt-1 text-ink-muted">
                {halted
                  ? "Paused campaigns pick up again within a minute or so. Every campaign's own compliance gate still applies — this only releases the platform-wide stop, nothing else."
                  : "Running campaigns stop within a minute or so and no new outbound call is placed for any client. Inbound calls are unaffected — the caller started those, and refusing them would silently break the receptionist your clients pay for."}
              </p>
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the activity log against your admin account, with the reason
                you type below.
              </p>
            </div>
          </div>

          {setState.error && (
            <WriteFailure
              error={setState.error}
              actionLabel={halted ? "Resume outbound calling" : "Halt all outbound calling"}
            />
          )}

          <label className="block">
            <span className={FIELD_LABEL}>Reason</span>
            <input
              required
              minLength={3}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={!access.allowed}
              placeholder={
                halted
                  ? "e.g. 'registrar confirmed the suspension was lifted'"
                  : "e.g. 'spike in complaints — stopping until we've read the logs'"
              }
              className={FIELD}
            />
            <span className={FIELD_HINT}>
              Whoever finds outbound calling stopped at 3am reads this to decide whether the
              reason still holds. It stays on record here, not only in the activity log.
            </span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Type {confirmWord} to confirm</span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed}
              placeholder={confirmWord}
              className={`${FIELD} font-mono`}
            />
          </label>

          <button
            type="submit"
            title={access.reason ?? undefined}
            disabled={!access.allowed || !ready || setState.isPending}
            className={halted ? PRIMARY_BUTTON : DANGER_BUTTON}
          >
            {halted ? (
              <PhoneCall aria-hidden className="h-4 w-4" />
            ) : (
              <PhoneOff aria-hidden className="h-4 w-4" />
            )}
            {setState.isPending
              ? "Sending…"
              : halted
                ? "Resume outbound calling"
                : "Halt all outbound calling"}
          </button>

          {/* A dead switch with no explanation is worse than a refusal after the click:
              the operator cannot tell it apart from a broken page. */}
          {!access.allowed && access.reason && (
            <p className="flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {access.reason}
            </p>
          )}
        </form>
      </div>
    </Card>
  );
}

/**
 * The load-shed mode — the second switch on the global row, and until now the one this
 * console could READ and not move.
 *
 * That gap is why `runbooks/calls-stopped.md` §2 sent an operator to a hand-written curl
 * with a step-up header in it, mid-incident, against production. Everything that makes the
 * halt switch safe applies here unchanged and for the same reasons, so none of it is
 * re-argued below — but two properties are this control's own:
 *
 * 1. **The form opens on NO CHANGE.** `target` is seeded from the mode the platform is
 *    actually in, so the button is dead until the operator has chosen a different one.
 *    A screen that preselected `normal` would make "click the obvious button" a release
 *    of a shed somebody imposed twenty minutes ago for a reason nobody has read yet.
 * 2. **The confirmation carries the TARGET MODE**, in the typed word and in the header
 *    (`set_load_shed:<mode>`, `platformConfirmation`). The API binds it that way because
 *    consent to `reduced` is not consent to `maintenance`; the typed word says the same
 *    thing to the human, so the two cannot drift apart in an operator's habits.
 *
 * The mode the platform is IN is printed from the server's string even when this build
 * has no copy for it — see `LOAD_SHED` on why that fails visible rather than silent.
 */
function LoadShedPanel({ state, access }: { state: PlatformState; access: OpsAccess }) {
  const setState = useSetPlatformState();
  const current = state.load_shed_mode;
  // A mode this build cannot name seeds `normal`: it is the only direction that is
  // meaningful to offer out of a state this console cannot describe, and it is still a
  // deliberate choice the operator has to type a word for.
  const [target, setTarget] = useState<LoadShedMode>(
    hasKey(LOAD_SHED, current) ? current : "normal",
  );
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  const note = lookup(LOAD_SHED, current);
  const confirmWord = target.toUpperCase();
  // The server would accept a request that re-asserts the current mode and would write an
  // audit row for it — a recorded platform change nobody made. `platform_confirmation`
  // refuses the empty transition for that exact reason; this is the same objection one
  // step earlier, where the operator can still see it.
  const unchanged = target === current;
  const ready = !unchanged && reason.trim().length >= 3 && confirm === confirmWord;

  return (
    <Card title="Protective slowdown">
      <div className="space-y-4">
        <NoticeBox
          tone={current === "normal" ? "ok" : "warn"}
          icon={<Gauge aria-hidden className="h-5 w-5" />}
          title={loadShedModeCopy(current).label}
        >
          <p className="mt-1">
            {note?.now ?? (
              <>
                This console has no description for that mode, so treat it as unknown until
                someone can confirm what it does.
              </>
            )}
          </p>
        </NoticeBox>

        {setState.error && (
          <WriteFailure
            error={setState.error}
            actionLabel={`Switch to “${loadShedModeCopy(target).label}”`}
          />
        )}

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            setState.mutate(
              { loadShedMode: target, reason: reason.trim() },
              {
                onSuccess: () => {
                  setReason("");
                  setConfirm("");
                },
              },
            );
          }}
        >
          <label className="block">
            <span className={FIELD_LABEL}>Change the mode to</span>
            <select
              value={target}
              onChange={(e) => {
                setTarget(e.target.value as LoadShedMode);
                // The confirmation word IS the target mode, so a word typed for a
                // different target must not survive the change and submit silently.
                setConfirm("");
              }}
              disabled={!access.allowed}
              className={FIELD}
            >
              {LOAD_SHED_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {loadShedModeCopy(mode).label}
                  {mode === current ? " — in force now" : ""}
                </option>
              ))}
            </select>
          </label>

          {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON — for the mode being chosen, not for
              the one in force. Every mode here refuses requests for every client at once. */}
          <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
            <TriangleAlert
              aria-hidden
              className={`mt-0.5 h-4 w-4 shrink-0 ${
                target === "normal" ? "text-ink-faint" : "text-rose-600"
              }`}
            />
            <div className="min-w-0">
              <p className="font-semibold text-ink">
                {unchanged
                  ? `The platform is already in “${loadShedModeCopy(current).label}”`
                  : `Switching to “${loadShedModeCopy(target).label}” applies to every client at once`}
              </p>
              <p className="mt-1 text-ink-muted">{LOAD_SHED[target].blast}</p>
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the activity log against your admin account, with the reason
                you type below. This does not stop a campaign that is already running, and
                it never affects inbound calls.
              </p>
            </div>
          </div>

          <label className="block">
            <span className={FIELD_LABEL}>Reason</span>
            <input
              required
              minLength={3}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={!access.allowed}
              placeholder="e.g. 'database under heavy load — pausing changes until it recovers'"
              className={FIELD}
            />
            <span className={FIELD_HINT}>
              Whoever finds the platform slowed reads this to decide whether the condition
              still holds.
            </span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Type {confirmWord} to confirm</span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed || unchanged}
              placeholder={confirmWord}
              className={`${FIELD} font-mono`}
            />
          </label>

          <button
            type="submit"
            title={access.reason ?? undefined}
            disabled={!access.allowed || !ready || setState.isPending}
            className={target === "normal" ? PRIMARY_BUTTON : DANGER_BUTTON}
          >
            <Gauge aria-hidden className="h-4 w-4" />
            {setState.isPending ? "Sending…" : `Switch to “${loadShedModeCopy(target).label}”`}
          </button>

          {!access.allowed && access.reason && (
            <p className="flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {access.reason}
            </p>
          )}
        </form>
      </div>
    </Card>
  );
}

// The five statuses in the order they are offered. The human label and one-line
// explanation for each come from `tmStatusCopy` (opsLanguage), so the select, the status
// banner and the facts grid all read the registration in one voice.
const TM_STATUSES: TmStatus[] = [
  "not_registered",
  "submitted",
  "active",
  "suspended",
  "revoked",
];

/**
 * `toLocalInput` WAS HERE AND IS GONE. It read `at.getHours()` — the BROWSER's wall clock
 * — while its own comment said the field held "the IST moment on the registrar's letter".
 * Those are the same number only on a machine set to India, and this is the admin console:
 * an operator reading it from another zone was shown, and would have posted back, a
 * different instant than the letter states. `formatISTInput`/`istInputToInstant`
 * (`components/ui.tsx`) are the pair that names the zone instead of assuming it, beside
 * the `formatIST` this screen already renders every other time through.
 */

/**
 * Calevate's own DLT telemarketer registration — the platform-wide campaign blocker.
 *
 * The symptom this fixes: the registration became a launch-gate input, and no surface
 * showed it. Every client's campaign could be refused with `tm_registration_missing`
 * while the ops console reported a healthy platform — outbound not halted, load-shed
 * normal, and nothing anywhere saying that Calevate itself may not lawfully dial.
 *
 * `is_live` comes from the server and is rendered as-is. The status is shown BESIDE it
 * rather than instead of it, because the two answer different questions: `submitted`
 * is real progress to report to a colleague, and it is still not live.
 */
function TmRegistrationPanel({
  registration,
  access,
}: {
  registration: TmRegistration;
  access: OpsAccess;
}) {
  const record = useSetTmRegistration();
  // Seeded from the current registration so re-recording after a re-verification is an
  // edit, not a retype — a blank `tm_id` posted by habit would erase the one we hold.
  // Deliberately NOT re-synced on the 30s refetch: clobbering a half-typed form with a
  // poll result is worse than a stale default an operator can see and change.
  const [status, setStatus] = useState<TmStatus>(
    TM_STATUSES.includes(registration.status as TmStatus)
      ? (registration.status as TmStatus)
      : "not_registered",
  );
  const [tmId, setTmId] = useState(registration.tm_id ?? "");
  const [registeredAt, setRegisteredAt] = useState(formatISTInput(registration.registered_at));
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  // Which write this is, in the operator's words and in the API's. Both derive from the
  // status being ACTIVE — the direction of this request — and neither is a claim about
  // what counts as live; `ops/routes.py` computes the same thing from the same field and
  // refuses a header that does not match.
  const makingLive = status === "active";
  const confirmWord = makingLive ? "RECORD" : "WITHDRAW";
  const live = registration.is_live;
  const ready = reason.trim().length >= 3 && confirm === confirmWord;

  return (
    <Card title="Our telemarketer registration">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Calevate is the registered{" "}
          <TermGloss term="telemarketer (TM)">
            the business registered with India&apos;s telecom system to place calls on a
            client&apos;s behalf
          </TermGloss>
          ; each client is its own{" "}
          <TermGloss term="principal entity (PE)">
            the business the calls are for, registered in its own name under India&apos;s
            telecom rules (DLT)
          </TermGloss>
          . This is one fact for the whole platform.
        </p>

        {/* The consequence, stated before the fields. An operator reading `submitted`
            and no consequence has to remember the rule; reading it here, they do not. */}
        <NoticeBox
          tone={live ? "ok" : "warn"}
          icon={
            live ? (
              <Landmark aria-hidden className="h-5 w-5" />
            ) : (
              <CircleAlert aria-hidden className="h-5 w-5" />
            )
          }
          title={live ? "LIVE — we may lawfully dial" : "NOT LIVE — no client can launch"}
        >
          <p className="mt-1">
            {live
              ? "This is not blocking any launches. Each client still needs its own registration in its own name, and to be linked to us as its telemarketer."
              : "While this is not live, NO client can launch an outbound campaign, however complete their own registration is. Inbound answering is unaffected — clients' receptionists keep working."}
          </p>
        </NoticeBox>

        <dl className="grid gap-3 sm:grid-cols-4">
          <Fact label="Status" value={tmStatusCopy(registration.status).label} />
          <Fact label="TM ID" value={registration.tm_id ?? "—"} mono />
          <Fact label="Registered" value={formatIST(registration.registered_at)} />
          <Fact label="Last verified" value={formatIST(registration.verified_at)} />
        </dl>

        {record.error && (
          <WriteFailure
            error={record.error}
            actionLabel={
              makingLive
                ? "Record registration as active"
                : `Record as “${tmStatusCopy(status).label}”`
            }
          />
        )}
        {/* The SERVER's `is_live` after the write, never this form's opinion of it. */}
        {record.data && (
          <p className="flex items-center gap-2 text-sm text-ink-muted">
            <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand" />
            Recorded. The launch gate now reads{" "}
            <span className="font-semibold text-ink">
              {record.data.is_live ? "live" : "not live"}
            </span>
            .
          </p>
        )}

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            record.mutate(
              {
                status,
                tm_id: tmId.trim() || null,
                registered_at: istInputToInstant(registeredAt),
                reason: reason.trim(),
              },
              { onSuccess: () => setConfirm("") },
            );
          }}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block">
              <span className={FIELD_LABEL}>Registration status</span>
              <select
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value as TmStatus);
                  // The confirmation word changes with the direction, so a word typed for
                  // the other direction must not survive the switch and submit silently.
                  setConfirm("");
                }}
                disabled={!access.allowed}
                className={FIELD}
              >
                {TM_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {tmStatusCopy(value).label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className={FIELD_LABEL}>TM id from the registrar</span>
              <input
                value={tmId}
                onChange={(e) => setTmId(e.target.value)}
                disabled={!access.allowed}
                className={`${FIELD} font-mono`}
              />
            </label>
            <label className="block">
              {/* THE ZONE IS ON SCREEN, and it is not decoration. A `datetime-local`
                  carries no zone, so an unlabelled one means "this machine's clock" to
                  every reader — and this field does not: it holds the moment printed on
                  the registrar's letter, which is IST wherever the operator is sitting.
                  Saying so is what lets someone in another zone type the letter's digits
                  rather than converting them, which is the whole correction here. */}
              <span className={FIELD_LABEL}>Registered on (IST)</span>
              <input
                type="datetime-local"
                value={registeredAt}
                onChange={(e) => setRegisteredAt(e.target.value)}
                disabled={!access.allowed}
                className={FIELD}
              />
              <span className={FIELD_HINT}>
                The date and time on the registrar&apos;s letter, in IST — type it as
                printed, wherever you are.
              </span>
            </label>
          </div>

          <label className="block">
            <span className={FIELD_LABEL}>Reason</span>
            <input
              required
              minLength={3}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={!access.allowed}
              placeholder="e.g. 'registrar grant letter 2026-08-04'"
              className={FIELD}
            />
            <span className={FIELD_HINT}>Recorded in the activity log with this change.</span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Type {confirmWord} to confirm</span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed}
              placeholder={confirmWord}
              className={`${FIELD} font-mono`}
            />
          </label>

          {/* What this write does to every tenant, before it is sent. */}
          <div className="flex gap-3 rounded-card border border-line bg-app p-4 text-sm">
            <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <p className="text-ink-muted">
              {makingLive
                ? "Recording this as active opens the platform-wide launch gate for every client."
                : "Anything other than active closes that gate: no client can launch an outbound campaign until it is recorded active again."}
            </p>
          </div>

          <button
            type="submit"
            title={access.reason ?? undefined}
            disabled={!access.allowed || !ready || record.isPending}
            className={makingLive ? PRIMARY_BUTTON : DANGER_BUTTON}
          >
            {record.isPending
              ? "Recording…"
              : makingLive
                ? "Record registration as active"
                : `Record as “${tmStatusCopy(status).label}”`}
          </button>

          {!access.allowed && access.reason && (
            <p className="flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {access.reason}
            </p>
          )}
        </form>
      </div>
    </Card>
  );
}

/**
 * The dead-letter queue as this screen may know it — three states, and never a fourth.
 *
 * BUILD-LOG §52's rule, expressed as a type rather than as discipline: loading is a
 * skeleton, failure is a refusal, and neither is a number. A depth of 0 and a depth that
 * could not be read are OPPOSITE facts — one says "there is nothing to replay", the other
 * says "we have no idea what you are about to send" — and the whole reason this field
 * exists is to stop the second being confirmed as if it were the first. A
 * `DeadLetterQueue | undefined` would have collapsed them at the first `??`.
 */
type DeadLetterState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; queue: DeadLetterQueue };

function deadLetterState(query: {
  data: PlatformState | undefined;
  error: unknown;
  isLoading: boolean;
}): DeadLetterState {
  // Error first: a refetch that fails leaves the previous `data` in place, and a stale
  // depth rendered as current is the same lie as an invented one.
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  return { status: "read", queue: query.data.outbox_dead_letters };
}

/**
 * The drift summary as this screen may know it — the same three states, and never a
 * fourth, for `DeadLetterState`'s reason: "no agent has drifted" and "we could not find
 * out whether any agent has drifted" are OPPOSITE facts, and a `EngineDrift | undefined`
 * collapses them at the first `??`.
 */
type EngineDriftState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; drift: EngineDrift };

function engineDriftState(query: {
  data: PlatformState | undefined;
  error: unknown;
  isLoading: boolean;
}): EngineDriftState {
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  // A PLATFORM READ THAT CARRIES NO `engine_drift` IS UNREADABLE, not empty. The field is
  // required on the wire, so this cannot happen against a current server — it happens
  // against an OLDER one, and mid-deploy is exactly when someone is on this screen. The
  // narrowing has to be defended at runtime because `read !== null` is TRUE for
  // `undefined`, which is not a type error and is a blank ops console (axe's screen scan
  // found it, by rendering the page with a bare payload).
  //
  // This is NOT the `?? 0` trap it superficially resembles: nothing here invents a count.
  // "The server did not send it" and "we could not read it" are the same fact to an
  // operator, and the panel says so instead of reporting an all-clear it never received.
  const drift: EngineDrift | undefined = query.data.engine_drift;
  if (!drift) return { status: "unreadable" };
  return { status: "read", drift };
}

/**
 * What the voice platform is ACTUALLY running, versus what we published (D-123).
 *
 * ## Why this panel exists at all
 *
 * `publish_agent` reads the agent back and refuses a proven mismatch, so at the moment of
 * publishing, "live" means something. Two divergences appear AFTERWARDS and neither
 * involves any code of ours running: somebody edits the agent in the vendor's own
 * dashboard, or a publish fails on our side after the vendor committed. Both leave every
 * table we own agreeing with itself and wrong, and until the half-hourly sweep existed
 * they were found only by whoever thought to open one agent's screen.
 *
 * ## Three numbers, not one, and the middle one is the point
 *
 * `out_of_sync` is a PROVEN mismatch and is the only one that is an alarm. `undetermined`
 * is "we could not read the answer" — a vendor having a slow afternoon — and folding it
 * into the alarm would report a fleet of agents speaking unapproved scripts every time
 * the platform was briefly unreachable, which is a number an operator learns to ignore
 * inside a week. `never_checked` is the third: an agent nobody has swept must not be
 * counted as one we swept and liked.
 *
 * ## And the pulse, which is what stops this panel lying by omission
 *
 * If the cron dies, every count freezes and `out_of_sync: 0` reads as "all clear" forever.
 * `oldest_checked_at` is the only field here that can say "nobody is watching", so the
 * panel leads with it whenever it is missing or old rather than burying it in a footnote.
 *
 * ## No lever
 *
 * There is deliberately no "re-publish" button. Re-publishing over a drift overwrites
 * whatever the vendor's console was used to change — plausibly the correct emergency edit,
 * made while ours was the thing that was down — and offering that as one click from a
 * platform-wide summary is the worst possible way to make that decision. The route from
 * here is the agent's own screen, which carries the sentence saying what actually differs.
 */
function EngineDriftPanel({ drift }: { drift: EngineDriftState }) {
  const read = drift.status === "read" ? drift.drift : null;
  // A platform whose sweep has never run is NOT the same as one whose sweep is healthy
  // and found nothing, and the difference is `oldest_checked_at`. Note this is true even
  // when `live_agents` is 0 — an empty platform has nothing to sweep, and saying "no
  // agent has drifted" there is accurate but says nothing about whether the job is alive.
  const swept = read !== null && read.oldest_checked_at !== null;

  return (
    <Card title="What the voice platform is running">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Every half hour a sweep reads live agents back off the voice platform and
          compares them with what we published. It only ever reads — an agent edited on the
          vendor&apos;s own console stays exactly as they left it.
        </p>

        {drift.status === "loading" && <Skeleton rows={2} />}

        {/* The refusal. NOT "0 drifted": an operator who cannot see this number is the one
            who most needs telling that nobody has checked. */}
        {drift.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We do not know what the voice platform is running"
          >
            <p className="mt-1">
              This is read with the platform state, and that read failed — so this screen
              will not tell you every agent is in sync. The error above says what stopped
              it.
            </p>
          </NoticeBox>
        )}

        {read !== null && !swept && (
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
            title="No agent has been checked yet"
          >
            <p className="mt-1">
              Nothing below is evidence: the counts are what the last check recorded, and it
              has not recorded anything. If this lasts more than half an hour, the check has
              stopped running and no agent on the platform is being watched.
            </p>
          </NoticeBox>
        )}

        {read !== null && read.out_of_sync > 0 && (
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
            title={`${formatCount(read.out_of_sync)} of ${formatCount(read.live_agents)} live agents are running something else`}
          >
            <p className="mt-1">
              Oldest divergence: <span className="font-semibold">{formatIST(read.oldest_drift_at)}</span>.
              These agents are answering callers with a script, greeting or voice other
              than the one we published. Open each agent to see what differs — publishing
              again from here would overwrite whatever was changed on the vendor&apos;s
              console.
            </p>
          </NoticeBox>
        )}

        {read !== null && swept && read.out_of_sync === 0 && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Every checked agent is running what we published"
          >
            <p className="mt-1">
              {read.undetermined > 0
                ? `${formatCount(read.undetermined)} could not be read back — that is the voice platform not answering, not a drifted agent, and it will be retried on the next sweep.`
                : "No divergence found."}
            </p>
          </NoticeBox>
        )}

        {read !== null && (
          <table className="w-full text-left text-xs">
            <tbody>
              <tr>
                <td className="py-0.5 text-ink-muted">Live agents</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.live_agents)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Running what we published</td>
                <td className="py-0.5 text-right tabular-nums">{formatCount(read.in_sync)}</td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Running something else</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.out_of_sync)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Could not be read back</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.undetermined)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Not yet checked</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.never_checked)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Oldest check</td>
                <td className="py-0.5 text-right">
                  {swept ? formatIST(read.oldest_checked_at) : "never"}
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

/**
 * The knowledge-drift summary as this screen may know it. Three states and never a fourth,
 * `EngineDriftState`'s reason: "no agent's knowledge has drifted" and "we could not find
 * out whether any has" are OPPOSITE facts, and a `KbDrift | undefined` collapses them at
 * the first `??`.
 */
type KbDriftState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; drift: KbDrift };

function kbDriftState(query: {
  data: PlatformState | undefined;
  error: unknown;
  isLoading: boolean;
}): KbDriftState {
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  // Defended at runtime for `engineDriftState`'s reason: the field is required on the
  // wire, so this cannot happen against a current server — it happens against an OLDER
  // one, and mid-deploy is exactly when someone is on this screen. `read !== null` is TRUE
  // for `undefined`, which is not a type error and is a blank panel.
  const drift: KbDrift | undefined = query.data.kb_drift;
  if (!drift) return { status: "unreadable" };
  return { status: "read", drift };
}

/**
 * What the voice platform is ANSWERING FROM, versus what a human approved (D-158).
 *
 * ## Why this is a second panel and not two more rows on the first
 *
 * `EngineDriftPanel` above answers "is the agent configured as we published" — prompt,
 * greeting, voice. This answers a different question about a different object at the
 * vendor: which knowledge bases the agent can retrieve from. An agent can be perfectly in
 * sync on the first and be reading out a price list somebody pasted into Bolna's console,
 * and the two are measured by two sweeps on two schedules. Each therefore carries its OWN
 * `oldest_checked_at`: folding them would let a healthy agent sweep's timestamp vouch for
 * a knowledge sweep that had died, which is the exact lying-by-omission the pulse exists
 * to prevent.
 *
 * ## Why the approval gate makes this the more serious of the two
 *
 * FLOWS §7 puts a human in front of every word a knowledge base contains, because a client
 * editing what their agent says is a client editing a legal instrument — the agent speaks
 * on their behalf under their PE registration. Text added at the vendor has been through
 * no gate at all, and the agent will read it to callers.
 *
 * ## `undetermined` carries more weight here than on the agent panel
 *
 * An EMPTY knowledge listing is ambiguous between "the documents are gone" and "the
 * vendor's listing does not attribute rows to agents at all" (pilot gate 8, still open),
 * and the sweep refuses to guess. So a large `undetermined` here is a real, actionable
 * signal about the VENDOR — go and settle gate 8 — rather than a count of drifted clients.
 *
 * ## No lever, and the reason is stronger than on the panel above
 *
 * There is deliberately no "fix it" button. The repair a knowledge drift superficially
 * invites is a detach — an irreversible DELETE at the vendor of a document our tables, by
 * hypothesis, cannot describe. One click from a platform-wide summary would destroy the
 * only copy of text somebody added by hand, plausibly during an incident.
 */
function KnowledgeDriftPanel({ drift }: { drift: KbDriftState }) {
  const read = drift.status === "read" ? drift.drift : null;
  // A platform whose sweep has never run is NOT the same as one whose sweep is healthy and
  // found nothing, and the difference is `oldest_checked_at`. True even when `live_agents`
  // is 0: an empty platform has nothing to sweep, and saying "no knowledge has drifted"
  // there is accurate and says nothing about whether the job is alive.
  const swept = read !== null && read.oldest_checked_at !== null;

  return (
    <Card title="What the voice platform is answering from">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Every hour a sweep reads live agents&apos; knowledge bases back off the voice
          platform and compares them with what was approved and published. It only ever
          reads — knowledge added on the vendor&apos;s own console stays exactly where it is.
        </p>

        {drift.status === "loading" && <Skeleton rows={2} />}

        {/* The refusal. NOT "0 drifted": an operator who cannot see this number is the one
            who most needs telling that nobody has checked. */}
        {drift.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We do not know what knowledge the voice platform is holding"
          >
            <p className="mt-1">
              This is read with the platform state, and that read failed — so this screen
              will not tell you every agent&apos;s knowledge is in sync. The error above
              says what stopped it.
            </p>
          </NoticeBox>
        )}

        {/* THE ENGINE HAS NO KNOWLEDGE BASE — checked BEFORE "nothing has been swept",
            because the two produce identical data and only one of them is a problem.
            `sweep_kb_drift` returns on its first line when the engine lacks the
            capability, so on Bolna (`BOLNA_CAPABILITIES.knowledge_base` is False, D-354)
            it records nothing on every run, for ever, by design. The warning below then
            told an operator "the reconciliation job is not running" — permanently, about
            a job running hourly at :23 and doing exactly the right thing. Found by
            walking the console: the panel had counts and a null pulse, which is the same
            shape a dead cron makes, and no way to tell them apart until the API grew
            `engine_supports_knowledge_base`. */}
        {read !== null && !read.engine_supports_knowledge_base && (
          <NoticeBox
            tone="neutral"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="This engine has no built-in knowledge base"
          >
            <p className="mt-1">
              There is nothing here for the sweep to watch, so it records nothing and the
              counts below stay at zero. That is the engine&apos;s shape, not a failure —
              agents answer from the prompt they were published with, and the panel above
              is what watches that. Nothing to do.
            </p>
          </NoticeBox>
        )}

        {read !== null && read.engine_supports_knowledge_base && !swept && (
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
            title="No agent's knowledge has been checked yet"
          >
            <p className="mt-1">
              Nothing below is evidence: the counts are what the last check recorded, and it
              has not recorded anything. If this lasts more than an hour, the knowledge check
              has stopped running and nobody is watching what the agents answer from.
            </p>
          </NoticeBox>
        )}

        {read !== null && read.out_of_sync > 0 && (
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
            title={`${formatCount(read.out_of_sync)} of ${formatCount(read.live_agents)} live agents hold knowledge we did not publish`}
          >
            <p className="mt-1">
              Oldest divergence: <span className="font-semibold">{formatIST(read.oldest_drift_at)}</span>.
              Either the platform is serving text that never went through approval, or a
              version we approved is no longer there. Open each agent&apos;s knowledge tab —
              removing a document from here would delete it at the vendor, and if it was
              added on their console this is the only copy.
            </p>
          </NoticeBox>
        )}

        {read !== null && swept && read.out_of_sync === 0 && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Every checked agent is answering from what we published"
          >
            <p className="mt-1">
              {read.undetermined > 0
                ? `${formatCount(read.undetermined)} could not be decided — either the voice platform did not answer, or it reported no knowledge for an agent that should have some and nothing proved its listing is per-agent. That is a question about the vendor, not a drifted client.`
                : "No divergence found."}
            </p>
          </NoticeBox>
        )}

        {read !== null && (
          <table className="w-full text-left text-xs">
            <tbody>
              <tr>
                <td className="py-0.5 text-ink-muted">Live agents</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.live_agents)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Holding what we published</td>
                <td className="py-0.5 text-right tabular-nums">{formatCount(read.in_sync)}</td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Holding something else</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.out_of_sync)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Could not be decided</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.undetermined)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Not yet checked</td>
                <td className="py-0.5 text-right tabular-nums">
                  {formatCount(read.never_checked)}
                </td>
              </tr>
              <tr>
                <td className="py-0.5 text-ink-muted">Oldest check</td>
                <td className="py-0.5 text-right">
                  {swept ? formatIST(read.oldest_checked_at) : "never"}
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

/** `""` = the operator has not chosen yet; `"*"` = every job. Neither can collide with a
 *  real job name, which the API bounds to `^[a-z][a-z0-9_]*$`. */
const EVERY_JOB = "*";

/**
 * The outbox dead-letter queue: how deep it is, and its one lever —
 * `POST /v1/ops/outbox/replay`.
 *
 * `runbooks/webhook-delivery-failures.md` §3 and `campaign-escalation-refused.md` both end
 * at this endpoint with the instruction "never by hand", and until recently the only way
 * to reach it was by hand. It is cross-tenant: `replay_dead_letters` has no tenant
 * predicate at all (`outbox_messages` carries no `tenant_id`), so one click moves other
 * people's clients' messages.
 *
 * THE BLAST RADIUS IS REDELIVERY, not the flip. Every message it moves back to `pending`
 * gets a fresh attempt budget and will be delivered again — and a message can dead-letter
 * *after* its side effect landed, so "delivered twice" is the outcome to be sure about
 * before clicking, not the flag in the row.
 *
 * ## The depth, and why the panel changed shape around it
 *
 * This panel used to say, in its own words, that there was no count to show before the
 * click because no endpoint published one. So an operator confirmed a redelivery of
 * unknown size, unknown mix and unknown age — every other confirmation on this router
 * binds to something visible (a tenant id, a target mode, a direction), and this one named
 * an action whose scope was whatever the queue happened to hold. A confirmation you cannot
 * size is a habit, not a control.
 *
 * `GET /v1/ops/platform` now carries `outbox_dead_letters`, so the depth, the per-`job`
 * breakdown and the age of the oldest message are on screen BEFORE the confirmation. Four
 * consequences, each deliberate:
 *
 * 1. **A depth we could not read is not a zero.** The panel refuses to state one and says
 *    the confirmation is unsized — and the button STAYS ENABLED, because the lever must
 *    not disappear when the platform is behaving strangely. That is the same rule the
 *    gating already followed (this control is gated on the permission, never on the
 *    platform row); riding that read costs a NUMBER here, never the control.
 * 2. **A depth of 0 disables the button, with the reason beside it.** The objection is the
 *    load-shed panel's, one step earlier: the server would accept an empty replay and
 *    write an `ops.outbox_replay` audit row for a redelivery nobody performed. It is the
 *    console's guard alone — the API cannot refuse an empty queue without lying about the
 *    race between the check and the claim.
 * 3. **The panel still renders when the queue is empty.** The runbook sends operators here
 *    by name ("Console: Operations — /admin/ops → Dead-lettered outbox messages"), and a
 *    panel that vanished would make "the runbook is wrong" indistinguishable from "there
 *    is nothing parked".
 * 4. **The scope is chosen, not defaulted.** See the select below.
 */
function OutboxReplayPanel({
  access,
  queue,
}: {
  access: OpsAccess;
  queue: DeadLetterState;
}) {
  const replay = useReplayOutbox();
  const [confirm, setConfirm] = useState("");
  // Opens on NO CHOICE, for the load-shed panel's reason applied to a bigger blast
  // radius: a select preloaded with "every job" would make "click the obvious button" a
  // cross-tenant redelivery of everything, chosen by nobody.
  const [scope, setScope] = useState("");

  const sized = queue.status === "read" ? queue.queue : null;
  const job = scope === "" || scope === EVERY_JOB ? null : scope;
  // Nothing to choose FROM when the queue could not be read, and nothing to choose
  // BETWEEN when it is empty — so in both cases the choice is not withheld and this term
  // stands aside. That is not tidiness: while it also covered the empty queue, two
  // independent guards produced one dead button, `replayable` was doing no work, and a
  // test asserting the empty-queue rule passed with that rule deleted (it was really
  // asserting the scope rule). One condition, one reason, one sentence under the button.
  const scopeChosen = sized === null || sized.depth === 0 || scope !== "";
  const replayable = queue.status === "unreadable" || (sized !== null && sized.depth > 0);
  // The permission is part of `ready` here rather than a second term at the button,
  // because the sentence under the button explains whichever condition is unmet and
  // "ready" must therefore mean the same thing as "the button is alive".
  const ready = access.allowed && replayable && scopeChosen && confirm === "REPLAY";

  const scopedDepth =
    job === null ? sized?.depth : sized?.by_job.find((entry) => entry.job === job)?.depth;

  // WHY the control is dead, in the order the operator can act on: their permission, then
  // ours to answer, then the queue's own answer. Rendered BESIDE the button — a reason a
  // screenful away from the control it explains is the defect §52 found on three screens.
  const deadReason = !access.allowed
    ? access.reason
    : queue.status === "loading"
      ? "Checking how many messages are stuck. The button unlocks once we know the size of the resend."
      : sized !== null && sized.depth === 0
        ? // THE ALL-CLEAR LIVES IN TWO PLACES, and only one of them was fixed first: the
          // green box above became conditional on `deferred` while this sentence — the one
          // physically next to the button, which is where an operator actually reads — went
          // on saying "nothing is stuck" during an outage. Caught by
          // `apps/web/tests/ops.test.tsx`, and worth the note: a panel with two voices needs
          // both of them changed, and the one beside the control is the one that counts.
          sized.deferred > 0
          ? `No message has failed yet, so there is nothing to resend — but ${formatCount(sized.deferred)} ` +
            "are waiting to retry on their own (shown above). Resending only helps messages that " +
            "have already failed; these need the queue to come back."
          : "Nothing is stuck, so there is nothing to resend. Running it anyway would record a " +
            "resend in the activity log that never actually happened."
        : !scopeChosen
          ? "Choose what to resend first. There is no default, because the default would be " +
            "the biggest possible action."
          : null;

  return (
    <Card title="Stuck outbound messages">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Messages that failed to send after several tries and are now stuck — things like
          a lead sent to a client&apos;s own system, or a hot-lead alert. Resending puts
          them back in line to be tried again, for every client at once, oldest first, up
          to 100 at a time.
        </p>

        {queue.status === "loading" && <Skeleton rows={2} />}

        {/* The refusal. NOT "0 parked" and NOT a hidden panel: an operator who cannot see
            the queue is exactly the one who must be told that the confirmation below is
            unsized, rather than reassured by a number nobody sent. */}
        {queue.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We do not know how many messages are stuck"
          >
            <p className="mt-1">
              The count is read together with the platform state, and that read failed — so
              this screen will not tell you nothing is stuck, and it will not tell you how
              large a resend would be. The error above says what stopped it.
            </p>
            <p className="mt-2">
              The button below still works, on purpose: removing a recovery tool because a
              number was unavailable is worse than running it without knowing the size. It
              will resend <span className="font-semibold">every type</span> — up to 100,
              oldest first.
            </p>
          </NoticeBox>
        )}

        {/* THE ALL-CLEAR, AND THE CASE THAT IS NOT ONE.
            `depth === 0` used to render "Nothing is dead-lettered" unconditionally, and
            during a queue outage that sentence was TRUE and the screen it produced was a
            lie: `defer_outbox_claim` holds a failing batch as `pending` with a lease into
            the future, so for the whole five minutes of tolerated downtime the DLQ really
            is empty while the backlog grows behind it. An operator opening this screen
            mid-incident read a green box. `deferred` is the same aggregate's answer to
            "and how many are waiting", so the tone follows the queue's actual health
            rather than the one state this panel happens to act on. */}
        {sized !== null && sized.depth === 0 && sized.deferred === 0 && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Nothing is stuck"
          >
            <p className="mt-1">
              No outbound message has failed, so there is nothing to resend and the button
              below is disabled. This is a live measurement, not an assumption — it
              refreshes every 30 seconds.
            </p>
          </NoticeBox>
        )}

        {/* Deferred messages are NOT this panel's lever — replay acts on `failed` rows
            only and would move none of them — so this box states the situation and
            explicitly says not to click, rather than implying the button is the answer. */}
        {sized !== null && sized.deferred > 0 && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title={`${formatCount(sized.deferred)} messages are waiting to retry on their own`}
          >
            <p className="mt-1">
              These are not stuck — the system will retry them by itself in a short while.
              A number here that keeps climbing means the whole queue is unreachable, not
              that any one message is bad; that&apos;s a separate alert, covered by the
              webhook-delivery runbook.
            </p>
            <p className="mt-2">
              Resending does nothing for these — it only acts on messages that have already
              failed. If they run out of automatic retries before the queue recovers, they
              become stuck, and then resending will apply.
            </p>
          </NoticeBox>
        )}

        {/* THE SIZE OF THE ACT, before the confirmation. The breakdown is the half a total
            cannot give: 142 CRM webhooks and 142 hot-lead emails are different things to
            re-send, and the oldest timestamp is what separates a retry from a client's CRM
            receiving a lead they closed last week. Counts and job names only — outbox
            payloads are JSONB carrying phone numbers and extraction output (hard rule 6),
            and the API publishes none of it. */}
        {sized !== null && sized.depth > 0 && (
          <NoticeBox
            tone="warn"
            icon={<PackageOpen aria-hidden className="h-5 w-5" />}
            title={`${formatCount(sized.depth)} messages are stuck`}
          >
            <p className="mt-1">
              Oldest: <span className="font-semibold">{formatIST(sized.oldest_at)}</span>.
              Resending sends them again; an old one may reach a client who has already
              dealt with it another way.
            </p>
            {/* The scroll container every other table in this repo already has. Its
                three columns (a job name, a count, an IST timestamp) do not fit 320px,
                and inside the shell's `overflow-hidden` the excess was CLIPPED rather
                than scrollable — the "Oldest" column was simply unreachable. */}
            <ScrollRegion label="Stuck message types" className="mt-3">
            <table className="w-full text-left text-xs">
              <thead className="text-ink-faint">
                <tr>
                  <th className="pb-1 font-medium">Type</th>
                  <th className="pb-1 text-right font-medium">Stuck</th>
                  <th className="pb-1 text-right font-medium">Oldest</th>
                </tr>
              </thead>
              <tbody>
                {sized.by_job.map((entry) => (
                  <tr key={entry.job}>
                    <td className="py-0.5 pr-2 font-mono">{entry.job}</td>
                    <td className="py-0.5 text-right tabular-nums">
                      {formatCount(entry.depth)}
                    </td>
                    <td className="py-0.5 pl-2 text-right">{formatIST(entry.oldest_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </ScrollRegion>
          </NoticeBox>
        )}

        {replay.error && <WriteFailure error={replay.error} actionLabel="Resend stuck messages" />}

        {/* The SERVER's count, rendered as the result it is. A toast would put the one
            number this control produces on a timer. */}
        {replay.data && (
          <NoticeBox
            tone={replay.data.replayed > 0 ? "ok" : "neutral"}
            icon={<RefreshCw aria-hidden className="h-5 w-5" />}
            title={
              replay.data.replayed > 0
                ? `${formatCount(replay.data.replayed)} messages queued to resend`
                : "Nothing was stuck"
            }
          >
            <p className="mt-1">
              {replay.data.replayed > 0
                ? "Each one gets a fresh set of attempts. Keep an eye on the count above rather than assuming they all land — the webhook-delivery runbook covers the follow-up."
                : "No message had failed, so nothing was resent. That is an answer, not a failure."}
            </p>
            {/* The scope the SERVER applied, not the one this form thinks it sent: a
                `replayed: 0` under a mistyped job is an operator's typo, and reading it
                back is what makes that visible rather than "the queue was empty". */}
            <p className="mt-2 text-xs">
              Resent: <span className="font-mono">{replay.data.job ?? "every type"}</span>
            </p>
            {/* The run is capped at 100 (`replay_dead_letters`), so a full batch is the
                one result that does NOT mean the queue is now empty. */}
            {replay.data.replayed === 100 && (
              <p className="mt-2 font-semibold">
                That is the per-run limit, so there may be more waiting. Run it again.
              </p>
            )}
          </NoticeBox>
        )}

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            replay.mutate(job, { onSuccess: () => setConfirm("") });
          }}
        >
          {/* THE SCOPE, offered only when we can enumerate it.
              `outbox_messages` has no `tenant_id` (infra table — the ids live inside the
              JSONB payload), so per-client scoping is impossible without a migration and
              `job` is the only bound available. It is not a consolation prize: the run
              takes the 100 OLDEST rows, so an operator recovering a client's webhooks out
              of a queue full of dead-lettered emails replays 100 emails, reads "100 moved"
              as success, and leaves every webhook parked. */}
          {sized !== null && sized.depth > 0 && (
            <label className="block">
              <span className={FIELD_LABEL}>What to resend</span>
              <select
                value={scope}
                onChange={(e) => {
                  setScope(e.target.value);
                  // The confirmation authorises THIS scope — the header carries it
                  // (`outboxReplayConfirmation`) — so a word typed for one selection must
                  // not survive a change of selection and submit against another.
                  setConfirm("");
                }}
                disabled={!access.allowed}
                className={FIELD}
              >
                <option value="">— choose —</option>
                <option value={EVERY_JOB}>
                  Every type — all {formatCount(sized.depth)} stuck messages
                </option>
                {sized.by_job.map((entry) => (
                  <option key={entry.job} value={entry.job}>
                    {entry.job} — {formatCount(entry.depth)} stuck
                  </option>
                ))}
              </select>
              <span className={FIELD_HINT}>
                Choosing a type limits what gets resent. It does not limit WHOSE — every
                type covers all clients at once, because these messages aren&apos;t split
                by client.
              </span>
            </label>
          )}

          <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
            <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
            <div className="min-w-0">
              <p className="font-semibold text-ink">
                This resends stuck messages for EVERY client, not one
              </p>
              <p className="mt-1 text-ink-muted">
                A message that actually reached its destination before it got stuck will be
                sent a second time — a duplicate WhatsApp alert, or a duplicate delivery to
                a client&apos;s own system. This can&apos;t be undone from here.
              </p>
              {/* What THIS submission will send, in numbers, immediately above the
                  confirmation it is asking for. */}
              {scopedDepth !== undefined && scopeChosen && (
                <p className="mt-1 font-semibold text-ink">
                  About to resend up to {formatCount(Math.min(scopedDepth, 100))} of the{" "}
                  {formatCount(scopedDepth)} stuck{" "}
                  {job !== null && (
                    <>
                      <span className="font-mono">{job}</span>{" "}
                    </>
                  )}
                  messages, oldest first.
                </p>
              )}
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the activity log with how many were resent and which type. The
                word you type below is also sent to confirm this exact action, so it
                can&apos;t be triggered from outside this form.
              </p>
            </div>
          </div>

          <label className="block">
            <span className={FIELD_LABEL}>Type REPLAY to confirm</span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed}
              placeholder="REPLAY"
              className={`${FIELD} font-mono`}
            />
          </label>

          <button
            type="submit"
            title={deadReason ?? undefined}
            disabled={!ready || replay.isPending}
            className={DANGER_BUTTON}
          >
            <RefreshCw aria-hidden className="h-4 w-4" />
            {replay.isPending ? "Resending…" : "Resend stuck messages"}
          </button>

          {deadReason && !ready && (
            <p className="flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {deadReason}
            </p>
          )}
        </form>
      </div>
    </Card>
  );
}

/**
 * The audit hash chain, verified on demand — `GET /v1/ops/audit/verify`.
 *
 * Three things make this panel different from every other control on the screen:
 *
 * 1. **It writes nothing, so it takes no typed confirmation.** The confirmations here
 *    exist to stop an accidental CHANGE; demanding one to run a read would be friction
 *    whose only lesson is that confirmations are things you type past.
 * 2. **A failure is an INCIDENT and is rendered as one.** `audit_log` is INSERT-only
 *    (hard rule 4) and each row's hash covers the previous one, so a broken link means a
 *    row was edited, deleted or reordered — evidence of tampering, or of a writer that
 *    bypassed `write_audit`. That does not belong in a toast that fades: it stays on
 *    screen, in the stop palette, naming the entry.
 * 3. **What it does NOT prove is on screen too.** The verdict now travels with its
 *    SCOPE — `entries_checked`, the `at` range, and `complete`, which is true only when
 *    the walk reached the end of the log. This copy used to hard-code "the oldest 1,000
 *    entries" because the route walked a fixed limit and published no scope, so the
 *    console had to compensate in prose. That prose outlived the limit and became false
 *    in the other direction, which is the argument for rendering the server's own
 *    numbers rather than a sentence about them: a fixed string cannot track a fix.
 *
 * The verdict is stamped with the moment it was asked for, because a verification carries
 * an implicit "as of", and one left on screen while an operator works elsewhere is
 * otherwise indistinguishable from a live one.
 */
/**
 * The weakly-attested era, rendered beside the verdict rather than under it.
 *
 * `entries_under_retired_key` is NOT a break and is not a component of `ok` — those
 * entries hash correctly. What they lack is attestation STRENGTH: on most deployments
 * they are the rows written before `AUDIT_CHAIN_SECRET` was required, when the chain
 * was signed with a constant that was printed in the source, so anyone who could read
 * the repository could have produced a row that verifies. That distinction only matters
 * at one moment — when an operator exports this log as evidence — and a caveat that
 * lives in a runbook reaches nobody at that moment.
 *
 * It renders on the intact verdict AND on the failed one, because the two facts are
 * independent: a log can be unbroken and still partly weakly attested, and a log with a
 * break has the same era question about everything either side of it.
 */
function WeaklyAttestedNote({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <p className="mt-2">
      <span className="font-semibold">
        {formatCount(count)} {count === 1 ? "entry" : "entries"} verified under a retired
        signing key.
      </span>{" "}
      Those rows are intact — they are not tampered with — but they were signed before this
      deployment had its own private signing key, when the key was a value anyone with the
      source code could read. Treat them as weaker evidence than the rest: if you are
      exporting this log for a dispute or an audit, say where that earlier period ends.
    </p>
  );
}

function AuditChainPanel({ access }: { access: OpsAccess }) {
  const verify = useVerifyAuditChain();
  const asOf = verify.data ? formatIST(new Date(verify.submittedAt).toISOString()) : null;

  return (
    <Card title="Activity-log tamper check">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Every entry in the activity log is sealed against the one before it, so any entry
          that was edited, deleted or reordered shows up as a broken seal. This re-checks
          the whole log and reports every break, not just the first — it&apos;s the check
          behind the quarterly compliance review, and the one to run when a client disputes
          a record.
        </p>

        {verify.error && <ProblemNotice error={verify.error} />}

        {/* `ok === false` is not a failed REQUEST — the request succeeded and the answer
            is bad. Rendering it as an error notice would file it under "try again". */}
        {verify.data && !verify.data.ok && (
          <NoticeBox
            tone="stop"
            icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
            title="TAMPER CHECK FAILED"
          >
            <p className="mt-1">
              {verify.data.breaks_found === 1
                ? "The seal is broken in one place."
                : `The seal is broken in ${formatCount(verify.data.breaks_found)} places.`}{" "}
              The check did not stop at the first — it carried on to the end, so what follows
              covers the whole log, not just the part before the earliest break.
            </p>
            {/* Every break, dated and typed. A single line naming only the first is how a
                historical break — which an append-only ledger can never repair — hides
                tonight's, and how an attacker buys silence on the recent past by damaging
                something old. `at` is what lets an operator tell those two apart. */}
            {verify.data.breaks.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {verify.data.breaks.map((entry) => (
                  <li key={entry.entry_id} className="text-sm">
                    <span className="font-mono font-semibold">{entry.entry_id}</span>
                    {" — "}
                    {entry.kind === "content"
                      ? "its own fields no longer hash to its recorded hash (edited)"
                      : "it names the wrong predecessor (deleted or reordered)"}
                    {", "}
                    {formatIST(entry.at)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2">
                The server reported a break at{" "}
                <span className="font-mono font-semibold">
                  {verify.data.first_bad_entry_id ?? "an entry it did not name"}
                </span>{" "}
                without listing it.
              </p>
            )}
            {verify.data.breaks_found > verify.data.breaks.length && (
              <p className="mt-2">
                Only the first {formatCount(verify.data.breaks.length)} are listed;{" "}
                {formatCount(verify.data.breaks_found - verify.data.breaks.length)} more
                were found. At this scale the count matters more than the individual rows —
                query the activity log directly.
              </p>
            )}
            <p className="mt-2">
              <span className="font-semibold">Treat this as an incident.</span> The activity
              log is add-only — entries are never meant to change — so a broken seal means an
              entry was edited, deleted or reordered in the database. Do not re-run and move
              on: note the entry IDs above, and do not let anyone &quot;repair&quot; the
              rows — the break itself is the evidence.
            </p>
            <WeaklyAttestedNote count={verify.data.entries_under_retired_key} />
            <p className="mt-2 text-xs">
              {verify.data.complete
                ? `Whole log checked — ${formatCount(verify.data.entries_checked)} entries. Checked at ${asOf}.`
                : `Covers ${formatCount(verify.data.entries_checked)} entries only, so there may be more beyond them. Checked at ${asOf}.`}
            </p>
          </NoticeBox>
        )}

        {verify.data?.ok && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="No tampering found in the entries checked"
          >
            <p className="mt-1">
              Every seal checked out, so nothing in that range was edited, deleted or
              reordered.
            </p>
            {/* The scope, beside the green box rather than in a tooltip: this is what
                stops "verified" being read as "the whole log is verified". It is the
                server's own count and range — an incomplete walk must never be allowed
                to read like a full audit. */}
            <p className="mt-2">
              {verify.data.complete
                ? `Whole log checked — ${formatCount(verify.data.entries_checked)} entries, from the first row to the last.`
                : `This covers ${formatCount(verify.data.entries_checked)} entries only, so it says nothing about the rest of the log.`}
            </p>
            <WeaklyAttestedNote count={verify.data.entries_under_retired_key} />
            <p className="mt-2 text-xs">Checked at {asOf}.</p>
          </NoticeBox>
        )}

        <div>
          <button
            type="button"
            title={access.reason ?? undefined}
            disabled={!access.allowed || verify.isPending}
            onClick={() => verify.mutate()}
            className={SECONDARY_BUTTON}
          >
            <FileSearch aria-hidden className="h-4 w-4" />
            {verify.isPending ? "Checking…" : "Run the tamper check"}
          </button>
          <p className="mt-2 text-xs text-ink-faint">
            This only reads and reports — it changes nothing, which is why it asks for no
            typed confirmation.
          </p>
          {!access.allowed && access.reason && (
            <p className="mt-2 flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {access.reason}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className={mono ? "mt-0.5 font-mono text-sm text-ink" : "mt-0.5 text-sm text-ink"}>
        {value}
      </dd>
    </div>
  );
}
