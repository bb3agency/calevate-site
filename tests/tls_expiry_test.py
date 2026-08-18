"""`tls_certificate_expiring` — OPERATIONS §4's cert half, which nothing raised.

WHAT THESE TESTS DRIVE. A real TLS server with a real certificate, on a real socket, with
`check_tls_expiry` pointed at it. Not a mocked `ssl` module: the two things most likely to
be wrong here are the handshake settings (an unvalidated peer makes `getpeercert()` return
an EMPTY dict, which would have made the check silently measure nothing) and the SNI, and
a mock would have agreed with whatever the code did.

`test_an_already_expired_certificate_is_still_readable` is the one that pins the design
decision. Verification is off precisely so that the condition the alarm exists to report
does not become an exception the alarm cannot describe — a checker that raises
`SSLCertVerificationError` on an expired certificate can say "something is wrong" and
never "it expired on the 14th".

**Let's Encrypt stopped sending expiration notices on 4 June 2025**, so there is nothing
else watching this. That is why the threshold sits at 21 days rather than at 7.
"""

from __future__ import annotations

import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.workers import tls_expiry
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

HOSTNAME = "hooks.calevate.invalid"


class _Alerts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, str]]] = []

    def __call__(self, stage: str, code: str, *, detail: str = "", **ids: str) -> None:
        self.calls.append((stage, code, detail, dict(ids)))

    def codes(self) -> list[str]:
        return [code for _, code, _, _ in self.calls]


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> _Alerts:
    captured = _Alerts()
    monkeypatch.setattr(tls_expiry, "alert", captured)
    return captured


class _Settings:
    """Only the three fields the cron reads. A stub rather than a real `Settings`, because
    `get_settings` is `lru_cache`d process-wide and several suites share it — mutating the
    real one here would leak into whatever runs next."""

    def __init__(self, *, app_env: str, webhook_base_url: str, tls_origin_address: str) -> None:
        self.app_env = app_env
        self.webhook_base_url = webhook_base_url
        self.tls_origin_address = tls_origin_address


def _self_signed(tmp_path: Path, *, days_remaining: int) -> tuple[Path, Path]:
    """A certificate whose `notAfter` is exactly `days_remaining` away. Negative = expired."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOSTNAME)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        # Backdated so an "expired" certificate is a plausible one rather than a
        # certificate whose validity window is inverted.
        .not_valid_before(now - timedelta(days=90))
        .not_valid_after(now + timedelta(days=days_remaining))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOSTNAME)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class _Origin:
    """A one-shot TLS listener standing in for the host's nginx."""

    def __init__(self, cert: Path, key: Path) -> None:
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.load_cert_chain(str(cert), str(key))
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.address = f"127.0.0.1:{self._sock.getsockname()[1]}"
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._stop = False
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop:
            try:
                client, _ = self._sock.accept()
            except OSError:
                return
            try:
                with self._context.wrap_socket(client, server_side=True):
                    pass
            except OSError:
                pass

    def close(self) -> None:
        self._stop = True
        self._sock.close()


def _point_at(monkeypatch: pytest.MonkeyPatch, address: str, *, app_env: str = "prod") -> None:
    settings = _Settings(
        app_env=app_env,
        webhook_base_url=f"https://{HOSTNAME}",
        tls_origin_address=address,
    )
    monkeypatch.setattr(tls_expiry, "get_settings", lambda: settings)


async def test_a_healthy_certificate_raises_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    origin = _Origin(*_self_signed(tmp_path, days_remaining=60))
    try:
        _point_at(monkeypatch, origin.address)
        outcome = await tls_expiry.check_tls_expiry({})
    finally:
        origin.close()
    assert outcome.startswith("ok days=")
    assert alerts.codes() == []


async def test_a_certificate_inside_the_window_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    """Certbot renews at 30 days and tries twice a day, so 21 days remaining is about
    eighteen failed renewals — past any transient failure, and still three weeks of
    runway."""
    origin = _Origin(*_self_signed(tmp_path, days_remaining=tls_expiry.EXPIRY_ALERT_DAYS - 1))
    try:
        _point_at(monkeypatch, origin.address)
        outcome = await tls_expiry.check_tls_expiry({})
    finally:
        origin.close()
    assert outcome.startswith("expiring days=")
    assert alerts.codes() == ["tls_certificate_expiring"]
    _, _, detail, ids = alerts.calls[0]
    assert HOSTNAME in detail
    assert ids == {"host": HOSTNAME}


async def test_a_certificate_one_day_outside_the_window_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    """The boundary, from the quiet side. An alarm that fires a day early every day is one
    somebody filters."""
    origin = _Origin(*_self_signed(tmp_path, days_remaining=tls_expiry.EXPIRY_ALERT_DAYS + 2))
    try:
        _point_at(monkeypatch, origin.address)
        await tls_expiry.check_tls_expiry({})
    finally:
        origin.close()
    assert alerts.codes() == []


async def test_an_already_expired_certificate_is_still_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    """Why verification is off. With `CERT_REQUIRED` this handshake raises and the alarm
    could only say "something is wrong" — never how long it has been wrong for."""
    origin = _Origin(*_self_signed(tmp_path, days_remaining=-3))
    try:
        _point_at(monkeypatch, origin.address)
        outcome = await tls_expiry.check_tls_expiry({})
    finally:
        origin.close()
    assert outcome.startswith("expiring days=-")
    assert alerts.codes() == ["tls_certificate_expiring"]
    assert "expired 3 day(s) ago" in alerts.calls[0][2]


async def test_an_unreachable_origin_is_its_own_alarm(
    monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    """Not being able to SEE the certificate hides an expiry rather than causing one, and
    it is the state a wrong address, a stopped nginx or a firewall change produces."""
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    _point_at(monkeypatch, f"127.0.0.1:{port}")

    outcome = await tls_expiry.check_tls_expiry({})
    assert outcome == "unreadable"
    assert alerts.codes() == ["tls_certificate_unreadable"]


async def test_local_is_a_stated_no_op(monkeypatch: pytest.MonkeyPatch, alerts: _Alerts) -> None:
    """A laptop has no origin and no certificate. It must say so rather than pass
    silently — the shape `BACKUP_HEARTBEAT_URL` uses."""
    _point_at(monkeypatch, "127.0.0.1:1", app_env="local")
    assert await tls_expiry.check_tls_expiry({}) == "skipped_local"
    assert alerts.codes() == []


def test_the_sni_name_comes_from_the_webhook_base_url() -> None:
    """One public hostname, already the one this deployment cannot be wrong about. A plain
    HTTP value means there is nothing to check rather than something to guess."""
    assert tls_expiry.public_hostname("https://hooks.example.com/x") == "hooks.example.com"
    assert tls_expiry.public_hostname("http://localhost:8100") is None


async def test_the_check_reads_the_certificate_the_sni_name_selects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    """The whole reason this connects to the ORIGIN rather than to the public name: the
    certificate that matters is chosen by SNI at the origin, not by DNS. If SNI were
    dropped, an nginx with several server blocks would hand back the default one — which
    in this deployment is a 15-year Cloudflare Origin CA certificate that never expires,
    i.e. an alarm that can never fire.
    """
    seen: list[str | None] = []
    real = tls_expiry._read_certificate

    def spy(address: str, *, server_hostname: str) -> Any:
        seen.append(server_hostname)
        return real(address, server_hostname=server_hostname)

    origin = _Origin(*_self_signed(tmp_path, days_remaining=60))
    try:
        monkeypatch.setattr(tls_expiry, "_read_certificate", spy)
        _point_at(monkeypatch, origin.address)
        await tls_expiry.check_tls_expiry({})
    finally:
        origin.close()
    assert seen == [HOSTNAME]
