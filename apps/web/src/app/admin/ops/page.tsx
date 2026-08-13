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
  PhoneCall,
  PhoneOff,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { useAdminAccess, type AdminAccess } from "@/app/admin/access";
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
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  usePlatformState,
  useReplayOutbox,
  useSetPlatformState,
  useSetTmRegistration,
  useVerifyAuditChain,
  type LoadShedMode,
  type PlatformState,
  type TmRegistration,
  type TmStatus,
} from "@/lib/api/admin";
import { hasKey, lookup } from "@/lib/lookup";

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
 *    and takes a typed confirmation — echoed to the API as a step-up header wherever the
 *    route demands one (`platformConfirmation`, `spendCapConfirmation`). Not a second
 *    factor and not pretending to be one — it stops the accidental click, and Clerk
 *    re-auth replaces it when admin MFA lands.
 *
 *    Two asymmetries are deliberate rather than oversights, and each is argued at its
 *    panel: the outbox replay takes the typed word but sends NO header, because the route
 *    accepts none and a header the server ignores would advertise an enforcement that
 *    does not exist; the audit-chain verification takes neither, because it writes
 *    nothing and a confirmation on a read only teaches operators to type past them.
 * 4. **`tm_registration.is_live` is DISPLAYED, never computed.** The launch gate refuses
 *    every tenant's campaign with `tm_registration_missing` from the same property, so a
 *    console that decided for itself whether `submitted` counts would be capable of
 *    showing a green platform while every client's launch was being refused. The same
 *    rule governs the two new readouts: the replay renders the server's count and the
 *    verification renders the server's verdict, including a FAILURE, which stays on
 *    screen in the stop palette rather than passing as a notification.
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
 * The `<h1>` stays: the admin shell (layout.tsx) prints "Calevate admin" and the nav, not
 * the page title, so removing it would leave the screen unnamed. It goes the moment the
 * shell prints one.
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
    now: "Everything is being served normally.",
    blast:
      "Takes the platform out of shedding: client-realm writes are accepted again and new self-serve signups reopen.",
  },
  reduced: {
    now: "Every client-realm write is being refused with 503 service_load_shed. Reads still work.",
    blast:
      "Every client-realm WRITE starts being refused with a 503 — launching a campaign, saving an agent, adding a lead. Reads keep working, and a campaign that is already running keeps dialling: the dispatch tick is not an HTTP request. New self-serve signups are refused.",
  },
  emergency: {
    now: "Every client-realm write is being refused with 503 service_load_shed. Reads still work.",
    blast:
      "Sheds exactly what reduced sheds. core/loadshed.py puts both in _SHED_WRITES and neither in _SHED_READS, so today this is a louder NAME for the same posture, not a stricter one — pick it to say how bad things are, not expecting reads to stop.",
  },
  maintenance: {
    now: "Planned downtime: reads are being shed too. Only health, auth, engine webhooks and the admin/ops surface are served.",
    blast:
      "Client screens go dark — reads are refused as well as writes, so a client opening their dashboard gets a 503. Engine webhooks still land, so no call's lead is lost. This console, /v1/ops and /v1/admin stay served, so you can always take the platform back out.",
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
  const access = opsAccess(mayManage, state);

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink">Operations</h1>
        <p className="mt-0.5 text-sm text-ink-muted">
          Platform-wide switches. Every change is audit-logged with its reason, and every
          one of them applies to every client at the same instant.
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
      <OutboxReplayPanel access={mayRecover} />
      <AuditChainPanel access={mayRecover} />

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
        If calls have stopped and you need the switch now, runbooks/calls-stopped.md §1
        carries the request to send by hand.
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
                No outbound call is being placed for any tenant. Inbound calls are
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
                  ? "Paused campaigns pick up at the next dispatch tick. Every campaign's own compliance gate still applies — this releases the platform-wide stop and nothing else."
                  : "Running campaigns stop at the next dispatch tick and no new outbound call is placed for any tenant. Inbound calls are unaffected — the caller initiated those, and refusing them would silently break the receptionist clients pay for."}
              </p>
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the audit log against your admin account, with the reason you
                type below.
              </p>
            </div>
          </div>

          {setState.error && <ProblemNotice error={setState.error} />}

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
                  : "e.g. 'DLT complaint spike — stopping until we have read the logs'"
              }
              className={FIELD}
            />
            <span className={FIELD_HINT}>
              Whoever finds outbound stopped at 3am reads this to decide whether the
              condition still holds. It is stored on the row, not only in the audit log.
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
    <Card title="Load-shed mode">
      <div className="space-y-4">
        <NoticeBox
          tone={current === "normal" ? "ok" : "warn"}
          icon={<Gauge aria-hidden className="h-5 w-5" />}
          title={
            current === "normal"
              ? "Serving normally"
              : `Shedding — the platform is in ${current} mode`
          }
        >
          <p className="mt-1">
            {note?.now ?? (
              <>
                This console has no description for that mode — read it as unknown and
                check core/loadshed.py before assuming what it sheds.
              </>
            )}
          </p>
          <p className="mt-2 text-xs">
            Current mode: <span className="font-mono">{current}</span>
          </p>
        </NoticeBox>

        {setState.error && <ProblemNotice error={setState.error} />}

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
                  {mode}
                  {mode === current ? " — the mode in force now" : ""}
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
                  ? `The platform is already in ${current} mode`
                  : `Switching to ${target} applies to every client at once`}
              </p>
              <p className="mt-1 text-ink-muted">{LOAD_SHED[target].blast}</p>
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the audit log against your admin account, with the reason you
                type below. Load-shedding does not stop a campaign that is already
                running, and it never touches inbound calls.
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
              placeholder="e.g. 'database CPU at 95% — shedding writes until the index build finishes'"
              className={FIELD}
            />
            <span className={FIELD_HINT}>
              Whoever finds the platform shedding reads this to decide whether the
              condition still holds.
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
            {setState.isPending ? "Sending…" : `Switch to ${target}`}
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

const TM_STATUSES: { value: TmStatus; label: string }[] = [
  { value: "not_registered", label: "not_registered — no application filed" },
  { value: "submitted", label: "submitted — filed, not yet granted" },
  { value: "active", label: "active — granted and in force" },
  { value: "suspended", label: "suspended — registrar action, e.g. complaints" },
  { value: "revoked", label: "revoked — registration withdrawn" },
];

/** `date-time` ⇄ `<input type="datetime-local">`. The input speaks LOCAL wall-clock
 * (an operator types the IST moment on the registrar's letter) and `Date` converts it
 * to the instant the API stores, so no timezone arithmetic happens by hand. */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(
    at.getHours(),
  )}:${pad(at.getMinutes())}`;
}

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
    TM_STATUSES.some((s) => s.value === registration.status)
      ? (registration.status as TmStatus)
      : "not_registered",
  );
  const [tmId, setTmId] = useState(registration.tm_id ?? "");
  const [registeredAt, setRegisteredAt] = useState(toLocalInput(registration.registered_at));
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
    <Card title="Our telemarketer registration (DLT)">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Calevate is the registered Telemarketer; each client is its own Principal
          Entity. One fact for the whole platform.
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
          title={live ? "LIVE — we may lawfully dial" : "NOT LIVE — no tenant can launch"}
        >
          <p className="mt-1">
            {live
              ? "Campaign launches are not blocked by this. Every client still needs its own Principal Entity registration and TM link."
              : "While this is not live, NO tenant can launch an outbound campaign, however complete their own registration is. Inbound answering is unaffected — clients' receptionists keep working."}
          </p>
        </NoticeBox>

        <dl className="grid gap-3 sm:grid-cols-4">
          <Fact label="Status" value={registration.status} />
          <Fact label="TM id" value={registration.tm_id ?? "—"} mono />
          <Fact label="Registered" value={formatIST(registration.registered_at)} />
          <Fact label="Last verified" value={formatIST(registration.verified_at)} />
        </dl>

        {record.error && <ProblemNotice error={record.error} />}
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
                registered_at: registeredAt ? new Date(registeredAt).toISOString() : null,
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
                {TM_STATUSES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
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
              <span className={FIELD_LABEL}>Registered on</span>
              <input
                type="datetime-local"
                value={registeredAt}
                onChange={(e) => setRegisteredAt(e.target.value)}
                disabled={!access.allowed}
                className={FIELD}
              />
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
            <span className={FIELD_HINT}>Recorded in the audit log with this change.</span>
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
                ? "Recording this as active turns the platform-wide launch gate green for every tenant."
                : "Anything other than active takes the gate away: no tenant can launch an outbound campaign until it is recorded active again."}
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
                : `Record as ${status.replace(/_/g, " ")}`}
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
 * The outbox dead-letter queue's one lever — `POST /v1/ops/outbox/replay`.
 *
 * `runbooks/webhook-delivery-failures.md` §"failed" and `campaign-escalation-refused.md`
 * both end at this endpoint with the instruction "never by hand", and until now the only
 * way to reach it was by hand. It is cross-tenant: `replay_dead_letters` selects on
 * `status = 'failed'` with no tenant predicate at all, so one click moves other people's
 * clients' messages.
 *
 * THE BLAST RADIUS IS REDELIVERY, not the flip. Every message it moves back to `pending`
 * gets a fresh attempt budget and will be delivered again — and a message can dead-letter
 * *after* its side effect landed, so "delivered twice" is the outcome to be sure about
 * before clicking, not the flag in the row.
 *
 * NO STEP-UP HEADER, and the console says so rather than inventing one: the route accepts
 * none (`ops/routes.py`). The typed word below is this screen's own guard and it is
 * honest about being that — see `useReplayOutbox` on why sending a header the server
 * never reads would be worse than sending none.
 *
 * There is no dead-letter COUNT to show before the click, because no endpoint publishes
 * one. That is stated instead of guessed at: this control does not move a state we failed
 * to read (the ops screen's rule), it moves a queue whose size nothing here can see, and
 * the response is the console's first and only measurement of it.
 */
function OutboxReplayPanel({ access }: { access: OpsAccess }) {
  const replay = useReplayOutbox();
  const [confirm, setConfirm] = useState("");
  const ready = confirm === "REPLAY";

  return (
    <Card title="Dead-lettered outbox messages">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Messages that exhausted their retries and were parked. Replaying moves them back
          to <span className="font-mono">pending</span> so the dispatcher picks them up
          again — for every client at once, oldest first, up to 100 per run.
        </p>

        {replay.error && <ProblemNotice error={replay.error} />}

        {/* The SERVER's count, rendered as the result it is. A toast would put the one
            number this control produces on a timer. */}
        {replay.data && (
          <NoticeBox
            tone={replay.data.replayed > 0 ? "ok" : "neutral"}
            icon={<RefreshCw aria-hidden className="h-5 w-5" />}
            title={
              replay.data.replayed > 0
                ? `${formatCount(replay.data.replayed)} messages moved back to pending`
                : "Nothing was dead-lettered"
            }
          >
            <p className="mt-1">
              {replay.data.replayed > 0
                ? "Each one will be attempted again from a fresh budget. Watch the DLQ rather than assuming they land — runbooks/webhook-delivery-failures.md carries the follow-up."
                : "The server found no message in the failed state, so nothing was moved. That is an answer, not a failure."}
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
            replay.mutate(undefined, { onSuccess: () => setConfirm("") });
          }}
        >
          <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
            <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
            <div className="min-w-0">
              <p className="font-semibold text-ink">
                This replays dead letters for EVERY client, not one
              </p>
              <p className="mt-1 text-ink-muted">
                A message that already reached its destination before it dead-lettered
                will be delivered a second time — a duplicate WhatsApp escalation, a
                duplicate webhook to a client&apos;s own system. Read the queue first if
                you can; this is not reversible from here.
              </p>
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the audit log as ops.outbox_replay with the number moved. The
                API asks for no step-up header on this one, so the word below is the only
                thing between this button and a redelivery.
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
            title={access.reason ?? undefined}
            disabled={!access.allowed || !ready || replay.isPending}
            className={DANGER_BUTTON}
          >
            <RefreshCw aria-hidden className="h-4 w-4" />
            {replay.isPending ? "Replaying…" : "Replay dead letters"}
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
 * 3. **What it does NOT prove is on screen too.** `verify_chain` walks `ORDER BY at ASC
 *    LIMIT 1000` — the OLDEST thousand entries. On a log longer than that, an intact
 *    verdict says nothing whatsoever about last night, which is the half an operator
 *    would otherwise assume. The route publishes no way to ask for a window, so the
 *    honest move is to state the limit rather than let a green box imply a full audit.
 *
 * The verdict is stamped with the moment it was asked for, because a verification carries
 * an implicit "as of", and one left on screen while an operator works elsewhere is
 * otherwise indistinguishable from a live one.
 */
function AuditChainPanel({ access }: { access: OpsAccess }) {
  const verify = useVerifyAuditChain();
  const asOf = verify.data ? formatIST(new Date(verify.submittedAt).toISOString()) : null;

  return (
    <Card title="Audit chain">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Recomputes the hash chain over <span className="font-mono">audit_log</span> and
          reports the first broken link. It is the check behind the quarterly compliance
          drill (OPERATIONS §6) and the one to run when a client disputes a record.
        </p>

        {verify.error && <ProblemNotice error={verify.error} />}

        {/* `ok === false` is not a failed REQUEST — the request succeeded and the answer
            is bad. Rendering it as an error notice would file it under "try again". */}
        {verify.data && !verify.data.ok && (
          <NoticeBox
            tone="stop"
            icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
            title="AUDIT CHAIN VERIFICATION FAILED"
          >
            <p className="mt-1">
              The recomputed hash does not match at{" "}
              <span className="font-mono font-semibold">
                {verify.data.first_bad_entry_id ?? "an entry the server did not name"}
              </span>
              . Every entry after it is unverifiable until this is explained.
            </p>
            <p className="mt-2">
              <span className="font-semibold">Treat this as an incident.</span> The ledger
              is INSERT-only, so a break means an entry was edited, deleted or reordered
              in the database, or something wrote to it without going through write_audit.
              Do not re-run and move on: capture the entry id above, and do not let anyone
              &quot;repair&quot; the row — the break is the evidence.
            </p>
            <p className="mt-2 text-xs">Checked at {asOf}.</p>
          </NoticeBox>
        )}

        {verify.data?.ok && (
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="Chain intact for the entries checked"
          >
            <p className="mt-1">
              Every link recomputed cleanly, so nothing in that range was edited, deleted
              or reordered.
            </p>
            {/* The limit, beside the green box rather than in a tooltip: this is the
                sentence that stops "verified" being read as "the whole log is verified". */}
            <p className="mt-2">
              This covers the OLDEST 1,000 entries only (verify_chain walks the log
              forwards with a limit). On a longer log it says nothing about recent
              activity.
            </p>
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
            {verify.isPending ? "Verifying…" : "Verify the audit chain"}
          </button>
          <p className="mt-2 text-xs text-ink-faint">
            Read-only: it recomputes hashes and writes nothing, which is why it asks for no
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
