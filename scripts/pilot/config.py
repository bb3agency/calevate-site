"""Pilot preflight — the shopping list, on day one instead of on day three.

    uv run python -m scripts.pilot preflight

OPERATIONS §2 budgets 5-7 working days for the Bolna pilot. The way that budget is
actually lost is not a hard gate going red; it is discovering on the third morning that
the Sarvam key was never issued, or that the webhook URL baked into the agent points at
`localhost` and no delivery was ever going to arrive. So this module answers one
question before anything runs: **what is missing, and where do I get it.**

THREE OUTCOMES PER REQUIREMENT, AND THE THIRD ONE IS THE HONEST PART:

* `satisfied`   — we checked, it is there.
* `missing`     — we checked, it is not, and `how_to_get` says what to do about it.
* `unverifiable` — the harness CANNOT check this from a laptop. Account credit, a
  purchased phone number, an nginx allowlist on a box we are not running: each is a
  real prerequisite and none is decidable from config. Reporting them as satisfied
  would be a lie and omitting them would be worse, so they are listed and marked, and
  the operator confirms them by eye.

**NOTHING HERE PRINTS A SECRET.** A key is reported present or absent and never
otherwise — not truncated, not fingerprinted, not length-disclosed. The rejected
alternative was a short hash prefix "so you can tell which key is loaded"; it solves a
problem nobody has (there is one Bolna account) and it puts a stable identifier for a
live credential into a file that gets pasted into chat.

WHY THIS READS `Settings` AND NEVER `os.environ`: `scripts/` is scanned by
`scripts/check_env_parity.py`, which forbids reading an environment variable that is
not a Settings field — config that nobody documented and nobody validates at boot. The
preflight is config-reading code and gets no exemption from the rule it exists to serve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx
from calevate_shared.config import Settings

RequirementState = Literal["satisfied", "missing", "unverifiable"]

#: Gate numbers as OPERATIONS §2 numbers them, so a requirement can say which gates it
#: blocks and an operator can read the two documents side by side.
Gate = int

#: Hostnames that mean "the engine can never reach this". Bolna delivers webhooks from
#: its own cloud; an agent published with a loopback `webhook_url` will simply never be
#: called back, and gates 1 and 6 would report a silence that says nothing about the
#: vendor. Cheaper to catch here than after ten PSTN calls.
_UNREACHABLE_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", ""})

#: The vendor's API root. Probed WITHOUT credentials — the question is whether packets
#: get there at all, which is a different question from whether we are authorised.
VENDOR_API_URL = "https://api.bolna.ai/"

#: Short on purpose. This check runs first, before anything else, and an operator
#: waiting thirty seconds to be told their network is fine will stop running it.
REACHABILITY_TIMEOUT_S = 6.0


@dataclass(frozen=True, slots=True)
class Reachability:
    """Can this machine talk to the vendor at all?

    THE CHEAPEST CHECK IN THE HARNESS, AND THE ONE THAT SAVES A WHOLE SESSION. It needs
    no credentials, no credit and no phone number, and it answers the question an
    operator otherwise discovers on gate 2 with the meter running: is the vendor even
    routable from here. It is not hypothetical — the sandbox these gates were written in
    cannot reach `api.bolna.ai` or `docs.bolna.ai` at all (the egress proxy answers
    `CONNECT tunnel failed, 403`), so the pilot is only executable from a machine with
    real network access, and that is a FACT ABOUT THE ENVIRONMENT with an action
    attached rather than an exception to be surprised by.

    ANY HTTP RESPONSE MEANS REACHABLE, including 401, 403 and 404. Authorisation is a
    separate requirement with its own row; conflating the two would report a missing key
    as a network fault and send an operator to argue with their firewall.
    """

    reachable: bool
    detail: str


def probe_vendor(
    url: str = VENDOR_API_URL, timeout: float = REACHABILITY_TIMEOUT_S
) -> Reachability:
    """One unauthenticated request. Performed at the CLI edge and INJECTED into
    `preflight`, so the report itself stays pure and testable without a network."""
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=False)
    except httpx.ProxyError as exc:
        # The exact shape seen in a sandboxed/corporate environment: the egress proxy
        # refuses the CONNECT before the vendor is ever contacted.
        return Reachability(False, f"an egress proxy refused the connection ({type(exc).__name__})")
    except httpx.HTTPError as exc:
        return Reachability(False, f"could not connect ({type(exc).__name__})")
    return Reachability(True, f"the API answered (HTTP {response.status_code})")


@dataclass(frozen=True, slots=True)
class Requirement:
    key: str
    state: RequirementState
    gates: tuple[Gate, ...]
    why: str
    how_to_get: str

    @property
    def blocking(self) -> bool:
        return self.state == "missing"


@dataclass(frozen=True, slots=True)
class Preflight:
    requirements: tuple[Requirement, ...]

    @property
    def missing(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if r.state == "missing")

    @property
    def unverifiable(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if r.state == "unverifiable")

    def blocked_gates(self) -> dict[Gate, list[str]]:
        """Gate number → the requirement keys that stop it. This is the shopping list
        organised the way the pilot is actually run: by gate."""
        blocked: dict[Gate, list[str]] = {}
        for req in self.missing:
            for gate in req.gates:
                blocked.setdefault(gate, []).append(req.key)
        return {gate: sorted(keys) for gate, keys in sorted(blocked.items())}

    def as_dict(self) -> dict[str, object]:
        return {
            "requirements": [
                {
                    "key": r.key,
                    "state": r.state,
                    "gates": list(r.gates),
                    "why": r.why,
                    "how_to_get": r.how_to_get,
                }
                for r in self.requirements
            ],
            "blocked_gates": {str(k): v for k, v in self.blocked_gates().items()},
        }


def _present(value: str | None) -> RequirementState:
    """Present or absent. The VALUE never leaves this function."""
    return "satisfied" if value else "missing"


def webhook_url_reachable(url: str) -> bool:
    """Could the engine's cloud plausibly reach this URL?

    A hostname test, not a connectivity test: the harness runs on the operator's laptop
    and can reach `localhost` perfectly well, which is exactly the false green this
    avoids. What matters is whether the address means anything from OUTSIDE, and a
    loopback or empty host provably does not. A tunnel (`*.ngrok.io`,
    `*.trycloudflare.com`) passes here and is confirmed for real by gate 1's first
    delivery — the only proof that counts.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    return (parsed.hostname or "") not in _UNREACHABLE_HOSTS


def _reachability_requirement(probe: Reachability | None) -> Requirement:
    """Listed FIRST because it is the cheapest and the most session-destroying.

    `None` means nobody probed — reported `unverifiable`, never assumed fine. An unasked
    question and a good answer must not look the same.
    """
    if probe is None:
        state: RequirementState = "unverifiable"
        why = "not probed on this run."
    elif probe.reachable:
        state = "satisfied"
        why = probe.detail
    else:
        state = "missing"
        why = (
            f"{probe.detail}. Every API gate would fail here for a reason that has "
            "nothing to do with Bolna, and the session would be lost discovering it."
        )
    return Requirement(
        key=f"network reachability ({VENDOR_API_URL})",
        state=state,
        gates=(1, 2, 6, 7),
        why=why,
        how_to_get="Run the pilot from a machine with unrestricted egress. Corporate and "
        "sandboxed networks commonly refuse the CONNECT to api.bolna.ai; a proxy that "
        "blocks the vendor blocks the whole pilot.",
    )


def preflight(settings: Settings, probe: Reachability | None = None) -> Preflight:
    """The whole shopping list, in the order an operator would work through it."""
    engine_is_bolna = settings.engine == "bolna"
    requirements: list[Requirement] = [
        _reachability_requirement(probe),
        Requirement(
            key="ENGINE=bolna",
            state="satisfied" if engine_is_bolna else "missing",
            gates=(1, 2, 6),
            why=(
                "The pilot verifies the adapter we will ship. Running these gates against "
                f"ENGINE={settings.engine} exercises the harness, not the vendor."
            ),
            how_to_get="Set ENGINE=bolna in the pilot environment (never in prod config).",
        ),
        Requirement(
            key="BOLNA_API_KEY",
            state=_present(settings.bolna_api_key),
            gates=(1, 2, 6),
            why="Bearer auth for every /v2/agent, /call and /executions call (TRD §5).",
            how_to_get="bolna.ai dashboard → Developers → API keys. Inject from the "
            "secrets manager; never commit it.",
        ),
        Requirement(
            key="SARVAM_API_KEY",
            state=_present(settings.sarvam_api_key),
            gates=(2, 3, 4, 5),
            why=(
                "BYOK: the agent created in gate 2 names Sarvam Saaras STT and Bulbul TTS "
                "(D-36). Without the key the agent is created but every call fails inside "
                "the vendor's pipeline, which looks like a vendor fault and is not one."
            ),
            how_to_get="sarvam.ai console → API keys. Note the key is ALSO pasted into "
            "Bolna's provider config (TRD §5 BYOK custody) — use a dedicated key.",
        ),
        Requirement(
            key="WEBHOOK_BASE_URL",
            state="satisfied" if webhook_url_reachable(settings.webhook_base_url) else "missing",
            gates=(1, 6),
            why=(
                "Baked into the agent at publish time and called back from Bolna's cloud. "
                "A loopback address means no delivery ever arrives, and gates 1 and 6 "
                "would score a silence that says nothing about the vendor."
            ),
            how_to_get="Run a tunnel (ngrok/cloudflared) to the voice-runtime port and set "
            "WEBHOOK_BASE_URL to the public https URL.",
        ),
        Requirement(
            key="BOLNA_WEBHOOK_SOURCE_IPS",
            state=_present(settings.bolna_webhook_source_ips),
            gates=(1,),
            why=(
                "The ENTIRE authenticity control for an unsigned engine (D-31). Gate 1 "
                "confirms deliveries arrive only from it and that everything else is "
                "rejected."
            ),
            how_to_get="Defaults to Bolna's documented egress 13.203.39.153; confirm with "
            "support during the pilot and update the variable if they renumber.",
        ),
        Requirement(
            key="pilot phone number",
            state="unverifiable",
            gates=(2, 3, 4, 5, 6, 7),
            why=(
                "Every call gate needs an outbound-capable number attached to the agent. "
                "Our adapter cannot provision one (see the gate 2 findings), so this is "
                "bought and attached by hand before the pilot starts."
            ),
            how_to_get="Buy/port a number in the Bolna dashboard or bring an Exotel/Vobiz "
            "trunk, then confirm it is attached to the pilot agent.",
        ),
        Requirement(
            key="account credit",
            state="unverifiable",
            gates=(2, 3, 4, 5, 6, 7, 13),
            why=(
                "Real PSTN spend. A balance-low account returns the `balance-low` status, "
                "which this harness maps to `failed` — a red gate that is our billing, not "
                "their platform."
            ),
            how_to_get="Bolna Pilots plan gives $5 signup credit; OPERATIONS §2 budgets "
            "₹3-5k total. Top up before the session, not during it.",
        ),
        Requirement(
            key="nginx source-IP allowlist",
            state="unverifiable",
            gates=(1,),
            why=(
                "Gate 1 requires the allowlist at nginx AND in-app. This harness can only "
                "exercise the in-app half in-process; the edge half needs a POST from a "
                "non-allowlisted host against the deployed receiver."
            ),
            how_to_get="Deploy the receiver behind the edge config, then curl it from any "
            "other machine and confirm the 401 (see the gate 1 human step).",
        ),
    ]
    return Preflight(requirements=tuple(requirements))


def format_preflight(report: Preflight) -> str:
    """Operator-facing rendering. Read at 11pm, so every line says what to do next."""
    lines = ["PILOT PREFLIGHT (OPERATIONS §2)", ""]
    for req in report.requirements:
        marker = {"satisfied": "  ok", "missing": "MISS", "unverifiable": "  ??"}[req.state]
        gates = ", ".join(str(g) for g in req.gates)
        lines.append(f"[{marker}] {req.key}  (gates {gates})")
        if req.state != "satisfied":
            lines.append(f"        why : {req.why}")
            lines.append(f"        get : {req.how_to_get}")
    blocked = report.blocked_gates()
    lines.append("")
    if blocked:
        lines.append("BLOCKED GATES — these cannot run until the listed items exist:")
        for gate, keys in blocked.items():
            lines.append(f"  gate {gate}: {', '.join(keys)}")
    else:
        lines.append("No gate is blocked by a checkable requirement.")
    if report.unverifiable:
        lines.append("")
        lines.append(
            "UNVERIFIABLE from here — confirm by eye before the session "
            "(they are NOT confirmed by this run):"
        )
        for req in report.unverifiable:
            lines.append(f"  - {req.key}")
    return "\n".join(lines)


__all__ = [
    "REACHABILITY_TIMEOUT_S",
    "VENDOR_API_URL",
    "Preflight",
    "Reachability",
    "Requirement",
    "RequirementState",
    "format_preflight",
    "preflight",
    "probe_vendor",
    "webhook_url_reachable",
]
