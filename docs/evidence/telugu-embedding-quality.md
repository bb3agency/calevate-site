# Is Telugu retrieval good enough? — the embedding half of the D-28 gate

**Lane: knowledge-base retrieval, model side. Written 31 August 2026 (UTC).** Commission:
answer the question that blocks the KB decision — *is Telugu retrieval good enough?* — and
say plainly which findings are about the STORE and which are about the MODEL.
`docs/evidence/kb-retrieval-bakeoff.md` measured the store and reported **no recall figure
by construction** (its vectors were random). This file is the other half.

**This lane decided nothing and adopted nothing.** It wrote this file and one throwaway
harness (`scripts/spike/telugu_embedding_eval.py`). No vendor account, no credential, no
migration, no embedding path in `apps/`, no decision row (§9 proposes the text). Nothing
under `apps/` or `packages/` was touched, `bolna-findings/mirror/` was not read or moved,
and the shared Postgres/Redis were not touched at all — the measurement needs neither.

---

## Evidence-class legend

| Class | Means |
|---|---|
| **MEASURED-HERE** | produced by running something on this machine this session; method and rerun command given |
| **VERIFIED-SDK** | the vendor's own published package/source, downloaded and read this session; package, version and file:line cited |
| **VERIFIED-FIRST-PARTY-DOCS** | the vendor's own documentation source, fetched and read this session at a named URL |
| **REPORTED** | a third-party summary or a search engine's synthesis. Corroborates; never satisfies a wire value, a price, or a client-facing claim |
| **UNKNOWN** | not verifiable from here. Names what a human must close it with |

Per hard rule 11 a repo-internal value is a CLAIM, not evidence. Where this file quotes
one it says so.

---

## 0. Headline — six findings, in the order that changes the decision

**1. The decision decomposes, and the second half of the brief's premise is CONFIRMED.**
Pinecone accepts caller-supplied vectors — not as a legacy corner but as the primary path,
with integrated inference the *alternative*. Their own SDK says so in the docstring of
`Index.query`: *"Use this method for indexes where you provide your own vectors. For
indexes with integrated inference (`IntegratedSpec`), use `search()` which handles
embedding server-side."* (**VERIFIED-SDK**: `pinecone` 9.1.0 wheel from PyPI, downloaded
and unpacked this session, `pinecone/index/__init__.py:577-580`; `upsert` takes
`vectors: Sequence[Vector | tuple[str, Sequence[float]] | ...]`, `:172-186`.) So **the
store choice and the embedding-model choice are independent decisions**, and a weak
default model does not disqualify the store. Everything below is about the MODEL unless it
says otherwise.

**2. Telugu is not the failure mode. TENGLISH is** — and Tenglish is what the product
actually receives. MEASURED-HERE on the best model this container can run
(`multilingual-e5-large`), dense retrieval over a Telugu-script corpus: Telugu-script
questions **recall@1 0.583 / recall@3 0.833**, and the *same* questions written in
romanized Tenglish **0.250 / 0.417** (n=24, §2). The English control on the identical
facts is **0.958 / 1.000**. The gap between "our product's language" and "the language
everything is benchmarked in" is roughly a third of the query set, and the gap between
Telugu script and Tenglish is another third on top.

**3. The English-centric controls are not merely worse in Telugu, they are ZERO** —
`all-MiniLM-L6-v2` and `bge-base-en-v1.5` both score **recall@1 0.000, recall@3 0.000,
MRR 0.000** on Telugu script (§2.3). A default English model is not a degraded Telugu
model; it is a coin flip with 36 sides. But note the reverse: on Tenglish over an English
corpus, `bge-base-en-v1.5` scores **0.667/0.750** — BETTER than multilingual-e5-large's
**0.500/0.583** — because Tenglish is Latin script studded with English nouns
("appointment", "booking", "2BHK"), which is closer to an English model's home ground than
to a Telugu-script model's. **"Multilingual" is not automatically the right pick for
Tenglish**, and this is the finding most likely to be got wrong by intuition.

**4. A mitigation was measured and it works: store an English gloss and fuse a lexical
arm.** With every fact stored in BOTH languages and dense+BM25 fused with RRF, the
worst cell in the table — Tenglish questions — goes from **0.250/0.417** (Telugu corpus,
dense only) to **0.750/0.917** (both corpora, hybrid), and Telugu-script questions go to
**0.750/0.875** (§4). ⚠ And the same experiment produced a trap: **unconditional RRF can
make things WORSE** — Telugu corpus, English question, dense 0.708 → hybrid **0.375**,
because fusing a ranking from an arm that cannot match a single token drags the good arm
down. A hybrid must gate its lexical arm, not always run it.

**5. `llama-text-embed-v2` — Pinecone's integrated-inference default — has no Telugu claim
and no Telugu number, and it could not be measured here.** Its published evaluation list
is **26 languages: English, Arabic, Bengali, Chinese, Czech, Danish, Dutch, Finnish,
French, German, Hebrew, Hindi, Hungarian, Indonesian, Italian, Japanese, Korean,
Norwegian, Persian, Polish, Portuguese, Russian, Spanish, Swedish, Thai, Turkish** — no
Telugu, and no Dravidian language at all (**REPORTED**, §5.1: `docs.pinecone.io`,
`www.pinecone.io`, `build.nvidia.com`, `docs.api.nvidia.com` and `ai.azure.com` are ALL
egress-blocked from this container, both to `curl` and to the fetch tool, so this list
comes from a search-engine synthesis and NOT from a page anyone here read). **UNKNOWN —
must be closed by a human opening the model card.** Until then, choosing Pinecone's
integrated inference for a Telugu-first product is choosing a model with no evidence in
our language.

**6. Sarvam is NOT an embedding option today.** Their official SDK `sarvamai` 0.1.31 (PyPI,
downloaded and read this session) exposes speech-to-text, TTS, translation, document AI,
chat and an open-source-models chat surface — and **the string "embed" does not occur
anywhere in the package** (**VERIFIED-SDK**, §5.6). ⚠ An SDK's silence is not an API's
silence, and `docs.sarvam.ai` is egress-blocked, so the API-level statement is **UNKNOWN**.
But nothing installable today gives us an Indian-vendor embedding leg.

**Where that points (§8):** the store decision is unblocked and does not depend on this
lane at all. The MODEL decision is: not the integrated default; a multilingual model with
a Telugu claim; an English gloss written at ingestion, which we can already produce on the
existing Azure leg; and a gated hybrid. Telugu retrieval is **usable, not good** — and
Tenglish retrieval without mitigation is **not usable**.

---

## 1. Reachability — what could and could not be reached, measured first

**MEASURED-HERE, 31 August 2026**, `curl` through the session's egress proxy (403 on
CONNECT = organization policy denial; the proxy README says report these, do not route
around them — so no mirror or proxy workaround was used for any of them):

| Host | Result | Consequence |
|---|---|---|
| `huggingface.co`, `hf.co`, `cdn-lfs.hf.co` | **403 CONNECT** | no model card, no leaderboard, no weights by the normal route |
| `docs.pinecone.io`, `www.pinecone.io`, `api.pinecone.io` | **403 CONNECT** | no Pinecone docs, no Pinecone API |
| `build.nvidia.com`, `docs.nvidia.com`, `developer.nvidia.com`, `docs.api.nvidia.com` | **403 CONNECT** | no `llama-text-embed-v2` model card |
| `ai.google.dev`, `openai.com`, `platform.openai.com`, `cohere.com`, `docs.cohere.com` | **403 CONNECT** | no first-party embedding docs by fetch |
| `www.sarvam.ai`, `docs.sarvam.ai`, `api.sarvam.ai` | **403 CONNECT** | consistent with CLAUDE.md's standing note |
| `arxiv.org`, `aclanthology.org`, `kaggle.com`, `dl.fbaipublicfiles.com`, `ai4bharat.iitm.ac.in`, `objectstore.e2enetworks.net` | **403 CONNECT** | no papers, no AI4Bharat/IndicNLP vectors |
| `storage.googleapis.com/tfhub-modules/...` | reachable host, **AccessDenied** on the object | LaBSE/USE not obtainable |
| `pypi.org`, `files.pythonhosted.org` | **200** (direct, in the proxy's `noProxy` list) | **vendor SDKs are readable** — this is where most of §5's evidence comes from |
| `raw.githubusercontent.com`, `api.github.com`, `codeload.github.com` | **200** | first-party doc SOURCES that live in git are readable |
| `storage.googleapis.com/qdrant-fastembed/...` | **200** | **model weights are obtainable** — this is the only reason §2 exists |

**The one that unlocked the measurement.** `fastembed` 0.2.7 (Qdrant's embedding package)
publishes an ONNX copy of several models to a public GCS bucket and falls back to it when
HuggingFace fails. Three models are served from there and were downloaded and run:
`intfloat/multilingual-e5-large` (2.1GB on disk), `sentence-transformers/all-MiniLM-L6-v2`
(88MB), `BAAI/bge-base-en-v1.5` (219MB). Everything else in fastembed's registry is
HuggingFace-only and is therefore **UNMEASURABLE from this container** — including
`paraphrase-multilingual-MiniLM-L12-v2`, and including every model in §5 that is not in
that list.

**What was installed, and where.** `fastembed==0.2.7` and its dependency closure
(`onnxruntime` 1.29.0, `tokenizers`, `numpy`, `onnx`, `huggingface-hub`) into a throwaway
venv at **`/var/tmp/telugu-embed/venv`** — outside the repo, on Python 3.11. **Nothing was
added to `pyproject.toml`, `uv.lock` or the project venv**, and the harness refuses with a
message rather than importing anything if run under the project interpreter. Model weights
live at `/var/tmp/telugu-embed/models` (2.4GB). Both directories are disposable.

---

## 2. THE MEASUREMENT — Telugu and Tenglish retrieval, on this machine

### 2.1 Method, so it can be rerun

```
python3 -m venv /var/tmp/telugu-embed/venv
/var/tmp/telugu-embed/venv/bin/pip install "fastembed==0.2.7"
/var/tmp/telugu-embed/venv/bin/python scripts/spike/telugu_embedding_eval.py \
    --model intfloat/multilingual-e5-large \
    --model sentence-transformers/all-MiniLM-L6-v2 \
    --model BAAI/bge-base-en-v1.5 \
    --method dense --method lexical --method hybrid \
    --corpus-lang te --corpus-lang en --corpus-lang both \
    --cache-dir /var/tmp/telugu-embed/models \
    --json /var/tmp/telugu-embed/results.json
```

* **Task.** 24 knowledge-base facts for the two verticals this repo actually seeds
  (`scripts/seed.py::VERTICAL_TEMPLATES` — clinic and real_estate): a Kukatpally clinic
  and a Kondapur flat project. Each fact is written as a passage TWICE, once in Telugu
  script and once in English, and asked THREE ways — Telugu script, Tenglish, English.
* **Tenglish spelling** follows `tests/fixtures/golden_transcripts.json` — Telugu grammar
  with English nouns, no diacritics ("Appointment ela book cheskovali?"), which that
  fixture's own header says is the form Sarvam Saaras returns, and which
  `apps/api/copilot/prompt.py:226` calls "normal and fine".
* **Distractors.** 12 further passages from the same two businesses with no question of
  their own, so the right answer must be picked out of near neighbours. Corpus = **36**
  passages (72 in the `both` condition).
* **Metric.** recall@1, recall@3, MRR@10 over the whole corpus, cosine similarity, exact
  search (no ANN index — this is a quality measurement, not a latency one).
* **Prefixes are applied per model's training contract** — `query: `/`passage: ` for e5,
  the English instruction prefix for bge. Omitting them would measure the model being used
  wrongly rather than the model.
* **Deterministic.** No sampling, no randomness; rerunning gives the same numbers.
* Machine: 4 cores, load average 0.24 at the time of the run; no sibling pytest was
  running. Speed is irrelevant to these figures anyway.

### 2.2 What this measurement is NOT

* **Not production recall.** 36 passages is a small corpus and every absolute figure here
  is therefore an **upper bound**; a real client KB is hundreds of chunks and every model
  will score lower. **The comparisons transfer; the absolute numbers do not.**
* **n=24 per cell.** One or two queries either way is noise. A third of the set is not.
  Every figure below should be quoted with its n.
* **The Telugu was written by this lane, not by a native-speaking client.** It is
  natural-register Telugu of the kind an SMB leaflet contains, but it is one author's
  Telugu and one author's idea of how a caller asks. **A pilot with real recordings would
  be a better instrument, and this does not replace one.** One internal check says the
  corpus is at least self-consistent: BM25 over the Telugu corpus with Telugu questions
  scores 0.625 recall@1, so the Telugu text and the Telugu questions share the vocabulary
  a human would expect — the dense models' failures are the models, not gibberish input.
* **No hosted model was measured.** Pinecone, OpenAI, Cohere, Google and Sarvam are all
  egress-blocked and none of them was called. No number in this file is estimated for
  them.

### 2.3 Results — dense retrieval, the models on their own

**MEASURED-HERE, 31 August 2026.** n=24 per row. `corpus` is the language the knowledge
base is written in; `query` is the language the caller asks in.

| model | corpus | query | recall@1 | recall@3 | MRR@10 |
|---|---|---|---|---|---|
| **multilingual-e5-large** | te | **te** | **0.583** | **0.833** | 0.721 |
| | te | **tenglish** | **0.250** | **0.417** | 0.386 |
| | te | en | 0.708 | 0.875 | 0.812 |
| | en | **te** | **0.625** | **0.833** | 0.739 |
| | en | **tenglish** | **0.500** | **0.583** | 0.601 |
| | en | en *(control)* | **0.958** | **1.000** | 0.979 |
| **all-MiniLM-L6-v2** (English-centric control) | te | te | **0.000** | **0.000** | 0.000 |
| | te | tenglish | 0.042 | 0.083 | 0.098 |
| | en | te | 0.042 | 0.083 | 0.087 |
| | en | tenglish | 0.417 | 0.708 | 0.575 |
| | en | en | 0.667 | 0.875 | 0.774 |
| **bge-base-en-v1.5** (English-centric control) | te | te | **0.000** | **0.000** | 0.000 |
| | te | tenglish | 0.000 | 0.125 | 0.083 |
| | en | te | 0.000 | 0.042 | 0.049 |
| | en | **tenglish** | **0.667** | **0.750** | 0.749 |
| | en | en | 0.958 | 0.958 | 0.969 |

**Read the four things this says, in order.**

**(a) A multilingual model genuinely does cross-lingual Telugu.** English corpus, Telugu
question — the shape most SMBs will actually have, because the source material is a
website in English — gives e5 **0.625/0.833**, statistically indistinguishable here from
the monolingual Telugu cell. Whatever else is true, an English knowledge base is not a
barrier to a Telugu question. That is a real capability and it is worth saying plainly.

**(b) Telugu costs about a third of the answers against the English control.** Same model,
same facts, same 36-way choice: 0.958 in English, 0.583–0.625 in Telugu. Anybody who has
seen an embedding demo in English and expects that experience in Telugu will be
disappointed, and by roughly that much.

**(c) Tenglish is the floor, and it is below the level where a phone agent could use it
unaided.** 0.250 recall@1 with a Telugu corpus means the top hit is wrong three times in
four. Even top-3 is 0.417. **This is the single most consequential number in the file**,
because Tenglish is not an edge case here — it is what the STT returns.

**(d) English-centric models are unusable on Telugu script and surprisingly good on
Tenglish.** Zeros on script; `bge-base-en-v1.5` at 0.667/0.750 on Tenglish over an English
corpus, beating the multilingual model. Tenglish is Latin-script text full of English
domain nouns, and an English tokenizer handles it better than a Telugu-script-oriented
representation does. **Do not assume "multilingual" wins every cell** — on this evidence
it does not.

### 2.4 Where the multilingual model actually fails

The harness prints every miss (`--show-misses`). The Telugu-script failures are
*topically adjacent*, not random: "can I bring someone at midnight with chest pain?"
retrieves the paediatrics passage rather than the no-ICU/no-ambulance passage;
"is Aarogyasri accepted?" retrieves the medical-certificate passage rather than the
insurance one. That is the classic embedding failure — the model has the domain but not
the distinction — and it is the failure a **reranker** is built for (§7).

The Tenglish failures are different in kind: the retrieved passage is often from the
*wrong business entirely* (a clinic question retrieving the villa-project distractor).
That is a representation failure, not a ranking failure, and a reranker cannot fix what
the retriever never surfaced.

---

## 3. What this says about the STORE (very little — deliberately)

**Nothing measured here is a property of any vector database.** All three models were run
with exact cosine search in process; no index was involved. The store questions —
latency, index behaviour, multi-tenancy — were measured by the sibling
(`docs/evidence/kb-retrieval-bakeoff.md`) and are unaffected by anything in this file.

The one store-shaped finding is §0.1: **Pinecone accepts caller-supplied vectors**
(VERIFIED-SDK, `pinecone` 9.1.0, `pinecone/index/__init__.py:172-186` for `upsert`,
`:577-580` for `query`, plus a separate `upsert_records`/`search_records` pair at `:468`
and `:1217` which is the integrated-inference path). Therefore:

* Choosing Pinecone does **not** commit us to `llama-text-embed-v2`.
* Choosing an embedding model does **not** commit us to any store — the same vectors go
  into `kb_chunks`' `vector(1024)` column (`docs/DATA-MODEL.md:348-352`, a repo-internal
  CLAIM cited as such) exactly as they go into a Pinecone namespace.
* So the two decisions can be taken separately and in either order. **The Telugu question
  is not blocking the store decision, and this lane's answer must not be read as if it
  were.**

⚠ One thing this does NOT establish: what dimensionality, metric or index type Pinecone
requires for caller-supplied vectors, or what it costs. Those are in `docs.pinecone.io`,
which is egress-blocked. **UNKNOWN — a human with the docs open, or an account, closes it.**

---

## 4. Mitigations, MEASURED rather than asserted

Same harness, same 24 questions. `lexical` is BM25 (k1=1.5, b=0.75) implemented in the
harness; `hybrid` is RRF (k=60) over dense+lexical, the same fusion the sibling's Postgres
query used. `both` stores every fact in Telugu **and** English (72 passages) and counts a
hit if either copy ranks — the **English-gloss mitigation**.

| corpus | query | dense (e5) | lexical (BM25) | **hybrid RRF** |
|---|---|---|---|---|
| te | te | 0.583 / 0.833 | 0.625 / 0.792 | **0.708 / 0.917** |
| te | **tenglish** | 0.250 / 0.417 | 0.042 / 0.125 | 0.292 / 0.500 |
| te | en | 0.708 / 0.875 | 0.042 / 0.125 | ⚠ **0.375** / 0.750 |
| en | te | 0.625 / 0.833 | 0.042 / 0.125 | ⚠ **0.292** / 0.833 |
| en | tenglish | 0.500 / 0.583 | 0.625 / 0.667 | **0.667 / 0.833** |
| en | en | 0.958 / 1.000 | 0.750 / 0.958 | **1.000 / 1.000** |
| **both** | te | 0.708 / 0.875 | 0.625 / 0.792 | **0.750 / 0.875** |
| **both** | **tenglish** | 0.542 / 0.667 | 0.625 / 0.667 | **0.750 / 0.917** |
| **both** | en | 0.917 / 1.000 | 0.792 / 0.958 | **1.000 / 1.000** |

*(recall@1 / recall@3, n=24, multilingual-e5-large for every dense and hybrid cell.)*

**(a) The gloss + hybrid combination is the answer to the Tenglish problem.** The worst
cell in §2.3 — Telugu corpus, Tenglish query, **0.250/0.417** — becomes **0.750/0.917**
when the fact is also stored in English and a lexical arm is fused. That is the difference
between "unusable" and "usable with a reranker on top", and it is bought with ingestion
work, not with a better model.

**(b) ⚠ RRF is not free and can HURT. Two cells got worse.** Telugu corpus + English query
falls 0.708 → 0.375; English corpus + Telugu query falls 0.625 → 0.292. Both are the
cross-script cells where BM25 matches essentially nothing, and RRF still averages its
(arbitrary) ranking into the result. **A hybrid must gate the lexical arm** — run it only
when the query shares a script/vocabulary with the corpus, or weight the arms rather than
fusing them equally. An unconditional `dense + sparse` hybrid, which is what the sibling's
Postgres query does and what most tutorials show, would have silently cost us recall on
exactly the cross-lingual cell this product lives in.

**(c) BM25 on Telugu is surprisingly strong, and that figure is optimistic.** 0.625/0.792
on Telugu script. Two caveats, both material: a caller's question naturally reuses the
passage's key nouns ("ఆరోగ్యశ్రీ", "ఆదివారం"), which flatters any lexical method; and
this BM25 tokenizes on word boundaries with **no stemming**, while Telugu is agglutinative
and inflects heavily — Postgres's `ts_rank_cd` has **no Telugu dictionary at all**, so a
real Postgres sparse arm would do *worse* than this, not better. Read §4's lexical column
as a ceiling.

**(d) The gloss costs exactly what it looks like it costs.** The corpus doubles: twice the
rows, twice the vectors, twice the embedding calls at ingestion, twice the storage. On the
sibling's measured figures for the pgvector contingency (a repo-internal CLAIM, cited as
such: ~1.6GB per 100k chunks) that is a capacity number, not a blocker. The *translation*
is one LLM call per chunk at ingestion time on the Azure leg we already have —
**no per-call in-call cost**, and it happens behind the existing human approval gate, so
a mistranslation is reviewable before publication rather than discovered on a phone call.

---

## 5. The model-by-model picture, with evidence classes

**Read the class before the claim.** Only §5.2 and §5.3 carry a number produced here;
everything else is a *language-coverage claim*, which is much weaker than a *Telugu
retrieval score*, and in most cases nobody publishes the latter at all.

### 5.1 `llama-text-embed-v2` (NVIDIA, via Pinecone integrated inference)
**Telugu: no claim found. Quality in Telugu: UNKNOWN.**
Published as evaluated on 26 languages, which include Hindi and Bengali (Indo-Aryan) and
**exclude Telugu and every other Dravidian language** — **REPORTED** (search-engine
synthesis, 31 Aug 2026; `docs.pinecone.io/models/llama-text-embed-v2` and
`build.nvidia.com/.../llama-3_2-nv-embedqa-1b-v2/modelcard` are both egress-blocked here,
and one of the two search syntheses returned a self-contradictory answer about Telugu,
which is exactly why this is not being upgraded to a fact). Built on Llama 3.2 1B, 8192
tokens, Matryoshka dimensions — same class, **REPORTED**.
**What would close it:** a human opening either model card and reading the language list.
**Consequence if it holds:** the default model of the store most likely to be chosen has
no published evidence in the product's primary language.

### 5.2 `multilingual-e5-large` (Microsoft) — **the one model measured here**
**MEASURED-HERE, §2.3/§4.** Telugu script 0.583/0.833; Tenglish 0.250/0.417; cross-lingual
(English corpus, Telugu query) 0.625/0.833; with gloss + hybrid, 0.750/0.917.
Coverage claim: 100 languages, XLM-RoBERTa-large base, 560M params, 1024-d — **REPORTED**
(search synthesis; `huggingface.co` blocked). `microsoft/unilm`'s own `e5/README.md`
(**VERIFIED-FIRST-PARTY-DOCS**, fetched from `raw.githubusercontent.com` 31 Aug 2026) lists
the four multilingual variants but names **no languages and no training sets**, so the
language count does not have a first-party source from here.
XLM-R's pretraining corpus includes Telugu, which is why the Telugu numbers are non-zero
at all — **REPORTED**.

### 5.3 `all-MiniLM-L6-v2` and `bge-base-en-v1.5` — **English controls, measured here**
**MEASURED-HERE, §2.3.** Zero on Telugu script, both models, every corpus. Non-trivial on
Tenglish over an English corpus (bge 0.667/0.750). They are in this file only as controls;
neither is a candidate.

### 5.4 BGE-M3 (BAAI)
**Not measured — HuggingFace-only, egress-blocked.**
*"Multi-Linguality (100+ languages)"* and *"Multi-Functionality (unification of dense,
lexical, multi-vec/colbert retrieval)"* — **VERIFIED-FIRST-PARTY-DOCS**
(`raw.githubusercontent.com/FlagOpen/FlagEmbedding/master/README.md`, read 31 Aug 2026).
**No Indian language is named anywhere in that README**, so "100+" is not a Telugu claim.
Interesting for one structural reason: it produces dense AND learned-sparse vectors from
one pass, which is the mitigation in §4 without a second system — but on the same evidence
we have no idea how its sparse arm behaves on agglutinative Telugu. **UNKNOWN.**

### 5.5 Cohere `embed-multilingual` / Embed v4
**Not measured — no credential, `cohere.com` blocked.**
**Telugu is explicitly in the supported-language list**, alongside Tamil, Kannada and
Malayalam, in a 101-language table — **VERIFIED-FIRST-PARTY-DOCS**, read this session from
Cohere's own documentation source repository
(`raw.githubusercontent.com/cohere-ai/cohere-developer-experience/main/fern/pages/text-embeddings/multilingual-language-models/supported-languages.mdx`),
which also says *"performance may vary across languages."* This is the strongest
*first-party* Telugu claim any candidate has. It is still a support claim, not a score.

### 5.6 Sarvam — **there is no embedding model to consider**
**VERIFIED-SDK.** `sarvamai` 0.1.31 (PyPI, downloaded and unpacked this session) exposes
`speech_to_text`, `speech_to_text_translate_job`, `text_to_speech`, `text`, `chat`,
`doc_ai`, `document_translation`, `dubbing`, `pronunciation_dictionary`, `play` and
`open_source_models` (chat completions + model list). A case-insensitive grep for `embed`
across the whole package returns **nothing**. So there is no Indian-vendor embedding leg
available through the client we would actually use. ⚠ **UNKNOWN at the API level** —
`docs.sarvam.ai` is egress-blocked (unchanged from CLAUDE.md's standing note), and an SDK
can lag an API. **What would close it:** the founder reading Sarvam's API reference index.
Worth closing, because a Telugu-first embedding model from an Indian vendor would be a
materially different option from everything in this table, and because we already hold
their credential for speech.

### 5.7 OpenAI `text-embedding-3-large`
**Not measured.** OpenAI publishes **no language list**; what they published is a MIRACL
average (ada-002 31.4 → 3-large 54.9) — **REPORTED** (search synthesis; `openai.com`
blocked). MIRACL's 18 languages **do** include Telugu (**VERIFIED-SDK**, §6), so a Telugu
number exists inside that average — but an 18-language average is not a Telugu score, and
the per-language table is not readable from here. **UNKNOWN in Telugu.**

### 5.8 Google `gemini-embedding-001`
**Not measured.** 100+ languages including **Telugu** (Kannada, Malayalam, Tamil also
listed) — **REPORTED** (search synthesis of `ai.google.dev/gemini-api/docs/embeddings`,
which is egress-blocked). Note the posture angle: `google` is already a declared leg of
`multi-provider-byok` and the founder already holds the key, so this is the candidate with
the least new procurement — but per D-456's own reasoning the Google Developer API has no
region to request, which is a compliance question for a KB leg exactly as it was for the
language leg. **Not this lane's call; flagged so it is not discovered later.**

### 5.9 LaBSE
**Not measured and not obtainable** — TF Hub's objects are `AccessDenied` to anonymous
callers and HuggingFace is blocked (§1). Its 109-language claim is **REPORTED** and could
not be checked against any first-party page from here. It is a bitext/translation-mining
model rather than a QA-retrieval model, which makes it a poor fit for this task anyway.

### 5.10 Indic-specific models (IndicSBERT/MuRIL family)
**REPORTED** (search, 31 Aug 2026): L3Cube's IndicSBERT (MuRIL-based) and the recent
IndicHeadline-ID benchmarking cover ten Indian languages including Telugu, and report
multilingual-e5 performing strongly against Indic-specific models. Nothing here was
verified at a primary source and nothing was measured. Worth naming only because it means
the field of candidates is wider than the five commercial APIs, at the cost of running our
own inference — which D-28 pushes against.

---

## 6. Does the benchmark even include Telugu? Yes — thinly, and never alone

**VERIFIED-SDK**, `mteb` 2.20.5 (PyPI, downloaded and read this session).

* **25 task modules carry `tel-Telu`**, including the retrieval tasks `MIRACLRetrieval`
  (`retrieval/multilingual/miracl_retrieval.py:21`), `MrTidyRetrieval`
  (`mr_tidy_retrieval.py:15`), `IndicQARetrieval` (`indic_qa_retrieval.py:15`),
  `BelebeleRetrieval` (`belebele_retrieval.py:110`), plus FLEURS/CommonVoice/SVQ and a
  Telugu-only classification task.
* **`MTEB(Indic, v1)` exists** and includes `tel` in its language filter — but its whole
  retrieval component is **two tasks**: `BelebeleRetrieval` and `XQuADRetrieval`
  (`mteb/benchmarks/benchmarks/benchmarks.py:1286-1331`).
* **There is no Telugu-only benchmark.** The named single-language suites are
  `eng, rus, fra, deu, kor, pol, por, slk, spa, jpn, cmn, fas, nld, tha` — Indic languages
  are pooled into one regional benchmark (same file, `name="MTEB(...)"` entries).

**The consequence for how you read any leaderboard number:** a strong `MTEB(Multilingual)`
or `MTEB(Indic)` score is an average over dozens of languages in which Telugu is one
thinly-covered member. **It is not evidence about Telugu**, and treating it as such is the
exact laundering hard rule 11 forbids. The only per-language Telugu retrieval evidence
that exists at all is inside MIRACL-te / Mr.TyDi-te / IndicQA-te, and reading those numbers
per model needs the leaderboard, which is on `huggingface.co` — **UNKNOWN from here**.

---

## 7. Mitigations not measured, with their honest cost

| Mitigation | What it buys | Cost | Status |
|---|---|---|---|
| **English gloss + gated hybrid** | Tenglish 0.250→0.750 recall@1 (§4) | 2× rows/vectors/storage; one LLM call per chunk at ingest on the existing Azure leg; gloss reviewed at the existing approval gate | **MEASURED-HERE** |
| **Query normalisation** (transliterate or LLM-rewrite the Tenglish question into Telugu script and/or English before embedding) | attacks the same failure at the query end instead of the corpus end | **an extra model call inside the in-call budget** — and the sibling already found the budget overdrawn by 100ms with zero retrieval in it | **UNMEASURED.** Do not adopt on the in-call path without measuring; it is cheap on the dashboard path where seconds are fine |
| **Reranker over top-20** | fixes §2.4's *adjacent-passage* failures, which are most of the Telugu-script misses | a second network call; most rerankers have the same Telugu evidence gap as the embedders | **UNMEASURED**, and inherits §5's UNKNOWNs |
| **Keep in-call on T0** | 0ms, no embedding call, no Telugu retrieval risk at all | the KB does not answer in-call questions | already the shipped position (`docs/TRD.md:948` — repo-internal CLAIM) |

---

## 8. Recommendation to the founder

**The honest answer to "is Telugu retrieval good enough?" is: good enough for the
dashboard, not good enough for a phone call unaided, and the reason is Tenglish rather
than Telugu.**

1. **Take the store decision on store grounds; it is not blocked by this.** Pinecone
   accepts our own vectors (VERIFIED-SDK), so the model can be changed later without
   moving the store, and the store can be chosen without betting on a model.
2. **Do not adopt Pinecone's integrated inference for Telugu content.** Its default model
   has no Telugu in its published evaluation list (REPORTED) and no Telugu score anywhere
   we can read. Using it would mean shipping the product's primary language on zero
   evidence. If integrated inference is wanted for operational simplicity, the thing to do
   first is read the model card — it is one page a human can open.
3. **Shortlist on Telugu evidence, in this order:** Cohere multilingual (only candidate
   with a *first-party* Telugu listing, §5.5); Gemini embedding (Telugu listed, REPORTED,
   and the key is already held — but the same no-region property D-456 recorded applies);
   `multilingual-e5-large` (the only one with a measured Telugu number, and it is ours to
   run anywhere). **Whichever is chosen, run this harness against it before adopting** —
   it takes minutes and the shape of the answer is already known.
4. **Design the retrieval for Tenglish from the start, not as a later fix.** Store an
   English gloss beside every approved Telugu chunk, and fuse a lexical arm **gated** by
   script overlap (§4b — an ungated RRF measurably makes cross-script queries worse). That
   is a design decision to take now, because it changes the ingestion pipeline and the
   `kb_chunks` shape, and retrofitting it means re-ingesting every client's KB.
5. **Leave in-call retrieval on T0.** Nothing here changes the sibling's finding that the
   voice budget is already overdrawn, and every mitigation above adds a call.

**What would change this recommendation:**
* a Telugu number for `llama-text-embed-v2` from its model card (could make integrated
  inference viable, and would collapse the whole model decision into the store decision);
* Sarvam publishing an embedding endpoint (§5.6) — an Indian-vendor Telugu embedding model
  with a credential we already hold would outrank everything in §5 on both quality
  plausibility and residency, and it is one page of their API reference away from being
  known;
* a pilot with **real** Saaras output instead of this lane's written Tenglish (the single
  biggest weakness in §2 — real STT output has recognition errors this corpus does not);
* a per-language MIRACL-te / IndicQA-te table for the candidates, which exists on the MTEB
  leaderboard and is unreadable from this container.

---

## 9. Proposed decision row (NOT added to `docs/ROADMAP.md` — text only)

> **D-4xx (31 Aug 2026) — Telugu KB retrieval: the store and the embedding model are
> separate decisions, and the model is chosen on Telugu evidence.** Pinecone accepts
> caller-supplied vectors (VERIFIED-SDK: `pinecone` 9.1.0,
> `pinecone/index/__init__.py:577-580`), so D-28's managed-store choice does not select an
> embedding model. **Pinecone's integrated-inference default `llama-text-embed-v2` is NOT
> adopted for Telugu content**: its published evaluation list names 26 languages and no
> Dravidian language (REPORTED — vendor hosts egress-blocked; a human must confirm at the
> model card). Measured on this repo's own verticals (`scripts/spike/telugu_embedding_eval.py`,
> `docs/evidence/telugu-embedding-quality.md`, n=24), `multilingual-e5-large` scores
> recall@1 0.583 on Telugu script, 0.625 cross-lingual, and **0.250 on Tenglish** against
> 0.958 in English — so **Tenglish, not Telugu script, is the binding constraint**, and
> Tenglish is what Saaras returns. Consequently: KB chunks carry an **English gloss**
> written at ingestion behind the existing approval gate, and retrieval fuses a lexical arm
> **gated on script overlap** (an ungated RRF measurably lowers cross-script recall,
> 0.708→0.375). Together these move Tenglish recall@1 to 0.750 / recall@3 0.917. In-call
> retrieval stays T0. No vendor adopted; no embedding path built. Closed by: a Telugu
> figure for any candidate model read from its vendor's own page, and a pilot against real
> Saaras transcripts.
