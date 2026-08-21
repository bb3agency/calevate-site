"""The host-side deploy artefacts D-167 built: the reclaim ladder, the hygiene job, the
lock they share, and the sudoers policy.

**Why a text-and-subprocess test and not a behavioural one.** Three of the four things
under test are shell that only means anything on a VPS with Docker, systemd, sudo and
nginx, and this repository has no host — `infra/README.md` and `docs/DEPLOYMENT.md` §4d
both say so plainly. What CAN be proved here is exactly the class of defect these files
exist to prevent, and each assertion below corresponds to a specific failure the reference
host paid for (`docs/evidence/raghava-deploy-teardown.md` §8.3, §8.6, §8.11):

* a sudoers wildcard in an argument position, which is unrestricted root;
* a cleanup job that deletes the CI runner's `_work` from a timer;
* the deploy and the timer disagreeing about which lock they take, which is the same as
  having no lock;
* the two disk floors collapsing into one, which silently deletes the escalation.

The one property no test here can reach is the interleaving itself: proving the lock needs
two processes and a real filesystem lock, and it is written down as a hand-check instead
(`infra/hygiene/README.md` §5 item 5).

Everything below is offline: no Docker, no network, no systemd.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.platform_support import requires_posix_shell

REPO_ROOT = Path(__file__).resolve().parents[1]

RECLAIM = REPO_ROOT / "scripts" / "deploy" / "docker-reclaim.sh"
LOCK = REPO_ROOT / "scripts" / "deploy" / "host-lock.sh"
HYGIENE = REPO_ROOT / "scripts" / "deploy" / "host-hygiene.sh"
DEPLOY = REPO_ROOT / "scripts" / "vps-deploy.sh"
SUDOERS = REPO_ROOT / "infra" / "privileged" / "sudoers.d" / "calevate-deploy"
NGINX_APPLY = REPO_ROOT / "infra" / "privileged" / "sbin" / "calevate-nginx-apply"
HYGIENE_SERVICE = REPO_ROOT / "infra" / "hygiene" / "systemd" / "calevate-hygiene.service"
HYGIENE_TIMER = REPO_ROOT / "infra" / "hygiene" / "systemd" / "calevate-hygiene.timer"

SHELL_FILES = [RECLAIM, LOCK, HYGIENE, NGINX_APPLY]


def _strip_comments(text: str) -> str:
    """Drop whole-line `#` comments.

    Every check that asks "does this script DO x" has to ignore the comments, because these
    files argue at length about the things they deliberately do not do — the `_work` check
    below would fail on the paragraph explaining why `_work` is never touched.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


# --------------------------------------------------------------------------------------
# the shell parses, and shellcheck agrees where it is available
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("script", SHELL_FILES, ids=lambda p: p.name)
@requires_posix_shell
def test_shell_parses(script: Path) -> None:
    """`bash -n` on every script this change added.

    `calevate-nginx-apply` needs this more than the rest: CI's shell job globs `*.sh`
    (`.github/workflows/ci.yml`) and that file deliberately has no extension, because the
    sudoers policy names its installed path and a repository name that differs from the
    installed name is a trap. So this test is its only parse gate.
    """
    subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True)


@pytest.mark.parametrize("script", SHELL_FILES, ids=lambda p: p.name)
def test_shellcheck_clean(script: Path) -> None:
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed here; CI's deploy-artefacts job runs it")
    result = subprocess.run(
        ["shellcheck", "-S", "warning", "-x", str(script)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --------------------------------------------------------------------------------------
# the reclaim ladder
# --------------------------------------------------------------------------------------


def _sourced(*paths: Path, script: str) -> str:
    """Run `script` with the libraries sourced, and return stdout."""
    prelude = "".join(f'source "{path}"\n' for path in paths)
    result = subprocess.run(
        ["bash", "-c", f"set -euo pipefail\n{prelude}{script}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _command_lines(text: str) -> list[str]:
    """Lines of shell that are CODE, with comments dropped and string BODIES removed.

    The distinction matters here and nowhere else in this file. `scripts/vps-deploy.sh`
    both refuses to run privileged commands AND prints several for a human to run by hand —
    the tombstone refusal quotes `sudo rm -rf /var/lib/docker/containers/<id>` inside a
    multi-line `die` message, and the `NGINX_AUTO_RELOAD`-unset branch prints the manual
    install commands (DEPLOYMENT §9.5a keeps the whole first pass manual, in the operator's
    own root shell). Text a script prints is not privilege a script holds, so a check that
    cannot tell them apart is a check that has to be weakened until it proves nothing.

    So: strip escaped quotes, strip complete `"…"` spans, and track the parity of what is
    left to know when a message runs on across lines.
    """
    inside_string = False
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if inside_string:
            # Continuation of a message. Its content is not code; only the closing quote
            # matters, and the parity update below finds it.
            pass
        elif not line.startswith("#"):
            code = line.replace('\\"', "")
            # A quoted bare variable is an ARGUMENT, not prose — keep it, so the check
            # below can tell `sudo -n "$NGINX_APPLY"` from `sudo -n "$ANYTHING_ELSE"`.
            code = re.sub(r'"(\$\{?\w+\}?)"', r"\1", code)
            lines.append(re.sub(r'"[^"]*"', "<text>", code))
        if line.replace('\\"', "").count('"') % 2:
            inside_string = not inside_string
    assert not inside_string, "unbalanced double quotes — the scan cannot be trusted"
    return lines


@requires_posix_shell
def test_two_floors_and_the_purge_floor_is_the_higher_one() -> None:
    """The gap between the floors IS the mechanism.

    Equal floors would parse, run, and silently be the single refusal this change replaced:
    nothing would ever escalate, because the ladder only runs below the purge floor and
    refuses below the refuse floor.
    """
    out = _sourced(RECLAIM, script='echo "$RECLAIM_PURGE_FLOOR_GB $RECLAIM_REFUSE_FLOOR_GB"')
    purge, refuse = (int(value) for value in out.split())
    assert purge > refuse, "the purge floor must be strictly above the refuse floor"
    assert refuse >= 1


def test_ladder_rungs_are_ordered_cheapest_loss_first() -> None:
    """Build cache before rollback images before everything.

    The order is the part that is easy to 'tidy' into the reference host's version, which
    reaches for `image prune --all` first — throwing away the artefact a rollback lands on
    in order to save a build cache. That is the wrong trade on the only day it is made.
    """
    body = _strip_comments(RECLAIM.read_text(encoding="utf-8"))
    cache = body.index("docker builder prune --all")
    rollback = body.index('reclaim_app_image_tags "$repo" 1')
    everything = body.index("docker image prune --all")
    assert cache < rollback < everything


def test_reclaim_never_prunes_volumes() -> None:
    """`redis-data` lives on this host. A volume prune at any tier would take the queue."""
    assert "volume prune" not in _strip_comments(RECLAIM.read_text(encoding="utf-8"))


def test_container_prune_is_scoped_to_a_compose_project() -> None:
    """Teardown §8.6's third correction: an unfiltered container prune is host-global."""
    body = _strip_comments(RECLAIM.read_text(encoding="utf-8"))
    match = re.search(r"docker container prune[^\n]*", body)
    assert match is not None
    assert "com.docker.compose.project=" in match.group(0)


def test_builder_cache_flag_is_asked_for_not_pinned() -> None:
    """`--keep-storage` is deprecated and its deprecation notice names a flag that does not
    exist (moby/moby#50120), so both spellings are wrong on some engine. The library asks
    the binary; nothing else in the tree may hardcode either spelling."""
    for path in (RECLAIM, DEPLOY, HYGIENE):
        body = _strip_comments(path.read_text(encoding="utf-8"))
        for spelling in ("--keep-storage", "--reserved-space"):
            uses = [line for line in body.splitlines() if spelling in line]
            if path is RECLAIM:
                # The library is allowed to NAME both — the detection asks the binary which
                # it has and then remembers the answer, so both spellings appear exactly
                # there and nowhere else.
                assert all("_builder_cache_flag=" in line or "grep -q" in line for line in uses), (
                    uses
                )
            else:
                assert not uses, f"{path.name} pins {spelling}; ask builder_cache_flag()"


def test_deploy_refuses_rather_than_building_below_the_hard_floor() -> None:
    body = _strip_comments(DEPLOY.read_text(encoding="utf-8"))
    reclaim_call = body.index("reclaim_for_build")
    assert "|| die" in body[reclaim_call : reclaim_call + 400]
    # ...and it runs before the build, which is the whole point.
    assert body.index("\nreclaim_disk\n") < body.index("\nbuild_images\n")


# --------------------------------------------------------------------------------------
# the lock the deploy and the hygiene job share
# --------------------------------------------------------------------------------------


@requires_posix_shell
def test_deploy_and_hygiene_resolve_the_same_lock_path() -> None:
    """Two callers computing the lock differently is the same as having no lock, and it is
    the kind of divergence that is invisible until the day the two do interleave."""
    from_lib = _sourced(LOCK, script='echo "$CALEVATE_HOST_LOCK"').strip()
    assert from_lib.endswith("/.deploy-state/host.lock")
    for path in (DEPLOY, HYGIENE):
        body = _strip_comments(path.read_text(encoding="utf-8"))
        assert "host-lock.sh" in body, f"{path.name} does not source the lock"
        assert "take_host_lock" in body, f"{path.name} never takes the lock"


def test_lock_is_flock_and_not_a_pid_file() -> None:
    """A pid file has to be cleaned up by the process that dies, which is exactly what does
    not happen when the OOM killer takes `next build`."""
    body = _strip_comments(LOCK.read_text(encoding="utf-8"))
    assert "flock" in body


@requires_posix_shell
def test_lock_is_released_when_the_holder_exits(tmp_path: Path) -> None:
    """The property flock buys and a pid file does not: a killed holder leaves no lock."""
    state = tmp_path / "state"
    child = f'export CALEVATE_DEPLOY_STATE={state}; source "{LOCK}"'
    script = f"""
        export CALEVATE_DEPLOY_STATE={state}
        source "{LOCK}"
        bash -c '{child}; take_host_lock victim 1; kill -9 $$' 2>/dev/null || true
        take_host_lock survivor 2 && echo ACQUIRED
    """
    assert "ACQUIRED" in _sourced(script=script)


@requires_posix_shell
def test_a_second_holder_is_refused_while_the_first_holds_it(tmp_path: Path) -> None:
    state = tmp_path / "state"
    child = f'export CALEVATE_DEPLOY_STATE={state}; source "{LOCK}"'
    script = f"""
        export CALEVATE_DEPLOY_STATE={state}
        source "{LOCK}"
        take_host_lock first 1
        if bash -c '{child}; take_host_lock second 0'; then
          echo BOTH_GOT_IT
        else
          echo REFUSED
        fi
    """
    assert "REFUSED" in _sourced(script=script)


# --------------------------------------------------------------------------------------
# the hygiene job
# --------------------------------------------------------------------------------------


def test_hygiene_never_touches_the_runner_work_directory() -> None:
    """Teardown §8.6, the strongest of the three corrections. `_work` and `_tool` are a CI
    job's staging area; a timer that deletes them deletes them under a running job."""
    body = _strip_comments(HYGIENE.read_text(encoding="utf-8"))
    for forbidden in ("_work", "_tool"):
        assert forbidden not in body, f"{forbidden} is reachable outside a comment"


def test_hygiene_does_not_escalate_the_reclaim_ladder() -> None:
    """A nightly job that quietly drops per-commit images removes the rollback artefact an
    incident needs. Hygiene reports disk pressure; the deploy escalates."""
    body = _strip_comments(HYGIENE.read_text(encoding="utf-8"))
    assert "reclaim_routine" in body
    assert "reclaim_for_build" not in body


def test_hygiene_reports_a_step_failure_rather_than_swallowing_it() -> None:
    body = _strip_comments(HYGIENE.read_text(encoding="utf-8"))
    assert "FAILED_STEPS" in body
    assert "exit 1" in body


def test_hygiene_alerts_through_the_one_existing_seam() -> None:
    """One alert vocabulary on this host, not two — `scripts/backup/notify.sh` is it."""
    body = _strip_comments(HYGIENE.read_text(encoding="utf-8"))
    assert "scripts/backup/notify.sh" in body
    assert (REPO_ROOT / "scripts" / "backup" / "notify.sh").exists()


def test_hygiene_units_point_at_files_that_exist() -> None:
    """A unit naming a path nothing installs is the half-wired shape CLAUDE.md names."""
    service = HYGIENE_SERVICE.read_text(encoding="utf-8")
    exec_start = re.search(r"^ExecStart=(\S+)", service, re.M)
    assert exec_start is not None
    assert exec_start.group(1).endswith("/scripts/deploy/host-hygiene.sh")
    assert HYGIENE.exists()
    assert "OnFailure=" in service
    timer = HYGIENE_TIMER.read_text(encoding="utf-8")
    assert "OnCalendar=" in timer
    # Idempotent by construction, which is what makes a catch-up run safe to ask for.
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer


def test_hygiene_unit_does_not_run_as_root() -> None:
    """The design output of capping the journal instead of vacuuming it. A scheduled job
    holding root is a scheduled root shell."""
    service = HYGIENE_SERVICE.read_text(encoding="utf-8")
    user = re.search(r"^User=(\S+)", service, re.M)
    assert user is not None and user.group(1) != "root"


def test_hygiene_does_not_collide_with_the_nightly_base_backup() -> None:
    """Both are IO-heavy and both run at night; a shared minute is a slow backup."""
    hygiene_when = re.search(r"^OnCalendar=(.+)$", HYGIENE_TIMER.read_text(encoding="utf-8"), re.M)
    backup_timer = REPO_ROOT / "infra" / "backup" / "systemd" / "calevate-basebackup.timer"
    backup_when = re.search(r"^OnCalendar=(.+)$", backup_timer.read_text(encoding="utf-8"), re.M)
    assert hygiene_when is not None and backup_when is not None
    assert hygiene_when.group(1) != backup_when.group(1)


# --------------------------------------------------------------------------------------
# the sudoers policy — the security-shaped half
# --------------------------------------------------------------------------------------


def _cmnd_lines() -> list[str]:
    """Every grant line in the policy: `<user> ALL=(root) NOPASSWD: <cmnd> ...`."""
    return [
        line.strip()
        for line in SUDOERS.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#") and "NOPASSWD:" in line
    ]


def test_the_policy_grants_something() -> None:
    """Guards every assertion below: a policy that granted nothing would pass them all."""
    assert _cmnd_lines(), "no NOPASSWD grant found — the checks below would be vacuous"


def test_no_wildcard_anywhere_in_a_grant() -> None:
    """THE rule. sudo matches a command line as one concatenated string and a wildcard in it
    spans `/` and words, so `rm -rf /var/lib/docker/containers/*` also permits
    `rm -rf /var/lib/docker/containers/x /etc /home` (teardown §8.3). This is a build
    failure, not a review comment."""
    for line in _cmnd_lines():
        assert "*" not in line, line
        assert "?" not in line, line
        assert "[" not in line, line


def test_every_grant_is_an_absolute_path_with_an_empty_argument_specification() -> None:
    """`""` after a Cmnd is sudoers for "may be run with NO arguments"; a Cmnd with no
    argument spec at all permits ANY arguments, which is the default and is wrong here."""
    for line in _cmnd_lines():
        cmnd = line.split("NOPASSWD:", 1)[1].strip()
        assert cmnd.startswith("/"), f"not an absolute path: {cmnd}"
        assert cmnd.endswith('""'), f"missing the empty-argument specification: {cmnd}"


def test_granted_commands_exist_in_this_repository() -> None:
    """A grant naming a script nobody wrote is a grant that hangs the deploy on a prompt."""
    shipped = {path.name for path in (REPO_ROOT / "infra" / "privileged" / "sbin").iterdir()}
    for line in _cmnd_lines():
        cmnd = line.split("NOPASSWD:", 1)[1].strip().rsplit(" ", 1)[0]
        assert Path(cmnd).name in shipped, f"{cmnd} is granted but not in infra/privileged/sbin"


def test_the_policy_filename_would_not_be_ignored_by_sudo() -> None:
    """`#includedir` silently skips any name containing a `.` or ending in `~`. The failure
    is a deploy that hangs on a password prompt and a policy file that looks installed."""
    assert "." not in SUDOERS.name
    assert not SUDOERS.name.endswith("~")


def test_the_deploy_user_name_agrees_across_all_three_places() -> None:
    """The script checks the staging directory's owner against its own constant at run time,
    so a half-renamed account fails loudly — but only if the two constants agree to begin
    with."""
    granted_users = {line.split()[0] for line in _cmnd_lines()}
    script_user = re.search(
        r"^readonly DEPLOY_USER=(\S+)", NGINX_APPLY.read_text(encoding="utf-8"), re.M
    )
    assert script_user is not None
    assert granted_users == {script_user.group(1)}


def test_the_deploy_composes_no_privileged_command_of_its_own() -> None:
    """The whole point. Every `sudo` the deploy runs must be the granted command, invoked
    with no arguments — `sudo install …`, `sudo cp …`, `sudo rm …`, `sudo nginx -t` and
    `sudo systemctl reload` are exactly what the argument-free grant refuses."""
    invocations = [
        line
        for line in _command_lines(DEPLOY.read_text(encoding="utf-8"))
        if re.search(r"(^|[;&|(]\s*)\bsudo\s", line)
    ]
    assert invocations, "no sudo invocation found — this check would be vacuous"
    for line in invocations:
        # The preflight probe asks sudo a question; it runs nothing.
        allowed = "sudo -n -l $NGINX_APPLY" in line or "sudo -n $NGINX_APPLY" in line
        assert allowed, f"the deploy composes a privileged command: {line}"


def test_the_privileged_script_refuses_arguments_itself() -> None:
    """Defence in depth, and the half that survives a policy someone widened by hand."""
    body = _strip_comments(NGINX_APPLY.read_text(encoding="utf-8"))
    assert "(( $# == 0 ))" in body
    assert "(( EUID == 0 ))" in body


def test_the_privileged_script_refuses_argument_free_but_hostile_staging() -> None:
    """Every refusal the threat model needs, asserted as a set so removing one is a failure
    rather than a quiet weakening. The threat model is 'the deploy account is compromised',
    in which the staging directory is attacker-controlled input."""
    body = _strip_comments(NGINX_APPLY.read_text(encoding="utf-8"))
    assert body.count("-L") >= 3, "symlink refusals (staging root, source dirs, files)"
    assert "stat -c '%U'" in body, "staging owner is verified"
    assert "8#0002" in body, "world-writable staging is refused"
    assert "NAME_RE" in body, "basenames are validated against one shape"


def test_the_privileged_script_writes_only_under_etc_nginx() -> None:
    """The one directory this grant is allowed to reach. A destination assembled from
    anything else would be the traversal the whole design exists to remove."""
    body = NGINX_APPLY.read_text(encoding="utf-8")
    targets = re.findall(r"^readonly (\w*TARGET)=(\S+)", body, re.M)
    assert targets, "no install targets declared"
    for _name, path in targets:
        assert path.startswith("/etc/nginx/"), path
