#!/usr/bin/env python3
"""Measure Gemini embedding quality on the Indic corpus. Standard library only.

THE HOST IS NOT SPELLED HERE. `google_openai_compat_base_url()` is the ONE place this
tree assembles a Gemini URL, and `scripts/check_model_residency.py` asserts exactly that —
it refused the first version of this file, correctly, for writing its own literal. A
second endpoint form would be a second residency story for one leg. Both routes were
probed live on 14 Sep 2026 and answer "Please pass a valid API key", i.e. they exist and
only auth was missing:
    GET  /v1beta/openai/models
    POST /v1beta/openai/embeddings

The embedding MODEL is discovered from the live models list, never named from memory.

RUN:
    export GOOGLE_API_KEY='...'
    uv run python -m scripts.gemini_embedding_harness tests/fixtures/telugu_gloss_corpus.json
    uv run python -m scripts.gemini_embedding_harness <corpus> embedding-2   # pin a model
"""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request

from calevate_shared.engine import google_openai_compat_base_url

BASE = google_openai_compat_base_url()
RESULT_PATH_TEMPLATE = "/tmp/gemini_embedding_result_{model}.json"


def _call(url: str, key: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"\nHTTP {e.code} from {url}\n{e.read().decode()[:700]}\n") from e


def embedding_models(key: str) -> list[str]:
    rows = _call(f"{BASE}/models", key).get("data", [])
    names = [r.get("id", "") for r in rows]
    picked = [n for n in names if "embed" in n.lower()]
    print("MODELS THIS KEY CAN SEE")
    for n in sorted(names):
        print(f"  {'* ' if n in picked else '  '}{n}")
    return picked


def embed(key: str, model: str, text: str) -> list[float]:
    body = _call(f"{BASE}/embeddings", key, {"model": model, "input": text})
    return body["data"][0]["embedding"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def main() -> None:
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set GOOGLE_API_KEY first")
    path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/telugu_gloss_corpus.json"
    with open(path, encoding="utf-8") as fh:
        corpus = json.load(fh)
    print(f"corpus: {len(corpus)} facts from {path}\n")

    picked = embedding_models(key)
    if not picked:
        raise SystemExit("\nNo embedding-capable model visible to this key.")
    # A SECOND ARGUMENT PINS THE MODEL, because choosing one later is not a config change —
    # it is a re-embedding of every client's corpus. Comparing two before anything is indexed
    # costs one run; comparing them afterwards costs a migration.
    wanted = sys.argv[2] if len(sys.argv) > 2 else ""
    if wanted:
        # EXACT FIRST, AND THAT IS NOT A NICETY. A bare substring match for "embedding-2"
        # also matches "gemini-embedding-2-preview" and silently took it — a PREVIEW id,
        # which is the precise trap hard rule 11's worked example is about (a retirement
        # date that belonged to a preview snapshot and was repeated as fact about the GA
        # model). The vendor prices the GA id, not the preview, so measuring one and
        # billing the other is two different models wearing one name.
        exact = [n for n in picked if n.rsplit("/", 1)[-1] == wanted or n == wanted]
        loose = [n for n in picked if wanted in n]
        if not exact and len(loose) > 1:
            raise SystemExit(
                f"\n{wanted!r} matches {len(loose)} models and none exactly: {loose}\n"
                "Name one exactly — a preview and its GA id are different models.\n"
            )
        if not exact and not loose:
            raise SystemExit(f"\nNo embedding model matching {wanted!r}. Seen: {picked}")
        model = exact[0] if exact else loose[0]
        if "preview" in model:
            print(f"\n⚠ {model} is a PREVIEW id. Vendor pricing names GA ids.\n")
    else:
        model = picked[0]
    print(f"\nusing: {model}\n")

    index = [embed(key, model, row["passage_en"]) for row in corpus]
    print(f"indexed {len(index)} English passages, width {len(index[0])}\n")

    out: dict = {"model": model, "dimensions": len(index[0]), "n": len(corpus), "forms": {}}
    print(f"{'query form':<16} {'recall@1':>9} {'recall@3':>9} {'MRR':>7}")
    print("-" * 45)
    for form in ("query_en", "query_te", "query_tenglish"):
        hits1 = hits3 = 0
        rr = 0.0
        for i, row in enumerate(corpus):
            q = embed(key, model, row[form])
            ranked = sorted(range(len(index)), key=lambda j: cosine(q, index[j]), reverse=True)
            rank = ranked.index(i) + 1
            hits1 += rank == 1
            hits3 += rank <= 3
            rr += 1.0 / rank
        n = len(corpus)
        out["forms"][form] = {
            "recall_at_1": round(hits1 / n, 4),
            "recall_at_3": round(hits3 / n, 4),
            "mrr": round(rr / n, 4),
        }
        print(f"{form:<16} {hits1 / n:>9.3f} {hits3 / n:>9.3f} {rr / n:>7.3f}")

    result_path = RESULT_PATH_TEMPLATE.format(model=model.rsplit("/", 1)[-1])
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"\nRESULT JSON ({result_path}):\n")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print("\nlexical baselines already measured here: Tenglish->English 0.625, bge-base-en 0.667")
    print(
        "decision: >=0.75 move retrieval to Gemini | 0.60-0.75 keep the English gloss"
        " | <0.60 do not pay"
    )


if __name__ == "__main__":
    main()
