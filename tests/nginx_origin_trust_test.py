"""The origin lock refused everybody, and it looked exactly like a working lock.

WHAT HAPPENED. `snippets/calevate-origin.conf` paired every Cloudflare range as

    set_real_ip_from  103.21.244.0/22;
    allow             103.21.244.0/22;

with a comment arguing that one list cannot drift from itself. The reasoning was right and
the mechanism was wrong. nginx's realip documentation is explicit that `set_real_ip_from`
"changes the client address for all places where the client address is used, including the
access module", and realip runs before the access phase — so `allow`/`deny` compared
Cloudflare's ranges against the VISITOR's address, which never matches, and the closing
`deny all` refused every proxied request. (nginx trac #1418, "Allow/Deny don't correctly
work with realip_module".)

**It failed in the direction that reads as correct.** Direct-to-IP was refused, which is
what the config promises; every real visitor was refused too, with the same 403. Nothing
was wrong until somebody used the product — and the first person to try was the founder,
holding a valid single-use setup link, on `admin.calevate.tech`.

So the properties here are the two that make the fix true rather than merely different:
the refusal must test `$realip_remote_addr` (the peer realip preserves) and not
`$remote_addr` (the one it overwrites), and the two files that now both carry the ranges
must carry the SAME ranges — which is the guarantee the paired-lines layout was reaching
for and could not deliver.
"""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[1] / "infra" / "nginx"
SNIPPET = INFRA / "snippets" / "calevate-origin.conf"
TRUST = INFRA / "origin-trust.conf.template"


def _uncommented(path: Path) -> str:
    return re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8"))


def test_the_snippet_no_longer_uses_allow_or_deny() -> None:
    """THE DEFECT, stated directly.

    FAILS IF: somebody restores the paired `allow` lines. They read correctly, they are
    what every Cloudflare-origin tutorial shows, and behind `set_real_ip_from` they
    refuse every visitor.
    """
    body = _uncommented(SNIPPET)
    for directive in ("allow", "deny"):
        assert not re.search(rf"^\s*{directive}\s", body, re.MULTILINE), (
            f"`{directive}` is back in calevate-origin.conf. realip rewrites "
            "$remote_addr before the access phase, so the access module tests the "
            "visitor's address against Cloudflare's ranges and refuses everyone."
        )


def test_the_decision_tests_the_address_realip_preserves() -> None:
    """`$realip_remote_addr` is the peer that opened the connection — Cloudflare's edge.
    `$remote_addr` is the one realip has already replaced. Testing the second is the
    original bug wearing a `geo` block."""
    body = _uncommented(TRUST)
    match = re.search(r"geo\s+(\$\w+)\s+\$calevate_from_cloudflare", body)
    assert match is not None, "the Cloudflare geo block is gone or renamed"
    assert match.group(1) == "$realip_remote_addr", (
        f"the origin decision tests {match.group(1)}, which realip overwrites with the "
        "visitor's address. It must test $realip_remote_addr."
    )


def test_loopback_is_judged_on_the_unconditional_peer_variable() -> None:
    """A local request carries no CF-Connecting-IP, so nothing is rewritten and what
    `$realip_remote_addr` holds is not settled by the documentation. The deploy's own
    health poll goes through this arm, so it asks about `$remote_addr` — which is
    unconditionally the peer — rather than finding out in production."""
    body = _uncommented(TRUST)
    match = re.search(r"geo\s+(\$\w+)\s+\$calevate_from_loopback", body)
    assert match is not None, "the loopback geo block is gone"
    assert match.group(1) == "$remote_addr"
    assert "127.0.0.1 1;" in body and "::1 1;" in body


def test_a_request_from_neither_is_the_only_one_refused() -> None:
    """The map is the whole policy in three lines; an inverted default would either
    publish the origin or black-hole it."""
    body = _uncommented(TRUST)
    mapping = re.search(
        r'map\s+"\$calevate_from_cloudflare\$calevate_from_loopback"\s+'
        r"\$calevate_origin_denied\s*\{([^}]*)\}",
        body,
    )
    assert mapping is not None, "the origin-denied map is gone or renamed"
    rules = mapping.group(1)
    assert re.search(r"default\s+0;", rules), (
        "the map defaults to DENIED, so any combination the two geos produce that is not "
        'literally "00" would be refused — including every Cloudflare request'
    )
    assert re.search(r'"00"\s+1;', rules), (
        "nothing is refused any more: the origin is open to a direct-to-IP scan"
    )


def test_the_snippet_still_restores_the_client_address() -> None:
    """The half that always worked, and the half three other controls depend on — the
    rate zones, `audit_log.ip`, and voice-runtime's source-IP allowlist, which is the
    ENTIRE authenticity check for an engine that does not sign its webhooks."""
    body = _uncommented(SNIPPET)
    assert "real_ip_header CF-Connecting-IP;" in body
    assert "real_ip_recursive on;" in body
    assert body.count("set_real_ip_from") >= 20


def _ranges(path: Path, pattern: str) -> set[str]:
    return set(re.findall(pattern, _uncommented(path), re.MULTILINE))


def test_the_two_files_carry_the_same_cloudflare_ranges() -> None:
    """The guarantee the paired-lines layout was reaching for, kept somewhere it works.

    One file decides who may CONNECT, the other decides whose `CF-Connecting-IP` to
    TRUST. They are two statements about one set of addresses, and a refresh that touches
    one is worse than a refresh that touches neither: the origin would either refuse a
    live edge or honour a header from an address Cloudflare has released.
    """
    trusted = _ranges(SNIPPET, r"^set_real_ip_from\s+(\S+);")
    admitted = _ranges(TRUST, r"^\s+(\S+/\d+)\s+1;")
    assert trusted, "no set_real_ip_from ranges parsed — this guard is blind"
    assert trusted == admitted, (
        "the two Cloudflare range lists have diverged.\n"
        f"  trusted but not admitted: {sorted(trusted - admitted)}\n"
        f"  admitted but not trusted: {sorted(admitted - trusted)}"
    )


def test_both_files_carry_a_freshness_stamp() -> None:
    """`vps-deploy.sh::check_cloudflare_ip_age` reads both and fails the deploy past 180
    days. A file without a stamp is one the check cannot judge."""
    for path in (SNIPPET, TRUST):
        assert re.search(r"CLOUDFLARE_IPS_UPDATED: \d{4}-\d{2}-\d{2}", path.read_text()), path
