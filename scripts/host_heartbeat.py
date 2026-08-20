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

import hashlib
import sys
import time

import httpx

EX_UNAVAILABLE = 69
EX_CONFIG = 78

# THE PING LIVES HERE AGAIN, and the round trip is worth one comment because the next
# reader will otherwise re-do it. D-408 extracted it to `apps/api/core/heartbeat.py`
# because a SECOND observer — the in-call LLM credential-rotation loop — needed the same
# mechanism from async code, and two copies of a retry policy is two things to get right.
# D-410 deleted that observer: Azure OpenAI takes a static key, so there is no rotation
# loop to watch. A shared module with one caller is not sharing, it is indirection, and
# this particular indirection also cost something concrete — it put an `apps.api.core`
# import at MODULE scope in a script whose whole discipline (see above) is that it must
# survive the failures it reports and therefore imports as little as possible.
#
# So the extraction is reverted rather than left standing with one caller. If a second
# heartbeat is ever needed, extract it again — the argument was right, it was the second
# caller that turned out to be temporary.

# Bounded so a health run can never hang on its own heartbeat: worst case is
# ATTEMPTS x (timeout + backoff) of about 21s, comfortably inside the unit's
# TimeoutStartSec and inside the 15-minute timer interval. The vendor documents that a
# ping can be lost to plain packet loss and recommends retrying
# (https://healthchecks.io/docs/reliability_tips/), and a lost ping here would eventually
# page a human out of hours for a healthy database — so retrying is noise reduction, not
# optimism.
PING_TIMEOUT_S = 5.0
PING_ATTEMPTS = 3
PING_BACKOFF_S = 2.0

# The vendor answers 200 with a two-byte body. Anything else — a 404 for a deleted
# check, a 5xx, an HTML captive portal — is NOT a heartbeat, and treating it as one
# would be the "silent pass that looks configured" failure in its final form.
_OK_STATUS = 200


def check_ref(url: str) -> str:
    """A stable, non-reversible handle for one ping URL, for operator output.

    The URL is a bearer secret (anyone holding it can silence the alarm), so it must
    never reach a log — but "which check did we ping" still has to be answerable when
    a rotation goes wrong, and a digest prefix answers it without carrying the secret.
    """
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def ping(url: str) -> tuple[bool, str]:
    """One heartbeat, retried. Returns (delivered, a reason safe to print).

    `reason` names a status code or an exception TYPE, never a URL and never an
    exception's message — which can quote the URL it failed to reach.
    """
    reason = "no attempt was made"
    for attempt in range(1, PING_ATTEMPTS + 1):
        try:
            # follow_redirects=False on purpose: a redirect to somewhere else is not
            # this check, and silently following one would let a hijacked DNS answer
            # "delivered" forever. GET (not POST) so there is no body to get wrong.
            response = httpx.get(
                url,
                timeout=PING_TIMEOUT_S,
                follow_redirects=False,
                headers={"user-agent": "calevate-backup-heartbeat"},
            )
        except httpx.HTTPError as exc:
            reason = f"{type(exc).__name__} on attempt {attempt}"
        else:
            if response.status_code == _OK_STATUS:
                return (True, f"HTTP {response.status_code}")
            reason = f"HTTP {response.status_code} on attempt {attempt}"
        if attempt < PING_ATTEMPTS:
            time.sleep(PING_BACKOFF_S)
    return (False, reason)


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

    delivered, reason = ping(url)
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
