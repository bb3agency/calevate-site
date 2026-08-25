"""The manual nginx path must not record a deploy of config nobody installed.

WHAT HAPPENED. `scripts/vps-deploy.sh nginx` with `NGINX_AUTO_RELOAD` unset — the mode
DEPLOYMENT §9.5a keeps the whole first pass in — rendered the config, PRINTED three
`install` commands for a human, and returned 0. The deploy then pruned, and
`record_deploy` filed `nginx` as deployed at HEAD.

On the first host that ever used it, that record was two commits ahead of the disk for
three attempts running: `.deploy-state` said the apex vhost was live and
`/etc/nginx/conf.d/calevate-site.conf` had never heard of `calevate.tech`. A deploy
record that can be wrong is worse than no record at all, because the next operator reads
it instead of reading the disk — which is exactly what happened.

Two properties, and the second is the one that made it invisible for so long:

1. The branch COMPARES rendered against installed and fails the step when they differ.
   Not "prints a warning": a step that returns 0 is a step `record_deploy` believes.
2. The commands it prints name each file INDIVIDUALLY. `render_nginx` stages into
   `mktemp -d` — mode 0700, owned by the deploy account — so `sudo install
   $NGINX_STAGING/*.conf` typed from any other account expands the glob as THAT user,
   matches nothing, and `install` fails while every `echo` after it still prints success.
   The operator sees a clean run and an unchanged file.

Read as text rather than executed, for the reason the other deploy guards here are: the
branch's failure mode is a live host with a root shell, and the property is a shape in
the script, not a behaviour that can be exercised in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "vps-deploy.sh"


def _install_nginx() -> str:
    """The body of `install_nginx()`, up to the start of the next function."""
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("install_nginx() {")
    end = source.index("\n}\n", start)
    return source[start:end]


def _manual_branch() -> str:
    """The `NGINX_AUTO_RELOAD != 1` arm — everything up to its closing `fi`."""
    body = _install_nginx()
    start = body.index('if [[ "$NGINX_AUTO_RELOAD" != "1" ]]; then')
    end = body.index("\n  fi\n", start)
    return body[start:end]


def _code_only(text: str) -> str:
    """Comments dropped. The comments here QUOTE the commands they warn about, so a
    check that reads them finds the defect in the prose describing its fix."""
    return re.sub(r"#[^\n]*", "", text)


def test_the_manual_branch_compares_what_it_rendered_against_what_is_installed() -> None:
    branch = _code_only(_manual_branch())
    assert re.search(r"\bcmp\b", branch), (
        "the NGINX_AUTO_RELOAD-unset branch no longer compares rendered against "
        "installed. Without that it cannot tell a human who ran the install commands "
        "from one who did not, and record_deploy believes it either way."
    )


def test_the_manual_branch_fails_rather_than_returning_zero_on_a_difference() -> None:
    """The whole defect in one property.

    FAILS IF: somebody softens the refusal back to a `log` + `return 0`. That reads
    friendlier and re-books deploys that did not happen.
    """
    branch = _code_only(_manual_branch())
    assert re.search(r"\bdie\b", branch), (
        "the manual branch has no `die`. A step that returns 0 is a step record_deploy "
        "files as a completed deploy of the current commit."
    )
    # A bare `return 0` is still legitimate — it is the "already installed byte-for-byte"
    # path — but it must be GUARDED by the comparison, i.e. appear after it.
    returns = [match.start() for match in re.finditer(r"\breturn 0\b", branch)]
    compare_at = re.search(r"\bcmp\b", branch)
    assert compare_at is not None
    assert all(at > compare_at.start() for at in returns), (
        "the manual branch returns 0 before comparing anything — the exact shape that "
        "recorded a deploy of config sitting untouched in the staging directory"
    )


def test_the_printed_install_commands_name_files_and_never_a_glob() -> None:
    """The reason three consecutive manual installs silently did nothing.

    The staging directory is `mktemp -d`: mode 0700, owned by the account that ran the
    render. `sudo install -m 0644 $NGINX_STAGING/*.conf …` has its glob expanded by the
    CALLER's shell, not by sudo — so from any other account it matches nothing, install
    fails, and the operator's next command prints as though it worked.
    """
    branch = _code_only(_manual_branch())

    # The branch's OWN `for staged in "$NGINX_STAGING"/*.conf` loop is fine and is not
    # what this tests: that glob is expanded by the script, running as the account that
    # owns the directory. What must never carry a glob is a command handed to a HUMAN,
    # who is typing it somewhere else — so the rule is about lines mentioning `sudo`.
    offenders = [
        line for line in branch.splitlines() if "sudo" in line and ("*" in line or "?" in line)
    ]
    assert not offenders, (
        "the manual branch hands an operator a command containing a glob: "
        f"{offenders}. The staging directory is mode 0700 and owned by the deploy "
        "account, so the glob expands to nothing for any other operator and `install` "
        "fails silently behind an `echo`."
    )
    assert "basename" in branch, (
        "the printed commands are no longer built per file — `basename` is how each "
        "staged file is paired with its installed counterpart"
    )
