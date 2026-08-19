"""Emit the backup chain's heartbeat to an EXTERNAL dead-man's switch.

    scripts/backup/backup-health.sh  (every 15 min, only when EVERY check passed)
      --> scripts/backup/heartbeat.sh --> python -m scripts.host_heartbeat
      --> GET <BACKUP_HEARTBEAT_URL>   (a hosted dead-man check)

WHY THIS EXISTS, AND WHY IT IS THE ONLY THING SHAPED LIKE THIS IN THE REPO. Every other
alarm here is a MESSAGE: something went wrong, so something is sent (`alert()`, D-49;
`notify.sh` → `host_alert`, D-50). All of them share one structural blind spot, stated
in `infra/backup/README.md` §5 and left open as D-50's residual: they run INSIDE the
failure domain they observe. Three failures therefore remove the observer along with the
observed —

  * the host being off, wedged, out of disk or off the network: no timer fires, nothing
    is checked, nothing is sent, and the absence of alerts is indistinguishable from
    health;
  * systemd not running, which takes the schedule and gap checks with it;
  * the alert path broken beyond us (wrong recipient, provider refusing us, a spam
    rule): every alert "succeeds" locally and lands nowhere.

Only an observer OUTSIDE the failure domain can turn silence into a page. So this file
inverts the polarity: success — and only success — emits, and something we do not run
complains when the emissions stop.

THE ASYMMETRY IS THE WHOLE MECHANISM, so do not "improve" it:

  * a passing run pings;
  * a FAILING run does not ping (`backup-health.sh` calls this only when `failures == 0`,
    and `tests/backup_heartbeat_test.py` fails if that guard is removed);
  * a dead box cannot ping.

The vendor offers a failure signal (`/fail`, `/<exit-status>`) and a start signal
(`/start`). **We deliberately use neither.** A `/fail` ping is a second delivery path for
"the backup broke" beside the email relay — two dedupe windows and two rate limits, the
thing this repo already refused once in `notify.sh` — and it is worthless for the three
failures above, which cannot send anything at all. One signal, one meaning: *absence*.

--------------------------------------------------------------------------------
VENDOR DECISION — hosted Healthchecks.io, and why the alternatives lost
--------------------------------------------------------------------------------
Their doc pages are egress-blocked from this environment (as Bolna's were for D-52), so
this rests on search-surfaced documentation text rather than a page fetch; the ping
semantics below are re-checked by hand at the first drill (`runbooks/backup-restore-
drill.md` §7.8), which is where they become a measured fact rather than a citation.

CHOSEN: **Healthchecks.io, hosted** (https://healthchecks.io/, ping host `hc-ping.com`).

  * It is exactly and only this: a check has a PERIOD and a GRACE TIME, a ping resets
    it, and no ping within period+grace raises an alert — the dead-man's-switch shape
    we need, packaged as one URL that `curl`/`httpx` can hit with no SDK and no auth
    header (https://healthchecks.io/docs/monitoring_cron_jobs/,
    https://healthchecks.io/docs/configuring_checks/).
  * Free tier covers 20 checks; we need ONE. The paid tiers ($5 supporter, $20 business)
    exist if that ever changes, so the price of this alarm is not a reason to skip it.
  * **BSD-licensed and self-hostable** (https://healthchecks.io/docs/self_hosted/), which
    matters here even though we host NOTHING: the exit door. If the vendor disappears or
    changes terms, the protocol is a GET at a URL and the same pings work against our own
    or anyone else's instance. That is a one-line config change, not a re-integration —
    the same "keep the exit door oiled" reasoning D-31 applied to the voice engine.
  * Its own reliability caveat is documented rather than hidden (packet loss on the ping
    path; https://healthchecks.io/docs/reliability_tips/), which is why this file retries
    and why the grace time is set to three intervals rather than one.

REJECTED — **self-hosting Healthchecks** (the same software, our infrastructure). It is
the strongest-looking option and it is the wrong one twice: it is a new deployable and
new infrastructure we run, and — decisive — an observer we run is back inside the failure
domain. On the DO Bangalore droplet it dies with the box; on a second droplet it becomes
a thing to patch, monitor and be paged about, which needs its own dead man. The whole
value here is that somebody else's uptime, not ours, is what notices our silence.

REJECTED — **Sentry Crons** (https://docs.sentry.io/product/crons/getting-started/http/).
The serious contender, because Sentry is ALREADY a vendor in this repo (`SENTRY_DSN`,
config-gated, TRD §2) and its check-in is likewise a plain URL
(`.../api/<project>/cron/<slug>/<key>/?status=ok`). Rejected on three counts:
  1. `SENTRY_DSN` is OPTIONAL and unset by default in this deployment — routing the
     backup dead man through it would make the last alarm standing depend on a
     credential that error reporting is allowed to not have.
  2. That credential is the platform's project key, with authority well beyond one
     check; the ping URL is a single-purpose bearer secret whose worst-case abuse is
     silencing this one alarm. Putting the project key on the DATABASE host, readable
     by `postgres`, buys a worse blast radius to save a login.
  3. The missed check-in rides Sentry's quota, alert rules and plan (one monitor free,
     then $0.78/monitor — https://sentry.zendesk.com/hc/en-us/articles/23058282687259).
     A quota exhausted by an unrelated error storm would silence backup monitoring as a
     side effect, which is the failure mode we are removing, not adding.

REJECTED — **Dead Man's Snitch**: conceptually identical and the name is literally the
pattern, but the free tier is one snitch and paid starts ~$19/mo, with no self-host path
— strictly dominated by the choice above for a solo operator.

REJECTED — **Cronitor** (2 free monitors, richer job telemetry/SDKs) and **Better Stack /
UptimeRobot heartbeats** (heartbeat as a side feature of an uptime product, priced with
the bundle). All three are capable; all three cost more configuration and more vendor
surface for telemetry a single 15-minute check does not need.
(Comparisons consulted: https://hyperping.com/blog/best-cron-job-monitoring-tools,
https://dev.to/mike_tickstem/healthchecksio-alternatives-for-developers-2026-bj5.)

NOT REJECTED, JUST NOT A VENDOR: the shape itself is standard — Prometheus's `Watchdog`
alert is an always-firing `vector(1)` routed to an external receiver so that the loss of
the whole alerting stack is itself alertable
(https://prometheus.io/docs/alerting/latest/configuration/). We have no Prometheus. This
is that idea with the receiver rented.

--------------------------------------------------------------------------------
WHAT THIS PROCESS PROMISES
--------------------------------------------------------------------------------
* **It never fails the backup.** `backup-health.sh` reports this outcome and ignores it
  for its own exit status: a heartbeat that cannot be sent is not a backup failure, and
  the consequence of not sending it is that the dead man fires — which is correct.
* **It is never silent about being unconfigured.** No URL = exit `EX_CONFIG` and one line
  saying the dead man is not armed. A no-op that looks configured is the defect.
* **It never logs the URL** (it is a credential). Operator-facing output names a short
  digest of it, which is enough to tell "the URL changed" from "the URL is wrong".
* **It sends no payload.** A bare GET carries no transcript, no phone number and no
  ids — hard rule 6 by construction rather than by redaction.
* **It touches no database and no Redis**, the same property `alerting` has and for the
  same reason: it must survive the failures it reports. `Settings` is one class, so the
  DSNs must be READABLE (`infra/backup/README.md` §5), but nothing here opens them —
  re-proved end to end in `tests/backup_heartbeat_test.py` against a closed port.

Exit status is the contract with `backup-health.sh`:

    0   the dead man was fed
    69  configured, but the ping did not get through (EX_UNAVAILABLE)
    78  no BACKUP_HEARTBEAT_URL — nothing was sent, and nothing is watching (EX_CONFIG)
"""

from __future__ import annotations

import sys

from apps.api.core.heartbeat import PING_ATTEMPTS, PING_TIMEOUT_S, check_ref, ping

EX_UNAVAILABLE = 69
EX_CONFIG = 78

# THE PING ITSELF LIVES IN `apps/api/core/heartbeat.py` (D-408), not here, because a
# second observer now needs the identical mechanism from async code. What moved is the
# transport, the retry policy and "what counts as delivered"; what stayed is this file's
# argument for the whole pattern, above, and its exit-status contract with
# `backup-health.sh`, below. The constants are re-exported so that contract still reads
# from one place.
#
# `PING_ATTEMPTS` and `PING_TIMEOUT_S` are imported for `__all__` and for the operator
# docs; the retry loop that uses them is `heartbeat.ping`.


def main() -> int:
    # Imported here rather than at module scope so that `--help`-shaped misuse and the
    # docstring above cost nothing, and so the failure of Settings to load is reported
    # by this file's own message rather than by an import traceback.
    from apps.api.core.settings import get_settings

    url = (get_settings().backup_heartbeat_url or "").strip()
    if not url:
        # Loud, not fatal, and NOT a lie. This is the local/CI/dev state and the
        # pre-launch state; `backup-health.sh` turns the transition into one journald
        # line rather than 96 a day, and OPERATIONS §8 makes arming it a gate.
        print(
            "host_heartbeat: BACKUP_HEARTBEAT_URL is not set; NO external dead-man's "
            "switch is armed — a dead host would page nobody (OPERATIONS §8)",
            file=sys.stderr,
        )
        return EX_CONFIG

    delivered, reason = ping(url, agent="backup-heartbeat")
    ref = check_ref(url)
    if delivered:
        print(f"host_heartbeat sent check={ref} ({reason})", file=sys.stderr)
        return 0
    print(
        f"host_heartbeat: the heartbeat did NOT reach the dead-man's switch "
        f"(check={ref}, {reason}); the backup itself was fine, but the external "
        f"monitor will page on the silence unless this is fixed",
        file=sys.stderr,
    )
    return EX_UNAVAILABLE


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests
    raise SystemExit(main())


__all__ = ["EX_CONFIG", "EX_UNAVAILABLE", "PING_ATTEMPTS", "PING_TIMEOUT_S", "main"]
