"""Render every nginx template and hand the result to nginx.

**TWO PRODUCTION FAILURES IN ONE EVENING, BOTH CAUGHT BY `nginx -t` ON A LIVE HOST**, and
neither reachable by any test in this repository:

1. `"proxy_connect_timeout" directive is duplicate` — the shared proxy snippet set a
   timeout and a vhost restated it after the include, which is two of one directive at one
   level. The whole config was refused, every vhost with it.
2. `"proxy_pass" cannot have URI part in location given by regular expression, or inside
   named location` — the 404 handler was a named location and needed a URI.

Every other guard here reads the templates as TEXT and asserts properties of the shapes it
expects to find. That catches an intent that drifted; it cannot catch a config nginx
refuses to load, because it does not know nginx's grammar. This one does the only thing
that does: it runs the parser.

**WHAT IT SUBSTITUTES AND WHY THAT IS SAFE.** The deploy renders with `envsubst` over an
explicit five-name list; this re-implements that substitution rather than shelling out to
`envsubst`, which is not present everywhere, and asserts afterwards that no `${...}`
placeholder survives — the same check `render_nginx` makes for the same reason.

TLS certificates are generated for the run, because `nginx -t` OPENS the files named by
`ssl_certificate` and fails on a missing one. That is a real property worth exercising: a
config that names a certificate path the deploy never creates is a config that tests clean
and refuses to reload.

SKIPPED when nginx is not installed rather than passing vacuously. `.github/workflows/ci
.yml` installs it, so the skip is a local-machine convenience and never CI's answer.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra" / "nginx"

#: DEPLOYMENT §2's floor, and the reason this test cannot run on a stock Ubuntu image:
#: `http2 on;` is 1.25.1+, and 24.04 ships 1.24, which refuses it as an unknown directive.
#: A parse failure caused by the PARSER being too old would read as a config bug and send
#: the next reader after nothing, so the version is checked rather than assumed.
NGINX_MINIMUM = (1, 25, 1)


def _nginx_version() -> tuple[int, ...] | None:
    binary = shutil.which("nginx")
    if binary is None:
        return None
    result = subprocess.run([binary, "-v"], capture_output=True, text=True)
    match = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", result.stderr + result.stdout)
    return tuple(int(part) for part in match.groups()) if match else None


_VERSION = _nginx_version()

pytestmark = pytest.mark.skipif(
    _VERSION is None or _VERSION < NGINX_MINIMUM,
    reason=(
        f"needs nginx >= {'.'.join(map(str, NGINX_MINIMUM))} (DEPLOYMENT §2); "
        f"found {_VERSION}. `.github/workflows/ci.yml` installs mainline so this runs there."
    ),
)

#: Exactly the names `render_nginx` passes to envsubst. A template that grows a sixth
#: would leave a literal `${NAME}` behind, which the placeholder assertion below catches
#: — the same failure the deploy raises, one push earlier.
SUBSTITUTIONS = {
    "ROOT_DOMAIN": "calevate.test",
    "ACME_WEBROOT": "/var/www/certbot",
}


def _self_signed(directory: Path, stem: str) -> tuple[Path, Path]:
    """A throwaway certificate, so `nginx -t` has a file to open."""
    key, crt = directory / f"{stem}.key", directory / f"{stem}.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(crt),
            "-days",
            "1",
            "-subj",
            "/CN=calevate.test",
        ],
        check=True,
        capture_output=True,
    )
    return crt, key


def _render(tmp: Path) -> Path:
    """Render every template into an nginx prefix and return the prefix."""
    tls = tmp / "tls"
    tls.mkdir()
    fullchain, privkey = _self_signed(tls, "fullchain")
    (tls / "privkey.pem").write_bytes(privkey.read_bytes())
    origin_crt, origin_key = _self_signed(tls, "origin")

    values = dict(SUBSTITUTIONS)
    values["TLS_LIVE_DIR"] = str(tls)
    values["ORIGIN_CERT_PATH"] = str(origin_crt)
    values["ORIGIN_KEY_PATH"] = str(origin_key)
    # `fullchain.pem`/`privkey.pem` are the names the templates compose from TLS_LIVE_DIR.
    (tls / "fullchain.pem").write_bytes(fullchain.read_bytes())

    prefix = tmp / "nginx"
    (prefix / "conf.d").mkdir(parents=True)
    (prefix / "snippets").mkdir()
    (prefix / "logs").mkdir()

    for template in sorted(INFRA.glob("*.conf.template")):
        rendered = template.read_text(encoding="utf-8")
        for name, value in values.items():
            rendered = rendered.replace(f"${{{name}}}", value)
        left = re.findall(r"\$\{[A-Z_]+\}", rendered)
        assert not left, (
            f"{template.name} still contains {sorted(set(left))} after substitution — "
            "add the variable to SUBSTITUTIONS here AND to render_nginx's envsubst list"
        )
        (prefix / "conf.d" / template.name.replace(".conf.template", ".conf")).write_text(
            rendered, encoding="utf-8"
        )

    for snippet in sorted((INFRA / "snippets").glob("*.conf")):
        (prefix / "snippets" / snippet.name).write_text(
            snippet.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Three edits are made to the rendered text and no others. First: the templates include
    # snippets by ABSOLUTE path (/etc/nginx/snippets/...), which a test prefix cannot
    # provide. The other two are argued at the lines that make them.
    for conf in (prefix / "conf.d").glob("*.conf"):
        text = conf.read_text().replace("/etc/nginx/snippets/", f"{prefix}/snippets/")
        # IPv6 `listen` lines are dropped, and this is the second and last edit.
        # `nginx -t` OPENS the listening sockets, so on a host with no IPv6 stack — this
        # container, and some CI runners — `listen [::]:80` fails with "Address family not
        # supported by protocol" AFTER nginx has already printed "syntax is ok". That is a
        # property of the machine, not of the config, and a gate that reports it as a
        # config error is a gate people learn to ignore. The v4 line beside each one is
        # kept, so every server block is still bound and still tested.
        text = re.sub(r"^\s*listen\s+\[::\]:.*\n", "", text, flags=re.MULTILINE)
        # THE PRIVILEGED PORTS ARE MOVED, and this is the third and last edit. `nginx -t`
        # does not merely parse — it OPENS the listening sockets — so on a runner that is
        # not root, every `listen 80` in the rendered config fails with
        # `bind() to 0.0.0.0:80 failed (13: Permission denied)` AFTER nginx has printed
        # "syntax is ok". That is a property of the ACCOUNT, not of the config, and it is
        # what made this gate red on GitHub Actions while passing on a workstation with
        # the capability — a gate that fails for a reason the diff cannot contain is one
        # people learn to override.
        #
        # 80 -> 8080 and 443 -> 8443. A port number is an argument to `listen` and nothing
        # else in the file reads it: no `proxy_pass`, no redirect and no `server_name`
        # here names a port, so every directive under test — the vhost split, the
        # locations, the timeouts, the certificates, `http2 on` — is parsed exactly as it
        # would be on the host. What this deliberately does NOT do is drop the `listen`
        # lines: a server block with none would still parse, and would stop testing the
        # thing that decides which vhost answers.
        text = re.sub(r"(^\s*listen\s+)80\b", r"\g<1>8080", text, flags=re.MULTILINE)
        text = re.sub(r"(^\s*listen\s+)443\b", r"\g<1>8443", text, flags=re.MULTILINE)
        conf.write_text(text, encoding="utf-8")

    (prefix / "nginx.conf").write_text(
        f"""daemon off;
pid {prefix}/nginx.pid;
error_log {prefix}/logs/error.log;
events {{ worker_connections 64; }}
http {{
    access_log off;
    client_body_temp_path {prefix}/logs;
    proxy_temp_path {prefix}/logs;
    fastcgi_temp_path {prefix}/logs;
    uwsgi_temp_path {prefix}/logs;
    scgi_temp_path {prefix}/logs;
    # NO upstreams and NO `map` here on purpose. `calevate.conf.template` declares both
    # at http scope itself, and declaring them again is `duplicate upstream` — a harness
    # bug that would read as a config bug. What this file supplies is only what a real
    # `nginx.conf` supplies and the templates cannot: the event loop, the temp paths, and
    # the include.
    include {prefix}/conf.d/*.conf;
}}
""",
        encoding="utf-8",
    )
    return prefix


def test_the_rendered_config_is_one_nginx_will_load(tmp_path: Path) -> None:
    """THE TEST. Everything above is setup; this is `nginx -t`.

    A failure here quotes nginx's own message, file and line — read it literally, it is
    the same sentence the deploy would print, one push later and on a live host.
    """
    prefix = _render(tmp_path)
    result = subprocess.run(
        ["nginx", "-t", "-p", str(prefix), "-c", str(prefix / "nginx.conf")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "the rendered nginx config does not parse:\n"
        + result.stderr.replace(str(prefix), "<prefix>")
    )


def test_every_upstream_the_templates_proxy_to_is_declared_by_a_template(
    tmp_path: Path,
) -> None:
    """A `proxy_pass` naming an upstream nothing declares.

    nginx would catch it too — "upstream not found" — but only once every other line
    parses, so this states it separately and names the missing one directly. It also pins
    the property the harness above depends on: the templates are SELF-CONTAINED at http
    scope, which is why the test nginx.conf declares no upstreams of its own.
    """
    del tmp_path
    sources = list(INFRA.glob("*.conf.template")) + list((INFRA / "snippets").glob("*.conf"))
    proxied: set[str] = set()
    declared: set[str] = set()
    for path in sources:
        text = path.read_text(encoding="utf-8")
        proxied |= set(re.findall(r"proxy_pass\s+http://(\w+)", text))
        declared |= set(re.findall(r"^upstream\s+(\w+)", text, re.MULTILINE))
    assert proxied, "no proxy_pass found at all — this guard is blind"
    assert proxied <= declared, (
        f"the templates proxy to {sorted(proxied - declared)}, which no template declares"
    )
