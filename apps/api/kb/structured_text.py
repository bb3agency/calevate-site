"""A Markdown document, read as sections of plain sentences, each a fact or a call instruction.

WHY THIS EXISTS. A `.md` guide used to be chunked as raw text (`service.chunk_text` splits on
blank lines), so every heading, separator and table row became a "fact" of its own, markup
and all, and that noise reached the engine's knowledge, the embeddings and the owner's
"What it knows" list. Worse, a guide written for the agent ("Say who you are", "If he says
he is busy, ask when to call back") was stored as knowledge to look up, when it is
behaviour: the engine's own docs keep the two apart (instructions are "tone and subject
matter" sent on every reply; knowledge is "material" searched to answer a question,
`thinnest-findings/mirror/snapshots/2026-10-29/pages/agent/behaviour.md:33-47`,
`agent/knowledge.md:9-11`), and a retrieved instruction is followed only if the caller's
question happens to retrieve it.

HOW. The established pattern is heading-aware splitting: chunk under each heading and carry
the heading with the chunk (LangChain `MarkdownHeaderTextSplitter`, which keeps headers as
chunk metadata and recommends a second size-bounded split inside each section,
python.langchain.com/docs/how_to/markdown_header_metadata_splitter, read 5 Nov 2026). We
parse with markdown-it-py (CommonMark plus GFM tables) rather than by line patterns, because
emphasis, escapes, links and nested lists are where hand-written regexes go wrong. Then:

* a heading is never a chunk; it is the title of what follows it;
* a separator (`---`) and markup are dropped; a link keeps its text and its address once;
* a numbered list stays one ordered list; a table row becomes one sentence built from its
  header cells ("Say this: X. Not this: Y. Why: Z."), never new wording;
* each block is a FACT or an INSTRUCTION (`classify`), deterministically and without a
  model, so the same file always splits the same way and a test can pin it.

The classifier reads English cues. A guide written wholly in Telugu splits nothing out and
reads as facts, which is the behaviour every file had before this module.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from markdown_it import MarkdownIt
from markdown_it.token import Token

Purpose = Literal["fact", "instruction"]

#: Bumped whenever the reading below changes what a stored upload would hold, so the sweep
#: re-reads every live text upload read by an older version (`kb_uploads.text_parser`).
PARSER_VERSION: Final = 1

#: The most call instructions kept from one file, and their total size. A guide is a few
#: dozen; the bound is for a file that is nothing but a script.
MAX_INSTRUCTIONS: Final = 120
MAX_INSTRUCTION_CHARS: Final = 30_000

_MD: Final = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])

#: Verbs that tell the AGENT what to do on the call. Deliberately not the verbs a how-to
#: tells the CALLER ("Open the App Store", "Tap Install"): those steps are facts the agent
#: answers from when asked how.
_AGENT_VERBS: Final = (
    "say",
    "ask",
    "tell",
    "greet",
    "introduce",
    "explain",
    "mention",
    "keep",
    "speak",
    "talk",
    "wait",
    "repeat",
    "confirm",
    "thank",
    "guide",
    "let",
    "make sure",
    "remember",
    "avoid",
    "do not",
    "don't",
    "dont",
    "never",
    "always",
    "be",
    "listen",
    "pause",
    "spell",
    "walk him",
    "walk her",
    "walk them",
    "reply",
    "respond",
    "apologise",
    "apologize",
    "move on",
    "note down",
    "write down",
    "check whether",
    "check that",
)
_STARTS_INSTRUCTION: Final = re.compile(
    r"^(?:" + "|".join(re.escape(v) for v in _AGENT_VERBS) + r")\b", re.IGNORECASE
)
#: "If he says…", "If the farmer is…": what to do when the person on the call does something.
#: "If you pay by UPI…" and "If the app shows an error…" are facts the caller is told.
_CONDITIONAL: Final = re.compile(
    r"^(?:if|when|whenever)\s+(?:he|she|they|the\s+\w+(?:'s)?\s+(?:\w+\s+)?"
    r"(?:says?|asks?|is|are|has|have|does|wants?|sounds?|refuses?|cannot|can't|doesn't|"
    r"didn't|knows?|picks?|answers?))\b",
    re.IGNORECASE,
)
#: Words that only appear when a sentence is about running the call.
_CALL_TALK: Final = re.compile(
    r"\b(?:the agent|this call|on the call|the caller|the call|our agent|the voice agent|"
    r"how the agent|agent should|you are calling|why you are calling)\b",
    re.IGNORECASE,
)
#: Headings that name a section of behaviour rather than of facts.
_INSTRUCTION_HEADING: Final = re.compile(
    r"\b(?:how (?:the|to) (?:agent|speak|talk|open|greet|handle|close|end)|tone|greeting|"
    r"opening lines?|script|objections?|what to say|words to use|speaking|say this|call flow|"
    r"do not|don't|rules|instructions|guidelines|if (?:he|she|they)\b)",
    re.IGNORECASE,
)
#: A table whose header says what to say is a script table.
_SAY_HEADER: Final = re.compile(r"^(?:say|ask|tell|what to say|you say|agent says|line)\b", re.I)
#: A line wholly in quotation marks is a line to say.
_QUOTED: Final = re.compile(r"^[\"'\u201c\u2018].*[\"'\u201d\u2019]\W*$", re.DOTALL)

_SPACES: Final = re.compile(r"[ \t]+")
#: "2. How the agent should speak": the author's section number is not part of the title.
_NUMBERED: Final = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+")
_URL_BARE: Final = re.compile(r"^(?:https?://)?(?:www\.)?", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Block:
    """One readable unit: a paragraph, a list, a table, a quote. `lines` carry no markup."""

    section: str | None
    lines: tuple[str, ...]
    purpose: Purpose


@dataclass(frozen=True, slots=True)
class Group:
    """Consecutive blocks under one heading with one purpose: what a chunk is made from."""

    section: str | None
    lines: tuple[str, ...]
    purpose: Purpose

    @property
    def text(self) -> str:
        return with_title(self.section, self.lines)


@dataclass(slots=True)
class Reading:
    facts: list[Group] = field(default_factory=list)
    instructions: list[Group] = field(default_factory=list)


def with_title(section: str | None, lines: Sequence[str]) -> str:
    """The section's title as a leading line ending in a colon, then the lines: plain text a
    person, an embedding and the engine's search all read the same way."""
    body = "\n".join(lines)
    if not section:
        return body
    title = section if section[-1] in ":?.!" else f"{section}:"
    return f"{title}\n{body}"


def without_title(section: str | None, content: str) -> str:
    """`with_title` undone: the lines under the title, for a screen that prints the title as
    a heading of its own. Content that does not start with that title comes back whole."""
    if not section:
        return content
    title = section if section[-1] in ":?.!" else f"{section}:"
    head, sep, rest = content.partition("\n")
    return rest if sep and head == title else content


# --- detection --------------------------------------------------------------------------


_SIGNALS: Final = (
    re.compile(r"^#{1,6}\s+\S", re.MULTILINE),
    re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", re.MULTILINE),
    re.compile(r"\*\*[^*\n]+\*\*"),
    re.compile(r"\[[^\]\n]+\]\(\S+\)"),
)


def looks_like_markdown(body: str) -> bool:
    """Two different Markdown signals (a heading, a table rule, bold, a link). One alone is
    common in plain text ("**" for emphasis in a pasted WhatsApp note)."""
    return sum(1 for s in _SIGNALS if s.search(body)) >= 2


# --- reading ----------------------------------------------------------------------------


def read_markdown(body: str) -> Reading:
    """`body` as fact groups and instruction groups, in document order within each."""
    blocks = list(_blocks(_MD.parse(body)))
    reading = Reading()
    for group in _grouped(blocks):
        (reading.instructions if group.purpose == "instruction" else reading.facts).append(group)
    return reading


def _grouped(blocks: Sequence[Block]) -> list[Group]:
    out: list[Group] = []
    for block in blocks:
        if out and out[-1].section == block.section and out[-1].purpose == block.purpose:
            last = out[-1]
            out[-1] = Group(last.section, last.lines + block.lines, last.purpose)
        else:
            out.append(Group(block.section, block.lines, block.purpose))
    return out


@dataclass(slots=True)
class _Heading:
    level: int
    text: str
    instruction: bool
    #: A bold paragraph standing in for a heading; the next one replaces it.
    pseudo: bool = False


def _blocks(tokens: Sequence[Token]) -> list[Block]:
    out: list[Block] = []
    headings: list[_Heading] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            level = int(tok.tag[1:])
            title = _NUMBERED.sub("", _tidy(_inline(tokens[i + 1]).replace("\n", " ")))
            while headings and headings[-1].level >= level:
                headings.pop()
            inherited = any(h.instruction for h in headings)
            headings.append(
                _Heading(level, title, inherited or bool(_heading_is_instruction(title)))
            )
            i = _close(tokens, i)
            continue
        section = headings[-1].text if headings else None
        in_instruction_section = bool(headings and headings[-1].instruction)
        end = _close(tokens, i)
        if tok.type == "paragraph_open" and _bold_only(tokens[i + 1]):
            # A paragraph that is one bold phrase is a heading the author typed by hand
            # (LangChain's `custom_header_patterns` reads `**…**` the same way).
            if headings and headings[-1].pseudo:
                headings.pop()
            level = (headings[-1].level if headings else 0) + 1
            title = _tidy(_inline(tokens[i + 1]).replace("\n", " "))
            inherited = any(h.instruction for h in headings)
            headings.append(
                _Heading(level, title, inherited or _heading_is_instruction(title), pseudo=True)
            )
        elif tok.type == "paragraph_open":
            text = _inline(tokens[i + 1])
            out.extend(_purposed(section, [text], in_instruction_section))
        elif tok.type in ("bullet_list_open", "ordered_list_open"):
            out.extend(_list_blocks(tokens[i : end + 1], section, in_instruction_section))
        elif tok.type == "blockquote_open":
            lines = _plain_lines(tokens[i + 1 : end])
            if lines:
                quoted = all(_QUOTED.match(line) for line in lines)
                purpose: Purpose = (
                    "instruction"
                    if in_instruction_section or quoted or _any_instruction(lines)
                    else "fact"
                )
                out.append(Block(section, tuple(lines), purpose))
        elif tok.type == "table_open":
            out.extend(_table_blocks(tokens[i : end + 1], section, in_instruction_section))
        elif tok.type in ("fence", "code_block"):
            lines = [ln.rstrip() for ln in tok.content.splitlines() if ln.strip()]
            if lines:
                out.append(Block(section, tuple(lines), _purpose_of(lines, in_instruction_section)))
        # `hr`, `html_block` and anything else carry nothing a caller can be told.
        i = end + 1
    return [b for b in out if b.lines]


def _bold_only(tok: Token) -> bool:
    """An inline that is exactly one bold span of a few words."""
    kids = [c for c in tok.children or [] if not (c.type == "text" and not c.content.strip())]
    return (
        len(kids) >= 3
        and kids[0].type == "strong_open"
        and kids[-1].type == "strong_close"
        and not any(c.type in ("strong_open", "strong_close") for c in kids[1:-1])
        and len(tok.content) <= 120
    )


def _close(tokens: Sequence[Token], start: int) -> int:
    """The index of the token closing the one at `start` (itself for a self-closing one)."""
    if tokens[start].nesting != 1:
        return start
    depth = 0
    for j in range(start, len(tokens)):
        depth += tokens[j].nesting
        if depth == 0:
            return j
    return len(tokens) - 1


def _heading_is_instruction(title: str) -> bool:
    return bool(
        _INSTRUCTION_HEADING.search(title) or _CONDITIONAL.match(title) or _CALL_TALK.search(title)
    )


def is_instruction(line: str) -> bool:
    """One line, read on its own: does it tell the agent how to behave on the call?"""
    stripped = line.strip().lstrip("0123456789.) ").strip()
    if not stripped:
        return False
    return bool(
        _STARTS_INSTRUCTION.match(stripped)
        or _CONDITIONAL.match(stripped)
        or _CALL_TALK.search(stripped)
        or _QUOTED.match(stripped)
    )


def _any_instruction(lines: Sequence[str]) -> bool:
    return any(is_instruction(line) for line in lines)


def _purpose_of(lines: Sequence[str], in_instruction_section: bool) -> Purpose:
    return "instruction" if in_instruction_section or _any_instruction(lines) else "fact"


def _purposed(section: str | None, lines: Sequence[str], forced: bool) -> list[Block]:
    """One paragraph, possibly several author lines: each line classified, consecutive lines
    of one purpose kept together, so a key-value paragraph splits only where it changes."""
    kept = [ln for ln in (_tidy(x) for line in lines for x in line.split("\n")) if ln]
    out: list[Block] = []
    for line in kept:
        purpose: Purpose = "instruction" if forced or is_instruction(line) else "fact"
        if out and out[-1].purpose == purpose:
            out[-1] = Block(section, (*out[-1].lines, line), purpose)
        else:
            out.append(Block(section, (line,), purpose))
    return out


def _list_blocks(tokens: Sequence[Token], section: str | None, forced: bool) -> list[Block]:
    """A list as one block of items. A numbered list is steps: it keeps its numbers and stays
    together, so "how do I install it" retrieves every step in order. A bullet list's items
    are classified one by one, because a "key details" list mixes facts with call settings."""
    ordered = tokens[0].type == "ordered_list_open"
    start = int(tokens[0].attrGet("start") or 1) if ordered else 1
    items = _items(tokens)
    if ordered:
        lines = [f"{start + n}. {item}" for n, item in enumerate(items)]
        if not lines:
            return []
        return [Block(section, tuple(lines), _purpose_of(items, forced))]
    out: list[Block] = []
    for item in items:
        out.extend(_purposed(section, [item], forced))
    return out


def _items(tokens: Sequence[Token]) -> list[str]:
    """The top-level items of one list; a nested list's items follow on their own lines."""
    items: list[str] = []
    depth = 0
    for k, tok in enumerate(tokens):
        if tok.type in ("bullet_list_open", "ordered_list_open"):
            depth += 1
        elif tok.type in ("bullet_list_close", "ordered_list_close"):
            depth -= 1
        elif tok.type == "inline":
            text = _inline(tok).replace("\n", " ")
            text = _tidy(text)
            if not text:
                continue
            opened = _last_open(tokens, k)
            if depth == 1 and opened:
                items.append(text)
            elif items:
                items[-1] = f"{items[-1]}\n{text}" if depth > 1 else f"{items[-1]} {text}"
            else:
                items.append(text)
    return items


def _last_open(tokens: Sequence[Token], k: int) -> bool:
    """Whether the inline at `k` is the first paragraph of its list item."""
    j = k - 1
    while j >= 0 and tokens[j].type == "paragraph_open":
        j -= 1
    return j >= 0 and tokens[j].type == "list_item_open"


def _table_blocks(tokens: Sequence[Token], section: str | None, forced: bool) -> list[Block]:
    """Each row as one sentence made of its header cells and its own cells."""
    header: list[str] = []
    rows: list[list[str]] = []
    current: list[str] | None = None
    in_head = False
    for k, tok in enumerate(tokens):
        if tok.type == "thead_open":
            in_head = True
        elif tok.type == "thead_close":
            in_head = False
        elif tok.type == "tr_open":
            current = []
        elif tok.type == "tr_close" and current is not None:
            if in_head:
                header = current
            elif any(current):
                rows.append(current)
            current = None
        elif tok.type in ("th_open", "td_open") and current is not None:
            inline = tokens[k + 1] if k + 1 < len(tokens) else None
            cell = _inline(inline) if inline is not None and inline.type == "inline" else ""
            current.append(_tidy(cell.replace("\n", " ")))
    script = forced or any(_SAY_HEADER.match(h) for h in header)
    lines = [_row_sentence(header, row) for row in rows]
    lines = [ln for ln in lines if ln]
    if not lines:
        return []
    return [Block(section, tuple(lines), "instruction" if script else _purpose_of(lines, False))]


def _row_sentence(header: Sequence[str], row: Sequence[str]) -> str:
    parts: list[str] = []
    for n, cell in enumerate(row):
        if not cell:
            continue
        name = header[n] if n < len(header) else ""
        piece = f"{name}: {cell}" if name and not _is_index_cell(name, cell) else cell
        parts.append(piece if piece[-1] in ".?!" else f"{piece}.")
    return " ".join(parts)


def _is_index_cell(name: str, cell: str) -> bool:
    """A "#" or "Step" column holding a number reads better as "7." than "Step: 7."."""
    return cell.isdigit() and name.strip().lower() in ("#", "no", "no.", "step", "sl", "s.no")


def _plain_lines(tokens: Sequence[Token]) -> list[str]:
    lines: list[str] = []
    for tok in tokens:
        if tok.type == "inline":
            lines.extend(x for x in (_tidy(p) for p in _inline(tok).split("\n")) if x)
    return lines


def _inline(tok: Token) -> str:
    """An inline token's text with its markup removed. A link keeps its words and, when they
    are not the address itself, the address once; a soft line break stays a line break,
    because a price list's lines are the author's own boundaries."""
    out: list[str] = []
    href_stack: list[tuple[str, int]] = []
    for child in tok.children or []:
        kind = child.type
        if kind in ("text", "code_inline"):
            out.append(child.content)
        elif kind in ("softbreak", "hardbreak"):
            out.append("\n")
        elif kind == "image":
            out.append(child.content or "")
        elif kind == "link_open":
            href_stack.append((str(child.attrGet("href") or ""), len(out)))
        elif kind == "link_close" and href_stack:
            href, at = href_stack.pop()
            words = "".join(out[at:]).strip()
            if href and not href.startswith("#") and not _same_address(words, href):
                address = re.sub(r"^(?:mailto|tel):", "", href)
                out.append(f" ({address})" if words else address)
    return "".join(out)


def _same_address(words: str, href: str) -> bool:
    if href.lower().startswith("tel:"):
        return re.sub(r"\D", "", words) == re.sub(r"\D", "", href)

    def bare(value: str) -> str:
        return _URL_BARE.sub("", re.sub(r"^(?:mailto|tel):", "", value)).rstrip("/").lower()

    return bool(words) and bare(words) == bare(href)


def _tidy(value: str) -> str:
    return _SPACES.sub(" ", value).strip()


__all__ = [
    "MAX_INSTRUCTIONS",
    "MAX_INSTRUCTION_CHARS",
    "PARSER_VERSION",
    "Block",
    "Group",
    "Reading",
    "is_instruction",
    "looks_like_markdown",
    "read_markdown",
    "with_title",
    "without_title",
]
