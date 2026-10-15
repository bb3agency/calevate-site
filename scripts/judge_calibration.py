"""Calibrate the test-conversation judge against a person's labels (D-777; gap D4 of
`docs/evidence/prompting-practices-2026-10.md`).

    uv run python -m scripts.judge_calibration export --tenant <uuid> [--tenant <uuid>] \\
        [--limit 50] --out calibration.csv
    uv run python -m scripts.judge_calibration score --labels calibration.csv \\
        [--judge calibration.judge.json] [--compare calibration.rejudged.json] [--out r.md]
    uv run python -m scripts.judge_calibration rejudge --judge calibration.judge.json \\
        --out calibration.rejudged.json

`export` writes two files. `calibration.csv` is what a person labels: each stored test
conversation, its expected outcome and two empty columns, `human_verdict` (passed,
needs_fix or failed) and `human_note`. It holds NO judge verdict, so the person labels
blind instead of agreeing with what they were shown. `calibration.judge.json` beside it
holds what the judge said about each row, the model it ran on and the position it was
shown at. Only results where the judge's own verdict was recorded are exported (runs from
D-777 on): an older result's stored verdict may be a hard check's, not the judge's.

`score` joins the two on (run, key) and reports agreement over the rows a person labelled:
exact agreement, Cohen's kappa, pass-vs-not-pass agreement, the confusion matrix, and the
same split by judge model, by position (first, middle or last third of the request) and by
probe. Strong LLM judges reach "over 80% agreement" with people (the evidence doc's S23).
Re-run it whenever the judge prompt or model changes. `--compare` adds the verdict flips
between two judge files.

`rejudge` asks the CURRENT judge about the exported conversations again and writes a new
judge file in the same shape, so the old and new judges are scored on the same labels. It
reads each agent's configuration as it is NOW (`load_brief`), so an agent edited since its
run is judged against its new facts. It spends the dashboard AI chain and meters nothing to
any client.

Every exported line passes through `redact()` (G-2, hard rule 6): saved and re-tested
conversations start from real callers' redacted words, and an agent can echo them. Export
only accounts whose conversations you may read: your own test accounts, or a client that
agreed.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.test_conversations import Scenario, get_run, load_brief
from apps.api.core.platform_config import refresh as refresh_platform_config
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.workers.agent_test_ai import (
    conversation_text,
    judge_conversations,
    judge_leg,
    safe_line,
)
from apps.workers.agent_test_conversations import agent_in_call_model, judge_entry
from sqlalchemy import text

VERDICTS: Final = ("passed", "needs_fix", "failed")
CSV_COLUMNS: Final = (
    "run_id",
    "key",
    "agent_id",
    "title",
    "category",
    "probe",
    "source",
    "expect",
    "conversation",
    "human_verdict",
    "human_note",
)
#: Finished runs read per tenant before `--limit` is applied (about ten results a run).
RUNS_PER_TENANT: Final = 40
_ALIASES: Final = {"pass": "passed", "fail": "failed", "fix": "needs_fix"}


@dataclass(frozen=True, slots=True)
class Pair:
    """One labelled conversation: what the person said and what the judge said."""

    human: str
    judge: str
    model: str = "unknown"
    position: str = "unknown"
    probe: str = "none"


@dataclass(slots=True)
class Agreement:
    n: int = 0
    exact: int = 0
    pass_agree: int = 0
    kappa: float | None = None
    confusion: Counter[tuple[str, str]] = field(default_factory=Counter)

    @property
    def exact_rate(self) -> float:
        return self.exact / self.n if self.n else 0.0

    @property
    def pass_rate(self) -> float:
        return self.pass_agree / self.n if self.n else 0.0


def normalise_verdict(value: object) -> str | None:
    """A label as one of `VERDICTS`, or None for a blank or unknown cell."""
    word = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    word = _ALIASES.get(word, word)
    return word if word in VERDICTS else None


def cohen_kappa(pairs: Sequence[Pair]) -> float | None:
    """Agreement beyond chance over the three verdicts. None when chance agreement is
    total (person and judge each used one and the same class), where kappa is undefined."""
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(p.human == p.judge for p in pairs) / n
    humans = Counter(p.human for p in pairs)
    judges = Counter(p.judge for p in pairs)
    expected = sum(humans[v] * judges[v] for v in VERDICTS) / (n * n)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def agreement(pairs: Sequence[Pair]) -> Agreement:
    out = Agreement(n=len(pairs), kappa=cohen_kappa(pairs))
    for pair in pairs:
        out.exact += pair.human == pair.judge
        out.pass_agree += (pair.human == "passed") == (pair.judge == "passed")
        out.confusion[(pair.human, pair.judge)] += 1
    return out


def position_bucket(position: object, of: object) -> str:
    """Which third of the judge's request a conversation sat in."""
    if not isinstance(position, int) or not isinstance(of, int) or of <= 0:
        return "unknown"
    return ("first", "middle", "last")[min(position * 3 // of, 2)]


def pairs_from(labels: Sequence[Mapping[str, str]], judged: Mapping[str, Any]) -> list[Pair]:
    """Labelled rows joined to the judge file. A row with no label or no judge verdict is
    left out, never guessed."""
    out: list[Pair] = []
    for row in labels:
        human = normalise_verdict(row.get("human_verdict"))
        entry = judged.get(f"{row.get('run_id')}:{row.get('key')}")
        if human is None or not isinstance(entry, dict):
            continue
        verdict = normalise_verdict(entry.get("verdict"))
        if verdict is None:
            continue
        out.append(
            Pair(
                human=human,
                judge=verdict,
                model=str(entry.get("model") or "unknown"),
                position=position_bucket(entry.get("position"), entry.get("of")),
                probe=str(row.get("probe") or "none"),
            )
        )
    return out


def flips(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """(row id, old verdict, new verdict) wherever two judge files disagree."""
    out = []
    for row_id, entry in sorted(old.items()):
        other = new.get(row_id)
        if not isinstance(entry, dict) or not isinstance(other, dict):
            continue
        before, after = entry.get("verdict"), other.get("verdict")
        if before and after and before != after:
            out.append((row_id, str(before), str(after)))
    return out


def _line(label: str, result: Agreement) -> str:
    kappa = "n/a" if result.kappa is None else f"{result.kappa:.2f}"
    return f"| {label} | {result.n} | {result.exact_rate:.0%} | {kappa} | {result.pass_rate:.0%} |"


def report(pairs: Sequence[Pair], *, flipped: Sequence[tuple[str, str, str]] = ()) -> str:
    """The calibration report, as Markdown."""
    if not pairs:
        return "No labelled row matched a judge verdict: fill in `human_verdict` first.\n"
    total = agreement(pairs)
    lines = [
        "# Judge calibration",
        "",
        "| Slice | Labelled | Exact agreement | Cohen's kappa | Pass vs not-pass |",
        "|---|---|---|---|---|",
        _line("all", total),
    ]
    for name in ("model", "position", "probe"):
        groups: dict[str, list[Pair]] = defaultdict(list)
        for pair in pairs:
            groups[getattr(pair, name)].append(pair)
        lines += [
            _line(f"{name}: {key}", agreement(group)) for key, group in sorted(groups.items())
        ]
    lines += ["", "Rows: the person's verdict. Columns: the judge's.", ""]
    lines += ["| | " + " | ".join(VERDICTS) + " |", "|---" * (len(VERDICTS) + 1) + "|"]
    for human in VERDICTS:
        cells = " | ".join(str(total.confusion[(human, judge)]) for judge in VERDICTS)
        lines.append(f"| {human} | {cells} |")
    if flipped:
        lines += ["", f"Verdicts that changed between the two judge files: {len(flipped)}", ""]
        lines += [f"- {row_id}: {before} -> {after}" for row_id, before, after in flipped]
    return "\n".join(lines) + "\n"


def conversation_cell(result: Mapping[str, Any]) -> str:
    """One stored conversation as the labeller reads it, every line redacted."""
    lines = []
    for turn in result.get("conversation") or []:
        lines.append(f"Caller: {safe_line(str(turn.get('said') or ''))}")
        lines.append(f"Agent: {safe_line(str(turn.get('reply') or '')) or '(said nothing)'}")
        if turn.get("tools"):
            lines.append(f"(actions used: {', '.join(str(t) for t in turn['tools'])})")
    return "\n".join(lines)


def export_rows(
    tenant_id: UUID, run_id: UUID, agent_id: UUID, results: Sequence[Mapping[str, Any]]
) -> Iterator[tuple[dict[str, str], dict[str, Any]]]:
    """(label row, judge entry) for every result whose judge verdict was recorded."""
    for result in results:
        entry = result.get("judge")
        if not isinstance(entry, dict) or normalise_verdict(entry.get("verdict")) is None:
            continue
        key = str(result.get("key"))
        yield (
            {
                "run_id": str(run_id),
                "key": key,
                "agent_id": str(agent_id),
                "title": str(result.get("title") or ""),
                "category": str(result.get("category") or ""),
                "probe": str(result.get("probe") or ""),
                "source": str(result.get("source") or ""),
                "expect": safe_line(str(result.get("expect") or "")),
                "conversation": conversation_cell(result),
                "human_verdict": "",
                "human_note": "",
            },
            {
                **entry,
                "reason": safe_line(str(entry.get("reason") or "")),
                "tenant_id": str(tenant_id),
                "agent_id": str(agent_id),
                "run_id": str(run_id),
                "key": key,
                "stored_verdict": result.get("verdict"),
            },
        )


# --- database and model sides ------------------------------------------------------------


async def _finished_runs(tenant_id: UUID) -> list[tuple[UUID, UUID, list[dict[str, Any]]]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, agent_id, results FROM agent_test_runs WHERE status = 'done' "
                    "ORDER BY created_at DESC, id DESC LIMIT :limit"
                ),
                {"limit": RUNS_PER_TENANT},
            )
        ).all()
    return [(row[0], row[1], list(_jsonb(row[2]) or [])) for row in rows]


def _jsonb(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def collect(
    tenants: Sequence[UUID], *, limit: int
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Up to `limit` (label row, judge entry) pairs, newest runs first."""
    rows: list[dict[str, str]] = []
    judged: dict[str, Any] = {}
    for tenant_id in tenants:
        for run_id, agent_id, results in await _finished_runs(tenant_id):
            for row, entry in export_rows(tenant_id, run_id, agent_id, results):
                if len(rows) < limit:
                    rows.append(row)
                    judged[f"{row['run_id']}:{row['key']}"] = entry
    return rows, judged


def write_export(rows: Sequence[Mapping[str, str]], judged: Mapping[str, Any], out: Path) -> Path:
    """The labelling sheet at `out` and the judge file beside it; returns the judge file."""
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    judge_path = out.with_suffix(".judge.json")
    write_judge(judge_path, judged)
    return judge_path


def write_judge(path: Path, judged: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(judged, ensure_ascii=False, indent=2), encoding="utf-8")


def read_labels(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_judge(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def score(labels: Path, judge: Path, *, compare: Path | None, out: Path | None) -> int:
    judged = read_judge(judge)
    flipped = flips(judged, read_judge(compare)) if compare is not None else []
    body = report(pairs_from(read_labels(labels), judged), flipped=flipped)
    if out is not None:
        out.write_text(body, encoding="utf-8")
    print(body)
    return 0


async def _rejudge_run(
    tenant: str, agent: str, run: str, keys: Sequence[str]
) -> dict[str, dict[str, Any]]:
    tenant_id, agent_id = UUID(tenant), UUID(agent)
    async with tenant_session(tenant_id) as session:
        brief = await load_brief(session, agent_id)
        account_leg = await account_assist_leg(session)
        stored = await get_run(session, agent_id, UUID(run))
    by_key = {str(r.get("key")): r for r in stored.results}
    chosen = [by_key[k] for k in keys if k in by_key]
    if not chosen:
        return {}
    model = await agent_in_call_model(tenant_id, agent_id, get_engine())
    texts = [
        conversation_text(
            Scenario.of(r),
            [
                (str(t.get("said") or ""), str(t.get("reply") or ""), list(t.get("tools") or []))
                for t in r.get("conversation") or []
            ],
        )
        for r in chosen
    ]
    answer = await judge_conversations(
        brief,
        texts,
        {str(r.get("key")) for r in chosen},
        tenant_leg=judge_leg(account_leg, agent_model=model, quota_exhausted=False),
    )
    out: dict[str, dict[str, Any]] = {}
    for position, r in enumerate(chosen):
        key = str(r.get("key"))
        out[f"{run}:{key}"] = {
            **judge_entry(answer.value.get(key)),
            "model": answer.model,
            "agent_model": model,
            "position": position,
            "of": len(chosen),
            "tenant_id": tenant,
            "agent_id": agent,
            "run_id": run,
            "key": key,
        }
    return out


async def rejudge(old: Mapping[str, Any]) -> dict[str, Any]:
    """The current judge's word on every conversation of an earlier judge file."""
    await refresh_platform_config(force=True)
    by_run: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for entry in old.values():
        by_run[(entry["tenant_id"], entry["agent_id"], entry["run_id"])].append(entry["key"])
    new: dict[str, Any] = {}
    for (tenant, agent, run), keys in sorted(by_run.items()):
        new.update(await _rejudge_run(tenant, agent, run, keys))
    return new


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    exporting = sub.add_parser("export")
    exporting.add_argument("--tenant", type=UUID, action="append", required=True)
    exporting.add_argument("--limit", type=int, default=50)
    exporting.add_argument("--out", type=Path, required=True)
    scoring = sub.add_parser("score")
    scoring.add_argument("--labels", type=Path, required=True)
    scoring.add_argument("--judge", type=Path)
    scoring.add_argument("--compare", type=Path)
    scoring.add_argument("--out", type=Path)
    rejudging = sub.add_parser("rejudge")
    rejudging.add_argument("--judge", type=Path, required=True)
    rejudging.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "export":
        rows, judged = asyncio.run(collect(args.tenant, limit=args.limit))
        judge_path = write_export(rows, judged, args.out)
        print(f"{len(rows)} conversations to label in {args.out}; the judge's in {judge_path}")
        return 0
    if args.command == "score":
        judge = args.judge or args.labels.with_suffix(".judge.json")
        return score(args.labels, judge, compare=args.compare, out=args.out)
    old = read_judge(args.judge)
    new = asyncio.run(rejudge(old))
    write_judge(args.out, new)
    print(f"{len(new)} conversations re-judged into {args.out}; {len(flips(old, new))} changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
