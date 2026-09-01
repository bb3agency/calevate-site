"""The operator's runbooks, searchable, with no retrieval vendor and no embeddings (D-499).

The founder's example question for the admin copilot was *"what do I do when
`engine_error_spike` fires"*, and the answer to it is already written down — in
`runbooks/`, twenty-two markdown files and about 5,700 lines that an operator today finds
by remembering which file it is in.

## WHY THIS IS NOT A VECTOR STORE, STATED FIRST BECAUSE IT IS THE CONSTRAINT

D-28 is OPEN. pgvector, Pinecone and Weaviate are all live options and the founder has
picked none, so adopting one here — for an internal convenience — would settle a platform
decision on the wrong surface. `copilot/memory.py` and `kb/models.py` both already refuse
an embedding column for the same reason, and `calevate_shared/config.py` records
`COHERE_API_KEY` being deleted because nothing read it.

So this is OUR OWN TEXT scored by OUR OWN RANKER: `retrieval/compiled_facts.tokens` and
`score_line`, the same lexical pass the T0 retrieval tier runs against a tenant's compiled
facts. Imported, never re-spelled — a second tokeniser would rank the same words
differently from the one the voice path uses, and the singularisation rule in particular is
argued at length there and would be re-derived wrongly here.

## THE UNIT IS A SECTION, NOT A LINE, AND THAT IS THE ONE DEPARTURE

`compiled_facts` scores LINES because a compiled fact IS a line. A runbook line ("2. Check
the poller lag") is useless out of its section; what answers an operator is the whole
procedure under one heading. So a file is split on its markdown headings and each section is
scored as one blob, then returned whole (up to a cap). The score is still `score_line` over
the section's text — share of the question's content words present — which is the same
normalisation and therefore comparable across sections.

The HEADING PATH is scored too and weighted, because "engine_error_spike" appears in the
alarm index's heading and in the body of the runbook it points at, and an operator asking
by alarm name wants both. `_HEADING_WEIGHT` is the whole of that thumb on the scale and it
is stated rather than tuned.

## LOADED ONCE, FROM DISK, AND THE DEPLOYMENT HALF IS FINISHED

`runbooks/` was NOT in the image — the Dockerfile copies `apps`, `packages`, `alembic` and
`scripts` and nothing else — so a tool reading it would have returned nothing in production
while working perfectly in every test. That is the half-wired shape CLAUDE.md names by hand,
so `Dockerfile` gains `COPY runbooks runbooks` in the same change. When the directory is
genuinely absent the index is EMPTY and the tool says so in those words; it never claims
there is no runbook for something it could not look at.

The index is built lazily on first use and cached for the process's life. The corpus is
~412 KB of text that changes only on deploy, so re-reading it per request would be pure
waste; a process that starts before an operator asks anything pays nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from apps.api.core.logging import get_logger
from apps.api.retrieval.compiled_facts import score_line, tokens

log = get_logger(__name__)

#: Where the runbooks live, relative to the repository/image root. Four parents up from
#: `apps/api/copilot/runbooks.py` is the root in both the checkout and the image (the
#: Dockerfile's WORKDIR is `/app` and it copies `apps` and `runbooks` as siblings).
RUNBOOK_DIR: Final = Path(__file__).resolve().parents[3] / "runbooks"

#: How much a match in the section's HEADING PATH counts for, on top of its body score.
#: An alarm code is a heading in `alarm-index.md` and a body word in the runbook it names,
#: and an operator typing the code wants the index row AND the procedure. 0.5 is enough to
#: lift a heading-only match above an incidental body mention and not enough to float a
#: section whose body says nothing.
_HEADING_WEIGHT: Final = 0.5

#: How many sections one search returns. Four, for `tools.MAX_PASSAGES`' reason: a tool
#: result stays in the message list for the rest of the request, so every passage is paid
#: for on every remaining turn.
MAX_SECTIONS: Final = 3

#: The longest one section may be in the result. A runbook procedure is the unit and a long
#: one is genuinely long, so this is well above `tools.MAX_PASSAGE_CHARS` — but it is a
#: ceiling, and a section that hits it is truncated visibly so the model can say "read the
#: file" rather than silently answering from half a procedure.
MAX_SECTION_CHARS: Final = 1_400

#: A markdown ATX heading. Setext headings (`===` underlines) are not used anywhere in
#: `runbooks/` — checked, not assumed — so this is the whole grammar.
_HEADING: Final = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

#: The floor a section must clear to be offered at all. A section sharing one content word
#: out of eight with the question is noise, and a model handed noise answers from it.
_MIN_SCORE: Final = 0.20


@dataclass(frozen=True, slots=True)
class RunbookSection:
    """One heading and the text under it, with the file it came from.

    `path` is the FILE NAME and never an absolute path: the model's answer reaches an
    operator's screen, and "runbooks/calls-stopped.md" is what they can open while
    "/app/runbooks/calls-stopped.md" is an internal detail (BACKEND-PATTERNS §3's rule
    about internals in user-visible text).
    """

    path: str
    heading: str
    body: str

    @property
    def title(self) -> str:
        return f"{self.path} — {self.heading}" if self.heading else self.path


def _split_sections(path: str, content: str) -> list[RunbookSection]:
    """One file into its headed sections, keeping the heading PATH rather than the heading.

    "Recovery > 3. Restart the poller" is what an operator needs to know they are reading;
    "3. Restart the poller" on its own is unplaceable. The path is maintained as a stack
    keyed by heading level, so a `###` under a `##` under a `#` renders all three.
    """
    sections: list[RunbookSection] = []
    stack: list[tuple[int, str]] = []
    heading = ""
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            sections.append(RunbookSection(path=path, heading=heading, body=text))

    for line in content.splitlines():
        match = _HEADING.match(line)
        if match is None:
            buffer.append(line)
            continue
        flush()
        buffer = []
        level, title = len(match.group(1)), match.group(2)
        stack = [entry for entry in stack if entry[0] < level]
        stack.append((level, title))
        heading = " > ".join(title for _, title in stack)
    flush()
    return sections


@lru_cache(maxsize=1)
def index() -> tuple[RunbookSection, ...]:
    """Every runbook section, read once per process.

    NEVER RAISES. A missing directory, an unreadable file or a decoding error yields an
    empty (or shorter) index and a log line — an operator asking the assistant a question
    must not get a 500 because the image was built without its documentation, and the
    caller says "I could not read them" rather than "there is nothing".
    """
    if not RUNBOOK_DIR.is_dir():
        log.warning("copilot_runbooks_missing", extra={"dir": str(RUNBOOK_DIR)})
        return ()
    sections: list[RunbookSection] = []
    for file in sorted(RUNBOOK_DIR.glob("*.md")):
        try:
            content = file.read_text(encoding="utf-8")
        except OSError:
            # The name, never the contents. One unreadable file must not cost the other
            # twenty-one.
            log.warning("copilot_runbook_unreadable", extra={"file": file.name})
            continue
        sections.extend(_split_sections(f"runbooks/{file.name}", content))
    log.info("copilot_runbooks_indexed", extra={"sections": len(sections)})
    return tuple(sections)


def search(question: str, *, limit: int = MAX_SECTIONS) -> tuple[RunbookSection, ...]:
    """The sections that best answer `question`, best first, or an empty tuple.

    The score is `score_line` over the section BODY plus `_HEADING_WEIGHT` times the same
    over its heading path — both normalised by the QUESTION, so a long section is not
    rewarded for its length (the argument `score_line` makes about lines applies unchanged
    to blobs). Ties break on input order, which is filename order, which is stable.
    """
    question_tokens = tokens(question)
    if not question_tokens:
        return ()
    scored = [
        (
            score_line(question_tokens, section.body)
            + _HEADING_WEIGHT * score_line(question_tokens, section.heading),
            position,
            section,
        )
        for position, section in enumerate(index())
    ]
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return tuple(section for score, _, section in scored[:limit] if score >= _MIN_SCORE)


__all__ = [
    "MAX_SECTIONS",
    "MAX_SECTION_CHARS",
    "RUNBOOK_DIR",
    "RunbookSection",
    "index",
    "search",
]
