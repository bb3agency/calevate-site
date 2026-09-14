#!/usr/bin/env python3
"""Measure Gemini embedding quality on the Telugu corpus. Standard library only.

WHY IT DISCOVERS THE MODEL INSTEAD OF NAMING ONE: a model id recalled from memory is
exactly the class of claim that has been wrong in this project before. The script asks
the live API which models support embedding, prints them, and uses one of those.

RUN:
    export GOOGLE_API_KEY='paste-your-key-here'
    python3 telugu_gemini_harness.py /path/to/tests/fixtures/telugu_gloss_corpus.json

On the VPS the corpus is at /var/www/calevate/tests/fixtures/telugu_gloss_corpus.json
"""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"


def _post(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:600]
        raise SystemExit(f"\nHTTP {e.code} from {url.split('?')[0]}\n{detail}\n") from e


def _get(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:600]
        raise SystemExit(f"\nHTTP {e.code} from {url.split('?')[0]}\n{detail}\n") from e


def discover_embedding_models(key: str) -> list[dict]:
    """Every model the account may call that supports embedding. Printed, never assumed."""
    out, token = [], ""
    while True:
        url = f"{BASE}/models?key={key}&pageSize=200" + (f"&pageToken={token}" if token else "")
        page = _get(url)
        for m in page.get("models", []):
            methods = m.get("supportedGenerationMethods", [])
            if any("mbed" in meth for meth in methods):
                out.append(m)
        token = page.get("nextPageToken", "")
        if not token:
            return out


def embed(key: str, model: str, text: str) -> list[float]:
    url = f"{BASE}/{model}:embedContent?key={key}"
    payload = {"model": model, "content": {"parts": [{"text": text}]}}
    data = _post(url, payload)
    return data["embedding"]["values"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def main() -> None:
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set GOOGLE_API_KEY first:  export GOOGLE_API_KEY='...'")
    path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/telugu_gloss_corpus.json"
    with open(path, encoding="utf-8") as fh:
        corpus = json.load(fh)
    print(f"corpus: {len(corpus)} facts from {path}\n")

    models = discover_embedding_models(key)
    if not models:
        raise SystemExit("No embedding-capable model is visible to this key.")
    print("EMBEDDING MODELS THIS KEY CAN SEE")
    for m in models:
        dims = m.get("outputDimensions") or m.get("outputTokenLimit") or "?"
        print(f"  {m['name']:<45} dims={dims}  in_limit={m.get('inputTokenLimit', '?')}")
    model = models[0]["name"]
    print(f"\nusing: {model}\n")

    # THE INDEX IS ENGLISH ONLY — that is the design being tested, not an accident.
    print(f"embedding {len(corpus)} English passages ...")
    index = [embed(key, model, row["passage_en"]) for row in corpus]

    forms = ("query_en", "query_te", "query_tenglish")
    print(f"embedding {len(corpus)} queries x {len(forms)} forms ...\n")

    print(f"{'query form':<16} {'recall@1':>9} {'recall@3':>9} {'MRR':>7}")
    print("-" * 45)
    results = {}
    for form in forms:
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
        results[form] = (hits1 / n, hits3 / n, rr / n)
        print(f"{form:<16} {hits1 / n:>9.3f} {hits3 / n:>9.3f} {rr / n:>7.3f}")

    print("\nCOMPARE AGAINST docs/evidence/telugu-embedding-quality.md")
    print("  word-matching, Tenglish query -> Telugu passages : 0.042")
    print("  word-matching, Tenglish query -> English passages: 0.625")
    print("  bge-base-en on Tenglish                          : 0.667")
    print("  multilingual-e5 on Tenglish                      : 0.500")
    print("\nThe number that decides the design is the Tenglish row above:")
    print("  >= 0.75  -> Gemini embeddings beat everything measured; use them for retrieval")
    print("  0.6-0.75 -> comparable to bge-base-en; keep the English-gloss design")
    print("  < 0.6    -> worse than a local encoder; do not pay for it")
