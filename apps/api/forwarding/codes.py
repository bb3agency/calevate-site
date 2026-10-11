"""How a client turns forwarding on and off, per carrier and mode: the catalogue (D-746).

Data, not screen copy: the guide, the settings screen and the admin card all read it through
`GET /v1/forwarding/codes`, and every code carries its evidence class and source (hard rule
11). Codes are templates: `{number}` is the client's Calevate number in the form a phone in
India dials it (`dialled_form`), `{seconds}` the ring time.

WHAT THE STANDARD SAYS, which is why the "set it once" mode works (3GPP TS 22.082, read 11 Oct
2026 through whatthespec.net's rendering of v19.0.0, standards-body text via an unofficial
mirror; the ETSI PDF is ts_122082v180001p.pdf):

* §3.3.3: the no-reply timer is "between 5 and 30 seconds, in steps of 5 seconds"; without
  one the network's own default applies, and the standard gives no number.
* §1.6.82.2-4: while all-calls forwarding is on, the conditional forwards are quiescent;
  when it is switched off they become operative again. So a client who registers the three
  conditional forwards once never has to dial them again.
* §2.3.8 (and TS 24.628 §4.1 for VoLTE): a call the person declines is forwarded under
  "busy". No Indian carrier page confirms it, so the guide says to check it with the test.

Not verified anywhere, and therefore left to the self-test rather than stated: that a
switched-off or flight-mode phone forwards at once on Indian networks, that Wi-Fi calling
keeps a flight-mode phone reachable, and whether each carrier honours the ring time.

tel: links are not offered: iOS does not dial a link containing `*` or `#` ("the Phone app
does not attempt to dial", developer.apple.com PhoneLinks reference, read 11 Oct 2026), so
every code has a copy button instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

EvidenceClass = Literal["carrier_own", "standards_body", "web_secondary"]

_TS_22082: Final = "https://whatthespec.net/friendlyspec/spec/22.082/19.0.0"
_TS_22030_DRAFT: Final = "https://3gpp.org/FTP/tsg_sa/WG1_Serv/TSGS1_08_Beijing/Docs/S1-000154.doc"
_VI: Final = "https://www.myvi.in/blog/how-to-activate-and-deactivate-call-forwarding-code-on-vi"
_AIRTEL: Final = "https://www.airtel.in/blog/airtel-app/divert-calls-in-airtel/"
_JIO: Final = "https://www.jio.com/help/faq/mobile/services/hd-voice/how-can-i-activate-call-forwarding-service"
_TELECOMTALK: Final = "https://telecomtalk.info/how-to-start-and-stop-call-forwarding/493353/"
READ_ON: Final = "2026-10-11"


@dataclass(frozen=True, slots=True)
class Code:
    """One thing to dial, and how to undo it."""

    #: `no_answer`, `busy`, `unreachable`, `all_calls`, `all_conditional`, `everything`, or
    #: `disputed` for a code whose meaning the sources disagree on.
    condition: str
    activate: str | None
    #: None when no source gives one for this condition alone.
    deactivate: str | None
    evidence: EvidenceClass
    source: str


@dataclass(frozen=True, slots=True)
class CarrierGuide:
    carrier: str
    #: `codes`: dial them; `app`: the carrier publishes no codes and points to its app or the
    #: phone's settings; `ask_provider`: the line is set by its provider.
    method: Literal["codes", "app", "ask_provider"]
    codes: tuple[Code, ...]
    #: Codes other sites give that the carrier itself does not publish (shown as such).
    unconfirmed: tuple[tuple[str, tuple[Code, ...]], ...] = ()
    #: Where to set it when the carrier points to an app or settings screen.
    app_path: str | None = None
    note: str | None = None


def _gsm(stars: str, evidence: EvidenceClass, source: str) -> tuple[Code, ...]:
    """The standard GSM set. `stars` is `**` (register and activate) or the single `*` Vi
    prints on its own page."""
    return (
        Code("no_answer", f"{stars}61*{{number}}**{{seconds}}#", "##61#", evidence, source),
        Code("busy", f"{stars}67*{{number}}#", "##67#", evidence, source),
        Code("unreachable", f"{stars}62*{{number}}#", "##62#", evidence, source),
        Code("all_calls", f"{stars}21*{{number}}#", "##21#", evidence, source),
        # TS 22.030 Annex B: 004 = all conditional forwards, 002 = every forward. Read in a
        # 2000 SA1 draft of that table, not the current text: standards body, draft.
        Code("all_conditional", None, "##004#", "standards_body", _TS_22030_DRAFT),
        Code("everything", None, "##002#", evidence, source),
    )


#: The ring-time clause of the no-answer code is the standard's, whatever the carrier.
RING_TIME_SOURCE: Final = (_TS_22082, "standards_body")

GUIDES: Final[dict[str, CarrierGuide]] = {
    "airtel": CarrierGuide(
        carrier="airtel",
        method="codes",
        # Airtel's own page gives only the all-calls divert and the Thanks app; the
        # conditional codes are from secondary guides.
        codes=_gsm("**", "web_secondary", _TELECOMTALK),
        app_path="Airtel Thanks app, or your phone's Settings > Phone > Call forwarding",
        note="Airtel's own page lists the all-calls code and the Airtel Thanks app.",
    ),
    "vi": CarrierGuide(
        carrier="vi",
        method="codes",
        codes=_gsm("*", "carrier_own", _VI),
        note="These are the codes Vi publishes. The ring time is the standard's addition.",
    ),
    "bsnl": CarrierGuide(
        carrier="bsnl",
        method="codes",
        codes=_gsm("**", "web_secondary", _TELECOMTALK),
        note="BSNL's own site lists no codes; these come from forwarding guides.",
    ),
    "jio": CarrierGuide(
        carrier="jio",
        method="app",
        codes=(),
        app_path=(
            "MyJio app: Profile > Mobile Settings > Service Settings > Call Forwarding. Or your "
            "phone: Settings > Call > Advanced settings > Call forwarding."
        ),
        unconfirmed=(
            ("Standard codes", _gsm("**", "web_secondary", _TELECOMTALK)),
            (
                "Jio-style codes",
                # Sites disagree on whether *403 and *409 are no-answer or unreachable, and
                # some say *401 no longer works; no source gives a per-condition stop code.
                (
                    Code("all_calls", "*401*{number}", None, "web_secondary", _TELECOMTALK),
                    Code("busy", "*405*{number}", None, "web_secondary", _TELECOMTALK),
                    Code("disputed", "*403*{number}", None, "web_secondary", _TELECOMTALK),
                    Code("disputed", "*409*{number}", None, "web_secondary", _TELECOMTALK),
                    Code("everything", None, "*413", "web_secondary", _TELECOMTALK),
                ),
            ),
        ),
        note=(
            "Jio publishes no codes and points to the MyJio app or your phone's settings. "
            "Sites disagree on the codes, so check in the MyJio app."
        ),
    ),
    "other": CarrierGuide(carrier="other", method="ask_provider", codes=()),
}

#: Landlines and office phone systems are set by whoever runs them.
PROVIDER_GUIDE: Final = CarrierGuide(
    carrier="provider",
    method="ask_provider",
    codes=(),
    note="Ask your provider to enable call divert to your Calevate number.",
)

JIO_SOURCE: Final = (_JIO, "carrier_own")
AIRTEL_SOURCE: Final = (_AIRTEL, "carrier_own")


def dialled_form(e164: str) -> str:
    """The Calevate number as a phone in India dials it inside a code: 0 and the ten digits.
    A mobile-series and a landline number cannot be told apart by their first digit (80 is
    both a Bengaluru area code and a mobile series), and the 0 prefix reaches both. Whether
    every network takes it inside a forwarding code is confirmed by the test (gate F-3)."""
    return f"0{e164.removeprefix('+91')}"


def render(template: str | None, *, number_e164: str, seconds: int) -> str | None:
    if template is None:
        return None
    return template.replace("{number}", dialled_form(number_e164)).replace(
        "{seconds}", str(seconds)
    )


__all__ = [
    "GUIDES",
    "PROVIDER_GUIDE",
    "READ_ON",
    "RING_TIME_SOURCE",
    "CarrierGuide",
    "Code",
    "EvidenceClass",
    "dialled_form",
    "render",
]
