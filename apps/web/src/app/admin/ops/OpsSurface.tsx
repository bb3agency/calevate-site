"use client";

import { ShieldCheck } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { Card, ProblemNotice, Skeleton } from "@/components/ui";
import { usePlatformState } from "@/lib/api/admin";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AuditChainPanel } from "./AuditChainPanel";
import { EngineDriftPanel } from "./EngineDriftPanel";
import { KnowledgeDriftPanel } from "./KnowledgeDriftPanel";
import { LoadShedPanel } from "./LoadShedPanel";
import { OutboundHaltPanel } from "./OutboundHaltPanel";
import { OutboxReplayPanel } from "./OutboxReplayPanel";
import { TmRegistrationPanel } from "./TmRegistrationPanel";
import { UnknownStatePanel } from "./UnknownStatePanel";
import { opsAccess } from "./opsAccess";
import {
  deadLetterState,
  engineDriftState,
  kbDriftState,
} from "./opsSurfaceState";

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
 *
 * ## Why the panels are seven files and not one
 *
 * This module was 2,173 lines, which is UX-DOCTRINE §6's smell with its named remedy:
 * extract by SUBJECT. Each panel below is a subject — one switch, one summary, one
 * recovery lever — with its own preconditions and its own confirmation, and each is now
 * its own file beside this one. Nothing about what any of them does changed; what changed
 * is that the hierarchy is visible from the directory listing rather than from a scroll.
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

export function OpsSurface() {
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
