"""Capture a real vendor payload as a committed adapter fixture — redacted on the way in.

    uv run python -m scripts.pilot.record --gate 4 --name execution_completed \
        --source "GET /executions/{id}" --by "ops@calevate" --input payload.json

OPERATIONS §2 asks gates 1, 2, 4, 7 and 8 to "capture the payload as an adapter
fixture", and that is where a pilot's value outlives the pilot week: the Bolna adapter
was hand-maintained from docs because this repository believed **Bolna publishes no
OpenAPI spec** — they publish one and it has now been read (D-350, `docs/vendor/bolna/
hosted-oas.md`). Captured payloads matter MORE rather than less: a spec is what the vendor
says the server does, and every defect D-350 uncovered was of the form "we called
something plausible and nothing could disagree". So
every field name in it is a claim. A committed real payload turns those claims into a
test. Without this step the pilot ends and the adapter is still guesswork.

WHY REDACTION IS PART OF CAPTURE AND NOT A STEP AFTERWARDS
-----------------------------------------------------------
A real Get Execution payload carries `telephony_data.to_number` (a caller's number), a
`recording_url` (usually presigned — its query string is a CREDENTIAL), the transcript
with recognised text in it, `transcriber.turns[].text` on the latency object OPERATIONS
§2 gate 4 asks us to capture, and `extracted_data` full of whatever the extraction
schema pulled out of the caller. Committing one of those to git is a permanent leak;
`git rm` does not remove it from history.

So there is exactly one way to write a fixture — `record_fixture()` — and it scrubs
before it serialises, verifies after it scrubs, and writes NOTHING if the verification
still finds something. A procedure ("remember to redact") is a procedure someone skips
at 11pm during a pilot week; a function that cannot emit an unscrubbed file is not.

HOW THE SCRUB WORKS: TWO PASSES, BECAUSE KEYS LIE
---------------------------------------------------
1. **By key** — a known PII-bearing key is replaced with a type- and shape-preserving
   placeholder, so the fixture still exercises the adapter (an E.164 string stays E.164,
   a transcript stays prefix-tagged, a recording URL stays a URL).
2. **By value, everywhere** — every remaining string runs the repo's own `redact()`,
   the same deterministic pass that produces `text_redacted` in production (validators
   for Aadhaar/Luhn, spoken digit runs in English, Telugu and Hindi). This is the half
   that catches a phone number in a field we have never seen, which is the realistic
   case: their payload shapes are undocumented and change without notice.

Then the serialised result is re-scanned. If anything survives, `UnredactedPayloadError`
names the JSON paths and the kinds — never the values (hard rule 6) — and no file is
written. Fail-closed: the alternative (write it and warn) puts the leak in the tree.

WHAT A PLACEHOLDER IS ALLOWED TO BE
------------------------------------
Placeholders must be unmistakably synthetic AND structurally valid, or the fixture stops
testing the adapter. Numbers use `+91 5XXXXXXXXX`: Indian mobile numbers are ten digits
beginning 9, 8, 7 or 6 (the 6-series opened in 2017), so level 5 is not a mobile
allocation and such a number can never route to a person, while still being E.164-shaped
for `start_outbound_call`'s `+` assertion and our own E.164 validators.
(https://en.wikipedia.org/wiki/Mobile_telephone_numbering_in_India; TRAI's National
Numbering Plan, https://www.trai.gov.in.) Recording URLs become `.invalid` hosts, the
TLD RFC 2606 §2 reserves precisely so it can never resolve. Transcript lines become a
fixed Telugu-transliterated script — the same register Saaras returns — so the
prefix-tagged parser test still means something.

Rejected alternative: hashing the values instead of replacing them, to keep the fixture
"faithful". A hash of a 10-digit number is reversible by brute force in milliseconds
(10^10 candidates), so it is not redaction, it is encoding. Faithfulness that matters
here is SHAPE, and a placeholder preserves it exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from apps.workers.redaction import redact

from scripts.pilot.scorecard import PHONE_IN_TEXT_RE

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURES_DIR: Final = (
    REPO_ROOT / "packages" / "shared" / "tests" / "engine_conformance" / "fixtures"
)
MANIFEST_NAME: Final = "MANIFEST.json"

# Placeholders. Every one of them is unroutable/unresolvable by construction — see the
# module docstring for the citation behind each choice.
PLACEHOLDER_NUMBER: Final = "+915550000000"
PLACEHOLDER_CALLEE: Final = "+915550000001"
PLACEHOLDER_RECORDING: Final = "https://recordings.invalid/redacted.wav"
PLACEHOLDER_URL: Final = "https://redacted.invalid/"
PLACEHOLDER_VALUE: Final = "[redacted]"

#: Every literal this module SUBSTITUTES IN. `residual_pii` strips them before judging a
#: string, because "residual" means PII that SURVIVED the scrub — and the scrub's own
#: output is not that. Without this the verification eats itself: the shared redactor was
#: widened to mask any `+91` followed by ten digits (grouped, trunk-prefixed or landline),
#: which correctly includes the deliberately-unroutable level-5 placeholder above, so
#: `record_fixture` refused to write ANY fixture and the recorder became unusable.
#:
#: Exempting a closed set of LITERALS is not a hole: a real number would have to be
#: byte-identical to a placeholder to be skipped, and every placeholder here is
#: unroutable, reserved or a fixed synthetic line by construction (see the contract
#: above). The alternative — picking a placeholder the redactor cannot claim — was
#: rejected: it would mean choosing a shape our own PII detector does not recognise,
#: which is a worse property for a fixture to have than this exemption is.
_SUBSTITUTED: Final = (
    PLACEHOLDER_NUMBER,
    PLACEHOLDER_CALLEE,
    PLACEHOLDER_RECORDING,
    PLACEHOLDER_URL,
    PLACEHOLDER_VALUE,
)


def _without_placeholders(value: str) -> str:
    """The string minus anything this module put there itself."""
    for placeholder in _SUBSTITUTED:
        value = value.replace(placeholder, " ")
    return value


# Keys that carry a phone number in some vendor payload we have seen or expect. Being
# wrong in the generous direction costs a fixture a realistic-looking number; being wrong
# in the stingy direction costs a caller their privacy — and pass 2 catches the misses.
PHONE_KEYS: Final = frozenset(
    {
        "from_number",
        "to_number",
        "recipient_phone_number",
        "caller_number",
        "callee_number",
        "phone",
        "phone_number",
        "mobile",
        "msisdn",
        "from_e164",
        "to_e164",
        "caller_e164",
        "contact_number",
        "callback_number",
    }
)
RECORDING_KEYS: Final = frozenset(
    {"recording_url", "recording", "recording_link", "audio_url", "stereo_recording_url"}
)
# Anything whose value is words a caller or the agent actually said.
TRANSCRIPT_KEYS: Final = frozenset(
    {"transcript", "transcript_text", "text", "content", "message", "summary", "utterance"}
)
# Free-form bags whose VALUES are per-call personal data by definition. Keys are kept
# (the shape is the point of the fixture); values become placeholders.
OPAQUE_VALUE_KEYS: Final = frozenset({"extracted_data", "user_data", "context_data", "variables"})

# A fixed, obviously-synthetic Telugu script in the transliterated register Saaras
# returns. Indexed by turn so a multi-turn transcript stays multi-turn.
_SYNTHETIC_TURNS: Final = (
    "Namaskaram, idi demo clinic AI assistant. Ee call record avutundi.",
    "Naaku appointment kavali.",
    "Tappakunda, ee roju evening slot unnadi.",
    "Sare, chala thanks.",
)

_AUDIO_SUFFIXES: Final = (".wav", ".mp3", ".m4a", ".ogg", ".flac")
_URL_RE: Final = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+")
_MOBILE_RE: Final = re.compile(r"[6-9]\d{9}")


def _phone_shaped(value: object) -> bool:
    """Is this whole scalar a phone number, in any of the forms a vendor writes one?

    `redact()` is the authority on a phone number sitting INSIDE a sentence, and it is
    reused for that. It cannot see two cases that only occur in machine payloads, and
    both are real: an integer (`"to_number": 919876543210`), and a bare digit string with
    the country code attached but no `+`, where its own `\\b(?:\\+91)?[6-9]\\d{9}\\b`
    cannot anchor because the 91 in front is a word character. A field that IS a number
    is the commonest place a caller's number lives, so it gets its own check.
    """
    if isinstance(value, bool) or not isinstance(value, int | str):
        return False
    digits = re.sub(r"[\s\-()+]", "", str(abs(value) if isinstance(value, int) else value))
    if not digits.isdigit():
        return False
    for prefix in ("0091", "091", "91", "0"):
        if len(digits) > 10 and digits.startswith(prefix):
            digits = digits[len(prefix) :]
            break
    return bool(_MOBILE_RE.fullmatch(digits))


class UnredactedPayloadError(RuntimeError):
    """Capture refused: something that must not be committed survived the scrub.

    Carries the JSON paths and the detector kinds so an operator can fix the scrubber,
    and deliberately not the values — this exception is printed to a terminal and a CI
    log, both of which are exactly as permanent as the file we just refused to write.
    """


def _scrub_text(value: str) -> str:
    """Pass 2, applied to every string: the repo's production redaction pass, plus URLs.

    One way per problem: `apps/workers/redaction.py` already owns "what is PII in a
    string", including the spoken-digit runs an Indian caller actually produces. A second
    detector here would drift from it, and the one that drifts is the one that misses.
    """
    text = PHONE_IN_TEXT_RE.sub(PLACEHOLDER_NUMBER, redact(value).text)

    def _url(match: re.Match[str]) -> str:
        url = match.group(0)
        lowered = url.lower()
        if any(suffix in lowered for suffix in _AUDIO_SUFFIXES):
            return PLACEHOLDER_RECORDING
        # Presigned links carry the credential in the query string, so a URL survives
        # only when it is bare — and even then only if it is not a recording.
        return url if "?" not in url else PLACEHOLDER_URL

    return _URL_RE.sub(_url, text)


def _synthetic_transcript(value: str) -> str:
    """Rebuild a prefix-tagged transcript with synthetic lines, preserving turn count and
    speaker tags — the two properties `parse_transcript` is actually tested on."""
    out: list[str] = []
    for idx, line in enumerate(value.splitlines()):
        speaker, sep, _ = line.partition(":")
        synthetic = _SYNTHETIC_TURNS[idx % len(_SYNTHETIC_TURNS)]
        out.append(f"{speaker}:{sep and ' '}{synthetic}" if sep else synthetic)
    return "\n".join(out)


def _scrub(value: Any, *, key: str | None = None, phone_seen: list[str]) -> Any:
    """Pass 1 (by key) and pass 2 (by value), applied recursively.

    `phone_seen` alternates the two placeholder numbers so a payload's from/to pair stays
    a PAIR — an adapter that swapped them would otherwise pass the fixture test.
    """
    lowered = (key or "").lower()

    if isinstance(value, dict):
        return {k: _scrub(v, key=k, phone_seen=phone_seen) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, key=key, phone_seen=phone_seen) for v in value]

    # dict/list were handled above, so anything reaching here under a bag key is a scalar.
    if lowered in OPAQUE_VALUE_KEYS:
        return PLACEHOLDER_VALUE
    if lowered in RECORDING_KEYS and isinstance(value, str):
        return PLACEHOLDER_RECORDING
    if lowered in PHONE_KEYS or _phone_shaped(value):
        placeholder = PLACEHOLDER_NUMBER if len(phone_seen) % 2 == 0 else PLACEHOLDER_CALLEE
        phone_seen.append(lowered)
        return placeholder
    if lowered in TRANSCRIPT_KEYS and isinstance(value, str):
        return _synthetic_transcript(value) if "\n" in value else _SYNTHETIC_TURNS[0]

    if isinstance(value, str):
        return _scrub_text(value)
    return value


def _scrub_opaque_bags(value: Any, *, key: str | None = None) -> Any:
    """`extracted_data`/`user_data` keep their KEYS (the shape is what the fixture is for)
    and lose every leaf value. Done as a second walk so the rule is stated once, at the
    bag, rather than repeated at every leaf inside it."""
    if isinstance(value, dict):
        if (key or "").lower() in OPAQUE_VALUE_KEYS:
            return dict.fromkeys(value, PLACEHOLDER_VALUE)
        return {k: _scrub_opaque_bags(v, key=k) for k, v in value.items()}
    if isinstance(value, list):
        if (key or "").lower() in OPAQUE_VALUE_KEYS:
            return [PLACEHOLDER_VALUE for _ in value]
        return [_scrub_opaque_bags(v, key=key) for v in value]
    return value


def scrub_payload(payload: Any) -> Any:
    """The full scrub. Pure; safe to call on anything JSON-shaped."""
    return _scrub_opaque_bags(_scrub(payload, phone_seen=[]))


def residual_pii(payload: Any, *, path: str = "$") -> dict[str, list[str]]:
    """Verification pass: what would still be committed if we wrote this?

    Runs over the SCRUBBED structure, and its findings are the reason capture can be
    trusted rather than believed. Returns {json path: [kinds]}.
    """
    findings: dict[str, list[str]] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            findings |= residual_pii(value, path=f"{path}.{key}")
        return findings
    if isinstance(payload, list):
        for idx, value in enumerate(payload):
            findings |= residual_pii(value, path=f"{path}[{idx}]")
        return findings
    if isinstance(payload, str):
        # Judge what is LEFT after our own substitutions — see `_SUBSTITUTED`.
        payload = _without_placeholders(payload)
        kinds = list(redact(payload).kinds)
        lowered = payload.lower()
        if any(suffix in lowered for suffix in _AUDIO_SUFFIXES) and "invalid" not in lowered:
            kinds.append("recording_url")
        if "?" in payload and _URL_RE.search(payload):
            kinds.append("presigned_url")
        if _phone_shaped(payload) or PHONE_IN_TEXT_RE.search(payload):
            kinds.append("phone")
        if kinds:
            findings[path] = sorted(set(kinds))
    elif _phone_shaped(payload):
        findings[path] = ["numeric_phone"]
    return findings


def _canonical_json(payload: Any) -> str:
    """Deterministic on purpose: a fixture that re-serialises differently produces a diff
    that hides the change somebody actually made."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def record_fixture(
    payload: Any,
    *,
    gate: int,
    name: str,
    source: str,
    captured_by: str,
    captured_at: datetime | None = None,
    fixtures_dir: Path | None = None,
) -> Path:
    """Scrub, verify, then write. The ONLY way a fixture reaches the tree.

    Raises `UnredactedPayloadError` (writing nothing, manifest untouched) if the
    verification pass still finds something. Raises `ValueError` on a name that would
    escape the fixtures directory.
    """
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{2,60}", name):
        raise ValueError(
            f"fixture name {name!r} must be lowercase snake_case (it becomes a filename "
            "and a manifest key, both of which are read by humans)"
        )

    directory = fixtures_dir or FIXTURES_DIR
    scrubbed = scrub_payload(payload)
    leaks = residual_pii(scrubbed)
    if leaks:
        raise UnredactedPayloadError(
            "refusing to write a fixture: personal data survived redaction at "
            + "; ".join(f"{p} ({', '.join(kinds)})" for p, kinds in sorted(leaks.items()))
            + ". Nothing was written. Add the key to the scrubber in scripts/pilot/"
            "record.py and re-run — do not edit the file by hand afterwards."
        )

    body = _canonical_json(scrubbed)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.json"
    target.write_text(body, encoding="utf-8")

    _update_manifest(
        directory,
        name=name,
        entry={
            "gate": gate,
            "source": source,
            "captured_by": captured_by,
            "captured_at": (captured_at or datetime.now(UTC)).isoformat(),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "redactions": sorted(_redaction_kinds(payload)),
        },
    )
    return target


def _redaction_kinds(original: Any) -> set[str]:
    """What the scrub actually had to remove, recorded in the manifest.

    This is evidence too: a fixture whose manifest says `[]` was either already clean or
    was written by something other than this function, and the two are worth being able
    to tell apart.
    """
    kinds: set[str] = set()
    for found in residual_pii(original).values():
        kinds.update(found)
    return kinds


def _update_manifest(directory: Path, *, name: str, entry: dict[str, Any]) -> None:
    manifest_path = directory / MANIFEST_NAME
    manifest: dict[str, Any] = {"fixtures": {}}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{manifest_path} is not valid JSON ({exc}); the fixture was written but "
                "the manifest was not updated. Fix the manifest and re-run."
            ) from exc
        if isinstance(loaded, dict) and isinstance(loaded.get("fixtures"), dict):
            manifest = loaded
    manifest["fixtures"][name] = entry
    manifest["fixtures"] = dict(sorted(manifest["fixtures"].items()))
    manifest_path.write_text(_canonical_json(manifest), encoding="utf-8")


def load_fixture(name: str, *, fixtures_dir: Path | None = None) -> Any:
    """Read a recorded fixture back — the seam the adapter tests use."""
    path = (fixtures_dir or FIXTURES_DIR) / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no recorded fixture named {name!r} in {path.parent} — it is captured during "
            "the pilot by `uv run python -m scripts.pilot.record`"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def recorded_fixtures(*, fixtures_dir: Path | None = None) -> dict[str, Any]:
    """Every recorded fixture, by name. Empty until the pilot runs, which is why the
    replay tests skip rather than fail on an empty directory: a test that fails because
    a vendor account does not exist teaches people to delete the test."""
    directory = fixtures_dir or FIXTURES_DIR
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        name: load_fixture(name, fixtures_dir=directory) for name in manifest.get("fixtures", {})
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture a vendor payload as a redacted adapter fixture.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gate", type=int, required=True, help="OPERATIONS §2 gate number")
    parser.add_argument("--name", required=True, help="fixture name, lowercase snake_case")
    parser.add_argument("--source", required=True, help='e.g. "GET /executions/{id}"')
    parser.add_argument("--by", required=True, help="who captured it")
    parser.add_argument(
        "--input",
        type=Path,
        help="JSON file holding the raw payload; omit to read stdin",
    )
    args = parser.parse_args(argv)

    try:
        raw = (args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()).strip()
    except OSError as exc:
        print(f"cannot read the payload: {exc}", file=sys.stderr)
        return 2
    if not raw:
        print("no payload on stdin (and no --input given)", file=sys.stderr)
        return 2
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"the payload is not valid JSON: {exc}", file=sys.stderr)
        return 2

    try:
        path = record_fixture(
            payload, gate=args.gate, name=args.name, source=args.source, captured_by=args.by
        )
    except (UnredactedPayloadError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"wrote {path.relative_to(REPO_ROOT)} (redacted on capture; manifest updated)")
    print(
        "Now cite it in the scorecard as an ArtifactRef, and delete the raw payload file "
        "you captured from — it is the unredacted copy."
    )
    return 0


__all__ = [
    "FIXTURES_DIR",
    "MANIFEST_NAME",
    "UnredactedPayloadError",
    "load_fixture",
    "record_fixture",
    "recorded_fixtures",
    "residual_pii",
    "scrub_payload",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
