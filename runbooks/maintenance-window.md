# Runbook — planned maintenance windows

**When to read this**: you are about to take Calevate down on purpose, or a window you
scheduled has done something you did not expect.

Design and decisions: D-544 in `docs/ROADMAP.md` §6. Code: `apps/api/ops/maintenance.py`
(state machine), `apps/workers/maintenance.py` (the one actuator),
`apps/api/ops/maintenance_routes.py` (the console's API).

---

## 1. What a window actually does, in order

A window has two live states and the difference between them is the whole feature.

| State | The platform | The client portal | Inbound calls | Campaigns |
| --- | --- | --- | --- | --- |
| `scheduled` | normal | open, with a banner | normal | running |
| `draining` | **accepts no new work** | **open**, with a banner | answered with the maintenance message | **paused** |
| `active` | shut to clients | **503, with the reason and a `Retry-After`** | answered with the maintenance message | paused |
| `completed` | normal | open | normal | **resumed where they stopped** |

`draining` begins at `starts_at`. `active` begins when in-flight work reaches ZERO — no
non-terminal call in any tenant, no pending outbox row, no unhandled webhook inbox row —
or when the drain deadline passes, whichever comes first.

**Operators are never locked out.** `/v1/ops`, `/v1/admin`, `/healthz`, `/hooks` and both
realms' sign-in routes are in `core/loadshed`'s exemption lists and are not shed in any
mode. If you cannot reach the console during a window, the window is not the cause.

## 2. Scheduling one

Admin console → Ops → Maintenance. You need three things and a fourth is optional:

* **start and end** — the end is what clients are told and what the `Retry-After` on every
  refused request is computed from. Over-run it and clients retry into a closed door; it is
  editable while the window runs, so extend it rather than hoping.
* **reason** — this is CLIENT-FACING, verbatim, in the email and on the lockout page. Write
  it for a clinic owner, not for an engineer.
* **drain bound** (default 15 minutes) — how long the platform waits for in-flight work
  before going active anyway. See §3.

Clients are emailed 24 hours ahead. **Once that notice has gone out the start time is
frozen** — you may still move the end, rewrite the reason and change the drain bound, and
any client-visible change re-mails everybody. To move the start, cancel and re-schedule:
that way every client hears the cancellation and the new time instead of quietly planning
around a time that moved.

## 3. It is stuck in DRAINING

The console shows what it is waiting for — calls, queued jobs, and how old the
measurement is — plus the deadline. Three cases:

* **The number is falling.** Nothing to do. A call ends when it ends; the ceiling is
  `agents.call_cap_seconds`, at most 15 minutes.
* **The number is flat and the deadline is close.** Extend the drain bound on the window
  (it is editable while draining) if you would rather wait, or let it force. Forcing is
  safe: nothing is cancelled, no call is hung up, and every in-flight call still produces
  its post-call pipeline afterwards, because the webhook path is never shed.
* **`maintenance_drain_forced` fired.** Read `stragglers` on the window row for the counts
  the decision was taken on. Calls will clear themselves. **Queued jobs that do not clear
  are a separate incident** — `outbox_dead_letter`, or the `inbox_lag_seconds` metric —
  which this window did not cause and will not fix. Do not start a migration that assumes
  an idle database until you know which.

**Never "force" a window by moving `ends_at` backwards to end it early and immediately
scheduling another.** Ending early is a button; use it.

## 4. Ending one early

Admin console → Ops → Maintenance → End now. It sets `ends_at` to now and nudges the
worker, which completes the window on its next pass (within a second). Completion, in
order: the load-shed mode is restored FIRST so clients get their portal back immediately,
then campaigns are resumed, then every live answering agent is republished from our own
record through the verified path.

## 5. Afterwards — the one thing to check

`maintenance_voice_incomplete` at the COMPLETION edge means one or more agents did not take
the restore, and an agent that did not take the restore **is still telling every caller the
platform is down**. This is the only failure in this feature that a client feels after the
window is over.

Read the ops engine-drift panel, find the named agents, and republish each from its own
screen. `sweep_engine_drift` will also report them against our record.

## 6. If the engine cannot carry the message

`maintenance_voice_unsupported` means the selected voice platform has no way to change what
a published agent says without republishing it (`EngineCapabilities.script_override` is
False for that adapter). The window still runs and calls are still answered — by the
client's ordinary agent, doing ordinary business, over a platform whose database is being
worked on. Warn affected clients directly, or keep windows on such an engine short and
outside their calling hours.

## 7. What a maintenance window is NOT

* It is not the big red switch. That halts OUTBOUND dialling platform-wide, immediately,
  with a recall of dials the vendor already holds (`runbooks/campaign-stall.md` §1). A
  window is a schedule, it stops inbound business too, and it puts everything back.
* It is not a load shed. `reduced`/`emergency` are what you reach for when the platform is
  failing to keep up and nobody was told. A window is planned, announced and reversible.
* It does not delete or move anything. No client data is touched by opening or closing one.
